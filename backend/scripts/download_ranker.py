"""Install the released query-caption ranker after verifying its archive and weights."""

import hashlib
import json
import shutil
import tarfile
import tempfile
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
URL = "https://github.com/wavachao/citeweave/releases/download/v0.1.0/citeweave-ranker-v1.tar.gz"
ARCHIVE_SHA256 = "8484704dc8f1658530d9c94c2d6e25cdc16b71720f05e8248f59c6ed523663fb"
WEIGHT_SHA256 = "354b7e3f813851b4f61848badad37a60fa0c115c92ddd6b922b8b8fc780632b5"
ALLOWED = {"selected.json", "provenance.json"} | {
    "best/" + name
    for name in (
        "config.json",
        "model.safetensors",
        "special_tokens_map.json",
        "tokenizer.json",
        "tokenizer_config.json",
        "vocab.txt",
        "LICENSE",
    )
}


def install(archive, destination):
    if hashlib.sha256(archive.read_bytes()).hexdigest() != ARCHIVE_SHA256:
        raise ValueError("Ranker archive SHA256 mismatch")
    destination.mkdir(parents=True, exist_ok=True)
    if (destination / "best").exists():
        raise ValueError("An existing checkpoint is present; move it aside before installation")
    with tempfile.TemporaryDirectory(dir=destination) as folder:
        staging = Path(folder)
        with tarfile.open(archive) as bundle:
            for member in bundle:
                if member.name not in ALLOWED or not member.isfile():
                    raise ValueError("Unexpected ranker archive member")
                path = staging / member.name
                path.parent.mkdir(exist_ok=True)
                path.write_bytes(bundle.extractfile(member).read())
        if (
            set(p.relative_to(staging).as_posix() for p in staging.rglob("*") if p.is_file())
            != ALLOWED
        ):
            raise ValueError("Incomplete ranker archive")
        if (
            hashlib.sha256((staging / "best/model.safetensors").read_bytes()).hexdigest()
            != WEIGHT_SHA256
        ):
            raise ValueError("Ranker weights SHA256 mismatch")
        selected = json.loads((staging / "selected.json").read_text())
        selected["path"] = "runs/crossencoder/best"
        shutil.move(str(staging / "best"), str(destination / "best"))
        (destination / "selected.json").write_text(json.dumps(selected, indent=2))
        shutil.move(str(staging / "provenance.json"), str(destination / "provenance.json"))


def main():
    destination = ROOT / "runs/crossencoder"
    weights = destination / "best/model.safetensors"
    if weights.exists() and (destination / "selected.json").exists():
        if hashlib.sha256(weights.read_bytes()).hexdigest() == WEIGHT_SHA256:
            print("The verified release ranker is already installed")
            return
        raise ValueError("A different trained checkpoint is already installed; preserving it")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as folder:
        archive = Path(folder) / "ranker.tar.gz"
        with httpx.stream("GET", URL, follow_redirects=True, timeout=120) as response:
            response.raise_for_status()
            size = 0
            with archive.open("wb") as output:
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > 100_000_000:
                        raise ValueError("Ranker download exceeds expected size")
                    output.write(chunk)
        install(archive, destination)
    print("Verified ranker installed into runs/crossencoder")


if __name__ == "__main__":
    main()
