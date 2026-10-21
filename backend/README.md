# Qwen3.5-9B backend with vLLM

[Plugin README](../README.md) · [Backend options](../docs/backend.md) · [中文说明](#中文说明)

The backend retrieves web evidence, describes images with Qwen3.5-9B through
vLLM, and ranks candidates on CPU. It serves `POST /api/evidence` for the DSH
plugin and `POST /api/search` for the included web application.

Complete application source, the durable queue and shared-GPU lifecycle are
included here. See [THIRD_PARTY.md](THIRD_PARTY.md) for upstream provenance and
licenses.

## Model configuration

| Component | Configuration |
| --- | --- |
| Base model | [Qwen/Qwen3.5-9B](https://huggingface.co/Qwen/Qwen3.5-9B) |
| Community quantization | [cyankiwi/Qwen3.5-9B-AWQ-4bit](https://huggingface.co/cyankiwi/Qwen3.5-9B-AWQ-4bit/tree/e4d2d39cede8c5d1716d824cd843e2889c648083) |
| Weight revision | `e4d2d39cede8c5d1716d824cd843e2889c648083` |
| Stored quantization | `compressed-tensors`, group size 32, symmetric INT4; vLLM automatically selects the Marlin kernel |
| Model server | vLLM `0.24.0`; immutable Docker digest in [compose.yml](compose.yml) |
| Served model alias | `citeweave-qwen3.5-9b-awq-e4d2d39` |
| Model context | 8,192 tokens |
| Scheduling | One model request at a time; chunked prefill; eager execution |
| Visual input | One image per model request, at most 262,144 pixels |
| Ranking | Existing embedding model and released CrossEncoder on CPU |

Use automatic quantization detection: this snapshot stores
`compressed-tensors`, which vLLM serves with its Marlin kernel.

## Requirements

- Linux, Python 3.12, [uv](https://docs.astral.sh/uv/), Docker Compose with GPU support, and [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html).
- A 12 GB NVIDIA GPU and sufficient host RAM for Python and CPU ranking. This deployment has been exercised on an RTX 3060 12 GB with 32 GB system RAM.
- An NVIDIA driver compatible with the pinned CUDA 13.0 model-server container.
- Disk space for the model snapshot (approximately 9.1 GB), container image, Python environment, embeddings, ranker, and caches. Outbound access is required for initial downloads and subsequent public-web retrieval.

## 1. Install the included backend

Clone this repository and enter its backend directory:

```sh
git clone --branch v0.5.1 --depth 1 https://github.com/wavachao/dsh-citeweave.git
cd dsh-citeweave
git switch -c deploy/citeweave
cd backend
uv sync --frozen --python 3.12 --no-dev
cp .env.example .env
```

All subsequent commands run from `dsh-citeweave/backend`. Python dependencies,
including Celery, Redis and PostgreSQL clients, are resolved in `uv.lock`.
Source code, deployment templates and tests are included in this repository.
Keep credentials, downloaded models and runtime data outside version control.

[GitHub Releases](https://github.com/wavachao/dsh-citeweave/releases) also provide
Python wheel and source-distribution archives with SHA-256 checksums. The
tagged checkout above includes the model download scripts, Compose files,
service templates and lock file used by this deployment guide.

## 2. Download the model and ranking assets

Use the locked Python environment:

```sh
uv run python download_model.py \
  --output models/Qwen3.5-9B-AWQ-4bit
```

The downloader uses the fixed revision and Hugging Face's resumable cache. It writes `source.json` only after the snapshot completes and rejects a directory marked with a different revision.

Download the backend's pinned embedding model and existing released ranker:

```sh
uv run python - <<'PY'
import json
from huggingface_hub import snapshot_download
from scripts.download_models import MODELS, ROOT

repo = 'BAAI/bge-small-en-v1.5'
destination = ROOT / 'models' / repo.split('/')[-1]
snapshot_download(repo, revision=MODELS[repo], local_dir=destination, max_workers=3)
(destination / 'source.json').write_text(
    json.dumps({'repo': repo, 'revision': MODELS[repo]}, indent=2)
)
PY
uv run python scripts/download_ranker.py
```

The ranker downloader verifies the release checksums.

## 3. Start the model server

From the backend directory:

```sh
export CITEWEAVE_MODEL_DIR="$(pwd)/models/Qwen3.5-9B-AWQ-4bit"
docker compose -f compose.yml up -d
docker compose -f compose.yml logs --follow vllm
```

The container mounts the snapshot read-only, serves offline, and binds to `127.0.0.1:8000`. Its restart policy is `no`, so a reboot does not reserve the shared GPU. The supplied local configuration does not require a model-server API key. For automatic startup on demand and idle memory release, configure the [shared-GPU lifecycle](model-lifecycle.md) with the queued backend.

Check the served alias once initialization completes:

```sh
curl -f http://127.0.0.1:8000/v1/models
curl -f http://127.0.0.1:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"citeweave-qwen3.5-9b-awq-e4d2d39","messages":[{"role":"user","content":"Reply with OK."}],"max_tokens":16,"chat_template_kwargs":{"enable_thinking":false}}'
```

## 4. Configure and start CiteWeave

Set these values in `.env`:

```dotenv
CITEWEAVE_BACKEND=api
CITEWEAVE_API_TYPE=vllm
CITEWEAVE_API_BASE=http://127.0.0.1:8000/v1
CITEWEAVE_API_MODEL=citeweave-qwen3.5-9b-awq-e4d2d39
CITEWEAVE_API_KEY=
CITEWEAVE_VISION_BACKEND=api
CITEWEAVE_VISION_API_BASE=http://127.0.0.1:8000/v1
CITEWEAVE_VISION_API_MODEL=citeweave-qwen3.5-9b-awq-e4d2d39
CITEWEAVE_VISION_API_KEY=
CITEWEAVE_RANKER_DEVICE=cpu
CITEWEAVE_MAX_INPUT_TOKENS=6144
CITEWEAVE_MAX_NEW_TOKENS=1600
DEEPSEEK_API_KEY=
```

Generate a separate CiteWeave workspace token:

```sh
uv run python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Save it as `CITEWEAVE_ACCESS_TOKEN` in that `.env`. It protects the evidence API and cached images, independently of model-server keys and Harness model-provider credentials.

```sh
uv run python -m citeweave serve --host 127.0.0.1 --port 8765
```

Vision endpoint, model alias and key inherit the corresponding text settings when omitted. Explicit vision settings allow a separate compatible endpoint. vLLM requests disable thinking through `chat_template_kwargs`. The input budget reserves room within the model context for completion and template overhead.

For a remote model service, configure its authentication and HTTPS or a private tunnel, then set its API keys in the backend.

## 5. Verify retrieval and connect Harness

```sh
curl -f http://127.0.0.1:8765/ready
```

Readiness checks embedding assets and performs an authenticated `/models` probe requiring the configured vision alias. It does not run inference. For a real evidence request, set `CITEWEAVE_ACCESS_TOKEN` in the terminal to the workspace token saved above:

```sh
curl -f http://127.0.0.1:8765/api/evidence \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $CITEWEAVE_ACCESS_TOKEN" \
  -d '{"query":"埃拉托色尼如何测量地球周长？","urls":["https://en.wikipedia.org/wiki/Eratosthenes"],"verify_images":true,"max_images":3,"refresh":true}'
```

Successful results contain source text and selected images. Visually described images use `caption_kind: "api_visual_description"`. Individual retrieval failures remain visible in `retrieval_errors`; usable sources and pictures can still be returned.

In Harness, open **Plugins → Installed plugins → CiteWeave → Configure CiteWeave**. Set the backend address and workspace token. Use a 300,000 ms timeout and three images, then ask an illustrated question.

## Hardware and performance

The deployment has been validated on an RTX 3060 12 GB with 32 GB system RAM.
The pinned vLLM profile reserves approximately 10.5 GiB of GPU memory while
running. The [benchmark report](../benchmarks/README.md) records measured DSH
requests, configurations and outputs.

## Caching and operation

For sustained or shared use, deploy the [Celery, Redis and PostgreSQL queue](queue.md).
It provides durable pending work and stored task results while preserving the
synchronous evidence endpoint used by existing Harness installations.

Source images pass through public-address validation and the JPEG resize cache before being sent as data URIs. The model server receives image bytes rather than fetching remote URLs.

Caption cache identities include endpoint, model alias, API type, prompt and image bytes. Use a new alias when changing weights. Answer-cache identities include API settings without credentials. Preserve model weights, the CPU ranker, configuration and cache volumes according to the [backend deployment guide](../docs/backend.md).

Use one CiteWeave worker for the GPU deployment. Request serialization remains in place; it does not coordinate unrelated applications also calling vLLM.

## Regression checks

From this backend directory, run the complete CPU test suite:

```sh
uv sync --frozen --only-group ci
PYTHONPATH=src CITEWEAVE_BACKEND_SOURCE="$PWD" \
  uv run --no-sync pytest -q tests test_vllm.py test_queue.py test_model_runtime.py
uv run --no-sync ruff check src scripts tests test_vllm.py test_queue.py test_model_runtime.py
```

The CI dependency group installs no PyTorch or model weights. `--only-group ci`
replaces the current environment with the test dependencies; use a separate
checkout for testing, or restore the runtime afterward with
`uv sync --frozen --no-dev`.

The checks use mock HTTP and need no running model server, GPU or API credentials. They cover request parameters, source-address checks, resizing, credential separation, cache identities, CPU ranking and readiness. Repeat the real evidence and Harness checks after changing the model, container or serving limits.

## 中文说明

后端使用 Qwen3.5-9B 和 vLLM 描述图片，并在 CPU 上完成嵌入和排序。完整源码、队列和显存生命周期管理均包含在本目录。

进入 `dsh-citeweave/backend`，运行 `uv sync --frozen --python 3.12 --no-dev`，按上文下载模型和排序资源、配置 `.env` 并启动服务。共享 GPU 部署请继续配置 [Celery 队列](queue.md)和[按需启停](model-lifecycle.md)。在 Harness 插件配置页填写后端地址和工作区令牌。实测数据见[性能报告](../benchmarks/README.md)。
