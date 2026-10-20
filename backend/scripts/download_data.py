"""Fetch the released input data and training-only relevance snapshots."""

import os
import subprocess
import tarfile
from pathlib import Path

ENDPOINT = os.getenv("HF_ENDPOINT", "https://huggingface.co").rstrip("/")
ROOT = Path(__file__).resolve().parents[1]
REVISIONS = {
    "ylwt/M2RAG-Bench": "e04331ef32c03ceb25e972aa54a24e313ef024a7",
    "ylwt/M2RAG-Distill-GPT-4o": "a2641aac69b6044d537dc752ed4f2a0e83a99438",
}


def download(repo, remote, local):
    local.parent.mkdir(parents=True, exist_ok=True)
    if local.exists() and local.stat().st_size:
        return
    partial = local.with_suffix(local.suffix + ".part")
    subprocess.run(
        [
            "curl",
            "-fL",
            "--retry",
            "4",
            "--max-time",
            "1200",
            "-C",
            "-",
            f"{ENDPOINT}/datasets/{repo}/resolve/{REVISIONS[repo]}/{remote}",
            "-o",
            str(partial),
        ],
        check=True,
    )
    partial.replace(local)


def main():
    dataset = ROOT / "data"
    bench = dataset / "benchmark/dev_set.jsonl.tar.gz"
    train = dataset / "training/data.tar.gz"
    download("ylwt/M2RAG-Bench", "dev_set.jsonl.tar.gz", bench)
    download("ylwt/M2RAG-Distill-GPT-4o", "data.tar.gz", train)
    for archive, target in [(bench, bench.parent), (train, train.parent)]:
        with tarfile.open(archive) as tar:
            tar.extractall(target, filter="data")
    for name in ("queries", "images", "aux_images"):
        download(
            "ylwt/M2RAG-Distill-GPT-4o",
            f"mongodb_snapshot/m2rag/training_set.{name}.bson.gz",
            dataset / "training/snapshot" / (name + ".bson.gz"),
        )


if __name__ == "__main__":
    main()
