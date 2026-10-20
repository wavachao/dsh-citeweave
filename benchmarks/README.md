# Benchmarks

Compare Harness answers with and without CiteWeave using shared prompts and model settings.

## Results

| Date | Report | Answers | Quality review |
| --- | --- | --- | --- |
| 2026-10-21 | [Timing and setup](results/2026-10-21/report.md) | [Transcripts and measurements](results/2026-10-21/) | [Fact and image review](quality-review.md) |

## Run

Install the repository's development dependencies with `npm ci`, configure the backend, and warm the visual model before starting.

```sh
export DEEPSEEK_API_KEY='...'
export CITEWEAVE_ENDPOINT='http://your-backend:8765'
export CITEWEAVE_ACCESS_TOKEN='...'
export BENCH_MODEL_READY_URL='http://your-vllm:8000/health'
export BENCH_REPEATS=2
node benchmarks/compare.mjs
```

The runner alternates conditions and starts a fresh session for each answer. It records elapsed answer time, tool calls, images, source links, and model usage. Model preparation occurs before timing begins.

| Variable | Description |
| --- | --- |
| `BENCH_MODEL_READY_URL` | Model server health endpoint. |
| `BENCH_MODEL_READY_TOKEN` | Optional health-check credential. |
| `BENCH_PREWARM_COMMAND` | Optional command to prepare an on-demand model before each run. |
| `BENCH_REPEATS` | Repetitions per condition; default `2`. |
| `BENCH_CASES` | Question file; default [cases.json](cases.json). |
| `BENCH_OUTPUT` | Output directory; default `benchmarks/private-runs/`. |
