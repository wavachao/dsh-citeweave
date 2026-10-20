# CiteWeave backend setup

[README](../README.md) · [中文说明](#中文说明) · [Plugin reference](reference.md)

The plugin calls a separate CiteWeave service. This release requires `POST /api/evidence`, provided by CiteWeave revision [`f6ac71eb6fe6335e52b9ee7a04f5a727c7fdbd24`](https://github.com/wavachao/citeweave/tree/f6ac71eb6fe6335e52b9ee7a04f5a727c7fdbd24). Use this revision rather than the backend's `main` branch. The Python service and models are not included in the plugin package.

## Requirements

- Linux, Python 3.12, and [uv](https://docs.astral.sh/uv/).
- A CUDA-capable NVIDIA GPU and a driver compatible with the pinned PyTorch CUDA 12.8 wheels. The full pipeline has been exercised on a 24 GB RTX 4090 D; other hardware is not validated.
- Approximately 50 GB free disk and outbound access to model downloads, public webpages, and the configured search provider.

See the backend's pinned [deployment guide](https://github.com/wavachao/citeweave/blob/f6ac71eb6fe6335e52b9ee7a04f5a727c7fdbd24/docs/DEPLOYMENT.md), [configuration reference](https://github.com/wavachao/citeweave/blob/f6ac71eb6fe6335e52b9ee7a04f5a727c7fdbd24/docs/CONFIGURATION.md), and [model documentation](https://github.com/wavachao/citeweave/blob/f6ac71eb6fe6335e52b9ee7a04f5a727c7fdbd24/docs/MODELS.md).

## Install and start

```sh
git clone https://github.com/wavachao/citeweave.git
cd citeweave
git checkout --detach f6ac71eb6fe6335e52b9ee7a04f5a727c7fdbd24
uv sync --frozen
cp .env.example .env
uv run python scripts/download_models.py
uv run python -m citeweave serve --host 127.0.0.1 --port 8765
```

The default model download installs the application models. The task-tuned image ranker is optional; install it with `uv run python scripts/download_ranker.py`. Without it, CiteWeave uses the documented similarity fallback.

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

在 Linux 主机上准备 Python 3.12、uv、兼容 CUDA 12.8 的 NVIDIA 驱动和约 50 GB 磁盘空间，按上方命令检出指定提交、安装依赖、下载模型并启动服务。完整流程已在 24 GB RTX 4090 D 上运行，其他硬件尚未验证。训练后的图片排序器为可选组件。

网络部署应在后端 `.env` 中设置至少 32 字符的随机 `CITEWEAVE_ACCESS_TOKEN`，并在启动 Harness 的环境中设置同一令牌。通过 HTTPS 或 SSH 隧道连接，后端地址必须能被 Harness 进程访问。图片由插件下载并存入 Harness，浏览器无需后端令牌。

先检查 `/health` 与 `/ready`，再执行上方真实 `/api/evidence` 请求，验证网页检索和 GPU 推理。健康检查本身不执行推理。若证据接口返回 `404`，检查后端提交和代理路由；返回 `409` 表示 GPU 工作进程繁忙，应等待当前任务结束后重试。
