"""CPU-only, frozen-ranker evaluation on released benchmark captions and weak labels.

This is an independent component test, not an M2RAG overall-quality score.
No relevance annotations enter model inputs; no weights or thresholds are tuned.
"""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import torch
from sentence_transformers import SentenceTransformer
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from citeweave import config
from citeweave.benchmark import PILOT_IDS
from citeweave.data import rows
from citeweave.train import ndcg


def samples(level):
    for row in rows(config.DATA / "benchmark/dev_set.jsonl"):
        if (level and row["level"] != level) or row["query_id"] in PILOT_IDS:
            continue
        pool = [i for p in row["webpages"] for i in p["images"]] + row["aux_images"]
        seen = set()
        captions = []
        labels = []
        for image in pool:
            caption = image.get("detailed_image_caption")
            score = image.get("final_score")
            key = image.get("cached_image_url") or image.get("image_url")
            if not image.get("valid") or not caption or score is None or key in seen:
                continue
            seen.add(key)
            captions.append(caption)
            labels.append(float(score))
        yield {
            "id": row["query_id"],
            "query": row["content"],
            "captions": captions,
            "labels": labels,
        }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--level", type=int, default=1, choices=[0, 1, 2, 3])
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--name", default="ranker-test-level1-v1")
    args = parser.parse_args()
    if not args.name.replace("-", "").isalnum() or args.threads < 1:
        parser.error("Use an alphanumeric/hyphen name and positive thread count")
    torch.set_num_threads(args.threads)
    groups = list(samples(args.level))
    directory = config.RUNS / args.name
    if directory.exists():
        raise ValueError("Use a new output name; component test results are immutable")
    directory.mkdir(parents=True)
    selected = json.loads((config.RUNS / "crossencoder/selected.json").read_text())
    path = Path(selected["path"])
    weights = path / "model.safetensors"
    model_hash = hashlib.sha256(weights.read_bytes()).hexdigest()
    manifest = {
        "scope": "frozen_ranker_test_only_not_official_overall",
        "level": args.level,
        "dataset_sha256": hashlib.sha256(
            (config.DATA / "benchmark/dev_set.jsonl").read_bytes()
        ).hexdigest(),
        "query_ids": [g["id"] for g in groups],
        "excluded_pilot_ids": sorted(PILOT_IDS),
        "fine_tuned_weights_sha256": model_hash,
        "selected_checkpoint": selected,
        "encoder": json.loads((Path(config.EMBEDDING_MODEL) / "source.json").read_text()),
        "metric": "linear-gain graded NDCG@5 using released weak VLM scores 0-10",
        "candidate_policy": "all valid captioned, scored images; deduplicate by archive URL; no oracle top-k/prefilter",
        "selection_and_threshold_tuning": False,
        "device": "cpu",
        "threads": args.threads,
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2))
    encoder = SentenceTransformer(config.EMBEDDING_MODEL, device="cpu", local_files_only=True)
    tokenizer = AutoTokenizer.from_pretrained(path, local_files_only=True)
    model = (
        AutoModelForSequenceClassification.from_pretrained(path, local_files_only=True).cpu().eval()
    )
    measurements = []
    for index, group in enumerate(groups):
        if not group["captions"] or not any(label > 0 for label in group["labels"]):
            measurements.append(
                {
                    "id": group["id"],
                    "status": "undefined_no_positive_scored_candidate",
                    "candidate_count": len(group["captions"]),
                }
            )
            continue
        vectors = encoder.encode(
            [group["query"], *group["captions"]],
            batch_size=32,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        cosine = vectors[1:] @ vectors[0]
        scores = []
        with torch.inference_mode():
            for start in range(0, len(group["captions"]), 32):
                batch = group["captions"][start : start + 32]
                tokens = tokenizer(
                    [group["query"]] * len(batch),
                    batch,
                    padding=True,
                    truncation=True,
                    max_length=selected["max_length"],
                    return_tensors="pt",
                )
                scores.extend(model(**tokens).logits.flatten().tolist())
        measurements.append(
            {
                "id": group["id"],
                "status": "scored",
                "candidate_count": len(scores),
                "labels": group["labels"],
                "cosine_scores": cosine.tolist(),
                "crossencoder_logits": scores,
                "cosine_ndcg5": ndcg(group["labels"], cosine),
                "crossencoder_ndcg5": ndcg(group["labels"], scores),
            }
        )
        with (directory / "per-query.jsonl").open("a") as file:
            file.write(json.dumps(measurements[-1]) + "\n")
        if index % 20 == 0:
            print(
                json.dumps({"processed": index + 1, "planned": len(groups), "device": "cpu"}),
                flush=True,
            )
    assert hashlib.sha256(weights.read_bytes()).hexdigest() == model_hash, (
        "Weights changed during evaluation"
    )
    scored = [r for r in measurements if r["status"] == "scored"]
    if not scored:
        raise ValueError("No defined ranking cases")
    a = np.array([r["cosine_ndcg5"] for r in scored])
    b = np.array([r["crossencoder_ndcg5"] for r in scored])
    rng = np.random.default_rng(42)
    deltas = (b - a)[rng.integers(0, len(a), size=(10000, len(a)))].mean(axis=1)
    report = {
        "scope": manifest["scope"],
        "planned": len(groups),
        "scored_queries": len(scored),
        "undefined_queries": [r["id"] for r in measurements if r["status"] != "scored"],
        "image_pairs": sum(r["candidate_count"] for r in scored),
        "cosine_ndcg5": float(a.mean()),
        "crossencoder_ndcg5": float(b.mean()),
        "difference": float((b - a).mean()),
        "paired_bootstrap_95_interval": np.quantile(deltas, [0.025, 0.975]).tolist(),
        "bootstrap_samples": 10000,
        "bootstrap_seed": 42,
        "threshold_tuned": False,
    }
    (directory / "report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
