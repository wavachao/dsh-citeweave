# Backend setup

The Python backend is maintained in this repository's [backend directory](https://github.com/wavachao/dsh-citeweave/tree/main/backend). It provides the evidence API used by the Harness plugin.

## Deployment

Follow the [deployment guide](https://github.com/wavachao/dsh-citeweave/blob/main/backend/README.md) for Python dependencies, model downloads, vLLM, and service configuration. The reference deployment uses an RTX 3060 12 GB with 32 GB RAM.

| Component | Role |
| --- | --- |
| Qwen3.5-9B, vLLM | Query assistance and image descriptions |
| CPU embeddings and CrossEncoder | Evidence and image ranking |
| Celery and Redis | Retrieval queue and worker coordination |
| PostgreSQL | Task states and results |
| DeepSeek in Harness | Final answer |

See the [queue guide](https://github.com/wavachao/dsh-citeweave/blob/main/backend/queue.md) for task admission and persistence, and the [model lifecycle guide](https://github.com/wavachao/dsh-citeweave/blob/main/backend/model-lifecycle.md) for shared-GPU operation.

## Connect Harness

In **Plugins → Installed plugins → CiteWeave → Configure CiteWeave**, enter the service address and the value of `CITEWEAVE_ACCESS_TOKEN` from the backend environment.

The address must be reachable from the Harness process. For remote access, use a private network, HTTPS, or an SSH tunnel:

```sh
ssh -N -L 8765:127.0.0.1:8765 user@backend-host
```

The backend workspace token is separate from the DeepSeek provider key.

## Verify

```sh
curl -f http://127.0.0.1:8765/health
curl -f http://127.0.0.1:8765/ready

curl -f http://127.0.0.1:8765/api/evidence \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $CITEWEAVE_ACCESS_TOKEN" \
  -d '{"query":"How did Eratosthenes measure Earth?","urls":["https://en.wikipedia.org/wiki/Eratosthenes"],"verify_images":true,"max_images":3}'
```

Health and readiness checks do not load the model. The first retrieval request starts it when needed. Successful evidence responses include `sources`, `images`, and retrieval diagnostics.

## 中文说明

后端完整源码位于本仓库的 [backend/](https://github.com/wavachao/dsh-citeweave/tree/main/backend)，与插件统一维护和发布。按照[部署指南](https://github.com/wavachao/dsh-citeweave/blob/main/backend/README.md)启动服务后，在 Harness 插件配置页填写服务地址与工作区令牌即可。最终回答由 Harness 配置的 DeepSeek 模型生成。
