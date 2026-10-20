# Harness on/off comparison

Twelve answers collected on 2026-10-21 (UTC+8): three questions, two runs per question and condition.

## Method

- Same prompt per question, official Harness `0.2.1-rc.2`, `deepseek-official/deepseek-flash`, thinking off, output cap 2,048 tokens, fresh session for every answer. Conditions alternated. Off retained the normal Harness tools, including `web_search` and `web_fetch`; on added only CiteWeave and its tool guidance. The model chose its tools.
- Time runs from the observed `turn_start` event to `turn_end`. CLI startup and the separate model prewarm are excluded. Before every trial, the backend lifecycle lease confirmed vLLM was healthy. All 12 readiness records have the same container start time; no GPU model loading or unloading occurred inside the measured runs. The initial 49.718-second warmup is excluded.
- Backend: RTX 3060 12 GB, Qwen3.5-9B-AWQ vision model, CPU ranker, Celery queue. Every successful recorded CiteWeave evidence response was a cache miss (`cache_hit: false`); actual `refresh` arguments are in the summaries.
- Plugin source: `b57e48958d390e7d4c9acb5c07f8a7b43f392346` (0.4.0). Backend revision: `441b803`. The same plugin implementation and backend retrieval code are included in 0.5.0.

Questions and exact prompts: [cases.json](cases.json). Full generated answers and per-run summaries: [results/2026-10-21](results/2026-10-21/). Independent factual and image review: [quality-review.md](quality-review.md).

## Results

Times are seconds. Images are embedded Markdown images in the original final answer. Sources are unique HTTP(S) Markdown links, not a correctness score.

| Question | Run | Off time | On time | Off images / sources | On images / sources |
|---|---:|---:|---:|---:|---:|
| Earth circumference | 1 | 26.524 | 26.407 | 0 / 4 | 1 / 3 |
| Earth circumference | 2 | 37.550 | 59.658 | 0 / 6 | 1 / 2 |
| Butterfly life cycle | 1 | 25.223 | 59.361 | 0 / 4 | 2 / 4 |
| Butterfly life cycle | 2 | 66.850 | 31.449 | 0 / 6 | 2 / 3 |
| HDD versus SSD | 1 | 48.189 | 51.237 | 0 / 4 | 2 / 3 |
| HDD versus SSD | 2 | 28.580 | 53.358 | 0 / 3 | 2 / 5 |

Across six answers per condition, mean time was **38.82 s off / 46.91 s on**; median was **33.07 s / 52.30 s**. CiteWeave produced illustrated answers in **6/6** runs, versus **0/6** for this baseline. All 12 turns completed. The on condition had one search-service failure followed by further model-selected calls; its full elapsed time remains in the table.

Machine-readable aggregate: [summary.json](results/2026-10-21/summary.json). Each run also records tool calls, failures, readiness, model usage, source/image metadata and the complete generated answer. Retrieved page bodies and private Harness runtime state are not published. Published answer image destinations were replaced with their exact original image URLs from the stored tool results; answer text and all original counts are unchanged. No third-party image files are redistributed.

## Limits

The Windows network resolves many public domains to fake-IP addresses. Native `web_fetch` rejected them as non-public, causing 64 failed calls in the off runs; the remote CiteWeave backend could fetch pages. This network difference affects both quality and elapsed time, so the comparison describes this deployment rather than isolating retrieval performance.

With two repeats per question, the results are descriptive. The [quality review](quality-review.md) examines facts, source traceability, and image usefulness separately.

## Reproduce

Use a checkout with the declared development dependencies installed. Supply existing credentials through environment variables; the runner does not read local credential files or SSH into any host.

```sh
export DEEPSEEK_API_KEY='...'
export CITEWEAVE_ENDPOINT='http://your-backend:8765'
export CITEWEAVE_ACCESS_TOKEN='...'
export BENCH_MODEL_READY_URL='http://your-vllm:8000/health'
export BENCH_REPEATS=2
node benchmarks/compare.mjs
```

Start and warm the model before running. `BENCH_MODEL_READY_URL` must check the actual model server, not CiteWeave `/ready`, which can admit an unloaded model. For an on-demand deployment, `BENCH_PREWARM_COMMAND` can run your lifecycle prewarm before every trial; its duration is excluded. Optional `BENCH_MODEL_READY_TOKEN` authenticates the model health check. Keep the idle window long enough for a trial, or confirm the model stayed loaded. New private runtime output defaults to ignored `benchmarks/private-runs/`; `BENCH_OUTPUT` and `BENCH_CASES` override the output directory and question file. Review and redact new runtime data before publishing it.
