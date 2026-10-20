"""On-demand ownership of one configured vLLM container on the shared GPU."""

import csv
import logging
import math
import os
import subprocess
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from uuid import uuid4

import httpx
from fastapi import HTTPException
from redis.exceptions import LockError, RedisError

from . import config  # noqa: F401 -- Load .env for the watchdog CLI.

logger = logging.getLogger("citeweave.model_runtime")
DESKTOP = {
    "xdg-desktop-portal-gnome",
    "xdg-desktop-portal",
    "gnome-shell",
    "xorg",
    "xwayland",
    "clash-verge",
}
RENEW = "if redis.call('get',KEYS[1])==ARGV[1] then return redis.call('expire',KEYS[1],30) else return 0 end"
RELEASE = "if redis.call('get',KEYS[1])==ARGV[1] then redis.call('set',KEYS[2],ARGV[2]); return redis.call('del',KEYS[1]) else return 0 end"


def enabled():
    return os.getenv("CITEWEAVE_MODEL_LIFECYCLE", "") == "ondemand"


class ModelUnavailable(HTTPException):
    pass


def unavailable(detail="The local model is unavailable; no evidence can be returned"):
    return ModelUnavailable(503, detail)


class Runtime:
    def __init__(self, broker):
        self.broker = broker
        self.container = os.getenv("CITEWEAVE_VLLM_CONTAINER", "dsh-citeweave-vllm")
        self.prefix = f"citeweave:model:{self.container}"
        self.lease = self.prefix + ":lease"
        self.cooldown = self.prefix + ":cooldown"
        self.last_used = self.prefix + ":last-used"
        self.idle_seconds = float(os.getenv("CITEWEAVE_MODEL_IDLE_SECONDS", "120"))
        self.start_timeout = float(os.getenv("CITEWEAVE_MODEL_START_TIMEOUT", "120"))

    def command(self, *args):
        timeout = 20 if args[:2] in (("docker", "start"), ("docker", "stop")) else 5
        return subprocess.run(
            list(args), check=True, capture_output=True, text=True, timeout=timeout
        ).stdout.strip()

    def snapshot(self):
        import json

        state = json.loads(
            self.command("docker", "inspect", "--format", "{{json .State}}", self.container)
        )
        total, free = next(
            csv.reader(
                self.command(
                    "nvidia-smi",
                    "-i",
                    "0",
                    "--query-gpu=memory.total,memory.free",
                    "--format=csv,noheader,nounits",
                ).splitlines()
            )
        )
        processes = self.command(
            "nvidia-smi",
            "-i",
            "0",
            "--query-compute-apps=pid,used_memory,process_name",
            "--format=csv,noheader,nounits",
        )
        own = set()
        if state["Running"]:
            own = {
                line.strip()
                for line in self.command("docker", "top", self.container, "-eo", "pid").splitlines()
                if line.strip().isdigit()
            }
        foreign = []
        for pid, memory, name in csv.reader(processes.splitlines()):
            if pid.strip() in own:
                continue
            desktop = name.strip().rsplit("/", 1)[-1].lower() in DESKTOP
            if desktop and memory.strip().isdigit() and int(memory) <= 256:
                continue
            foreign.append(pid.strip())
        return {
            "running": state["Running"],
            "started": state.get("StartedAt", ""),
            "total": int(total),
            "free": int(free),
            "foreign": foreign,
        }

    def check_gpu(self, state):
        if state["foreign"]:
            raise unavailable(
                "The GPU is in use by another compute task; no evidence can be returned"
            )
        minimum = int(
            os.getenv("CITEWEAVE_MODEL_MIN_FREE_MIB", str(math.ceil(state["total"] * 0.9) + 256))
        )
        if not state["running"] and state["free"] < minimum:
            raise unavailable(
                "Insufficient free GPU memory to start the model; no evidence can be returned"
            )

    def healthy(self):
        base = os.getenv(
            "CITEWEAVE_VISION_API_BASE", os.getenv("CITEWEAVE_API_BASE", "http://127.0.0.1:8000/v1")
        )
        model = os.getenv("CITEWEAVE_VISION_API_MODEL", os.getenv("CITEWEAVE_API_MODEL", ""))
        key = (
            os.getenv("CITEWEAVE_VISION_API_KEY")
            or os.getenv("CITEWEAVE_API_KEY")
            or os.getenv("DEEPSEEK_API_KEY")
        )
        try:
            with httpx.Client(timeout=2) as client:
                response = client.get(
                    base.rstrip("/") + "/models",
                    headers={"Authorization": f"Bearer {key}"} if key else {},
                )
                response.raise_for_status()
                return any(row["id"] == model for row in response.json()["data"])
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            return False

    def preflight(self, *, require_healthy=True):
        try:
            if os.getenv("CITEWEAVE_QUEUE", "") != "celery":
                raise unavailable("On-demand models require the Celery queue")
            if not self.broker.ping() or self.broker.get(self.cooldown):
                raise unavailable(
                    "The local model is cooling down after a failure; try again later"
                )
            state = self.snapshot()
            self.check_gpu(state)
            if require_healthy and state["running"] and not self.healthy():
                raise unavailable("The local model is not ready; no evidence can be returned")
            return state
        except HTTPException:
            raise
        except Exception:
            raise unavailable() from None

    def stop(self):
        self.command("docker", "stop", "--time", "10", self.container)

    def fail_closed(self, token=None):
        try:
            with self.broker.lock(self.prefix + ":control", timeout=60, blocking_timeout=3):
                owner = self.broker.get(self.lease)
                if token and owner and owner != token:
                    return
                try:
                    self.stop()
                finally:
                    self.broker.set(self.cooldown, "failed", ex=30)
        except LockError:
            # Another controller is legitimately starting/stopping this model.
            # Do not bypass its distributed lock.
            return
        except RedisError:
            # If Redis cannot arbitrate ownership, keeping this GPU allocation
            # is unsafe. Only the configured container is ever stopped.
            try:
                self.stop()
            except Exception:
                logger.exception("Could not stop the configured model container")
        except Exception:
            logger.exception("Could not stop the configured model container")

    @contextmanager
    def session(self):
        token = uuid4().hex
        finished, lost = threading.Event(), threading.Event()

        def heartbeat():
            while not finished.wait(5):
                try:
                    if not self.broker.eval(RENEW, 1, self.lease, token):
                        lost.set()
                        return
                except Exception:
                    lost.set()
                    return

        thread = None
        acquired = False
        body_failed = False
        try:
            with self.broker.lock(self.prefix + ":control", timeout=60, blocking_timeout=30):
                state = self.preflight(require_healthy=False)
                if not self.broker.set(self.lease, token, nx=True, ex=30):
                    raise unavailable("The model worker is already in use")
                acquired = True
                thread = threading.Thread(
                    target=heartbeat, name="citeweave-model-lease", daemon=True
                )
                thread.start()
                if not state["running"]:
                    self.command("docker", "start", self.container)
            deadline = time.monotonic() + self.start_timeout
            while True:
                if lost.is_set() or self.broker.get(self.lease) != token:
                    raise unavailable("The model worker lease was lost")
                state = self.preflight(require_healthy=False)
                if not state["running"]:
                    raise unavailable("The local model stopped during startup")
                if self.healthy():
                    break
                if time.monotonic() >= deadline:
                    raise unavailable("The local model failed to become ready")
                finished.wait(1)
            try:
                yield
            except Exception:
                body_failed = True
                # Retrieval failures do not invalidate a healthy model. A real
                # GPU/model failure still fences the entire result below.
                if lost.is_set() or self.broker.get(self.lease) != token:
                    raise unavailable("The model worker lease was lost") from None
                if not self.preflight()["running"]:
                    raise unavailable("The local model was interrupted") from None
                raise
            if lost.is_set() or self.broker.get(self.lease) != token:
                raise unavailable("The model worker lease was lost; no evidence can be returned")
            state = self.preflight()
            if not state["running"]:
                raise unavailable("The local model was interrupted; no evidence can be returned")
        except ModelUnavailable:
            if acquired:
                self.fail_closed(token)
            raise
        except HTTPException:
            raise
        except Exception:
            if acquired and not body_failed:
                self.fail_closed(token)
            if body_failed:
                raise
            raise unavailable() from None
        finally:
            finished.set()
            if thread is not None:
                thread.join(timeout=4)
                if thread.is_alive():
                    self.fail_closed(token)
                    raise unavailable("The model worker lease could not be verified")
            if acquired:
                try:
                    if not self.broker.eval(
                        RELEASE, 2, self.lease, self.last_used, token, str(time.time())
                    ):
                        raise unavailable("The model worker lease was lost")
                except Exception:
                    self.fail_closed(token)
                    raise unavailable("The model worker lease could not be released") from None

    def watch_once(self):
        try:
            with self.broker.lock(self.prefix + ":control", timeout=60, blocking_timeout=3):
                state = self.snapshot()
                if not state["running"]:
                    return
                if state["foreign"]:
                    self.stop()
                    self.broker.set(self.cooldown, "preempted", ex=30)
                    return
                if not self.broker.ping():
                    raise RuntimeError("Redis unavailable")
                if self.broker.get(self.lease):
                    return
                last = self.broker.get(self.last_used)
                since = (
                    float(last)
                    if last is not None
                    else datetime.fromisoformat(state["started"].replace("Z", "+00:00")).timestamp()
                )
                if time.time() - since >= self.idle_seconds:
                    self.stop()
        except LockError:
            return
        except Exception:
            self.fail_closed()


def preflight(broker):
    if enabled():
        Runtime(broker).preflight()


@contextmanager
def session(broker):
    if not enabled():
        yield
        return
    with Runtime(broker).session():
        yield


def watch():
    from .jobs import broker

    if not enabled():
        raise SystemExit("Set CITEWEAVE_MODEL_LIFECYCLE=ondemand before starting the watchdog")
    runtime = Runtime(broker)
    while True:
        runtime.watch_once()
        time.sleep(5)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["watch"])
    parser.parse_args()
    watch()
