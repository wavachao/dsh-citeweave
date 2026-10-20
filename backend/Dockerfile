# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:0.11.8 AS uv
FROM python:3.12-slim-bookworm
COPY --from=uv /uv /uvx /bin/
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates libgomp1 libglib2.0-0 libgl1 git \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 citeweave && useradd --uid 10001 --gid 10001 --create-home citeweave
WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH" UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_NO_CACHE=1 CITEWEAVE_ROOT=/app HF_HOME=/app/.cache/huggingface
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY README.md LICENSE ./
RUN uv sync --frozen --no-dev \
    && mkdir -p data models runs work .cache \
    && chown -R citeweave:citeweave /app
USER citeweave
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/health', timeout=3)"
CMD ["python", "-m", "citeweave", "serve", "--host", "0.0.0.0", "--port", "8765"]
