from contextlib import nullcontext
from unittest.mock import Mock

import numpy as np
import pytest
from fastapi.testclient import TestClient

from citeweave import app as service
from citeweave.cache import AnswerCache
from citeweave.security import RequestLimiter


@pytest.fixture
def evidence_service(monkeypatch, tmp_path):
    calls = []
    unloaded = []
    sources = [
        {
            "id": "s0",
            "title": "Illustrated guide",
            "url": "https://example.com/guide",
            "text": (
                "A useful explanation of shadows and the position of a light source. " * 30 + "\n\n"
            )
            * 20,
        }
    ]
    images = [
        {
            "id": f"i{n}",
            "url": f"https://example.com/diagram{n}.jpg",
            "source_id": "s0",
            "source_url": sources[0]["url"],
            "caption": f"Shadow diagram {n}",
            "caption_kind": "local_visual_description",
        }
        for n in range(2)
    ]
    image_path = service.cache_dir / (tmp_path.name + ".jpg")
    image_path.write_bytes(b"test image bytes")

    def retrieve(request):
        calls.append((request.query, request.verify_images, request.refresh))
        return request.query, sources, images, []

    def no_generation(*args, **kwargs):
        pytest.fail("Evidence requests must not generate an answer")

    monkeypatch.setattr(service.config, "ACCESS_TOKEN", "")
    monkeypatch.setattr(service, "limiter", RequestLimiter(limit=100))
    monkeypatch.setattr(service, "answer_cache", AnswerCache(tmp_path / "answers.sqlite3"))
    monkeypatch.setattr(service, "gpu_session", lambda **kwargs: nullcontext())
    monkeypatch.setattr(service, "retrieve_evidence", retrieve)
    monkeypatch.setattr(service, "cache_image", lambda url: image_path)
    monkeypatch.setattr(service.engine, "answer", no_generation)
    monkeypatch.setattr(service.engine.generator, "complete", no_generation)
    monkeypatch.setattr(service.engine.generator, "unload", lambda: unloaded.append("generator"))
    monkeypatch.setattr(service.engine.ranker, "unload", lambda: unloaded.append("ranker"))
    monkeypatch.setattr(service.engine.ranker, "encode", lambda texts: np.ones((len(texts), 1)))
    monkeypatch.setattr(
        service.engine.ranker,
        "select",
        lambda query, candidates, limit: [
            {**image, "relevance_score": 0.9} for image in candidates[:limit]
        ],
    )
    try:
        yield TestClient(service.app), calls, unloaded, images
    finally:
        image_path.unlink(missing_ok=True)


def test_evidence_preserves_bounded_sources_and_authenticated_images(evidence_service, monkeypatch):
    client, calls, unloaded, _ = evidence_service
    token = "evidence-access-token-" + "a" * 32
    monkeypatch.setattr(service.config, "ACCESS_TOKEN", token)
    assert client.post("/api/evidence", json={"query": "Why shadows?"}).status_code == 401
    headers = {"Authorization": "Bearer " + token}
    response = client.post(
        "/api/evidence", headers=headers, json={"query": "Why shadows?", "max_images": 1}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "evidence" and data["cache_hit"] is False
    assert data["query"] == "Why shadows?" and data["created_at"] > 0
    assert data["total_seconds"] >= 0
    assert 0 < sum(len(source["text"]) for source in data["sources"]) <= 12000
    assert {source["id"] for source in data["sources"]} == {"s0"}
    assert len(data["images"]) == 1
    image = data["images"][0]
    assert image["id"] == "i0" and image["source_id"] == "s0"
    assert image["source_url"] == data["sources"][0]["url"]
    assert image["caption_kind"] == "local_visual_description"
    assert image["relevance_score"] == 0.9
    assert image["render_url"].startswith("/cache/")
    assert "local_path" not in image and "cached_image_url" not in image
    assert client.get(image["render_url"]).status_code == 401
    assert client.get(image["render_url"], headers=headers).content == b"test image bytes"
    assert len(calls) == 1 and unloaded == ["generator", "ranker"]


def test_evidence_cache_is_separate_from_answers_and_honors_refresh(evidence_service):
    client, calls, _, _ = evidence_service
    query = "Why shadows?"
    answer_key = service.answer_cache.key(
        service.cache_parameters(service.SearchRequest(query=query))
    )
    service.answer_cache.put(
        answer_key,
        {"query": query, "title": "Cached answer", "blocks": [], "sources": [], "images": []},
    )
    for expected_hit in (False, True):
        response = client.post("/api/evidence", json={"query": query, "max_images": 1})
        assert response.status_code == 200
        assert response.json()["cache_hit"] is expected_hit
        assert response.json()["mode"] == "evidence"
        assert response.json()["images"][0]["id"] == "i0"
    assert len(calls) == 1
    refreshed = client.post(
        "/api/evidence", json={"query": query, "max_images": 1, "refresh": True}
    )
    assert refreshed.status_code == 200 and refreshed.json()["cache_hit"] is False
    larger = client.post("/api/evidence", json={"query": query, "max_images": 2})
    assert larger.status_code == 200 and len(larger.json()["images"]) == 2
    assert len(calls) == 3
    original = client.post("/api/search", json={"query": query})
    assert original.status_code == 200 and original.json()["title"] == "Cached answer"


def test_evidence_without_downloadable_images_still_returns_text(evidence_service, monkeypatch):
    client, _, _, images = evidence_service

    def download_failed(url):
        raise ValueError("Image origin unavailable")

    monkeypatch.setattr(service, "cache_image", download_failed)
    failed = client.post("/api/evidence", json={"query": "Why shadows?"})
    assert failed.status_code == 200
    assert failed.json()["images"] == [] and failed.json()["sources"][0]["text"]
    assert failed.json()["retrieval_errors"]
    images.clear()
    empty = client.post("/api/evidence", json={"query": "Why shadows?", "refresh": True})
    assert empty.status_code == 200
    assert empty.json()["images"] == [] and empty.json()["sources"][0]["text"]


def test_evidence_busy_and_failed_requests_release_resources(evidence_service, monkeypatch):
    client, _, unloaded, _ = evidence_service
    # Exercise the admission timeout without spending 60 seconds holding a lock.
    with monkeypatch.context() as admission:
        locked = Mock(acquire=Mock(return_value=False))
        admission.setattr(service, "request_lock", locked)
        busy = client.post("/api/evidence", json={"query": "Why shadows?"})
        assert busy.status_code == 409 and busy.headers["retry-after"] == "10"
        locked.acquire.assert_called_once_with(timeout=60)
        locked.release.assert_not_called()

    def failed_retrieval(request):
        raise ValueError("No readable sources retrieved")

    monkeypatch.setattr(service, "retrieve_evidence", failed_retrieval)
    failed = client.post("/api/evidence", json={"query": "Why shadows?"})
    assert failed.status_code == 503
    assert service.request_lock.acquire(blocking=False)
    service.request_lock.release()
    assert unloaded == ["generator", "ranker"]


@pytest.mark.parametrize("max_images", [0, 9])
def test_evidence_validates_image_budget(evidence_service, max_images):
    client, calls, _, _ = evidence_service
    response = client.post(
        "/api/evidence", json={"query": "Why shadows?", "max_images": max_images}
    )
    assert response.status_code == 422 and not calls
