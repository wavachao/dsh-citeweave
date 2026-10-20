# CiteWeave backend setup

[README](../README.md) · [中文说明](#中文说明) · [Plugin reference](reference.md)

The plugin calls a separate CiteWeave service. This release requires `POST /api/evidence`, provided by CiteWeave revision [`f6ac71eb6fe6335e52b9ee7a04f5a727c7fdbd24`](https://github.com/wavachao/citeweave/tree/f6ac71eb6fe6335e52b9ee7a04f5a727c7fdbd24). Use this revision rather than the backend's `main` branch. The Python service and models are not included in the plugin package.

## Requirements

- Linux, Python 3.12, and [uv](https://docs.astral.sh/uv/).
- A CUDA-capable NVIDIA GPU and a driver compatible with the pinned PyTorch CUDA 12.8 wheels. Validated configurations are RTX 3060 12 GB with API text generation and RTX 4090 D 24 GB.
- Approximately 50 GB free disk for the default model set, plus outbound access to model downloads, public webpages, and the configured search provider. The API text profile below downloads only the vision and embedding models.

See the backend's pinned [deployment guide](https://github.com/wavachao/citeweave/blob/f6ac71eb6fe6335e52b9ee7a04f5a727c7fdbd24/docs/DEPLOYMENT.md), [configuration reference](https://github.com/wavachao/citeweave/blob/f6ac71eb6fe6335e52b9ee7a04f5a727c7fdbd24/docs/CONFIGURATION.md), and [model documentation](https://github.com/wavachao/citeweave/blob/f6ac71eb6fe6335e52b9ee7a04f5a727c7fdbd24/docs/MODELS.md).

## Install

```sh
git clone https://github.com/wavachao/citeweave.git
cd citeweave
git checkout --detach f6ac71eb6fe6335e52b9ee7a04f5a727c7fdbd24
uv sync --frozen
cp .env.example .env
```

Choose one text-generation profile before downloading models.

### Local text generation

The default profile loads Qwen2.5-7B locally and has been exercised on RTX 4090 D 24 GB:

```sh
uv run python scripts/download_models.py
```

### RTX 3060 12 GB: API text generation

Set these entries in the backend's `.env`:

```dotenv
CITEWEAVE_BACKEND=api
CITEWEAVE_API_BASE=https://api.deepseek.com
CITEWEAVE_API_MODEL=deepseek-flash
DEEPSEEK_API_KEY=your-provider-key
CITEWEAVE_MAX_INPUT_TOKENS=8192
CITEWEAVE_MAX_NEW_TOKENS=512
```

Text tasks use the configured API; visual descriptions and image ranking remain local. This profile needs no 7B text-model weights or tokenizer. Download the two required models using the backend's pinned revisions:

```sh
uv run python - <<'PY'
import json
from huggingface_hub import snapshot_download
from scripts.download_models import MODELS, ROOT

for repo in ('Qwen/Qwen2.5-VL-3B-Instruct', 'BAAI/bge-small-en-v1.5'):
    revision = MODELS[repo]
    destination = ROOT / 'models' / repo.split('/')[-1]
    snapshot_download(
        repo, revision=revision, local_dir=destination, max_workers=3,
        allow_patterns=['*.json', '*.safetensors', '*.txt', '*.model', '*.jinja', 'LICENSE*', 'README.md'],
    )
    (destination / 'source.json').write_text(json.dumps({'repo': repo, 'revision': revision}, indent=2))
PY
```

A cold evidence request with visual verification, one source page, and one returned image completed in approximately 25 seconds on an RTX 3060 12 GB with 32 GB system RAM. GPU memory sampled at 500 ms intervals peaked at 7,838 MiB. These figures describe that request; page size, image count, caching, and provider latency affect subsequent requests. Start with the plugin's `timeoutMs: 300000` and `maxImages: 3`.

The task-tuned image ranker is optional; install it with `uv run python scripts/download_ranker.py`. Without it, CiteWeave uses the documented similarity fallback. The RTX 3060 validation included the released ranker.

## Start the service

```sh
uv run python -m citeweave serve --host 127.0.0.1 --port 8765
```

For network deployment, set `CITEWEAVE_ACCESS_TOKEN` to a random value of at least 32 characters in the backend's `.env`. Generate one locally:

```sh
uv run python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Set the same token in the environment that starts Harness. Keep the application port private and use an HTTPS reverse proxy or SSH tunnel. The backend's deployment guide also covers Docker, TLS termination, and persistent volumes.

## Verify the evidence API

In a second terminal:

```sh
curl -f http://127.0.0.1:8765/health
curl -f http://127.0.0.1:8765/ready
```

These check process and model-file availability. Confirm retrieval and GPU inference with a real evidence request:

```sh
curl -f http://127.0.0.1:8765/api/evidence \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $CITEWEAVE_ACCESS_TOKEN" \
  -d '{"query":"How did Eratosthenes measure Earth?","urls":["https://en.wikipedia.org/wiki/Eratosthenes"],"verify_images":true,"max_images":3}'
```

For an unprotected loopback deployment, omit the Authorization header. A successful response has `mode: "evidence"`, `sources`, `images`, and `retrieval_errors`. An empty image list is valid when no suitable image is found. `404` at this endpoint usually indicates the wrong backend revision or an incorrect reverse-proxy route.

The endpoint returns evidence without generating the final answer. It may use the text model to translate a search query and the vision model to describe images. See the pinned [API reference](https://github.com/wavachao/citeweave/blob/f6ac71eb6fe6335e52b9ee7a04f5a727c7fdbd24/docs/API.md#post-apievidence).

## Remote connection

`CITEWEAVE_ENDPOINT` must be reachable from the Harness process, not just from the browser. If Harness and CiteWeave run on different hosts, an SSH tunnel can expose the backend locally on the Harness host:

```sh
ssh -N -L 8765:127.0.0.1:8765 user@backend-host
```

Then use `CITEWEAVE_ENDPOINT=http://127.0.0.1:8765`. Authenticated image downloads pass through the plugin and are imported into Harness storage, so backend tokens do not appear in the final image URLs.

Run one backend worker per GPU. The service rejects overlapping expensive requests with `409`; it does not provide a multi-tenant inference queue. Preserve the model, ranker, configuration, and data directories according to the backend deployment guide.

## 中文说明

本插件需要独立运行的 CiteWeave GPU 服务，且必须具备 `POST /api/evidence`。请使用本文固定的 `f6ac71e…` 提交；后端 `main` 分支目前没有此接口。

在 Linux 主机上准备 Python 3.12、uv 和兼容 CUDA 12.8 的 NVIDIA 驱动，按上方命令检出指定提交、安装依赖并选择文本模式。默认本地文本模式的完整模型集建议预留约 50 GB 磁盘空间，已在 RTX 4090 D 24 GB 上运行。

RTX 3060 12 GB 使用本文的 **API 文本模式**：设置 `CITEWEAVE_BACKEND=api` 和提供方密钥，仅下载视觉与嵌入模型，无需本地 7B 文本模型。图像描述和排序仍在本机 GPU 执行。32 GB 系统内存的 RTX 3060 上，一次包含视觉验证的冷启动请求约 25 秒，返回一张图片，观测显存峰值为 7,838 MiB；这不代表所有问题的固定耗时或最高占用。插件可先设置超时 `300000` 毫秒、最多 `3` 张图片。训练后的图片排序器为可选组件，本次验证已包含该排序器。

网络部署应在后端 `.env` 中设置至少 32 字符的随机 `CITEWEAVE_ACCESS_TOKEN`，并在启动 Harness 的环境中设置同一令牌。通过 HTTPS 或 SSH 隧道连接，后端地址必须能被 Harness 进程访问。图片由插件下载并存入 Harness，浏览器无需后端令牌。

先检查 `/health` 与 `/ready`，再执行上方真实 `/api/evidence` 请求，验证网页检索和 GPU 推理。健康检查本身不执行推理。若证据接口返回 `404`，检查后端提交和代理路由；返回 `409` 表示 GPU 工作进程繁忙，应等待当前任务结束后重试。
