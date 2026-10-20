"""Vendor pinned, licensed webfonts; runtime never contacts a font CDN."""

import base64
import hashlib
import io
import json
import re
import tarfile
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "src/citeweave/static/fonts"
PACKAGE = "https://registry.npmjs.org/lxgw-wenkai-webfont/-/lxgw-wenkai-webfont-1.7.0.tgz"
INTEGRITY = (
    "kVJmT4xMAyOLhG6q0w63wJkVU7RP8UMQRGoAWj9tnpzL7sWFFYiEHBdUQyW9myqBQFa5SQfWfa2VLYF4IJBL5g=="
)


def main():
    DESTINATION.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        response = client.get(PACKAGE)
        response.raise_for_status()
        archive = response.content
        if base64.b64encode(hashlib.sha512(archive).digest()).decode() != INTEGRITY:
            raise ValueError("LXGW font package integrity mismatch")
        with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
            css = bundle.extractfile("package/lxgwwenkai-regular.css").read().decode()
            names = re.findall(r"url\('\./(files/[^']+\.woff2)'\)", css)
            for name in names:
                target = DESTINATION / name
                target.parent.mkdir(exist_ok=True)
                content = bundle.extractfile("package/" + name).read()
                if content[:4] != b"wOF2":
                    raise ValueError("Invalid WOFF2 font")
                target.write_bytes(content)
            (DESTINATION / "lxgw.css").write_text(css, encoding="utf-8")
            for source, target in [
                ("OFL.txt", "LXGW-OFL.txt"),
                ("LICENSE", "LXGW-package-MIT.txt"),
            ]:
                (DESTINATION / target).write_bytes(bundle.extractfile("package/" + source).read())
        for source, target in [
            ("docs/font-files/InterVariable.woff2", "InterVariable.woff2"),
            ("LICENSE.txt", "Inter-OFL.txt"),
        ]:
            response = client.get("https://raw.githubusercontent.com/rsms/inter/v4.1/" + source)
            response.raise_for_status()
            (DESTINATION / target).write_bytes(response.content)
    files = {
        p.relative_to(DESTINATION).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(DESTINATION.rglob("*"))
        if p.is_file() and p.name != "manifest.json"
    }
    (DESTINATION / "manifest.json").write_text(
        json.dumps(
            {
                "inter": "rsms/inter v4.1",
                "lxgw": "lxgw-wenkai-webfont 1.7.0",
                "lxgw_package_sha512_base64": INTEGRITY,
                "files_sha256": files,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Vendored {len(names)} LXGW subsets and Inter Variable")


if __name__ == "__main__":
    main()
