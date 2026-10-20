import copy
import json

from fastapi.testclient import TestClient

from citeweave import app as service
from citeweave.cache import AnswerCache
from citeweave.security import RequestLimiter


def test_access_control_cookies_bearer_limits_and_safe_response(monkeypatch, tmp_path):
    token = "valid-access-token-" + "a" * 32
    monkeypatch.setattr(service.config, "ACCESS_TOKEN", token)
    monkeypatch.setattr(service, "limiter", RequestLimiter(limit=20))
    monkeypatch.setattr(service, "answer_cache", AnswerCache(tmp_path / "answers.sqlite3"))
    client = TestClient(service.app)
    assert client.post("/api/search", json={"query": "Why?"}).status_code == 401
    assert client.post("/api/session", json={"token": "错误的令牌"}).status_code == 401
    assert client.post("/api/session", json={"token": token}).status_code == 200
    assert client.cookies.get("citeweave_session") == token
    assert client.get("/api/status").json()["authentication_required"] is False
    assert client.get("/").headers["content-security-policy"].find("script-src 'self'") >= 0
    key = service.answer_cache.key(service.cache_parameters(service.SearchRequest(query="Why?")))
    answer = {
        "query": "Why?",
        "title": "Reason",
        "blocks": [],
        "images": [
            {
                "id": "i0",
                "url": "https://example.com/image.jpg",
                "local_path": "/private/a.jpg",
                "cached_image_url": "http://internal/a.jpg",
            }
        ],
        "sources": [],
        "raw_response": "private model trace",
    }
    service.answer_cache.put(key, answer)
    result = client.post("/api/search", json={"query": "Why?"})
    assert result.status_code == 200 and result.json()["cache_hit"] is True
    assert "private" not in result.text and "internal" not in result.text
    assert "HttpOnly" in client.post("/api/session", json={"token": token}).headers["set-cookie"]
    assert client.delete("/api/session").status_code == 200
    assert client.post("/api/search", json={"query": "Why?"}).status_code == 401
    assert (
        client.post(
            "/api/search", headers={"Authorization": "Bearer " + token}, json={"query": "Why?"}
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/session", content="{}", headers={"Content-Type": "text/plain"}
        ).status_code
        == 415
    )
    assert (
        client.post(
            "/api/session",
            content=json.dumps({"token": "x" * 17000}),
            headers={"Content-Type": "application/json"},
        ).status_code
        == 413
    )
    monkeypatch.setattr(service, "limiter", RequestLimiter(limit=1))
    assert client.post("/api/session", json={"token": token}).status_code == 200
    assert client.post("/api/session", json={"token": token}).status_code == 429


def test_answer_cache_survives_restart_expires_and_evicts(tmp_path, monkeypatch):
    import citeweave.cache as module

    clock = [100.0]
    monkeypatch.setattr(module.time, "time", lambda: clock[0])
    path = tmp_path / "cache.sqlite3"
    cache = AnswerCache(path, ttl=20, limit=2)
    for n in range(3):
        clock[0] += 1
        cache.put(str(n), {"answer": n})
    restarted = AnswerCache(path, ttl=20, limit=2)
    assert restarted.get("0") is None and restarted.get("2") == {"answer": 2}
    clock[0] += 21
    assert restarted.get("2") is None


def test_browser_export_does_not_mutate_persisted_answer():
    original = {"images": [], "sources": [], "raw_response": "trace"}
    exported = service.browser_answer(copy.deepcopy(original), "live_web")
    assert "raw_response" not in exported and original["raw_response"] == "trace"
