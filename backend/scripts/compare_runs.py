"""Paired coverage/latency diagnostics. These are NOT answer-quality scores."""

import argparse
import json
from pathlib import Path

import numpy as np


def read_run(path):
    manifest = json.loads((path / "manifest.json").read_text())
    records = {}
    for qid in manifest["query_ids"]:
        file = path / f"{qid}.json"
        if file.exists():
            records[qid] = json.loads(file.read_text())
    return manifest, records


def recall(record):
    result = record["result"]
    positives = {
        i["cached_image_url"]
        for page in result["webpages"]
        for i in page["images"]
        if i.get("final_score") is not None and i["final_score"] >= 8
    }
    positives.update(
        i["cached_image_url"]
        for i in result["aux_images"]
        if i.get("final_score") is not None and i["final_score"] >= 8
    )
    selected = {i["cached_image_url"] for i in result["output_images"]}
    return len(positives & selected) / len(positives) if positives else 1.0


def compare(left, right):
    lm, lr = read_run(left)
    rm, rr = read_run(right)
    for key in (
        "query_ids",
        "dataset_sha256",
        "model_revision",
        "adapter_revision",
        "max_input_tokens",
        "max_new_tokens",
        "max_output_image_candidates",
    ):
        if lm.get(key) != rm.get(key):
            raise ValueError(f"Comparison settings differ: {key}")
    ids = [
        q for q in lm["query_ids"] if lr.get(q, {}).get("success") and rr.get(q, {}).get("success")
    ]
    result = {
        "scope": "paired_coverage_diagnostics_not_official_quality",
        "planned": len(lm["query_ids"]),
        "paired_successes": len(ids),
        "left_attempted": len(lr),
        "right_attempted": len(rr),
        "left_failed": sum(not r["success"] for r in lr.values()),
        "right_failed": sum(not r["success"] for r in rr.values()),
        "all_predictions_successful": len(ids) == len(lm["query_ids"]),
    }
    if not ids:
        return result
    a, b = np.array([recall(lr[q]) for q in ids]), np.array([recall(rr[q]) for q in ids])
    rng = np.random.default_rng(42)
    differences = (b - a)[rng.integers(0, len(ids), size=(10000, len(ids)))].mean(axis=1)
    result.update(
        left_image_recall=float(a.mean()),
        right_image_recall=float(b.mean()),
        recall_difference=float((b - a).mean()),
        paired_bootstrap_95_interval=np.quantile(differences, [0.025, 0.975]).tolist(),
        left_median_seconds=float(np.median([lr[q]["seconds"] for q in ids])),
        right_median_seconds=float(np.median([rr[q]["seconds"] for q in ids])),
    )
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("left", type=Path)
    parser.add_argument("right", type=Path)
    args = parser.parse_args()
    print(json.dumps(compare(args.left, args.right), indent=2))


if __name__ == "__main__":
    main()
