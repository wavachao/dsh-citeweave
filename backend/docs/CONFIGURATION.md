# Configuration

Copy `.env.example` to `.env` in this repository's `backend/` directory. Existing environment variables take precedence. `CITEWEAVE_ROOT` selects a different runtime root; models, runtime data, checkpoints and the `.env` file are resolved from that root. See the [vLLM installation guide](../README.md), [queue settings](../queue.md) and [lifecycle settings](../model-lifecycle.md) for the shared-GPU profile.

| Variable | Default | Purpose |
|---|---|---|
| `CITEWEAVE_ACCESS_TOKEN` | empty | Workspace credential, at least 32 characters. Required for non-loopback binding. |
| `CITEWEAVE_BACKEND` | `local` | `local` Qwen generation or `api` DeepSeek-compatible text generation. |
| `CITEWEAVE_MODEL` | `models/Qwen2.5-7B-Instruct` | Local text model directory. |
| `CITEWEAVE_VISION_MODEL` | `models/Qwen2.5-VL-3B-Instruct` | Local image-description model. |
| `CITEWEAVE_EMBEDDING_MODEL` | `models/bge-small-en-v1.5` | Local embedding model. |
| `CITEWEAVE_RANKER` | `runs/ranker/best.pt` | Optional residual-ranker checkpoint. A deployed cross-encoder takes precedence. |
| `CITEWEAVE_MAX_INPUT_TOKENS` | `24576` | Maximum text input context. |
| `CITEWEAVE_MAX_NEW_TOKENS` | `1600` | Maximum generated tokens; cap exhaustion is reported as incomplete. |
| `CITEWEAVE_MAX_IMAGES` | `10` | Upper bound on selected image candidates. |
| `CITEWEAVE_CACHE_TTL` | `900` | Recent web-answer cache lifetime in seconds; `0` disables it. |
| `CITEWEAVE_RATE_LIMIT` | `10` | Maximum admitted POST requests per client address per minute. |
| `CITEWEAVE_DOH` | `0` | `1` resolves origin hostnames through Google's HTTPS DNS endpoint, bypassing polluted system DNS. Public-address validation and TLS verification still apply. |
| `SEARXNG_URL` | empty | Administrator-controlled SearXNG base URL with JSON search enabled. Empty uses DDGS. |
| `CITEWEAVE_API_BASE` | `https://api.deepseek.com` | Text generation API base URL, when API mode is selected. |
| `CITEWEAVE_API_MODEL` | `deepseek-flash` | API text model. Thinking is disabled in generation requests. |
| `DEEPSEEK_API_KEY` | empty | API credential. Never required for local generation. |
| `OPENAI_API_KEY` | empty | Optional original-judge evaluation credential. Never used by normal local searches. |

All secrets remain server-side. The browser receives a workspace session cookie after login, never the model-provider API key. API mode can incur provider charges. Vision can use a compatible API through `CITEWEAVE_VISION_BACKEND=api`; embeddings and ranking remain local and can run on CPU with `CITEWEAVE_RANKER_DEVICE=cpu`.

## Search backends

If your network needs an HTTP CONNECT proxy, set `HTTPS_PROXY`/`HTTP_PROXY` in the service environment. When system DNS returns fake or polluted addresses, `CITEWEAVE_DOH=1` can provide public origin resolution through DNS over HTTPS. This requires access to `https://dns.google`; DNS names are sent to that resolver. Private IP literals and nonpublic resolver answers remain blocked. Do not disable destination or TLS checks to work around network problems.

The default DDGS backend is convenient for individual installations. Managed workspaces should configure a controlled SearXNG service with JSON enabled. Explicit public URLs work independently of search discovery. A configured SearXNG backend is trusted infrastructure, not a user-supplied destination.

## Cache behavior

Answers live in `data/cache/answers.sqlite3`, with a maximum of 256 entries. Cache identity includes the question, explicit URLs, visual-verification choice, implementation fingerprint, model/checkpoint file metadata, backend and generation budgets. Recent answers expire by TTL; `refresh: true` fetches again. SQLite connections are scoped to individual operations.

Images live in `data/cache/images/`; visual descriptions in `data/cache/captions/`. Descriptions are keyed by image content, vision-model revision and caption prompt. The image directory is not automatically size-limited: provision a disk quota and apply an appropriate retention policy when the service is stopped. Deleting an old image may make a browser-history preview unavailable; its original source link remains usable.

Browser history stores up to 12 answers on that device. It is not synchronized to a user account and can be cleared in the sidebar. Workspaces use a shared access credential; per-user data isolation is not implemented.
