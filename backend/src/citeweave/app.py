import hashlib
import logging
import os
import secrets
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__, config, model_runtime
from .cache import AnswerCache
from .engine import Engine, pack_sources
from .resources import gpu_session
from .security import RequestLimiter, authorized, denied
from .web import NoEvidenceError, cache_image, retrieve

app = FastAPI(title="CiteWeave", version=__version__)
logger = logging.getLogger("citeweave")
engine = Engine()
request_lock = threading.Lock()
limiter = RequestLimiter(limit=config.RATE_LIMIT)
answer_cache = AnswerCache(config.DATA / "cache/answers.sqlite3", ttl=config.CACHE_TTL)
static = Path(__file__).parent / "static"
runtime_fingerprint = hashlib.sha256(
    b"".join(p.read_bytes() for p in sorted(Path(__file__).parent.glob("*.py")))
).hexdigest()
images_dir = config.DATA / "images"
images_dir.mkdir(parents=True, exist_ok=True)
cache_dir = config.DATA / "cache/images"
cache_dir.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=images_dir), name="media")
app.mount("/cache", StaticFiles(directory=cache_dir), name="cache")
app.mount("/static", StaticFiles(directory=static), name="static")


@app.middleware("http")
async def admission(request: Request, call_next):
    request_id = secrets.token_hex(8)
    request.state.request_id = request_id
    protected = request.url.path.startswith(
        ("/api/search", "/api/evidence", "/api/jobs", "/cache/", "/media/")
    )
    if protected and not authorized(request):
        return denied("Access token required. Connect this workspace to continue.")
    if request.method == "POST":
        if not request.headers.get("content-type", "").startswith("application/json"):
            return denied("Expected application/json", 415)
        if len(await request.body()) > 16384:
            return denied("Request body exceeds 16 KiB", 413)
        if not limiter.allow(request.client.host):
            return JSONResponse(
                {"detail": "Too many requests. Please try again in one minute."},
                status_code=429,
                headers={"Retry-After": "60"},
            )
    response = await call_next(request)
    response.headers.update(
        {
            "X-Request-ID": request_id,
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "X-Frame-Options": "DENY",
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; "
            "font-src 'self'; img-src 'self' https: http: data:; connect-src 'self'; "
            "object-src 'none'; base-uri 'self'; frame-ancestors 'none'",
        }
    )
    if task_id := getattr(request.state, "task_id", None):
        response.headers["X-Task-ID"] = task_id
    if request.url.path.startswith(("/api/", "/cache/", "/media/")):
        response.headers["Cache-Control"] = "no-store"
    return response


class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=3000)
    urls: list[str] = Field(default_factory=list, max_length=5)
    verify_images: bool = True
    refresh: bool = False


class EvidenceRequest(SearchRequest):
    max_images: int = Field(default=3, ge=1, le=8)


class SessionRequest(BaseModel):
    token: str = Field(min_length=1, max_length=256)


@app.post("/api/session")
def session(request: Request, body: SessionRequest):
    if not config.ACCESS_TOKEN or not secrets.compare_digest(
        body.token.encode(), config.ACCESS_TOKEN.encode()
    ):
        raise HTTPException(401, "Invalid access token")
    response = JSONResponse({"connected": True})
    response.set_cookie(
        "citeweave_session",
        body.token,
        httponly=True,
        samesite="strict",
        secure=request.url.scheme == "https",
        max_age=8 * 60 * 60,
    )
    return response


@app.delete("/api/session")
def disconnect():
    response = JSONResponse({"connected": False})
    response.delete_cookie("citeweave_session")
    return response


def browser_answer(answer, mode):
    preview_images = [s["preview_image"] for s in answer["sources"] if s.get("preview_image")]
    for image in answer["images"] + preview_images:
        relative = urlparse(image.get("cached_image_url", "")).path.lstrip("/")
        if relative and (images_dir / relative).is_file():
            image["render_url"] = "/media/" + relative
        elif image.get("local_path") and Path(image["local_path"]).is_file():
            image["render_url"] = "/cache/" + Path(image["local_path"]).name
        else:
            image["render_url"] = image["url"]
        image.pop("local_path", None)
        image.pop("cached_image_url", None)
    answer.pop("raw_response", None)
    answer["mode"] = mode
    return answer


@app.get("/")
def home():
    return FileResponse(static / "index.html")


@app.get("/health")
def health():
    return {
        "status": "ok",
        "backend": os.getenv("CITEWEAVE_BACKEND", "local"),
        "local_model_ready": (Path(config.MODEL) / "model.safetensors.index.json").exists(),
        "trained_ranker_ready": (config.RUNS / "crossencoder/selected.json").exists()
        or config.RANKER.exists(),
    }


@app.get("/api/status")
def status(request: Request):
    return {
        "authentication_enabled": bool(config.ACCESS_TOKEN),
        "authentication_required": not authorized(request),
        "backend": os.getenv("CITEWEAVE_BACKEND", "local"),
    }


@app.get("/ready")
def ready():
    paths = [Path(config.EMBEDDING_MODEL)]
    if os.getenv("CITEWEAVE_VISION_BACKEND", "local") != "api":
        paths.append(Path(config.VISION_MODEL))
    if os.getenv("CITEWEAVE_BACKEND", "local") == "local":
        paths.append(Path(config.MODEL))
    available = all((p / "config.json").is_file() for p in paths)
    if available and model_runtime.enabled():
        from .jobs import broker

        try:
            model_runtime.preflight(broker)
        except HTTPException:
            available = False
    elif available and os.getenv("CITEWEAVE_VISION_BACKEND", "local") == "api":
        base = os.getenv(
            "CITEWEAVE_VISION_API_BASE",
            os.getenv("CITEWEAVE_API_BASE", "https://api.deepseek.com"),
        )
        model = os.getenv(
            "CITEWEAVE_VISION_API_MODEL",
            os.getenv("CITEWEAVE_API_MODEL", "deepseek-flash"),
        )
        key = (
            os.getenv("CITEWEAVE_VISION_API_KEY")
            or os.getenv("CITEWEAVE_API_KEY")
            or os.getenv("DEEPSEEK_API_KEY")
        )
        try:
            with httpx.Client(timeout=3) as client:
                response = client.get(
                    base.rstrip("/") + "/models",
                    headers={"Authorization": f"Bearer {key}"} if key else {},
                )
                response.raise_for_status()
                available = any(row["id"] == model for row in response.json()["data"])
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            available = False
    if available and os.getenv("CITEWEAVE_QUEUE", "") == "celery":
        from .jobs import dependencies_ready

        available = dependencies_ready()
    return JSONResponse({"ready": available}, status_code=200 if available else 503)


def cache_parameters(request):
    resources = []
    for path in (
        Path(config.MODEL) / "source.json",
        Path(config.VISION_MODEL) / "source.json",
        Path(config.EMBEDDING_MODEL) / "source.json",
        config.RUNS / "crossencoder/selected.json",
        config.RUNS / "crossencoder/best/model.safetensors",
        config.RANKER,
    ):
        if path.is_file():
            stat = path.stat()
            resources.append((str(path), stat.st_size, stat.st_mtime_ns))
    return {
        "query": request.query,
        "urls": request.urls,
        "verify_images": request.verify_images,
        "implementation": runtime_fingerprint,
        "resources": resources,
        "backend": os.getenv("CITEWEAVE_BACKEND", "local"),
        "api_model": os.getenv("CITEWEAVE_API_MODEL", "deepseek-flash"),
        "api_base": os.getenv("CITEWEAVE_API_BASE", "https://api.deepseek.com"),
        "api_type": os.getenv("CITEWEAVE_API_TYPE", "deepseek"),
        "vision_backend": os.getenv("CITEWEAVE_VISION_BACKEND", "local"),
        "vision_api_model": os.getenv(
            "CITEWEAVE_VISION_API_MODEL",
            os.getenv("CITEWEAVE_API_MODEL", "deepseek-flash"),
        ),
        "vision_api_base": os.getenv(
            "CITEWEAVE_VISION_API_BASE",
            os.getenv("CITEWEAVE_API_BASE", "https://api.deepseek.com"),
        ),
        "search": os.getenv("SEARXNG_URL", ""),
        "budgets": [config.MAX_INPUT, config.MAX_NEW, config.MAX_IMAGES],
    }


def retrieve_evidence(request):
    """Share discovery and visual descriptions between answers and agent evidence."""
    retrieval_query = request.query
    if any(ord(c) > 127 for c in request.query):
        translation = engine.generator.complete(
            "Translate this search question to English. Preserve names, numbers and formulas. "
            "Output only the translated question, do not answer it:\n" + request.query
        )
        retrieval_query = translation["response"].strip()
    try:
        sources, images, errors = retrieve(retrieval_query, request.urls)
    except NoEvidenceError as first:
        if request.urls or retrieval_query == request.query:
            raise
        # Preserve the original language when translated discovery finds no evidence.
        sources, images, errors = retrieve(request.query)
        retrieval_query = request.query
        errors = first.errors + errors
    if request.verify_images and images:
        from .vision import caption_images

        candidates = engine.ranker.select(retrieval_query, images, limit=8)
        if not candidates:
            candidates = images[:8]
        images = caption_images(candidates, engine.generator, limit=8)
    return retrieval_query, sources, images, errors


@app.post("/api/search")
def ask(request: SearchRequest, http_request: Request):
    return dispatch_search(request, http_request)


@app.post("/api/evidence")
def evidence(request: EvidenceRequest, http_request: Request):
    """Return sourced text and verified image files for the caller's own answer model."""
    return dispatch_search(request, http_request, evidence_only=True)


def dispatch_search(request, http_request, evidence_only=False):
    if model_runtime.enabled() and os.getenv("CITEWEAVE_QUEUE", "") != "celery":
        raise HTTPException(503, "On-demand models require the Celery queue")
    if os.getenv("CITEWEAVE_QUEUE", "") == "celery":
        from .jobs import submit_job, wait_for_job

        task_id = submit_job(request.model_dump(), evidence_only, http_request.state.request_id)
        http_request.state.task_id = task_id
        return wait_for_job(task_id)
    return run_search(request, http_request, evidence_only=evidence_only)


@app.post("/api/jobs", status_code=202)
def create_job(request: EvidenceRequest, http_request: Request):
    if os.getenv("CITEWEAVE_QUEUE", "") != "celery":
        raise HTTPException(503, "Durable retrieval jobs are not enabled")
    from .jobs import submit_job

    task_id = submit_job(request.model_dump(), True, http_request.state.request_id)
    http_request.state.task_id = task_id
    return {"task_id": task_id, "state": "PENDING", "status_url": f"/api/jobs/{task_id}"}


@app.get("/api/jobs/{task_id}")
def job_status(task_id: str):
    if os.getenv("CITEWEAVE_QUEUE", "") != "celery":
        raise HTTPException(503, "Durable retrieval jobs are not enabled")
    from .jobs import get_job

    return get_job(task_id)


@app.delete("/api/jobs/{task_id}")
def revoke_job(task_id: str):
    if os.getenv("CITEWEAVE_QUEUE", "") != "celery":
        raise HTTPException(503, "Durable retrieval jobs are not enabled")
    from .jobs import cancel_job

    return cancel_job(task_id)


def run_search(request, http_request, evidence_only=False):
    started = time.monotonic()
    parameters = cache_parameters(request)
    mode = "evidence" if evidence_only else "live_web"
    if evidence_only:
        parameters.update(mode=mode, max_images=request.max_images)
    key = answer_cache.key(parameters)
    cached = answer_cache.get(key) if not request.refresh else None
    if cached:
        cached.update(cache_hit=True, total_seconds=round(time.monotonic() - started, 2))
        return browser_answer(cached, mode)
    # A short queue absorbs simultaneous tool calls without overlapping GPU work.
    if not request_lock.acquire(timeout=60):
        raise HTTPException(
            409,
            "A search is already running. Please retry when it finishes.",
            headers={"Retry-After": "10"},
        )
    try:
        with gpu_session(blocking=False):
            try:
                retrieval_query, sources, images, errors = retrieve_evidence(request)
                if evidence_only:
                    selected = engine.ranker.select(
                        retrieval_query, images, limit=request.max_images
                    )
                    usable = []
                    for image in selected:
                        try:
                            path = cache_image(image["url"])
                            usable.append({**image, "local_path": str(path)})
                        except (httpx.HTTPError, ValueError, OSError) as exc:
                            errors.append({"url": image["url"], "error": str(exc)[:250]})
                    packed = pack_sources(
                        retrieval_query, sources, engine.ranker, char_budget=12000
                    )
                    texts, remaining = {}, 12000
                    for source in packed:
                        texts[source["id"]] = source["text"][:remaining]
                        remaining -= len(texts[source["id"]])
                    answer = {
                        "query": request.query,
                        "sources": [{**s, "text": texts.get(s["id"], "")} for s in sources],
                        "images": usable,
                    }
                else:
                    answer = engine.answer(
                        request.query, sources, images, retrieval_query=retrieval_query
                    )
                answer["retrieval_errors"] = errors
                answer["total_seconds"] = round(time.monotonic() - started, 2)
                answer["created_at"] = time.time()
                answer["cache_hit"] = False
                answer_cache.put(key, answer)
                return browser_answer(answer, mode)
            finally:
                engine.generator.unload()
                engine.ranker.unload()
    except NoEvidenceError as e:
        if evidence_only:
            return {
                "query": request.query,
                "sources": [],
                "images": [],
                "retrieval_errors": e.errors,
                "mode": mode,
                "cache_hit": False,
                "total_seconds": round(time.monotonic() - started, 2),
            }
        raise HTTPException(422, str(e)) from e
    except BlockingIOError as e:
        raise HTTPException(
            409,
            "The compute worker is busy. Please retry shortly.",
            headers={"Retry-After": "10"},
        ) from e
    except Exception as e:
        logger.exception("Search failed; request_id=%s", http_request.state.request_id)
        raise HTTPException(
            503,
            "Search could not be completed. Try another question or specify a public source URL.",
        ) from e
    finally:
        request_lock.release()
