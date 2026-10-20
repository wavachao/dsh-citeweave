"""On-demand GPU lifecycle contract; no Docker, Redis, GPU or models required.

CITEWEAVE_BACKEND_SOURCE=/path/to/patched/backend python backend/test_model_runtime.py
"""

import json
import os
import sys
import tempfile
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx
from fastapi import HTTPException
from redis.exceptions import ConnectionError, LockError

source = Path(os.environ.get("CITEWEAVE_BACKEND_SOURCE", ".")).resolve()
sys.path.insert(0, str(source / "src"))
with patch.dict(
    os.environ,
    {
        "CITEWEAVE_BROKER_URL": "redis://127.0.0.1:6379/15",
        "CITEWEAVE_RESULT_BACKEND": "db+postgresql://test:test@127.0.0.1/citeweave_test",
    },
):
    from citeweave import jobs  # noqa: E402
    from citeweave import model_runtime as runtime


class Broker:
    def __init__(self):
        self.values = {}
        self.clock = 1000.0
        self.broken = False
        self.busy = False
        self.lock_waits = []

    def ping(self):
        if self.broken:
            raise ConnectionError("unavailable")
        return True

    def get(self, key):
        self.ping()
        item = self.values.get(key)
        if item and item[1] > self.clock:
            return item[0]
        return None

    def set(self, key, value, ex=None, nx=False):
        if nx and self.get(key):
            return False
        self.values[key] = (value, self.clock + ex if ex else float("inf"))
        return True

    @contextmanager
    def lock(self, _name, **kwargs):
        self.ping()
        self.lock_waits.append(kwargs["blocking_timeout"])
        if self.busy:
            raise LockError("busy")
        yield

    def eval(self, script, count, *args):
        lease = args[0]
        token = args[count]
        if self.get(lease) != token:
            return 0
        if script == runtime.RENEW:
            self.set(lease, token, ex=30)
        else:
            self.set(args[1], args[3])
            self.values.pop(lease, None)
        return 1


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(patch.stopall)
        patch.dict(
            os.environ,
            {
                "CITEWEAVE_MODEL_LIFECYCLE": "ondemand",
                "CITEWEAVE_QUEUE": "celery",
                "CITEWEAVE_MODEL_START_TIMEOUT": "0",
                "CITEWEAVE_MODEL_IDLE_SECONDS": "120",
                "CITEWEAVE_MODEL_MIN_FREE_MIB": "11316",
            },
        ).start()
        self.broker = Broker()
        self.model = runtime.Runtime(self.broker)
        self.running = False
        self.free = 11720
        self.extra = "9845, 33, /usr/libexec/xdg-desktop-portal-gnome"
        self.commands = []
        self.healthy = True
        self.start_error = False
        patch.object(runtime.time, "time", side_effect=lambda: self.broker.clock).start()
        patch.object(self.model, "command", side_effect=self.command).start()
        patch.object(self.model, "healthy", side_effect=lambda: self.healthy).start()

    def command(self, *args):
        self.commands.append(args)
        if args[:2] == ("docker", "inspect"):
            self.assertEqual(args[-1], self.model.container)
            return json.dumps({"Running": self.running, "StartedAt": "1970-01-01T00:15:00Z"})
        if args[:2] == ("docker", "top"):
            return "PID\n100\n101"
        if args[0] == "nvidia-smi":
            if "--query-gpu=memory.total,memory.free" in args:
                return f"12288, {self.free}"
            own = "100, 10000, /usr/bin/python\n" if self.running else ""
            return own + self.extra
        self.assertEqual(args[0], "docker")
        self.assertEqual(args[-1], self.model.container)
        if args[1] == "start":
            if self.start_error:
                raise RuntimeError("Docker failed")
            self.running = True
        elif args[1] == "stop":
            self.running = False
        else:
            self.fail(f"Unexpected mutation: {args}")
        return self.model.container

    def mutations(self, verb):
        return [args for args in self.commands if args[:2] == ("docker", verb)]

    def test_cold_preflight_does_not_start_and_desktop_fixture_is_allowed(self):
        self.assertFalse(self.model.preflight()["running"])
        self.assertFalse(self.mutations("start"))
        self.free = 11000
        with self.assertRaisesRegex(HTTPException, "Insufficient free"):
            self.model.preflight()

    def test_foreign_compute_and_high_memory_or_similar_desktop_names_are_rejected(self):
        for process in [
            "1, 1, /usr/bin/python",
            "2, 257, /usr/bin/gnome-shell",
            "3, 1, /tmp/fake-xdg-desktop-portal-gnome",
        ]:
            with self.subTest(process=process):
                self.extra = process
                with self.assertRaisesRegex(HTTPException, "another compute"):
                    self.model.preflight()
        self.assertFalse(self.mutations("start"))

    def test_success_releases_lease_and_idle_watchdog_stops_only_after_deadline(self):
        with self.model.session():
            self.assertTrue(self.broker.get(self.model.lease))
            self.free = 1000  # A warm owned model does not need cold-start free memory.
            self.model.watch_once()
            self.assertFalse(self.mutations("stop"))
        self.assertIsNone(self.broker.get(self.model.lease))
        self.assertEqual(float(self.broker.get(self.model.last_used)), 1000)
        self.broker.clock += 119
        self.model.watch_once()
        self.assertFalse(self.mutations("stop"))
        self.broker.clock += 1
        self.model.watch_once()
        self.assertEqual(len(self.mutations("stop")), 1)
        self.assertEqual(self.broker.lock_waits[0], 30)

    def test_dead_worker_lease_expiry_allows_independent_idle_cleanup(self):
        self.running = True
        self.broker.set(self.model.lease, "dead-worker", ex=30)
        self.broker.set(self.model.last_used, "900")
        self.model.watch_once()
        self.assertTrue(self.running)
        self.broker.clock += 31
        self.model.watch_once()
        self.assertFalse(self.running)

    def test_startup_failure_stops_owned_container_and_cools_down_without_retry(self):
        for start_error in (False, True):
            with self.subTest(start_error=start_error):
                self.broker.values.clear()
                self.running = False
                self.start_error = start_error
                self.healthy = False
                with self.assertRaises(HTTPException):
                    with self.model.session():
                        self.fail("must not execute retrieval")
                self.assertFalse(self.running)
                self.assertTrue(self.broker.get(self.model.cooldown))
                starts = len(self.mutations("start"))
                with self.assertRaises(HTTPException):
                    self.model.preflight()
                self.assertEqual(starts, len(self.mutations("start")))

    def test_final_gate_discards_evidence_if_foreign_compute_appears(self):
        with self.assertRaises(HTTPException):
            with self.model.session():
                self.extra = "999, 20, /usr/bin/python"
        self.assertFalse(self.running)
        self.assertTrue(self.broker.get(self.model.cooldown))

    def test_external_retrieval_failure_preserves_a_healthy_model(self):
        for error in (HTTPException(503, "Search provider unavailable"), ValueError("bad HTML")):
            with self.subTest(error=error):
                with self.assertRaises(type(error)):
                    with self.model.session():
                        raise error
                self.assertTrue(self.running)
                self.assertFalse(self.broker.get(self.model.cooldown))
                self.assertFalse(self.broker.get(self.model.lease))
        self.assertFalse(self.mutations("stop"))

    def test_watchdog_preempts_foreign_compute_even_with_active_lease(self):
        self.running = True
        self.broker.set(self.model.lease, "active", ex=30)
        self.extra = "999, 10, /usr/bin/python"
        self.model.watch_once()
        self.assertFalse(self.running)
        self.assertTrue(self.broker.get(self.model.cooldown))

    def test_watchdog_lock_contention_skips_but_redis_outage_stops_owned_model(self):
        self.running = True
        self.broker.busy = True
        self.model.watch_once()
        self.assertTrue(self.running)
        self.broker.busy = False
        self.broker.broken = True
        self.model.watch_once()
        self.assertFalse(self.running)

    def test_lost_lease_never_deletes_or_stops_a_new_owners_model(self):
        with self.assertRaises(HTTPException):
            with self.model.session():
                self.broker.set(self.model.lease, "new-owner", ex=30)
        self.assertEqual(self.broker.get(self.model.lease), "new-owner")
        self.assertFalse(self.mutations("stop"))

    def test_compute_snapshot_precedes_owner_snapshot_to_cover_new_children(self):
        self.running = True
        self.extra = "101, 100, /usr/bin/python"
        self.model.preflight()
        compute = next(
            i
            for i, args in enumerate(self.commands)
            if "--query-compute-apps=pid,used_memory,process_name" in args
        )
        owners = next(i for i, args in enumerate(self.commands) if args[:2] == ("docker", "top"))
        self.assertLess(compute, owners)

    def test_readiness_is_available_while_cold_and_never_starts_a_model(self):
        from citeweave import app, config

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"CITEWEAVE_BACKEND": "api", "CITEWEAVE_VISION_BACKEND": "api"}),
            patch.object(config, "EMBEDDING_MODEL", directory),
            patch.object(jobs, "broker", self.broker),
            patch.object(runtime, "Runtime", return_value=self.model),
            patch.object(jobs, "dependencies_ready", return_value=True),
        ):
            Path(directory, "config.json").write_text("{}")
            self.assertEqual(app.ready().status_code, 200)
            self.assertFalse(self.mutations("start"))
            self.extra = "999, 10, /usr/bin/python"
            self.assertEqual(app.ready().status_code, 503)

    def test_health_requires_expected_alias_and_uses_configured_auth(self):
        # Use an unpatched instance to exercise the real HTTP boundary.
        model = runtime.Runtime(self.broker)
        requests = []
        alias = ["wrong-model"]

        def respond(request):
            requests.append(request)
            return httpx.Response(200, json={"data": [{"id": alias[0]}]})

        client = httpx.Client
        with (
            patch.dict(
                os.environ,
                {
                    "CITEWEAVE_VISION_API_BASE": "http://127.0.0.1:8000/v1",
                    "CITEWEAVE_VISION_API_MODEL": "expected-model",
                    "CITEWEAVE_VISION_API_KEY": "vision-secret",
                },
            ),
            patch.object(
                httpx,
                "Client",
                side_effect=lambda **kwargs: client(
                    transport=httpx.MockTransport(respond), **kwargs
                ),
            ),
        ):
            self.assertFalse(model.healthy())
            alias[0] = "expected-model"
            self.assertTrue(model.healthy())
        self.assertEqual(str(requests[0].url), "http://127.0.0.1:8000/v1/models")
        self.assertEqual(requests[0].headers["Authorization"], "Bearer vision-secret")

    def test_release_failure_refuses_a_successful_result(self):
        with patch.object(self.broker, "eval", side_effect=ConnectionError("offline")):
            with self.assertRaises(HTTPException):
                with self.model.session():
                    pass
        self.assertFalse(self.running)

    def test_heartbeat_renews_lease_while_retrieval_runs(self):
        with self.model.session():
            token = self.broker.get(self.model.lease)
            self.broker.clock += 20
            time.sleep(5.1)
            self.broker.clock += 15
            self.assertEqual(self.broker.get(self.model.lease), token)

    def test_cached_worker_result_and_api_result_are_fenced_when_gpu_is_preempted(self):
        from citeweave import app

        task = jobs.search_task
        task.push_request(id="job-1")
        self.addCleanup(task.pop_request)

        def cached_result(*_args, **_kwargs):
            self.extra = "999, 10, /usr/bin/python"
            return {"images": [{"caption": "cached evidence"}]}

        with (
            patch.object(jobs, "broker", self.broker),
            patch.object(jobs, "job_metadata", return_value={}),
            patch.object(runtime, "Runtime", return_value=self.model),
            patch.object(app, "run_search", side_effect=cached_result),
        ):
            failed = task.run({"query": "question"}, True, "request-1")
            self.assertFalse(failed["ok"])
            self.assertEqual(failed["error"]["status"], 503)
            self.assertNotIn("cached evidence", json.dumps(failed))
            with patch.object(
                jobs.celery_app,
                "AsyncResult",
                return_value=SimpleNamespace(
                    get=Mock(return_value={"ok": True, "value": {"images": ["cached evidence"]}})
                ),
            ):
                with self.assertRaises(HTTPException):
                    jobs.wait_for_job("job-1")
            with patch.object(jobs.search_task, "apply_async") as publish:
                with self.assertRaises(HTTPException):
                    jobs.submit_job({"query": "question"}, True, "request-1")
                publish.assert_not_called()


if __name__ == "__main__":
    unittest.main()
