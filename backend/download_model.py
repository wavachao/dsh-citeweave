"""Download the pinned community AWQ model used by the vLLM deployment."""

import argparse
import json
from pathlib import Path

REPO = "cyankiwi/Qwen3.5-9B-AWQ-4bit"
REVISION = "e4d2d39cede8c5d1716d824cd843e2889c648083"


def download(output):
    from huggingface_hub import snapshot_download

    output = Path(output).resolve()
    metadata = output / "source.json"
    expected = {"repo": REPO, "revision": REVISION}
    existing = json.loads(metadata.read_text()) if metadata.exists() else expected
    if any(existing.get(key) != value for key, value in expected.items()):
        raise ValueError(f"Existing model revision differs: {output}")
    snapshot_download(REPO, revision=REVISION, local_dir=output, max_workers=3)
    metadata.write_text(json.dumps({**existing, **expected}, indent=2) + "\n", encoding="utf-8")
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path, help="Local model directory")
    args = parser.parse_args()
    print(download(args.output))


if __name__ == "__main__":
    main()
