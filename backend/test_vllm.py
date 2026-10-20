"""Keyless checks for the vLLM patch, against an already patched backend checkout.

Run with CITEWEAVE_BACKEND_SOURCE=/path/to/citeweave python backend/test_vllm.py.
No GPU, model downloads, running server, or real credentials are used.
"""

import base64
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx
import numpy as np
from fastapi.testclient import TestClient
from PIL import Image

source = Path(os.environ.get("CITEWEAVE_BACKEND_SOURCE", ".")).resolve()
sys.path.insert(0, str(source / "src"))

from citeweave import config, generation, ranking, vision, web  # noqa: E402


class VllmTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="citeweave-vllm-")
        self.addCleanup(self.directory.cleanup)
        self.addCleanup(patch.stopall)
        patch.object(config, "DATA", Path(self.directory.name)).start()
        patch.dict(
            os.environ,
            {
                "CITEWEAVE_BACKEND": "api",
                "CITEWEAVE_API_TYPE": "vllm",
                "CITEWEAVE_API_BASE": "http://127.0.0.1:8000/v1",
                "CITEWEAVE_API_MODEL": "served-vlm",
                "CITEWEAVE_API_KEY": "text-secret",
                "CITEWEAVE_VISION_BACKEND": "api",
                "CITEWEAVE_VISION_API_BASE": "http://127.0.0.1:8000/v1",
                "CITEWEAVE_VISION_API_MODEL": "served-vlm",
                "CITEWEAVE_VISION_API_KEY": "vision-secret",
                "CITEWEAVE_RANKER_DEVICE": "cpu",
                "CITEWEAVE_QUEUE": "",
                "CITEWEAVE_MODEL_LIFECYCLE": "",
            },
        ).start()
        self.requests = []
        client = httpx.Client

        def respond(request):
            self.requests.append(request)
            if request.method == "GET":
                return httpx.Response(200, json={"data": [{"id": self.served_model}]})
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {"content": "A red circle on white."},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 8,
                        "completion_tokens": 6,
                        "total_tokens": 14,
                    },
                },
            )

        transport = httpx.MockTransport(respond)
        self.served_model = "served-vlm"
        patch.object(
            httpx,
            "Client",
            side_effect=lambda **kwargs: client(transport=transport, **kwargs),
        ).start()

    def test_text_api_uses_vllm_template_without_loading_local_text_model(self):
        generator = generation.Generator()
        generator.load = Mock(side_effect=AssertionError("local text model must not load"))
        long_prompt = "Describe diffraction using the supplied evidence. " * 4000
        with patch.object(config, "MAX_INPUT", 6144):
            result = generator.complete(long_prompt, system="Use evidence")
        self.assertEqual(result["response"], "A red circle on white.")
        request = self.requests[0]
        body = json.loads(request.content)
        self.assertEqual(str(request.url), "http://127.0.0.1:8000/v1/chat/completions")
        self.assertEqual(request.headers["authorization"], "Bearer text-secret")
        self.assertEqual(body["model"], "served-vlm")
        self.assertEqual(body["chat_template_kwargs"], {"enable_thinking": False})
        self.assertEqual(body["truncate_prompt_tokens"], 6144)
        self.assertEqual(body["messages"][-1]["content"], long_prompt)
        self.assertNotIn("thinking", body)
        generator.load.assert_not_called()

    def test_backend_authentication_does_not_accept_the_model_server_key(self):
        from citeweave import app

        with (
            patch.object(config, "ACCESS_TOKEN", "workspace-token-not-model-token"),
            TestClient(app.app) as client,
        ):
            self.assertEqual(client.post("/api/evidence", json={"query": "x"}).status_code, 401)
            denied = client.post(
                "/api/evidence",
                json={"query": "x"},
                headers={"Authorization": "Bearer vision-secret"},
            )
            self.assertEqual(denied.status_code, 401)
            accepted = client.post(
                "/api/evidence",
                json={"query": "x"},
                headers={"Authorization": "Bearer workspace-token-not-model-token"},
            )
            self.assertEqual(
                accepted.status_code,
                422,
                "workspace auth must pass before query validation",
            )
        self.assertEqual(self.requests, [], "rejected requests must not reach the model server")

    def test_default_text_api_keeps_deepseek_thinking_parameter(self):
        with patch.dict(os.environ, {"CITEWEAVE_API_TYPE": "deepseek"}):
            generation.Generator().complete("A question")
        body = json.loads(self.requests[0].content)
        self.assertEqual(body["thinking"], {"type": "disabled"})
        self.assertNotIn("chat_template_kwargs", body)
        self.assertNotIn("truncate_prompt_tokens", body)

    def test_vision_uses_validated_jpeg_data_uri_and_model_keyed_cache(self):
        image = io.BytesIO()
        Image.new("RGB", (1600, 800), "red").save(image, "PNG")
        public_image = "https://example.org/original.png"
        evidence = [
            {
                "id": "i0",
                "url": public_image,
                "source_id": "s0",
                "source_url": "https://example.org/page",
                "caption": "Publisher caption",
            }
        ]
        generator = Mock()
        with patch.object(
            web, "fetch", return_value=(image.getvalue(), public_image, "image/png")
        ) as fetch:
            first = vision.caption_images(evidence, generator)
            again = vision.caption_images(evidence, generator)
            self.assertEqual(len(self.requests), 1, "caption cache must avoid a second model call")
            self.assertEqual(
                fetch.call_count, 1, "the original validated image cache remains in use"
            )
            self.assertEqual(first, again)
            with patch.dict(os.environ, {"CITEWEAVE_VISION_API_MODEL": "new-served-revision"}):
                vision.caption_images(evidence, generator)
            self.assertEqual(
                len(self.requests),
                2,
                "changing model identity must invalidate captions",
            )
        request = self.requests[0]
        body = json.loads(request.content)
        self.assertEqual(request.headers["authorization"], "Bearer vision-secret")
        self.assertEqual(body["chat_template_kwargs"], {"enable_thinking": False})
        uri = body["messages"][0]["content"][0]["image_url"]["url"]
        self.assertTrue(uri.startswith("data:image/jpeg;base64,"))
        with Image.open(io.BytesIO(base64.b64decode(uri.split(",", 1)[1]))) as resized:
            self.assertEqual(resized.format, "JPEG")
            self.assertEqual(resized.size, (1024, 512))
        self.assertNotIn(public_image, request.content.decode())
        self.assertNotIn("text-secret", request.content.decode())
        self.assertEqual(first[0]["source_url"], evidence[0]["source_url"])
        self.assertEqual(first[0]["caption_kind"], "api_visual_description")
        self.assertEqual(first[0]["publisher_caption"], "Publisher caption")
        generator.unload.assert_not_called()

    def test_private_image_url_is_rejected_before_vision_http(self):
        images = [{"id": "i0", "url": "http://127.0.0.1/private", "caption": "Untrusted"}]
        result = vision.caption_images(images, Mock())
        self.assertIn("Nonpublic", result[0]["image_error"])
        self.assertEqual(self.requests, [])

    def test_ready_requires_the_served_api_alias_but_not_old_local_models(self):
        from citeweave import app

        embedding = Path(self.directory.name) / "embedding"
        embedding.mkdir()
        (embedding / "config.json").write_text("{}")
        with (
            patch.object(config, "EMBEDDING_MODEL", str(embedding)),
            patch.object(config, "VISION_MODEL", "/not-present/old-vision"),
            patch.object(config, "MODEL", "/not-present/old-text"),
        ):
            self.assertEqual(app.ready().status_code, 200)
            self.served_model = "another-model"
            self.assertEqual(app.ready().status_code, 503)
            self.served_model = "served-vlm"
            (embedding / "config.json").unlink()
            self.assertEqual(app.ready().status_code, 503)
        self.assertEqual(str(self.requests[0].url), "http://127.0.0.1:8000/v1/models")
        self.assertEqual(self.requests[0].headers["authorization"], "Bearer vision-secret")
        query = SimpleNamespace(query="question", urls=[], verify_images=True)
        parameters = app.cache_parameters(query)
        with patch.dict(os.environ, {"CITEWEAVE_VISION_API_MODEL": "different-model"}):
            self.assertNotEqual(parameters, app.cache_parameters(query))
        self.assertNotIn("vision-secret", json.dumps(parameters))

    def test_cpu_embedding_and_crossencoder_use_the_configured_device(self):
        devices = []
        selected = Path(self.directory.name) / "crossencoder"
        (selected / "best").mkdir(parents=True)
        (selected / "selected.json").write_text(
            json.dumps({"deploy": True, "threshold": 0.5, "max_length": 32})
        )
        patch.object(config, "RUNS", Path(self.directory.name)).start()
        patch.object(config, "EMBEDDING_MODEL", "embedding-fixture").start()

        class Encoder:
            def __init__(self, _path, *, device, local_files_only):
                devices.append(("embedding", device))

            def encode(self, texts, **_kwargs):
                return np.ones((len(texts), 384), dtype=np.float32)

        class Batch(dict):
            def to(self, device):
                devices.append(("tokens", device))
                return self

        class CrossEncoder:
            def to(self, device):
                devices.append(("crossencoder", device))
                return self

            def eval(self):
                return self

            def __call__(self, **_kwargs):
                logits = Mock()
                logits.sigmoid.return_value.flatten.return_value.cpu.return_value.tolist.return_value = [
                    0.9
                ]
                return SimpleNamespace(logits=logits)

        tokenizer = Mock(return_value=Batch())
        with patch.dict(
            sys.modules,
            {
                "sentence_transformers": SimpleNamespace(SentenceTransformer=Encoder),
                "transformers": SimpleNamespace(
                    AutoTokenizer=SimpleNamespace(from_pretrained=Mock(return_value=tokenizer)),
                    AutoModelForSequenceClassification=SimpleNamespace(
                        from_pretrained=Mock(return_value=CrossEncoder())
                    ),
                ),
                "torch": SimpleNamespace(
                    inference_mode=lambda: __import__("contextlib").nullcontext()
                ),
            },
        ):
            ranker = ranking.Ranker(checkpoint=Path(self.directory.name) / "no-head.pt")
            scores, _ = ranker.score("question", ["caption"])
        self.assertEqual(scores.tolist(), [0.9])
        self.assertEqual(
            devices, [("embedding", "cpu"), ("crossencoder", "cpu"), ("tokens", "cpu")]
        )

    def test_search_no_results_is_empty_but_provider_failures_still_raise(self):
        failure = type("DDGSException", (Exception,), {})
        search = Mock(side_effect=failure("No results found."))
        with patch.dict(sys.modules, {
            "ddgs": SimpleNamespace(DDGS=Mock(return_value=SimpleNamespace(text=search))),
            "ddgs.exceptions": SimpleNamespace(DDGSException=failure),
        }), patch.dict(os.environ, {"SEARXNG_URL": ""}):
            self.assertEqual(web.search("rare topic"), [])
            search.side_effect = failure("Search provider timed out")
            with self.assertRaises(failure):
                web.search("rare topic")

    def test_unreadable_sources_preserve_retrieval_diagnostics(self):
        with patch.object(web, "fetch", side_effect=ValueError("HTTP 403")):
            with self.assertRaises(web.NoEvidenceError) as caught:
                web.retrieve("topic", ["https://example.org/page"])
        self.assertEqual(caught.exception.errors, [
            {"url": "https://example.org/page", "error": "HTTP 403"}
        ])

    def test_translated_discovery_can_fall_back_to_original_language(self):
        from citeweave import app

        engine = Mock()
        engine.generator.complete.return_value = {"response": "ink wash painting realism"}
        request = SimpleNamespace(query="水墨画和写实画", urls=[], verify_images=False)
        with patch.object(app, "engine", engine), patch.object(app, "retrieve", side_effect=[
            web.NoEvidenceError([]), ([{"id": "s0"}], [], [])
        ]) as retrieve:
            query, sources, _, notes = app.retrieve_evidence(request)
        self.assertEqual(query, request.query)
        self.assertEqual(sources, [{"id": "s0"}])
        self.assertTrue(notes)
        self.assertEqual(retrieve.call_args_list[-1].args, (request.query,))

    def test_empty_evidence_is_not_a_service_failure_and_is_not_cached(self):
        from citeweave import app
        from contextlib import nullcontext

        cache = Mock()
        cache.get.return_value = None
        with patch.object(config, "ACCESS_TOKEN", ""), \
             patch.object(app, "engine", Mock()), \
             patch.object(app, "answer_cache", cache), \
             patch.object(app, "gpu_session", return_value=nullcontext()), \
             patch.object(app.limiter, "allow", return_value=True), \
             patch.object(app, "retrieve_evidence", side_effect=web.NoEvidenceError([])), \
             TestClient(app.app) as client:
            response = client.post("/api/evidence", json={"query": "rare topic"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["sources"], [])
            self.assertEqual(response.json()["images"], [])
            self.assertTrue(response.json()["retrieval_errors"])
            cache.put.assert_not_called()

    def test_concurrent_evidence_calls_wait_instead_of_immediate_conflict(self):
        from citeweave import app
        from concurrent.futures import ThreadPoolExecutor
        from contextlib import nullcontext
        import threading
        import time

        entered = threading.Event()
        active, peak = 0, 0

        def retrieve(_request):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            entered.set()
            time.sleep(0.1)
            active -= 1
            raise web.NoEvidenceError([])

        cache = Mock()
        cache.get.return_value = None
        with patch.object(config, "ACCESS_TOKEN", ""), \
             patch.object(app, "engine", Mock()), \
             patch.object(app, "answer_cache", cache), \
             patch.object(app, "gpu_session", side_effect=lambda **_: nullcontext()), \
             patch.object(app.limiter, "allow", return_value=True), \
             patch.object(app, "retrieve_evidence", side_effect=retrieve), \
             TestClient(app.app) as client, ThreadPoolExecutor(2) as pool:
            first = pool.submit(client.post, "/api/evidence", json={"query": "first topic"})
            self.assertTrue(entered.wait(2))
            second = pool.submit(client.post, "/api/evidence", json={"query": "second topic"})
            self.assertEqual([first.result().status_code, second.result().status_code], [200, 200])
        self.assertEqual(peak, 1)


if __name__ == "__main__":
    unittest.main()
