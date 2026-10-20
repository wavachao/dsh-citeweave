# DeepSeek proxy evaluation

This is a separate judge protocol, not the paper's GPT-4o/GPT-4o-mini result. Both methods receive the same judge, prompts, context trimming and pooling. The eight metrics are retained: four text metrics, three image precision metrics and local image recall. Original predictions and the evaluator checkout remain unchanged.

The [official Vision documentation](https://api-docs.deepseek.com/guides/vision/) supports images in `deepseek-flash`. As checked on 2026-10-19, the [pricing page](https://api-docs.deepseek.com/quick_start/pricing/) maps that alias to DeepSeek-V4.1-Flash-1017. The alias can change; the spending ledger records returned model names and available system fingerprints.

## Completed, authorized pilot

The pilot uses 20 identical questions per method: base original multi-stage versus base CiteWeave, 40 existing answers. IDs are ordered by SHA256(`42:query_id`), without selecting favorable scores. Copies retain parent bytes and hashes. This pilot is a diagnostic, not a full 194-query result.

The recorded pilot used **USD 2 total across both methods**. Both runs share the same budget batch. For a new experiment, configure `DEEPSEEK_API_KEY` in the local `.env`, choose a new run identity and explicitly set the evaluation budget. Never reuse or reset an existing spending ledger to bypass its total. Full 194-query inputs were prepared, but no full paired quality scores were computed.

The pilot is complete and validated: original multi-stage overall 0.7271848, CiteWeave 0.7191391, paired difference -0.0080457 with 95% query-bootstrap interval [-0.0609008, 0.0476231]. This provides no evidence of overall superiority or equivalence. The 700 corrected-protocol requests all ended with `stop`; both methods used the same returned system fingerprint. See `RESULTS.md` for all metrics. The budget ledger, including the interrupted earlier attempt, has a conservative upper bound of USD 1.2502971, not an actual invoice. The key remains only in the private server environment.

```bash
# No API requests; already completed on the server.
.venv-eval/bin/python scripts/evaluate_official.py runs/comparison-v1-base-multi-proxy-pilot-v1 --judge-protocol deepseek --prepare-only
.venv-eval/bin/python scripts/evaluate_official.py runs/comparison-v1-base-citeweave-proxy-pilot-v1 --judge-protocol deepseek --prepare-only

# Paid: same ledger, USD 2 combined, after key configuration.
.venv-eval/bin/python scripts/evaluate_official.py runs/comparison-v1-base-multi-proxy-pilot-v1 --judge-protocol deepseek --allow-paid-evaluation --budget-usd 2 --budget-batch paired-proxy-pilot-v1
.venv-eval/bin/python scripts/evaluate_official.py runs/comparison-v1-base-citeweave-proxy-pilot-v1 --judge-protocol deepseek --allow-paid-evaluation --budget-usd 2 --budget-batch paired-proxy-pilot-v1
.venv-eval/bin/python scripts/official_quality_report.py runs/comparison-v1-base-multi-proxy-pilot-v1 runs/comparison-v1-base-citeweave-proxy-pilot-v1 --judge-protocol deepseek
```

## Adapter and spending limit

The external SDK adapter disables thinking and SDK retries, caps outputs at 8,192 tokens and serializes evaluation. RAGAS retains its original prompts; context trimming uses the original wrapper's `cl100k_base` fallback, an approximation for DeepSeek. These differences and the adapter hash enter the proxy fingerprint.

A cross-process file lock serializes calls sharing a ledger. Before sending, the adapter durably reserves USD 0.3244032: the service-reported 1,048,576-token context at USD 0.30/M plus 8,192 output tokens at USD 1.20/M. Successful calls refund unused reservation using reported usage at peak cache-miss rates. Unknown, failed or interrupted calls retain the full reservation. Crashes cannot reset spending. This ledger is a conservative upper bound under the recorded price snapshot, not an invoice.

Requests stop if the next reservation exceeds the remaining budget or 10,000 requests are reached. Keep the same ledger on resume; do not delete it or switch batches to bypass the authorized total. Changed ledger profiles are rejected. Credentials are not recorded. Truncated/unmetered judge outputs remain failures. Provider prices and aliases may change, so review the recorded snapshot before future paid runs.

## Isolation and offline verification

Proxy files use `work/deepseek-proxy/` and `runs/deepseek-proxy-evaluation/`. Original judge files stay separate. Proxy completion always keeps `official_judge_completed` false. Reporting requires explicit `--judge-protocol deepseek`, and original-judge reports reject proxy identities, even if caches are copied.

```bash
.venv-eval/bin/python scripts/check_evaluator_transport.py --judge-protocol deepseek
.venv-eval/bin/python -m pytest -q
```

The transport check intercepts an actual archived image after the original 512-pixel resize/base64 conversion. It validates model, disabled thinking and token cap using a dummy key and synthetic non-score response. Tests cover sync/async calls, cancellation, unknown billing, no SDK retry, spending/request limits and score-label isolation. These checks make zero external judge requests and produce no quality scores.
