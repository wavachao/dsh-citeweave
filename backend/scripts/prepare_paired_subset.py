"""Identical deterministic evaluation-only subsets; no generation or API calls."""

import argparse
import hashlib
import json
from pathlib import Path


def prepare(left, right, count=20, seed=42, label="proxy-pilot-v1"):
    if count < 1 or not label.replace("-", "").isalnum():
        raise ValueError("Use a positive count and alphanumeric/hyphen label")
    parents = [Path(left).resolve(), Path(right).resolve()]
    manifests = [json.loads((p / "manifest.json").read_text()) for p in parents]
    for key in (
        "query_ids",
        "dataset_sha256",
        "model_revision",
        "adapter_revision",
        "max_input_tokens",
        "max_new_tokens",
        "precision",
        "candidate_protocol",
    ):
        if manifests[0].get(key) != manifests[1].get(key):
            raise ValueError(f"Parent comparison differs: {key}")
    ids = sorted(
        manifests[0]["query_ids"],
        key=lambda qid: hashlib.sha256(f"{seed}:{qid}".encode()).hexdigest(),
    )[:count]
    if len(ids) != count:
        raise ValueError("Requested more questions than the parent runs contain")
    contents = []
    for parent in parents:
        records = {qid: (parent / (qid + ".json")).read_bytes() for qid in ids}
        if not all(json.loads(data).get("success") for data in records.values()):
            raise ValueError(
                "Selected subset contains failed predictions; never drop them silently"
            )
        contents.append(records)
    outputs = [p.with_name(p.name + "-" + label) for p in parents]
    if len(set(outputs)) != 2 or any(p.exists() for p in outputs):
        raise ValueError("Subset outputs must be distinct and new")
    for parent, manifest, records, output in zip(parents, manifests, contents, outputs):
        output.mkdir()
        for qid, content in records.items():
            (output / (qid + ".json")).write_bytes(content)
        subset = {
            **manifest,
            "query_ids": ids,
            "parent_generation_run": str(parent),
            "evaluation_subset": {
                "scope": "engineering_pilot_not_full_benchmark",
                "selection": "first count IDs ordered by SHA256(seed:query_id)",
                "count": count,
                "seed": seed,
                "generation_calls": 0,
                "parent_prediction_sha256": {
                    qid: hashlib.sha256(content).hexdigest() for qid, content in records.items()
                },
            },
        }
        (output / "manifest.json").write_text(json.dumps(subset, indent=2))
    return {
        "scope": "paired_evaluation_pilot_no_generation_or_api_calls",
        "query_ids": ids,
        "runs": [str(p) for p in outputs],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("left", type=Path)
    parser.add_argument("right", type=Path)
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--label", default="proxy-pilot-v1")
    args = parser.parse_args()
    print(json.dumps(prepare(args.left, args.right, args.count, args.seed, args.label), indent=2))


if __name__ == "__main__":
    main()
