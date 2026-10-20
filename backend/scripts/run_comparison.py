"""Run a fixed, resumable comparison matrix on one GPU; no judge API calls."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--level", type=int, default=1, choices=[0, 1, 2, 3])
    parser.add_argument("--prefix", default="comparison-v1")
    args = parser.parse_args()
    if args.limit < 0 or not args.prefix.replace("-", "").isalnum():
        parser.error("Use a nonnegative limit and an alphanumeric/hyphen prefix")
    stages = [
        ("base-single", "reference-single", None),
        ("base-citeweave", "citeweave", None),
        ("base-multi", "reference-multi", None),
        ("distilled-single", "reference-single", "models/M2RAG-Qwen2.5-7B-Instruct"),
        ("distilled-citeweave", "citeweave", "models/M2RAG-Qwen2.5-7B-Instruct"),
    ]
    for label, method, adapter in stages:
        name = f"{args.prefix}-{label}"
        command = [
            sys.executable,
            "-m",
            "citeweave",
            "benchmark",
            "--method",
            method,
            "--limit",
            str(args.limit),
            "--level",
            str(args.level),
            "--name",
            name,
        ]
        if adapter:
            command += ["--adapter", adapter]
        print(json.dumps({"stage": label, "status": "starting"}), flush=True)
        subprocess.run(command, cwd=ROOT, check=True)
        subprocess.run(
            [sys.executable, "-m", "citeweave", "diagnostics", str(ROOT / "runs" / name)],
            cwd=ROOT,
            check=True,
        )
        print(json.dumps({"stage": label, "status": "predictions_finished"}), flush=True)


if __name__ == "__main__":
    main()
