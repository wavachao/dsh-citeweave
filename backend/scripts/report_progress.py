"""Snapshot generation status and validate archived inputs; no judge API calls."""

import argparse
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path

from preflight_evaluation import check_run

ROOT = Path(__file__).resolve().parents[1]
TRACKS = (
    "base-single",
    "base-citeweave",
    "base-multi",
    "distilled-single",
    "distilled-citeweave",
)


def snapshot(prefix):
    plan = json.loads((ROOT / "runs/comparison-plan.json").read_text())
    report = {
        "scope": "generation_and_input_validation_not_answer_quality",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "plan": plan,
        "tracks": {},
    }
    expected_ids = None
    for label in TRACKS:
        run = ROOT / "runs" / f"{prefix}-{label}"
        if not (run / "manifest.json").exists():
            report["tracks"][label] = {"state": "not_started"}
            continue
        manifest = json.loads((run / "manifest.json").read_text())
        for key in ("implementation_sha256", "uv_lock_sha256", "level"):
            if manifest[key] != plan[key]:
                raise ValueError(f"Run differs from frozen plan: {label}/{key}")
        ids = manifest["query_ids"]
        if len(ids) != plan["expected_queries_per_track"] or len(ids) != len(set(ids)):
            raise ValueError(f"Unexpected query IDs: {label}")
        if expected_ids is not None and ids != expected_ids:
            raise ValueError(f"Query IDs differ between tracks: {label}")
        expected_ids = ids
        records = []
        for qid in ids:
            file = run / f"{qid}.json"
            if file.exists():
                record = json.loads(file.read_text())
                if record["id"] != qid:
                    raise ValueError(f"Mismatched prediction ID: {file}")
                records.append(record)
        successes = [r for r in records if r.get("success")]
        validation = check_run(run, require_complete=True)
        destination = ROOT / "runs/input-preflight" / (run.name + ".json")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(validation, indent=2))
        report["tracks"][label] = {
            "state": (
                "generation_complete"
                if len(successes) == len(ids)
                else "attempts_finished_with_failures"
                if len(records) == len(ids)
                else "incomplete"
            ),
            "planned": len(ids),
            "attempted": len(records),
            "execution_successes": len(successes),
            "failed_ids": [r["id"] for r in records if not r.get("success")],
            "valid_inputs_for_judging": validation["valid_predictions"],
            "input_errors": validation["errors"],
            "no_image_answers": sum(not r["result"]["output_images"] for r in successes),
            "median_generation_seconds": statistics.median(r["seconds"] for r in successes)
            if successes
            else None,
            "truncated_calls": sum(
                c.get("input_truncated", False) for r in records for c in r.get("calls", [])
            ),
            "output_budget_reached_calls": sum(
                c.get("output_budget_reached", False) for r in records for c in r.get("calls", [])
            ),
        }
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prefix", default="comparison-v1")
    args = parser.parse_args()
    if not args.prefix.replace("-", "").isalnum():
        parser.error("Use an alphanumeric/hyphen prefix")
    report = snapshot(args.prefix)
    output = ROOT / "runs" / f"{args.prefix}-progress.json"
    temporary = output.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, indent=2))
    temporary.replace(output)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
