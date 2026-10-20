# Models and provenance

## Application models

`scripts/download_models.py` pins upstream revisions and records each download in `source.json`.

| Resource | Pinned revision | Role |
|---|---|---|
| `Qwen/Qwen2.5-7B-Instruct` | `a09a35458c702b33eeacc393d103063234e8bc28` | Local answer generation |
| `Qwen/Qwen2.5-VL-3B-Instruct` | `66285546d2b821cf421d4f5eb2576359d3770cd3` | Local visible-content descriptions |
| `BAAI/bge-small-en-v1.5` | `5c38ec7c405ec4b44b94cc5a9bb96e735b38267a` | Text embeddings and cosine fallback |

Passing `--all` also downloads the MiniLM training base and the original M²RAG Qwen adapter. Normal web search does not need those research resources.

## Released image ranker

`scripts/download_ranker.py` installs the `citeweave-ranker-v1.tar.gz` release asset after archive and weight SHA256 verification. The archive contains model/tokenizer files, the selected operating threshold, the Apache-2.0 license and provenance metadata. It does not contain training examples.

- Base: `cross-encoder/ms-marco-MiniLM-L-6-v2`, revision `233902d25c440f23af6f7d6e94d2946bac0bee0a`.
- Fine-tuning: 1,024 query groups from the M²RAG training snapshot; 122 query groups for validation. Positive relevance >=8, negative <=3; intermediate weak labels excluded.
- Selection: epoch 1 of 3, seed 42, based on validation NDCG@5. Abstention threshold selected using validation F1.
- Benchmark query overlap in training: zero under the recorded audit.
- Weight SHA256: `354b7e3f813851b4f61848badad37a60fa0c115c92ddd6b922b8b8fc780632b5`.
- License: Apache-2.0 for the derived ranker; upstream dataset and resource terms still apply.

The model scores English question/caption relevance. It does not see image pixels, authenticate pictures, establish identity, or verify the factual claims in an answer. Live non-English questions use an English retrieval/ranking translation while answers follow the original question language. Weak labels and domain shift limit calibration, particularly recall. See `RESULTS.md` for measured tradeoffs.

## Re-training

```bash
uv run python scripts/download_models.py --all
uv run python scripts/download_data.py
uv run python -m citeweave audit
uv run python -m citeweave train-crossencoder --epochs 3 --seed 42
```

Training writes into `runs/crossencoder/` and can replace its selected checkpoint. Back up a deployed ranker first. Keep benchmark/evaluation labels out of inference inputs and avoid tuning on observed test scores. The protocol documents data splits and hashes.
