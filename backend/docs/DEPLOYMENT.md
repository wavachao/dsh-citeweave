# Deployment

CiteWeave supports a single protected workspace on a Linux NVIDIA host. Run commands from this repository's `backend/` directory. For the vLLM deployment, use the [backend installation guide](../README.md), [durable queue](../queue.md) and [shared-GPU lifecycle](../model-lifecycle.md). The remaining instructions describe the optional local Transformers profile.

## Local service

Install uv, Python 3.12 and a driver compatible with the pinned CUDA 12.8 PyTorch wheels. From `backend/`, run `uv sync --frozen`, copy `.env.example` to `.env`, and run `uv run python scripts/download_models.py`. Optionally install the released ranker with `uv run python scripts/download_ranker.py`.

```bash
uv run python -m citeweave serve --host 127.0.0.1 --port 8765
```

Loopback mode can run without an access token. For network binding, set a random `CITEWEAVE_ACCESS_TOKEN` of at least 32 characters. The CLI refuses unprotected non-loopback binding, and application middleware independently rejects unauthenticated non-loopback search requests.

## Container service

Install Docker Compose and NVIDIA Container Toolkit. Download the application models into `./models` before starting. For a container-only setup, uv can run the downloader without installing the full application on the host:

```bash
uv run --no-project --with huggingface-hub python scripts/download_models.py
mkdir -p runs
docker compose -f compose.yaml up --build -d
docker compose -f compose.yaml logs -f citeweave
```

The image runs as UID/GID 10001, drops Linux capabilities, and disables privilege escalation. The Compose file requires `CITEWEAVE_ACCESS_TOKEN`; generate it and save it in `.env` before startup. Model files must be readable by that UID. Model and trained-ranker directories are read-only mounts; data and work directories use persistent named volumes.

The host port binds to `127.0.0.1`, preserving a private application boundary. The default CUDA environment and model-loading path are intended for NVIDIA Linux hosts, not macOS or CPU-only inference.

## HTTPS reverse proxy

Terminate TLS at a reverse proxy. Keep the application port private. An Nginx location can use:

```nginx
location / {
    proxy_pass http://127.0.0.1:8765;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    client_max_body_size 16k;
    proxy_read_timeout 300s;
    proxy_send_timeout 300s;
}
```

For HTTPS cookie security behind a trusted local proxy, run Uvicorn directly with an explicit trusted proxy address:

```bash
uv run uvicorn citeweave.app:app --host 127.0.0.1 --port 8765 \
  --proxy-headers --forwarded-allow-ips=127.0.0.1
```

Do not trust arbitrary forwarded headers. The normal CLI disables proxy-header trust. A proxy may coalesce client addresses, so the in-process rate limit can become workspace-wide; add per-client limits at the proxy if needed. Workspace tokens belong in an Authorization header or the HttpOnly session cookie, never in a URL.

## Health and acceptance

- `GET /health`: process liveness and model-asset summary; it does not load GPU models.
- `GET /ready`: local model config availability, returning `503` until required assets are present. This is an asset check, not a successful-inference guarantee.
- Submit a real `/api/search` request with a fixed public source URL to validate the GPU, retrieval and complete pipeline.
- Confirm that an unauthenticated search returns `401`, a second identical search returns `cache_hit: true`, and an explicit refresh regenerates.
- Verify fonts, source links, image loading and export in the browser.

Do not expose the service publicly until the authenticated acceptance check succeeds. The service is designed for a trusted team workspace, not anonymous unmetered traffic.

## Persistence, backups and updates

Back up `runs/crossencoder` and environment configuration separately from the repository. Back up the data volume for cached answers and images only if retention is desired; these are regenerable. Stop the service or use SQLite's backup API before copying a live database. Provider keys and workspace tokens must not be committed or included in public support logs.

For an update, preserve model/ranker/data volumes, pull a chosen release, rebuild, and repeat readiness plus one real search. Implementation changes invalidate recent-answer cache keys. Manage image-cache retention through disk quotas or maintenance while the service is stopped.
