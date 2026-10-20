# Qwen3.5-9B backend with vLLM

[Plugin README](../README.md) · [Backend options](../docs/backend.md) · [中文说明](#中文说明)

This deployment runs CiteWeave's query assistance and image descriptions on a local Qwen3.5-9B community AWQ 4-bit model. Embeddings and the existing released CrossEncoder run on the CPU. The final Harness answer continues to use its configured DeepSeek model; installing this backend does not change that provider. No model training or fine-tuning is required.

The included adapter is an optional patch for CiteWeave revision [`f6ac71eb6fe6335e52b9ee7a04f5a727c7fdbd24`](https://github.com/wavachao/citeweave/tree/f6ac71eb6fe6335e52b9ee7a04f5a727c7fdbd24). Apply it to a separate backend checkout. The plugin protocol remains `POST /api/evidence`, so compatible deployments can continue using their current backend.

## Pinned deployment

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

The weights are published by a community distributor, rather than an official Qwen INT4 release. The model card identifies the Apache-2.0 license. The downloader preserves the upstream model files, license and README, and records the repository and revision in `source.json`.

Keep automatic quantization detection. The repository name contains `AWQ`, but its stored configuration uses `compressed-tensors`; do not add `--quantization awq` to the serving command.

## Requirements

- Linux, Python 3.12, [uv](https://docs.astral.sh/uv/), Docker Compose with GPU support, and [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html).
- A 12 GB NVIDIA GPU and sufficient host RAM for Python and CPU ranking. This deployment has been exercised on an RTX 3060 12 GB with 32 GB system RAM.
- A driver compatible with the pinned container. The validated combination used NVIDIA driver `595.99.02` and the container's PyTorch `2.11.0+cu130` / CUDA `13.0`; these are tested versions, not a claimed minimum driver requirement.
- Disk space for the model snapshot (approximately 9.1 GB), container image, Python environment, embeddings, ranker, and caches. Outbound access is required for initial downloads and subsequent public-web retrieval.

## 1. Prepare a separate backend checkout

Run from this plugin repository's root:

```sh
export CITEWEAVE_PLUGIN_DIR="$(pwd)"
cd ..
git clone https://github.com/wavachao/citeweave.git citeweave-backend
cd citeweave-backend
git checkout --detach f6ac71eb6fe6335e52b9ee7a04f5a727c7fdbd24
git apply --check "$CITEWEAVE_PLUGIN_DIR/backend/vllm-openai.patch"
git apply "$CITEWEAVE_PLUGIN_DIR/backend/vllm-openai.patch"
uv sync --frozen --python 3.12 --no-dev
cp .env.example .env
```

The adapter changes stay in this dedicated clone. The original CiteWeave checkout does not need to be modified.

## 2. Download the model and ranking assets

From the backend clone, use its locked Python environment:

```sh
uv run python "$CITEWEAVE_PLUGIN_DIR/backend/download_model.py" \
  --output models/Qwen3.5-9B-AWQ-4bit
```

The downloader uses the fixed revision and Hugging Face's resumable cache. It writes `source.json` only after the snapshot completes and rejects a directory marked with a different revision. It does not quantize or train a model.

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

The ranker downloader verifies the release checksums. Neither the original Qwen2.5 text weights nor the original Qwen2.5-VL vision weights are needed when both backend modes use the API.

## 3. Start the model server

Still in the backend clone:

```sh
export CITEWEAVE_MODEL_DIR="$(pwd)/models/Qwen3.5-9B-AWQ-4bit"
docker compose -f "$CITEWEAVE_PLUGIN_DIR/backend/compose.yml" up -d
docker compose -f "$CITEWEAVE_PLUGIN_DIR/backend/compose.yml" logs --follow vllm
```

The container mounts the snapshot read-only, serves offline, and binds to `127.0.0.1:8000`. Its restart policy is `unless-stopped`. The supplied local configuration does not require a model-server API key.

Check the served alias once initialization completes:

```sh
curl -f http://127.0.0.1:8000/v1/models
curl -f http://127.0.0.1:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"citeweave-qwen3.5-9b-awq-e4d2d39","messages":[{"role":"user","content":"Reply with OK."}],"max_tokens":16,"chat_template_kwargs":{"enable_thinking":false}}'
```

## 4. Configure and start CiteWeave

Set these values in the backend clone's `.env`:

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

For a remote model service, configure its own authentication and HTTPS or a private tunnel, then set its API keys in the backend. Harness's final-answer provider is configured separately in Harness.

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

In Harness, open **Plugins → Installed plugins → CiteWeave → Configure CiteWeave**. Set the backend address and workspace token. Start with a 300,000 ms timeout and three images. Ask an illustrated question and verify that a source-linked image loads. Leave Harness's DeepSeek answer-model configuration unchanged.

The model server accepts one image per inference request. CiteWeave captions candidates sequentially, so one evidence result or Harness answer can still contain multiple images.

## Validation scope

Representative RTX 3060 12 GB results with the pinned snapshot, container and CPU ranking:

| Request | Observed result |
| --- | --- |
| Chinese Eratosthenes question, fixed public source, forced refresh | 34.808 s; two visually described images; no retrieval errors |
| Chinese HDD/SSD question, automatic source discovery | 19.486 s; four sources and one visually described comparison image; one source returned `403` while other evidence remained usable |
| Peacock butterfly (*Aglais io*) question, fixed public source | 25.207 s; three visually described images; no retrieval errors |
| Harness with its DeepSeek Flash answer model | Final answer displayed a retrieved image with no browser script errors |

The model server reserved approximately 10.5 GiB GPU memory after startup. During the Eratosthenes request, 500 ms sampling observed a peak of 10,785 MiB. Cached-image authentication, repeated-request caching, and the existing `/api/search` endpoint were also checked. A long text prompt was truncated to the configured 6,144-token input budget and completed successfully. These are individual acceptance examples, not a throughput benchmark or a guarantee for every query, image size, or host.

## Caching and operation

For sustained or shared use, deploy the [Celery, Redis and PostgreSQL queue](queue.md).
It provides durable pending work and stored task results while preserving the
synchronous evidence endpoint used by existing Harness installations.

Source images pass through public-address validation and the JPEG resize cache before being sent as data URIs. The model server receives image bytes rather than fetching remote URLs.

Caption cache identities include endpoint, model alias, API type, prompt and image bytes. Use a new alias when changing weights. Answer-cache identities include API settings without credentials. Preserve model weights, the CPU ranker, configuration and cache volumes according to the [backend deployment guide](../docs/backend.md).

Use one CiteWeave worker for the GPU deployment. Request serialization remains in place; it does not coordinate unrelated applications also calling vLLM.

## Regression checks

From the patched backend clone:

```sh
CITEWEAVE_BACKEND_SOURCE="$PWD" \
  uv run python "$CITEWEAVE_PLUGIN_DIR/backend/test_vllm.py"
```

The checks use mock HTTP and need no running model server, GPU or API credentials. They cover request parameters, source-address checks, resizing, credential separation, cache identities, CPU ranking and readiness. Repeat the real evidence and Harness checks after changing the model, container or serving limits.

## 中文说明

此方案使用固定版本的 **Qwen3.5-9B 社区 AWQ 4-bit 权重**，通过 vLLM 为 CiteWeave 提供辅助查询与视觉描述；嵌入模型和已有 CrossEncoder 在 CPU 上运行，无需重新训练。Harness 的最终回答仍由原来配置的 DeepSeek 模型生成。

按本文步骤，在插件仓库旁建立独立 CiteWeave 后端副本，检出指定提交并应用附带补丁；原 CiteWeave 工作目录无需修改。在后端锁定的 Python 环境中运行 `download_model.py`，下载固定模型快照并记录 `source.json`，再下载嵌入模型和现有排序器。随后使用 Compose 启动固定镜像、配置后端 `.env`，运行证据接口检查，并在 Harness 插件页面填写后端地址和工作区令牌。

已验证 RTX 3060 12 GB、32 GB 系统内存，8,192-token 上下文、单并发、单次推理最多一张图片和 262,144 像素。后端会顺序描述多张候选图，一次检索仍可返回多张图片。代表性请求与显存观测见上表，不能视为所有问题的性能保证。模型服务、证据服务与 Harness 模型提供方各自使用独立配置；图形配置页不负责启动 GPU 后端。
