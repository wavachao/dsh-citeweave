"""Download and safely extract the pinned official benchmark image archives."""

import os
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REVISION = "e04331ef32c03ceb25e972aa54a24e313ef024a7"


def main():
    os.environ.setdefault("HF_HOME", str(ROOT / ".cache/huggingface"))
    from huggingface_hub import snapshot_download

    folder = ROOT / "data/benchmark"
    snapshot_download(
        "ylwt/M2RAG-Bench",
        repo_type="dataset",
        revision=REVISION,
        local_dir=folder,
        allow_patterns=["images/ELI5/dev_set/*.tar"],
        max_workers=3,
        endpoint=os.getenv("HF_ENDPOINT", "https://huggingface.co"),
    )
    target = ROOT / "data/images/ELI5/dev_set"
    target.mkdir(parents=True, exist_ok=True)
    for archive in sorted((folder / "images/ELI5/dev_set").glob("*.tar")):
        with tarfile.open(archive) as tar:
            tar.extractall(target, filter="data")


if __name__ == "__main__":
    main()
