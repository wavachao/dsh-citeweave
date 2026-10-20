# Harness comparison — 2026-10-21

Three questions, two runs per condition, twelve answers in total.

## Setup

| Component | Configuration |
| --- | --- |
| Harness | `0.2.1-rc.2` |
| Answer model | Official `deepseek-flash`, thinking disabled, output cap 2,048 tokens |
| Plugin | `0.4.0`, commit `b57e48958d390e7d4c9acb5c07f8a7b43f392346` |
| Backend | Revision `441b803`, RTX 3060 12 GB, Qwen3.5-9B-AWQ through vLLM, CPU ranking, Celery |
| Sessions | Fresh session for each run; conditions alternate |
| Timing | Observed `turn_start` to `turn_end`, excluding CLI startup and model preparation |

Each pair uses the same [prompt](../../cases.json). Both conditions retain native Harness tools; the enabled condition adds CiteWeave and its tool guidance. Tool selection is autonomous.

Before each run, a backend lifecycle lease checked model readiness. All twelve checks recorded the same container start time. The initial 49.718-second preparation occurred before timed runs. Successful evidence responses recorded `cache_hit: false`.

## Results

| Question | Run | Off time | On time | Off images / sources | On images / sources |
| --- | ---: | ---: | ---: | ---: | ---: |
| Earth circumference | 1 | 26.524 s | 26.407 s | 0 / 4 | 1 / 3 |
| Earth circumference | 2 | 37.550 s | 59.658 s | 0 / 6 | 1 / 2 |
| Butterfly life cycle | 1 | 25.223 s | 59.361 s | 0 / 4 | 2 / 4 |
| Butterfly life cycle | 2 | 66.850 s | 31.449 s | 0 / 6 | 2 / 3 |
| HDD versus SSD | 1 | 48.189 s | 51.237 s | 0 / 4 | 2 / 3 |
| HDD versus SSD | 2 | 28.580 s | 53.358 s | 0 / 3 | 2 / 5 |

Mean time: **38.82 s off / 46.91 s on**. Median: **33.07 s / 52.30 s**. All twelve turns completed. Images appeared in **0/6 off** and **6/6 on** answers.

Image counts use the original final Markdown; source counts use unique HTTP(S) Markdown links. Published transcripts replace local attachment destinations with the recorded original image URLs. Answer text and counts are preserved.

## Observations

The Windows network resolved several public domains to fake-IP addresses. Native `web_fetch` rejected those addresses, accounting for 64 failed calls in the off condition. The remote backend fetched pages through a different network path. These timings therefore include that network difference.

One enabled run encountered a search-service 503 before further tool calls succeeded. Its complete elapsed time is included. Both conditions contained factual or wording errors, detailed in the [quality review](../../quality-review.md).

Data: [summary.json](summary.json), [environment.json](environment.json), and the [individual answers and measurements](.).
