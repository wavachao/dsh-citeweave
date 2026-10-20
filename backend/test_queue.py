"""Queue contract checks with real Celery objects and mocked Redis/SQL results.

CITEWEAVE_BACKEND_SOURCE=/path/to/patched/backend python backend/test_queue.py
No running Redis, PostgreSQL, GPU, or external model service is required.
"""

import json
import os
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from celery.exceptions import TaskRevokedError
from celery.exceptions import TimeoutError as ResultTimeout
from fastapi import HTTPException
from fastapi.testclient import TestClient

source = Path(os.environ.get("CITEWEAVE_BACKEND_SOURCE", ".")).resolve()
sys.path.insert(0, str(source / "src"))
with patch.dict(
    os.environ,
    {
        "CITEWEAVE_BROKER_URL": "redis://127.0.0.1:6379/15",
        "CITEWEAVE_RESULT_BACKEND": "db+postgresql://test:test@127.0.0.1/citeweave_test",
        "CITEWEAVE_WORKER": "",
    },
):
    from citeweave import config, jobs  # noqa: E402


class Broker:
    def __init__(self):
        self.values = {}
        self.queue = []
        self.mutex = threading.Lock()

    @contextmanager
    def lock(self, _name, **_kwargs):
        with self.mutex:
            yield

    def llen(self, name):
        assert name == "citeweave"
        time.sleep(0.001)
        return len(self.queue)

    def set(self, key, value, *, ex):
        assert ex > 0
        self.values[key] = value

    def get(self, key):
        return self.values.get(key)

    def ping(self):
        return True


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="citeweave-queue-test-")
        self.addCleanup(self.directory.cleanup)
        self.addCleanup(patch.stopall)
        patch.object(config, "DATA", Path(self.directory.name)).start()
        self.broker = Broker()
        patch.object(jobs, "broker", self.broker).start()
        patch.object(jobs, "MAX_WAITING", 4).start()
        self.published = []

        def publish(**kwargs):
            time.sleep(0.003)
            self.broker.queue.append(kwargs["task_id"])
            self.published.append(kwargs)

        self.publish = patch.object(jobs.search_task, "apply_async", side_effect=publish).start()

    def test_admission_serializes_capacity_check_and_publication_across_api_threads(self):
        def submit(index):
            try:
                return jobs.submit_job({"query": f"question {index}"}, True, f"request-{index}")
            except HTTPException as error:
                self.assertEqual(error.status_code, 429)
                self.assertEqual(error.headers["Retry-After"], "10")
                return None

        with ThreadPoolExecutor(max_workers=8) as threads:
            submitted = list(threads.map(submit, range(8)))
        accepted = [task_id for task_id in submitted if task_id]
        self.assertEqual(len(accepted), 4)
        self.assertEqual(len(self.broker.queue), 4)
        self.assertEqual(self.publish.call_count, 4)
        for publication in self.published:
            self.assertEqual(publication["queue"], "citeweave")
            self.assertEqual(len(publication["args"]), 3)
            metadata = jobs.job_metadata(publication["task_id"])
            self.assertEqual(metadata["request_id"], publication["args"][2])

    def test_celery_configuration_has_one_durable_json_worker_and_result_cleanup(self):
        conf = jobs.celery_app.conf
        self.assertEqual(conf.worker_pool, "solo")
        self.assertEqual(conf.worker_concurrency, 1)
        self.assertEqual(conf.worker_prefetch_multiplier, 1)
        self.assertTrue(conf.task_acks_late)
        self.assertTrue(conf.task_reject_on_worker_lost)
        self.assertEqual(conf.task_default_delivery_mode, 2)
        self.assertTrue(conf.task_track_started)
        self.assertEqual(conf.task_serializer, "json")
        self.assertEqual(conf.result_serializer, "json")
        self.assertFalse(
            conf.result_backend_always_retry, "API result reads must not retry indefinitely"
        )
        self.assertEqual(conf.broker_transport_options["visibility_timeout"], 3600)
        self.assertEqual(
            conf.beat_schedule["expired-job-results"]["task"], "celery.backend_cleanup"
        )

    def test_worker_returns_json_envelopes_and_does_not_retry_external_retrieval(self):
        from citeweave import app

        task_id = jobs.submit_job({"query": "question", "max_images": 2}, True, "request-1")
        task = jobs.search_task
        task.push_request(id=task_id)
        self.addCleanup(task.pop_request)
        with patch.object(app, "run_search", return_value={"sources": [], "images": []}) as run:
            result = task.run({"query": "question", "max_images": 2}, True, "request-1")
            self.assertTrue(result["ok"])
            self.assertEqual(result["task_id"], task_id)
            self.assertEqual(run.call_args.args[0].max_images, 2)
            self.assertEqual(run.call_args.args[1].state.request_id, "request-1")
            run.assert_called_once()
        with patch.object(
            app, "run_search", side_effect=HTTPException(422, "No readable sources")
        ) as run:
            failed = task.run({"query": "question"}, True, "request-1")
            self.assertEqual(failed["error"]["status"], 422)
            run.assert_called_once()
        with (
            patch.object(app, "run_search", side_effect=RuntimeError("postgresql://secret-key")),
            patch.object(jobs.logger, "exception"),
        ):
            failed = task.run({"query": "question"}, True, "request-1")
            self.assertEqual(failed["error"]["status"], 503)
            self.assertNotIn("secret-key", json.dumps(failed))
            self.assertNotIn("traceback", json.dumps(failed))

    def test_sync_wait_is_one_result_read_with_interval_and_safe_failures(self):
        result = Mock()
        result.get.return_value = {"ok": True, "value": {"query": "question"}}
        with patch.object(jobs.celery_app, "AsyncResult", return_value=result):
            self.assertEqual(jobs.wait_for_job("job-1"), {"query": "question"})
        result.get.assert_called_once_with(timeout=jobs.WAIT_TIMEOUT, interval=1, propagate=False)
        self.publish.assert_not_called()
        for exception, expected in [
            (ResultTimeout(), 504),
            (RuntimeError("database-password"), 503),
        ]:
            with (
                patch.object(
                    jobs.celery_app,
                    "AsyncResult",
                    return_value=Mock(get=Mock(side_effect=exception)),
                ),
                patch.object(jobs.logger, "exception"),
            ):
                with self.assertRaises(HTTPException) as raised:
                    jobs.wait_for_job("job-1")
                self.assertEqual(raised.exception.status_code, expected)
                self.assertEqual(raised.exception.headers["X-Task-ID"], "job-1")
                self.assertNotIn("database-password", raised.exception.detail)
        with patch.object(
            jobs.celery_app,
            "AsyncResult",
            return_value=Mock(get=Mock(return_value=TaskRevokedError())),
        ):
            with self.assertRaises(HTTPException) as raised:
                jobs.wait_for_job("job-1")
            self.assertEqual(raised.exception.status_code, 409)

    def test_http_errors_are_restored_and_public_job_failures_are_safe(self):
        task_id = jobs.submit_job({"query": "question"}, True, "request-1")
        failure = jobs.failure(
            task_id, "request-1", 422, "No readable sources", {"Retry-After": "10"}
        )
        with self.assertRaises(HTTPException) as raised:
            jobs.restore_result(failure, task_id)
        self.assertEqual(raised.exception.status_code, 422)
        self.assertEqual(raised.exception.headers["X-Task-ID"], task_id)
        with patch.object(
            jobs.celery_app,
            "AsyncResult",
            return_value=SimpleNamespace(state="SUCCESS", result=failure),
        ):
            self.assertEqual(jobs.get_job(task_id)["state"], "FAILURE")
        with (
            patch.object(
                jobs.celery_app, "AsyncResult", side_effect=RuntimeError("postgresql://password")
            ),
            patch.object(jobs.logger, "exception"),
        ):
            with self.assertRaises(HTTPException) as raised:
                jobs.get_job(task_id)
            self.assertEqual(raised.exception.status_code, 503)
            self.assertNotIn("password", raised.exception.detail)

    def test_queued_cancellation_is_recorded_and_never_kills_running_work(self):
        task_id = jobs.submit_job({"query": "question"}, True, "request-1")
        with (
            patch.object(
                jobs.celery_app, "AsyncResult", return_value=SimpleNamespace(state="PENDING")
            ),
            patch.object(jobs.celery_app.control, "revoke") as revoke,
        ):
            self.assertTrue(jobs.cancel_job(task_id)["cancel_requested"])
            revoke.assert_called_once_with(task_id, terminate=False)
        task = jobs.search_task
        task.push_request(id=task_id)
        try:
            self.assertTrue(task.run({"query": "question"}, True, "request-1")["cancelled"])
        finally:
            task.pop_request()
        with (
            patch.object(
                jobs.celery_app, "AsyncResult", return_value=SimpleNamespace(state="STARTED")
            ),
            patch.object(jobs.celery_app.control, "revoke") as revoke,
        ):
            with self.assertRaises(HTTPException) as raised:
                jobs.cancel_job(task_id)
            self.assertEqual(raised.exception.status_code, 409)
            revoke.assert_not_called()

    def test_sync_and_async_routes_submit_once_and_jobs_require_authentication(self):
        from citeweave import app

        with (
            patch.dict(os.environ, {"CITEWEAVE_QUEUE": "celery"}),
            patch.object(config, "ACCESS_TOKEN", "workspace-token"),
            patch.object(jobs, "submit_job", return_value="job-1") as submit,
            patch.object(
                jobs,
                "wait_for_job",
                return_value={"query": "question", "images": [], "sources": []},
            ) as wait,
            TestClient(app.app) as client,
        ):
            self.assertEqual(client.post("/api/jobs", json={"query": "question"}).status_code, 401)
            self.assertEqual(client.get("/api/jobs/job-1").status_code, 401)
            self.assertEqual(client.delete("/api/jobs/job-1").status_code, 401)
            submit.assert_not_called()
            response = client.post(
                "/api/evidence",
                json={"query": "question"},
                headers={"Authorization": "Bearer workspace-token"},
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["X-Task-ID"], "job-1")
            submit.assert_called_once()
            wait.assert_called_once_with("job-1")
            queued = client.post(
                "/api/jobs",
                json={"query": "question"},
                headers={"Authorization": "Bearer workspace-token"},
            )
            self.assertEqual(queued.status_code, 202)
            self.assertEqual(queued.json()["status_url"], "/api/jobs/job-1")
            self.assertEqual(submit.call_count, 2)
            wait.assert_called_once()

    def test_readiness_checks_redis_and_postgres_without_exposing_connection_urls(self):
        from sqlalchemy.exc import OperationalError

        engine = Mock()
        connection = engine.connect.return_value.__enter__ = Mock(return_value=Mock())
        engine.connect.return_value.__exit__ = Mock(return_value=False)
        with patch("sqlalchemy.create_engine", return_value=engine) as create:
            self.assertTrue(jobs.dependencies_ready())
            self.assertEqual(create.call_args.kwargs["connect_args"]["connect_timeout"], 3)
            connection.return_value.execute.assert_called_once()
            engine.dispose.assert_called_once()
        with patch(
            "sqlalchemy.create_engine",
            side_effect=OperationalError("secret", {}, Exception("password")),
        ):
            self.assertFalse(jobs.dependencies_ready())


if __name__ == "__main__":
    unittest.main()
