# Architecture

## Request path

1. **Admission.** A shared workspace credential protects search and cached media. Browser sessions use HttpOnly cookies; API clients use bearer headers. The service limits POST frequency, validates JSON, and admits one GPU request at a time.
2. **Recent answer lookup.** SQLite caches up to 256 completed answers with a configurable TTL. Identity includes the query, evidence options, implementation, model/checkpoint metadata and budgets. Cache hits avoid repeated inference; with the shared-GPU lifecycle they still pass resource and model admission.
3. **Discovery and reading.** A managed SearXNG endpoint or DDGS discovers public pages. Explicit source URLs skip discovery. Fetching validates public addresses before each redirect and pins the connection to a validated address while retaining hostname/TLS verification. HTML extraction retains page text, figures, captions and source URLs.
4. **Visual descriptions.** Candidate images are fetched under type, byte and resolution limits. The configured local or API vision model describes visible content. Publisher captions and model descriptions are labeled separately; content/model/prompt-keyed caching avoids repeated description work.
5. **Ranking and generation.** A task-tuned query–caption cross-encoder, when installed, scores candidate images. Cosine similarity is the fallback. Redundancy control limits repeated illustrations. Relevant text chunks and selected image descriptions enter a bounded Qwen prompt.
6. **Evidence resolution.** Only known source and image IDs survive parsing. Duplicate image placements are removed. A semantic placement fallback can attach selected images when prose omitted valid image markers; it does not invent text citations. Truncated answers are rejected.
7. **Delivery.** The API returns structured answer blocks and source cards. The browser renders text through DOM text nodes, supports image zoom and export, and retains up to twelve searches locally.

## Storage

Agent integrations can call `POST /api/evidence` to stop before answer generation. This path shares admission, discovery, visual descriptions and ranking with search, packs at most 12,000 text characters, and caches downloadable selected images. Source metadata remains available even when its text is omitted from the budget. Evidence and complete answers use distinct cache keys. The DeepSeek Harness plugin imports the selected images into Harness and passes image destinations and original source links to its own answer model.

| Path | Contents | Lifecycle |
|---|---|---|
| `models/` | Pinned upstream model resources | Read-only during serving |
| `runs/crossencoder/` | Optional released or locally trained image ranker | Read-only during serving |
| `data/cache/answers.sqlite3` | Recent complete answers | TTL and bounded row count |
| `data/cache/images/` | Downloaded normalized preview images | Operator-managed disk retention |
| `data/cache/captions/` | Local image descriptions | Content/model/prompt-keyed |
| `work/gpu.lock` | Interprocess GPU admission | Released on process exit |
| Browser local storage | Search history | Device-local; user can clear it |

No benchmark dataset is required for normal web searches. Training and reference evaluation are separate CLI workflows. A source file change invalidates application answer-cache identities; frozen research runs retain their own recorded implementation hashes.

## Resource model

The local Transformers profile loads text and vision models sequentially.
The vLLM profile keeps generation in its model-server container and runs ranking
on CPU. A single Celery worker serializes inference; Redis coordinates admission
and leases, and PostgreSQL stores durable task results. See the [queue](../queue.md)
and [shared-GPU lifecycle](../model-lifecycle.md) guides.

## Trust boundaries

Webpages, captions, image content and model output are untrusted. Prompt rules identify retrieved material as data. The server resolves evidence IDs and validates network destinations; the browser avoids interpreting source/model content as HTML. These measures improve traceability but do not guarantee factual correctness or immunity to prompt injection.

The deployment administrator controls model paths, search infrastructure, API endpoints and secrets. A shared workspace token provides workspace access, not separate user identities. HTTPS termination and controlled proxy forwarding belong at the deployment boundary.
