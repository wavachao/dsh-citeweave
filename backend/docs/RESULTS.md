# Measured results — 2026-10-19

Hardware: NVIDIA GeForce RTX 4090 D, 24,564 MiB. Environment: uv, Python 3.12, PyTorch 2.7.1+cu128, Transformers 4.57.6. Refer to `uv.lock` for the full environment.

## Image relevance component

The official **training** snapshot yields 1,146 usable queries with both positive and negative image examples. Deterministic query-level splitting gives 1,024 training queries / 11,403 pairs and 122 validation queries / 1,292 pairs. Positive labels are original VLM relevance >=8; negative labels <=3. Ambiguous scores are excluded. Benchmark query overlap: zero.

| Method | Validation NDCG@5 | Decision |
|---|---:|---|
| Frozen BGE-small cosine similarity | 0.73963 | Baseline |
| Pointwise MLP on frozen embeddings | 0.71382 | Rejected |
| Pairwise cosine residual head | 0.73963 | Retained initial cosine ordering; no measured gain |
| MS MARCO MiniLM cross-encoder before task training | 0.73828 | Starting checkpoint |
| Joint query-caption cross-encoder after task training | **0.74961** | Selected epoch 1 of 3 on validation |

The cross-encoder improves validation ranking by approximately 0.010 absolute NDCG@5 over cosine. This is a small component-level improvement on weakly labeled training validation data. It does **not** establish an improvement in overall answer quality, statistical significance, or superiority to M²RAG.

A paired query bootstrap (10,000 resamples, seed 42) gives a descriptive 95% interval of **[-0.03172, 0.05366]** for the difference. The interval includes zero. This checkpoint was selected on the same validation set, so this interval is not an independent test estimate.

## Frozen ranker component test

After checkpoint and threshold selection, the frozen ranker was evaluated on released level-1 benchmark image captions. The six development/demo questions were excluded. Neither weights nor threshold were tuned on this test. All valid, captioned, scored images were considered, deduplicated by archive URL, without the generation benchmark's oracle top-k prefilter.

Of 194 planned questions, 186 had a defined positive-gain ranking target, covering 2,491 image pairs. Eight undefined cases are listed explicitly in the report. The metric uses linear gains from released 0–10 VLM relevance scores; it differs from binary-label training validation and measures a weakly supervised ranking component, not answer quality.

| Method | Test graded NDCG@5 |
|---|---:|
| Frozen BGE cosine | 0.724448 |
| Selected fine-tuned cross-encoder | 0.759809 |
| Paired difference | +0.035361 |

The paired query bootstrap interval (10,000 resamples, seed 42) is **[0.014515, 0.056550]**. An independent scikit-learn recomputation agrees with every stored per-query NDCG to within 4.45e-16. The selected weight hash was unchanged before/after evaluation. This supports a gain in caption relevance ranking on this subset. It does not establish a gain in the eight M²RAG metrics. Artifacts: `runs/ranker-test-level1-v1/{manifest,report}.json` and `per-query.jsonl`.

## Engineering smoke tests

The unchanged original single-stage baseline and the initial CiteWeave implementation each generated three real predictions successfully. Those cases exposed output parsing and presentation issues. They are engineering examples, not held-out performance evidence; their IDs and the three UI demo IDs are excluded by default from subsequent comparison runs.

## Official evaluation status

Five-track, 194-query-per-track local generation was launched on 2026-10-19 with frozen implementation and uv-lock hashes in `runs/comparison-plan.json`. All five tracks have attempted all 194 predictions. Distilled CiteWeave completed 189 and failed five at the output cap; the other four tracks have 194 execution successes each. Check `runs/comparison-v1-progress.json` for the timestamp and exact counts. This is not a completed quality evaluation. The six engineering/demo questions are excluded; all tracks use the same eligible IDs and token budgets.

| Completed track | Execution successes | Valid inputs | Median generation seconds | Mean unique images | Diagnostic image recall |
|---|---:|---:|---:|---:|---:|
| Original single-stage | 194/194 | 191/194 | 16.86 | 2.129 | 0.8836 |
| CiteWeave | 194/194 | 194/194 | 8.04 | 0.871 | 0.7241 |
| Original multi-stage | 194/194 | 194/194 | 30.71 | 3.216 | 0.9865 |
| Distilled original single-stage | 194/194 | 187/194 | 19.78 | 1.923 | 0.8182 |
| Distilled CiteWeave | 189/194 | 189/194 | 11.66* | 1.492* | 0.8220* |

*Distilled CiteWeave latency/image summaries are conditional on its 189 successful predictions. The five failed IDs are `1jphmq`, `1vtk4p`, `407zex`, `7ixgmx`, `j2ozz`; each reached the output cap. Their raw responses, usage and failures are retained. This row is not a complete 194-query quality comparison.

These are generation/coverage diagnostics, **not official quality scores**. Diagnostic recall deduplicates image URLs and assigns 1 to questions without a positive image; the official recall denominator follows the original evaluator instead. CiteWeave produces fewer illustrations and lower coverage: 72/194 answers have no image, versus 25/194 in the original multi-stage track. Its lower latency does not establish overall superiority. Two calls hit the output budget in each original track; none did in CiteWeave. No input truncations were observed in these three completed tracks.

Tracing the 72 no-image CiteWeave answers gives 23 with no candidates after the shared official prefilter and 49 where the trained selector rejects every candidate. No case has preselected images lost at the placement step. A training-validation-only calibration audit confirms the selected 0.55 threshold has the best micro-F1 among the original threshold grid; lowering it increases recall while admitting more weak-label negatives. The test results were not used to adjust that threshold. Attribution IDs are in `runs/comparison-v1-base-citeweave/reports/image-omission-attribution.json`; calibration details are in `runs/crossencoder/calibration-diagnostics.json`.

The original single-stage parser lost three nonempty raw answers. A separate `comparison-v1-base-single-repaired` control changes only outer-Markdown-fence parsing, preserving the raw generations, prompts and original run. It changes 71 exports and recovers all three empty answers; 194/194 derived inputs pass validation. This supplementary control prevents attributing a parser repair to an algorithmic gain. It has made zero new generation calls. The original multi-stage path is unchanged.

The distilled original single-stage track has seven placeholder/image-list count mismatches and 25 calls at the output cap, with no input truncations. Inspection of the pinned original parser shows that its global string replacement can turn identical repeated image markers into multiple placeholders while recording the image only once. An outer-fence-only derived control changes none of this track's exports and still fails input validation on those seven cases. These problems are retained explicitly; neither incomplete exports nor cap hits are interpreted as quality successes, and no incompatible seven-case dropping is used for a formal comparison.

A second, separately named parser control (`*-single-repaired-v2`) removes repeated valid image-ID markers in one pass before the original handler, keeping the first occurrence. Both 194-query single-stage controls now pass input validation. The base control changes 71 exports and removes two repeated markers; the distilled control changes exactly the seven inconsistent exports and removes 40 repeated markers across the track. Original runs and v1 controls remain unchanged. A per-query integrity audit verifies that model inputs, raw responses, usage, calls and evidence are identical to the parent, and that parent hashes still match the earlier v1 control. The 25 distilled cap hits remain recorded. These controls have also been prepared for judging with zero new generation or judge requests. This supports fairer supplemental comparison; it is not an algorithm-quality result.

Not completed. The eight original M²RAG metrics require the original judge setup. No original-judge overall score or claim of exceeding M²RAG is made. The project includes the original evaluator bridge and controlled prediction runner so this can be evaluated once judge access is available.

The original evaluator's imports were verified in an isolated uv environment after pinning compatible datasets/PyArrow versions. An intercepted offline transport test also exercised the original VLM's image loading, 512-pixel resize, base64 request and dated model name with a synthetic response; it made zero external judge requests and produced no quality score. Input validation checks question/image IDs, nonempty answers, placeholder counts, image decoding and archive hashes before any paid evaluation. Judge-cache identity checks prevent reusing scores for changed predictions, images or judge protocols. Application/parser/provenance/evaluation checks: **35 passed** in the isolated evaluator environment on the server.

Both primary-comparison runs have now been staged via `--prepare-only`: 194 predictions each, with 624 used image files for original multi-stage and 169 for CiteWeave. The input/protocol manifests are stored under `runs/official-evaluation/<run>/request-manifest.json`, with `official_judge_completed: false`. Preparation requires no key and starts no judge process; a regression check explicitly forbids evaluator startup in that mode. These are prepared inputs, not score logs.

The generation snapshot remains at implementation hash `21b3848cb3d79e0419898923f563913b211fb488379beda224d9ef959f565d1f` and lock hash `a87433dc263e4b5bf57a95c3a2c7b1dc6daf4275b528b9dd85d501341839e7bd`. The application subsequently received Clash proxy-environment compatibility and comparison-formula parsing fixes; its current source is distinct from the frozen generation snapshot. The previous tag-stripping regex removed text between comparison operators such as `a < b and c > d`. The application now preserves plain answer text, which the existing UI renders through `textContent`, and a regression check verifies the formula and citation are retained. The frozen generation source is unchanged. Both source versions are delivered separately.

Artifacts on the server: `runs/data-audit.json`, `runs/ranker-mlp-v1/report.json`, `runs/ranker/report.json`, `runs/crossencoder/report.json`, per-query benchmark logs and manifests. These contain the actual results, including unsuccessful approaches.


## Completed DeepSeek proxy pilot

Current official DeepSeek documentation supports images in `deepseek-flash`. A separate adapter preserves original evaluator prompts/metrics while replacing the judges, disabling thinking, limiting outputs to 8,192 tokens and enforcing a shared budget. These are proxy scores, not original-judge scores. The original image encoding plus proxy SDK transport passed offline interception with zero external requests. Budget, retry, cancellation and judge-identity isolation checks are included in the 35-test run.

Full primary-comparison proxy inputs are prepared (194 per method), but paid evaluation was authorized only for the deterministic 20-query paired pilot. The pilot completed on 2026-10-19: 58 original multi-stage image files and 16 CiteWeave image files. All expected metric tasks succeeded, their aggregates match the original evaluator tables, and both methods used the same returned system fingerprint. See `DEEPSEEK_PROXY.md` and `runs/deepseek-pilot-plan.json`.

| DeepSeek proxy metric (0–1) | Original multi-stage | CiteWeave | Difference |
|---|---:|---:|---:|
| Fluency | 0.70500 | 0.69000 | -0.01500 |
| Response relevancy | 0.84500 | 0.89000 | +0.04500 |
| Context precision | 0.54438 | 0.42502 | -0.11937 |
| Faithfulness | 0.65068 | 0.71060 | +0.05991 |
| Image coherence | 0.74310 | 0.78750 | +0.04440 |
| Image helpfulness | 0.63966 | 0.73125 | +0.09159 |
| Image reference | 0.73966 | 0.75625 | +0.01659 |
| Image recall | 0.95000 | 0.76250 | -0.18750 |
| Overall | **0.72718** | **0.71914** | **-0.00805** |

The paired query bootstrap (10,000 draws, seed 42) gives an overall difference interval of **[-0.06090, 0.04762]**, with no undefined draws. It includes zero and supports neither a superiority nor an equivalence claim. Context precision's descriptive per-metric interval is [-0.24110, -0.02559]; these eight exploratory metric intervals have no multiplicity correction. The main observed weaknesses are context precision and image coverage. Eight CiteWeave answers have no image, versus three baseline answers. Higher pooled image precision is conditional on the smaller selected image set and does not compensate for missing illustrations by itself. These are 20-question proxy diagnostics, not GPT-4o scores or full benchmark completion. Artifact: `runs/deepseek-proxy-evaluation/paired-pilot-report.json`.

The corrected 8,192-token protocol made 700 metered requests, all ending with `stop`. Including the preserved first attempt, the shared ledger contains 849 started requests: 848 metered and one unknown interrupted request. Recomputing usage at peak cache-miss rates gives USD 0.9332667 for metered requests; USD 0.3170304 remains reserved for the unknown request, giving a conservative total upper bound of **USD 1.2502971**, below the authorized USD 2. This is not the provider invoice. A separate terminal audit verifies the earlier ledger prefix is unchanged, both subsets remain byte-identical to parent predictions, and every metered response has the same model/fingerprint. Audit: `runs/deepseek-proxy-evaluation/pilot-audit.json`. No additional paid evaluation has been launched.


The first real proxy attempt used a 2,048-token cap and returned 12 truncated judge responses among 149 started requests. It was stopped; its cache and exact adapter source are preserved separately. The corrected protocol uses 8,192 tokens, with fresh caches for both methods. An authenticated model-metadata query reports a 1,048,576-token context; the conservative per-call reservation is USD 0.3244032. The original USD 2 authorization, all 149 earlier calls and USD 0.4972491 of settled/unknown upper-bound spending were retained in the same ledger. This is not an additional authorization. No capped scores are mixed into the corrected paired comparison.


A fresh live Chinese application request after the comparison-formula fix returned HTTP 200 in 13.62 seconds, using local generation and the original Wikipedia source. This is a deployment smoke test, not benchmark quality evidence; the raw API result is saved as `runs/live-local-smoke-v2.json`.
