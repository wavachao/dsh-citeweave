# Experiment protocol

## Objective and comparison tracks

This appendix defines controlled comparisons against M²RAG, separately from the deployable web application. A quality-superiority claim requires real comparable benchmark results and is not implied by a working interface. No such superiority claim is made for this release.

1. **Implementation parity:** execute the original single-stage and multi-stage summarizer classes at pinned commit `ea6b9977f5a153215b38cd9a6aa3e4702ffbda22`. Keep known behavior, including its parsing behavior, unchanged in reference runs.
2. **Controlled method comparison:** same Qwen2.5-7B-Instruct model (optionally the same released distilled adapter), precision, input candidate pool, token budgets, question IDs, and judges. The official prefilter uses released relevance annotations; this is disclosed and shared by both methods. CiteWeave's learned inference does not receive relevance labels or evaluator rationales.
3. **Live-web application:** retrieve live sources with no benchmark labels. This is a separate deployment test, not a directly comparable benchmark score.

## Dataset audit

The paper describes 1,000 questions, with a 200-query main comparison. The currently released `dev_set.jsonl` contains 750 unique questions: 200 at level 1, 300 at level 2 and 250 at level 3. The official provided generation config selects level 1. Always report the released subset, not an implied 1,000-question replication.

Released training data contains 1,605 records. Some have little or no webpage context. The distilled outputs include almost every supplied image, so output inclusion is unsuitable as a negative label. Ranking training instead reads the original training-only BSON element relevance labels, keeps >=8 positives and <=3 negatives, excludes ambiguous labels, deduplicates queries and splits by SHA-256 of normalized question. These are preference labels, not human annotations.

Benchmark question overlap is checked before training. Benchmark scores and evaluator reasoning are never input features for the trained relevance head. Model selection and abstention threshold calibration use training-set validation questions only.

## Official metrics

The primary local method comparison is base CiteWeave versus the reproduced original Qwen2.5-7B multi-stage method on identical held-out IDs. Single-stage and released distilled-adapter tracks are additional controls. A higher sample mean with an uncertainty interval spanning zero is inconclusive. These 7B controls do not establish superiority to the paper's strongest 72B configuration, which has not been reproduced on this GPU.

Four text metrics: fluency, response relevance, context precision, faithfulness.

Four image metrics: coherence, helpfulness, reference, recall.

The original implementation aggregates eight normalized metrics; image precision-related metrics are aggregated over output images. Preserve this convention for official comparisons. Also report output image counts and failure rates so higher recall cannot obscure excessive illustration or missing outputs.

Original judge configuration: `gpt-4o-2024-08-06`, with `gpt-4o-mini-2024-07-18` for RAGAS metrics. Judge replacements, local diagnostics, caption similarity and training-validation NDCG must be explicitly labeled and must not be called published M²RAG overall scores.

## Reproducibility and fair reporting

- Store exact question IDs, input hashes, reference commit, model revisions, precision and generation settings.
- No silent dropping of failed generations or judge failures.
- No tuning on benchmark predictions or labels; use the training validation split.
- Report context truncation counts and shared hardware limits.
- Compare base-model methods separately from distilled-model methods.
- For the final claim, evaluate both methods on the same completed subset with the same judges; report each metric, latency, image count and a paired query-level uncertainty estimate.
- A gain in image recall or weak-label NDCG alone does not establish better total answer quality.

## Gates for a benchmark superiority claim

1. uv-locked environment and tests pass on the 4090D.
2. Real local model generation, source cards and image display work.
3. Ranking training and held-out validation run on the GPU.
4. Reference and proposed predictions finish on identical benchmark IDs.
5. Official quality evaluation completes, with independently reviewable image/text samples.
6. Claim achievement only if the predeclared comparable target is actually reached.

## Engineering pilot exclusion

Known smoke/demo IDs: `14v6kn`, `1847u5`, `18amxd`, `2xhua3`, `5ajwkl`, `1zghby`. These are excluded by default from subsequent held-out comparisons. This leaves 194 level-1 questions / 744 across all released levels. Original full-subset replication remains available via `--include-pilot`, with explicit reporting.

## Proposed answer formatting

The proposed method generates natural paragraphs with source/image ID markers, resolves only known IDs, preserves evidence captions and removes duplicate image insertions. If no valid image marker is supplied, semantic paragraph matching places preselected illustrations above a fixed similarity threshold (0.3, an engineering heuristic). Source citations are never invented by this fallback. The unchanged original path uses its original prompts, stage logic and parser. The proposed prompts, parser and image selector are part of the method; their code hash and the uv lock hash are stored in each prediction manifest. Format development used the excluded engineering queries. The generation snapshot was frozen before the proxy pilot was judged. The 20 now-observed proxy questions must not be reused as an untouched confirmatory test for future changes based on these results.

Local Qwen text/vision models and LoRA adapters use BF16; ranking encoders use FP32. Generation computes last-token logits only, which preserves autoregressive decoding while reducing prefill memory on the 24 GB GPU. The proposed method reports output-budget exhaustion as an incomplete-answer failure; the reference parser behavior is retained. Budget exhaustion and failed generations are logged for both methods.

## Frozen code and supplementary controls

The current batch imports generation code from `work/frozen/comparison-v1/src` via `PYTHONPATH`. Its implementation hash is `21b3848cb3d79e0419898923f563913b211fb488379beda224d9ef959f565d1f`; its uv lock hash is `a87433dc263e4b5bf57a95c3a2c7b1dc6daf4275b528b9dd85d501341839e7bd`. Application proxy/formula-parsing fixes and evaluation helpers were added after freezing. They do not alter the generation snapshot, weights, inputs or settings. The frozen source archive and current application archive are separate artifacts.

A supplementary single-stage parser-repaired control reprocesses unchanged raw generations into a new directory. It strips only an outer Markdown fence, preserving interior fences and surrounding prose. The original run is immutable; no generation or API call occurs. Its manifest records the parent run and script hash; each derived record records its parent's prediction hash. This is a postprocessing control, not a new algorithm-quality result. Multi-stage intermediate generations are not repaired by this export control.

The separately named v2 control also removes repeated valid image-ID markers before the original handler, preserving the first marker and all non-image prose. This avoids the upstream global-replacement mismatch between placeholder count and the unique output-image list. Unknown IDs still pass to the unchanged original handler. V1 outputs remain intact, and their exact helper source is preserved at `work/frozen/parser-repair-v1.py` in the experiment snapshot. Raw-generation integrity audits compare all model inputs, raw responses, evidence, usage and call records against the parents. Neither control changes original generation or erases output-cap flags. Report original and repaired results separately; do not label parser repairs as proposed algorithm gains.

The frozen ranker's additional component test uses all valid captioned, scored images from the held-out level-1 questions, deduplicated by archive URL. Released VLM scores are labels only, never model inputs. No checkpoint or threshold selection uses these test results. Graded linear-gain NDCG@5 is reported separately from binary training-validation NDCG and the official eight metrics. Undefined zero-gain/empty cases are listed explicitly. Both candidate scoring and the paired bootstrap run on CPU without interfering with GPU generation.

## Judge input and result validation

Preflight verifies every planned prediction, nonempty answer, image identity, placeholder count, archive location and image decoding. Proposed `iN` IDs are converted to original numeric IDs only in separate evaluator input copies, after verifying the candidate index and cached image URL. Original prediction files remain unchanged. Failed or empty answers are not silently removed.

The evaluation request manifest hashes raw predictions, staged inputs, used image files and the actual judge protocol (original commit, judge settings, metric package versions and endpoint identity). A changed identity rejects the previous cache. No key is stored in this manifest. A successful process exit alone is insufficient: all expected per-task scores must be finite and normalized correctly, and recomputed aggregates must agree with the original summary table. The supplemental bootstrap resamples paired queries and recomputes pooled image metrics for each draw, preserving the original pooling and duplicate-image recall denominator.

An offline transport contract uses an in-process mock, a dummy key and a synthetic non-score response to check original image request formatting. This is engineering verification only and never creates actual evaluation scores. Original judges remain necessary for the declared official comparison.


## DeepSeek proxy protocol

A separately labeled DeepSeek protocol reuses original prompts, metric code and pooling, with `deepseek-flash` for text and images. An external adapter disables thinking/retries, caps outputs at 8,192 tokens and serializes metered requests. The original tokenizer's cl100k_base fallback remains an approximation. None of this is labeled an original GPT-4o result. Provider version, adapter hash and settings enter a separate protocol fingerprint, cache directory and completion flag.

A deterministic SHA256(seed:query_id) pilot selects the same 20 questions for both primary methods without reading scores. The recorded pilot used a USD 2 total budget shared across both runs through one durable spending ledger. Full 194-query quality scores were not computed. See `DEEPSEEK_PROXY.md` for commands, spending assumptions, failure behavior and evidence.
