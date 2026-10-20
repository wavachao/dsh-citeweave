import os
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

ROOT = Path(os.getenv("CITEWEAVE_ROOT", ".")).resolve()
load_dotenv(ROOT / ".env", override=False)
# Clash can expose an HTTP CONNECT route and a SOCKS-only fallback together.
# HTTPX initializes every route, even when a request uses HTTPS. Reuse the
# configured HTTPS proxy for unsupported fallbacks, retaining NO_PROXY and TLS.
_https_proxy = os.getenv("https_proxy") or os.getenv("HTTPS_PROXY")
if _https_proxy and urlsplit(_https_proxy).scheme in ("http", "https"):
    for _proxy_name in ("HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
        if urlsplit(os.getenv(_proxy_name, "")).scheme.startswith("socks"):
            os.environ[_proxy_name] = _https_proxy
MODEL = os.getenv("CITEWEAVE_MODEL", str(ROOT / "models/Qwen2.5-7B-Instruct"))
VISION_MODEL = os.getenv("CITEWEAVE_VISION_MODEL", str(ROOT / "models/Qwen2.5-VL-3B-Instruct"))
EMBEDDING_MODEL = os.getenv("CITEWEAVE_EMBEDDING_MODEL", str(ROOT / "models/bge-small-en-v1.5"))
RANKER = Path(os.getenv("CITEWEAVE_RANKER", str(ROOT / "runs/ranker/best.pt")))
MAX_INPUT = int(os.getenv("CITEWEAVE_MAX_INPUT_TOKENS", "24576"))
MAX_NEW = int(os.getenv("CITEWEAVE_MAX_NEW_TOKENS", "1600"))
MAX_IMAGES = int(os.getenv("CITEWEAVE_MAX_IMAGES", "10"))
DATA = ROOT / "data"
RUNS = ROOT / "runs"
ACCESS_TOKEN = os.getenv("CITEWEAVE_ACCESS_TOKEN", "")
if ACCESS_TOKEN and len(ACCESS_TOKEN) < 32:
    raise ValueError("CITEWEAVE_ACCESS_TOKEN must contain at least 32 characters")
CACHE_TTL = int(os.getenv("CITEWEAVE_CACHE_TTL", "900"))
RATE_LIMIT = int(os.getenv("CITEWEAVE_RATE_LIMIT", "10"))
if CACHE_TTL < 0 or RATE_LIMIT < 1 or MAX_INPUT < 4096 or MAX_NEW < 64 or MAX_IMAGES < 1:
    raise ValueError("Invalid cache, rate or generation budget configuration")
