# Changelog

## [0.3.0](https://github.com/wavachao/dsh-citeweave/releases/tag/v0.3.0) — 2026-10-20

- Durable Celery retrieval jobs with a Redis broker and PostgreSQL task results, compatible with the existing synchronous evidence API.
- Bounded queue admission, single-worker processing, task lookup and queued cancellation, persistent service volumes, and result retention cleanup.
- Pinned infrastructure images and hash-locked queue dependencies.
- Empty search results and unreadable sources return evidence diagnostics instead of a generic service error; translated discovery can fall back to the original language.
- Harness declares retrieval calls non-concurrent and shows backend error details, request IDs and queue-admission guidance without automatically resubmitting failed requests.

## [0.2.0](https://github.com/wavachao/dsh-citeweave/releases/tag/v0.2.0) — 2026-10-20

- Optional Qwen3.5-9B community AWQ 4-bit backend for text assistance and visual descriptions on RTX 3060 12 GB.
- Reproducible model download with an immutable revision and `source.json`, plus a digest-pinned vLLM Compose service.
- OpenAI-compatible text and vision adapter, CPU embeddings and existing CrossEncoder, model-aware caching, and API readiness checks.
- Model-server credentials remain separate from CiteWeave workspace authentication and Harness provider configuration.
- vLLM input-token budgeting for the 8,192-token context; the original DeepSeek API behavior is retained.
- Deployment instructions, adapter regression checks and representative live evidence results. The adapter applies to a separate backend clone; the Harness tool contract is unchanged.

## [0.1.2](https://github.com/wavachao/dsh-citeweave/releases/tag/v0.1.2) — 2026-10-20

- Illustrated examples covering geology, wildlife identification, and bridge engineering.
- Source-image attribution and licenses distributed with the documentation.
- Backend deployment guide for RTX 3060 12 GB using API text generation and local vision models.
- Documentation and example images included in the installation archive.

## [0.1.1](https://github.com/wavachao/dsh-citeweave/releases/tag/v0.1.1) — 2026-10-20

- Plugin configuration page for the shared Harness Desktop/Web client.
- Backend address, masked access-token entry, timeout, and image-limit controls.
- Immediate application of saved configuration to new tool calls.
- Write-only token handling: blank input preserves the saved token; a separate action clears it.
- GUI installation and configuration instructions, with command-line and environment options retained.

## [0.1.0](https://github.com/wavachao/dsh-citeweave/releases/tag/v0.1.0) — 2026-10-20

- Native DeepSeek Harness plugin bundle for `0.2.1-rc.2`.
- Web evidence and sourced image retrieval through `citeweave_search`.
- Native image attachment storage, structured attachment references, and inline Markdown output.
- Backend authentication, configurable image limits and timeout, and retrieval diagnostics.
- English and Chinese documentation, localized plugin metadata, automated tests, and versioned release archives.
