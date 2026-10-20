"""Download immutable model revisions with standard resumable caching."""

import argparse
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODELS = {
    "Qwen/Qwen2.5-7B-Instruct": "a09a35458c702b33eeacc393d103063234e8bc28",
    "Qwen/Qwen2.5-VL-3B-Instruct": "66285546d2b821cf421d4f5eb2576359d3770cd3",
    "BAAI/bge-small-en-v1.5": "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a",
    "cross-encoder/ms-marco-MiniLM-L-6-v2": "233902d25c440f23af6f7d6e94d2946bac0bee0a",
    "ylwt/M2RAG-Qwen2.5-7B-Instruct": "8803cdd8429a7e1fd0c4a1e62623e30dd7fda73f",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--all", action="store_true", help="Also download training and reference-adapter resources"
    )
    args = parser.parse_args()
    os.environ.setdefault("HF_HOME", str(ROOT / ".cache/huggingface"))
    from huggingface_hub import snapshot_download

    for repo, revision in MODELS.items():
        if not args.all and repo.startswith(("cross-encoder/", "ylwt/")):
            continue
        destination = ROOT / "models" / repo.split("/")[-1]
        metadata = destination / "source.json"
        expected = {"repo": repo, "revision": revision}
        if metadata.exists() and json.loads(metadata.read_text()) != expected:
            raise ValueError(f"Existing model revision differs: {destination}")
        snapshot_download(
            repo,
            revision=revision,
            local_dir=destination,
            endpoint=os.getenv("HF_ENDPOINT", "https://huggingface.co"),
            max_workers=3,
            allow_patterns=[
                "*.json",
                "*.safetensors",
                "*.txt",
                "*.model",
                "*.jinja",
                "LICENSE*",
                "README.md",
            ],
        )
        metadata.write_text(json.dumps(expected, indent=2))


if __name__ == "__main__":
    main()
