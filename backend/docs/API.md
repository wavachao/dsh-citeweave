# API reference

Base URL: your own CiteWeave deployment. JSON endpoints are same-origin by default; cross-origin browser access is not enabled.

## Authentication

Protected searches and cached media accept `Authorization: Bearer <workspace-token>`. The web UI exchanges that same workspace token through `POST /api/session` with `{"token":"…"}` for an eight-hour HttpOnly, SameSite=Strict cookie. HTTPS requests receive a Secure cookie. `DELETE /api/session` clears it.

`GET /api/status` reports whether the current request needs authentication, without returning credentials. With no configured token, only loopback requests can search. Health endpoints and static UI assets are public.

## `POST /api/search`

```json
{
  "query": "How did Eratosthenes measure Earth's circumference?",
  "urls": ["https://en.wikipedia.org/wiki/Eratosthenes"],
  "verify_images": true,
  "refresh": false
}
```

| Field | Type | Behavior |
|---|---|---|
| `query` | string | Required, 2–3,000 characters. |
| `urls` | string[] | Optional, maximum five public HTTP(S) pages. Empty performs search discovery. |
| `verify_images` | boolean | Default true. Uses the local vision model to describe candidate images. |
| `refresh` | boolean | Default false. Bypasses the TTL answer cache when true. |

A successful response includes:

```json
{
  "query": "…",
  "title": "…",
  "blocks": [{"text":"…", "source_ids":["s0"], "image_id":"i0", "image_caption":"…"}],
  "sources": [{"id":"s0", "title":"…", "url":"https://…", "preview_image":{}}],
  "images": [{"id":"i0", "url":"https://…", "render_url":"/cache/…", "source_url":"https://…", "caption":"…"}],
  "mode": "live_web",
  "total_seconds": 18.4,
  "cache_hit": false,
  "created_at": 1792410000.0
}
```

The example illustrates the schema, not a stored model result. The response also includes generation usage and retrieval diagnostics. Source text is untrusted content. `image_id` may be null; not every question has a suitable illustration. The API strips raw model traces and internal image-file paths from browser responses.

## `POST /api/evidence`

Retrieves text and selects illustrations for an agent's own answer model, without generating a CiteWeave answer. Accepts the same fields as `/api/search`, plus `max_images` (integer, default 3, range 1–8). Authentication, request limits and GPU admission are shared with search. Non-English questions may still invoke the text model for search-query translation.

```json
{
  "query": "How did Eratosthenes measure Earth's circumference?",
  "urls": ["https://en.wikipedia.org/wiki/Eratosthenes"],
  "verify_images": true,
  "max_images": 3,
  "refresh": false
}
```

The result contains `query`, `sources`, `images`, `retrieval_errors`, `total_seconds`, `created_at`, `cache_hit` and `mode: "evidence"`. Sources retain their IDs, titles, original URLs and packed `text` (at most 12,000 characters in total). A source may have empty text when other evidence used the budget. Images retain their IDs, captions, relevance scores, `source_id`, original `url`, original `source_url`, and an authenticated `render_url` such as `/cache/<hash>.jpg`. Internal file paths are removed. Image content is downloaded and decoded before inclusion; failed downloads appear in `retrieval_errors`. No suitable image is a successful result with `images: []`.

Evidence has its own cache identity, including the image limit. `refresh: true` bypasses that recent-evidence cache; image descriptions and downloaded files can still be reused. Clients must fetch cached images with the same bearer header or browser session. The Harness plugin imports those bytes into its own image storage so the browser does not need a CiteWeave credential.

## Status codes

| Code | Meaning |
|---|---|
| `200` | Completed answer/evidence or valid cached result. |
| `401` | Missing/invalid workspace credential. |
| `409` | A pending job was cancelled, active cancellation was refused, or legacy execution admission timed out. |
| `413` | Request JSON exceeds 16 KiB. |
| `415` | POST body is not JSON. |
| `422` | Invalid request fields. |
| `429` | Per-address admission limit or durable queue capacity reached; inspect `Retry-After`. |
| `503` | Queue/storage unavailable, GPU busy or model execution failed. No evidence is returned. |
| `504` | The synchronous wait expired; use `X-Task-ID` with `/api/jobs/{task_id}` to recover its result. |

`GET /health` checks process liveness; `GET /ready` checks assets, the configured model API and queue dependencies. With the on-demand lifecycle, a cold model can be ready when GPU admission succeeds; readiness never starts it. Neither endpoint performs GPU inference. Request and task IDs aid server-log correlation. See [queue.md](../queue.md) for asynchronous job endpoints. The interactive OpenAPI reference is available at `/docs`.
