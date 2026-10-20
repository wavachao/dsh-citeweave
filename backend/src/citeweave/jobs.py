"""Durable single-worker retrieval jobs: Redis admission and PostgreSQL results."""

import json
import logging
import os
from types import SimpleNamespace
from uuid import uuid4

from celery import Celery
from celery.exceptions import TaskRevokedError
from celery.exceptions import TimeoutError as ResultTimeout
from fastapi import HTTPException
from redis import Redis

from . import (
    config,  # noqa: F401 -- Load .env for the Celery CLI entrypoint.
    model_runtime,
)

logger = logging.getLogger("citeweave.jobs")
QUEUE = "citeweave"
MAX_WAITING = int(os.getenv("CITEWEAVE_MAX_WAITING", "4"))
WAIT_TIMEOUT = float(os.getenv("CITEWEAVE_JOB_WAIT_TIMEOUT", "280"))
RESULT_TTL = int(os.getenv("CITEWEAVE_RESULT_TTL", "86400"))
BROKER = os.environ["CITEWEAVE_BROKER_URL"]
BACKEND = os.environ["CITEWEAVE_RESULT_BACKEND"]

celery_app = Celery("citeweave", broker=BROKER, backend=BACKEND)
celery_app.conf.update(
    task_default_queue=QUEUE,
    task_default_priority=0,
    task_default_delivery_mode=2,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    worker_pool="solo",
    worker_concurrency=1,
    task_track_started=True,
    task_publish_retry=False,
    broker_connection_retry_on_startup=True,
    broker_transport_options={
        "visibility_timeout": 3600,
        "priority_steps": [0],
        "socket_connect_timeout": 3,
        "socket_timeout": 3,
    },
    database_engine_options={"connect_args": {"connect_timeout": 3}, "pool_pre_ping": True},
    result_expires=RESULT_TTL,
    result_backend_always_retry=os.getenv("CITEWEAVE_WORKER", "") == "1",
    result_backend_base_sleep_between_retries_ms=100,
    result_backend_max_sleep_between_retries_ms=10000,
    beat_schedule={
        "expired-job-results": {"task": "celery.backend_cleanup", "schedule": 3600},
    },
)
broker = Redis.from_url(BROKER, decode_responses=True, socket_connect_timeout=3, socket_timeout=3)


def dependencies_ready():
    engine = None
    try:
        broker.ping()
        from sqlalchemy import create_engine, text

        engine = create_engine(BACKEND.removeprefix("db+"), connect_args={"connect_timeout": 3})
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
    finally:
        if engine is not None:
            engine.dispose()


def job_key(task_id):
    return f"citeweave:job:{task_id}"


def job_metadata(task_id):
    value = broker.get(job_key(task_id))
    if value is None:
        raise HTTPException(404, "Job not found or expired")
    return json.loads(value)


def submit_job(payload, evidence_only, request_id):
    """Reserve waiting capacity and publish under one cross-process lock."""
    model_runtime.preflight(broker)
    task_id = str(uuid4())
    try:
        with broker.lock("citeweave:admission", timeout=60, blocking_timeout=5):
            if broker.llen(QUEUE) >= MAX_WAITING:
                raise HTTPException(
                    429, "Retrieval queue is full; try again later", headers={"Retry-After": "10"}
                )
            broker.set(job_key(task_id), json.dumps({"request_id": request_id}), ex=RESULT_TTL)
            search_task.apply_async(
                args=[payload, evidence_only, request_id], task_id=task_id, queue=QUEUE
            )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Job submission failed; request_id=%s task_id=%s", request_id, task_id)
        raise HTTPException(
            503, "Retrieval queue is unavailable", headers={"X-Task-ID": task_id}
        ) from None
    return task_id


def failure(task_id, request_id, status, detail, headers=None):
    return {
        "ok": False,
        "task_id": task_id,
        "request_id": request_id,
        "error": {
            "status": status,
            "detail": detail,
            "headers": headers or {},
        },
    }


@celery_app.task(bind=True, name="citeweave.search")
def search_task(task, payload, evidence_only, request_id):
    """Worker-owned execution; return JSON errors rather than serialized exceptions."""
    task_id = task.request.id
    try:
        if job_metadata(task_id).get("cancel_requested"):
            return {
                **failure(task_id, request_id, 409, "Job was cancelled before execution"),
                "cancelled": True,
            }
        from .app import EvidenceRequest, SearchRequest, run_search

        request = (EvidenceRequest if evidence_only else SearchRequest).model_validate(payload)
        http_request = SimpleNamespace(state=SimpleNamespace(request_id=request_id))
        with model_runtime.session(broker):
            value = run_search(request, http_request, evidence_only=evidence_only)
        return {"ok": True, "task_id": task_id, "request_id": request_id, "value": value}
    except HTTPException as error:
        return failure(task_id, request_id, error.status_code, error.detail, error.headers)
    except Exception:
        logger.exception("Job failed; request_id=%s task_id=%s", request_id, task_id)
        return failure(
            task_id, request_id, 503, "Retrieval task failed; check server logs using the task ID"
        )


def restore_result(value, task_id):
    if not isinstance(value, dict) or "ok" not in value:
        raise HTTPException(503, "Retrieval task failed", headers={"X-Task-ID": task_id})
    if not value["ok"]:
        error = value["error"]
        raise HTTPException(
            error["status"], error["detail"], headers={**error["headers"], "X-Task-ID": task_id}
        )
    return value["value"]


def wait_for_job(task_id):
    """Wait on durable results without resubmitting or polling the HTTP endpoint."""
    try:
        value = celery_app.AsyncResult(task_id).get(
            timeout=WAIT_TIMEOUT, interval=1, propagate=False
        )
    except ResultTimeout:
        raise HTTPException(
            504,
            "Retrieval is still processing; query the job using its task ID",
            headers={"X-Task-ID": task_id},
        ) from None
    except Exception:
        logger.exception("Job result read failed; task_id=%s", task_id)
        raise HTTPException(
            503, "Job result storage is unavailable", headers={"X-Task-ID": task_id}
        ) from None
    if isinstance(value, TaskRevokedError):
        raise HTTPException(
            409, "Job was cancelled before execution", headers={"X-Task-ID": task_id}
        )
    value = restore_result(value, task_id)
    model_runtime.preflight(broker)
    return value


def get_job(task_id):
    try:
        metadata = job_metadata(task_id)
        result = celery_app.AsyncResult(task_id)
        state = result.state
        answer = {"task_id": task_id, "request_id": metadata["request_id"], "state": state}
        if state == "SUCCESS":
            value = result.result
            if isinstance(value, dict):
                if value.get("ok"):
                    model_runtime.preflight(broker)
                answer.update(
                    {"result": value["value"]} if value.get("ok") else {"error": value["error"]}
                )
                if not value.get("ok"):
                    answer["state"] = "REVOKED" if value.get("cancelled") else "FAILURE"
            else:
                answer["error"] = {"status": 503, "detail": "Retrieval task failed"}
        elif state in ("FAILURE", "REVOKED"):
            answer["error"] = {
                "status": 503 if state == "FAILURE" else 409,
                "detail": "Job failed" if state == "FAILURE" else "Job was cancelled",
            }
        return answer
    except HTTPException:
        raise
    except Exception:
        logger.exception("Job status read failed; task_id=%s", task_id)
        raise HTTPException(503, "Retrieval queue is unavailable") from None


def cancel_job(task_id):
    """Request cancellation of queued work; running inference is never killed."""
    try:
        metadata = job_metadata(task_id)
        if celery_app.AsyncResult(task_id).state != "PENDING":
            raise HTTPException(
                409, "Only queued jobs can be cancelled; running work is not interrupted"
            )
        metadata["cancel_requested"] = True
        broker.set(job_key(task_id), json.dumps(metadata), ex=RESULT_TTL)
        celery_app.control.revoke(task_id, terminate=False)
        return {"task_id": task_id, "cancel_requested": True}
    except HTTPException:
        raise
    except Exception:
        logger.exception("Job cancellation failed; task_id=%s", task_id)
        raise HTTPException(503, "Retrieval queue is unavailable") from None
