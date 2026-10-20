# CiteWeave backend setup

[README](../README.md) · [Qwen3.5 vLLM deployment](../backend/README.md) · [Plugin reference](reference.md) · [中文说明](#中文说明)

The plugin calls a separate CiteWeave service with `POST /api/evidence`. Use CiteWeave revision [`f6ac71eb6fe6335e52b9ee7a04f5a727c7fdbd24`](https://github.com/wavachao/citeweave/tree/f6ac71eb6fe6335e52b9ee7a04f5a727c7fdbd24), rather than the backend's `main` branch, which currently lacks this endpoint. The Python service and model weights are separate from the Harness plugin.

## Choose a deployment

| Profile | Hardware exercised | Text and vision assistance | Ranking |
| --- | --- | --- | --- |
| [Qwen3.5 vLLM](../backend/README.md) | RTX 3060 12 GB, 32 GB RAM | One pinned Qwen3.5-9B community 4-bit model served locally through vLLM | Existing embedding model and CrossEncoder on CPU |
| Original local pipeline | RTX 4090 D 24 GB | Separate local Qwen2.5 text and vision models | Original GPU ranking |

Both profiles return evidence to Harness; its configured DeepSeek model writes the final answer. The Qwen3.5 option requires no training and is supplied as an optional adapter for a dedicated backend clone. The original backend deployment can continue unchanged if it already provides the evidence API.

## RTX 3060 12 GB: Qwen3.5 vLLM

Follow the [complete deployment guide](../backend/README.md). It includes:

1. A separate backend checkout at the immutable evidence-API revision and a checked adapter patch.
2. The community model snapshot at revision `e4d2d39cede8c5d1716d824cd843e2889c648083`, with `source.json` provenance.
3. vLLM `0.24.0` through a digest-pinned Compose service, 8,192-token context, one concurrent request and one image per model call.
4. CPU embeddings and the existing released CrossEncoder.
5. Workspace authentication, real evidence checks, and GUI connection settings.

The model's stored quantization is `compressed-tensors` symmetric INT4 with group size 32. Leave vLLM's quantization detection automatic even though the repository name contains `AWQ`. Model-serving image input is bounded to 262,144 pixels. Candidate images are described sequentially, so one evidence response may still contain several pictures.

The guide records representative evidence and Harness results, plus the tested driver/container combination. Individual request timings and memory observations are not a general benchmark.

For shared or continuous service, add the [Celery, Redis and PostgreSQL queue](../backend/queue.md). It preserves the evidence API contract and stores task results for later lookup.

## Original local pipeline

For the original unpatched backend, use Linux, Python 3.12, [uv](https://docs.astral.sh/uv/), a CUDA-capable NVIDIA GPU, a driver compatible with the locked CUDA 12.8 PyTorch wheels, and approximately 50 GB free disk for the default model set:

```sh
git clone https://github.com/wavachao/citeweave.git citeweave-backend
cd citeweave-backend
git checkout --detach f6ac71eb6fe6335e52b9ee7a04f5a727c7fdbd24
uv sync --frozen --python 3.12 --no-dev
cp .env.example .env
uv run python scripts/download_models.py
uv run python scripts/download_ranker.py
uv run python -m citeweave serve --host 127.0.0.1 --port 8765
```

The trained ranker is an existing release; the downloader verifies its checksums. It is optional for this original profile, which also supports the documented similarity fallback.

See the pinned backend [deployment guide](https://github.com/wavachao/citeweave/blob/f6ac71eb6fe6335e52b9ee7a04f5a727c7fdbd24/docs/DEPLOYMENT.md), [configuration reference](https://github.com/wavachao/citeweave/blob/f6ac71eb6fe6335e52b9ee7a04f5a727c7fdbd24/docs/CONFIGURATION.md), and [model documentation](https://github.com/wavachao/citeweave/blob/f6ac71eb6fe6335e52b9ee7a04f5a727c7fdbd24/docs/MODELS.md) for additional backend settings and containers.

## Authentication and connection

For a protected backend, generate a workspace token and save it as `CITEWEAVE_ACCESS_TOKEN` in the backend's `.env`:

```sh
uv run python -c "import secrets; print(secrets.token_urlsafe(32))"
```

In Harness, open **Plugins → Installed plugins → CiteWeave → Configure CiteWeave** and enter the backend URL and the same workspace token. The plugin configuration page does not start the GPU backend or install its models. The workspace token is independent of model-server keys and Harness provider credentials.

For network deployment, keep the backend port private and use HTTPS or an SSH tunnel. The endpoint must be reachable from the Harness process, not just from the browser. A tunnel on the Harness host can expose a remote loopback backend locally:

```sh
ssh -N -L 8765:127.0.0.1:8765 user@backend-host
```

Then configure `http://127.0.0.1:8765` as the plugin's backend address. The plugin fetches authenticated image bytes and imports them into Harness storage; browser image links do not carry backend tokens.

## Verify the evidence API

```sh
curl -f http://127.0.0.1:8765/health
curl -f http://127.0.0.1:8765/ready
```

Health and readiness do not execute inference. With the vLLM adapter, readiness also probes the vision server's model list for the configured alias. Confirm retrieval and inference with a real request. Set `CITEWEAVE_ACCESS_TOKEN` in the terminal to the workspace token first:

```sh
curl -f http://127.0.0.1:8765/api/evidence \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $CITEWEAVE_ACCESS_TOKEN" \
  -d '{"query":"How did Eratosthenes measure Earth?","urls":["https://en.wikipedia.org/wiki/Eratosthenes"],"verify_images":true,"max_images":3}'
```

For an unprotected loopback deployment, omit the Authorization header. A successful response has `mode: "evidence"`, `sources`, `images`, and `retrieval_errors`. An empty image list is valid when no suitable picture is found; a failed source does not necessarily invalidate the remaining evidence. `404` usually indicates an incorrect backend revision or proxy route. The queue profile accepts concurrent submissions and returns `429` when full; legacy deployments can return `409` when a worker is busy.

The endpoint retrieves evidence without writing the final answer. It may use text assistance to translate a search query and vision inference to describe images. See the pinned [API reference](https://github.com/wavachao/citeweave/blob/f6ac71eb6fe6335e52b9ee7a04f5a727c7fdbd24/docs/API.md#post-apievidence).

Run one CiteWeave worker per GPU deployment. Preserve model, ranker, configuration and data directories according to the chosen deployment guide. The Compose model server uses `restart: unless-stopped`; manage the separate Python backend with your normal service supervisor.

## 中文说明

本插件依赖独立 CiteWeave 证据服务。请使用提供 `POST /api/evidence` 的固定提交，后端 `main` 分支目前没有此接口。

**RTX 3060 12 GB** 推荐使用 [Qwen3.5 vLLM 部署指南](../backend/README.md)：固定的社区 4-bit 权重在本地提供辅助查询和视觉描述，已有嵌入模型与 CrossEncoder 在 CPU 上运行，不重新训练。按指南在独立后端副本应用附带补丁即可，原 CiteWeave 工作目录无需修改。**RTX 4090 D 24 GB** 也可继续使用原本地文本与视觉模型方案。

两种方案都把证据交给 Harness，由原来配置的 DeepSeek 模型生成最终回答。模型服务、证据服务和 Harness 模型提供方分别配置，不能混用访问令牌。

后端部署完成后，在 Harness 插件配置页填写地址和工作区令牌即可。网络连接使用 HTTPS 或 SSH 隧道，地址必须可由 Harness 进程访问。先检查健康与就绪接口，再执行真实证据请求；图片会导入 Harness 附件存储，浏览器无需后端令牌。
