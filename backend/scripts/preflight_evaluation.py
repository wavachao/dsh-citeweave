"""Validate prediction/image inputs before any judge API calls. No quality scores."""

import argparse
import copy
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
IMAGE_PREFIX = "http://0.0.0.0:65535/"


def http_proxy_environment(environment):
    """Use the configured HTTP CONNECT route when Clash also sets SOCKS fallbacks.

    Keep proxying HTTPS; never disable TLS verification or fall back to direct access.
    The caller changes only its own process/subprocess environment.
    """
    result = dict(environment)
    secure = result.get("https_proxy") or result.get("HTTPS_PROXY")
    if secure and urlsplit(secure).scheme in ("http", "https"):
        for key in ("HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
            if urlsplit(result.get(key, "")).scheme.startswith("socks"):
                result[key] = secure
    return result


def canonical_record(record):
    """Keep generation intact; export original evaluator's numeric image IDs."""
    result = copy.deepcopy(record)
    if not result.get("success"):
        raise ValueError("Prediction failed")
    data = result["result"]
    pool = [i for p in data["webpages"] for i in p["images"]] + data["aux_images"]
    outputs = data["output_images"]
    if data["placeholder_response"].count("<IMAGE_PLACEHOLDER>") != len(outputs):
        raise ValueError("Image placeholder/output count mismatch")
    if data["num_output_images"] != len(outputs):
        raise ValueError("num_output_images mismatch")
    if not data["user_query"].strip() or not data["placeholder_response"].strip():
        raise ValueError("Empty question or answer")
    for image in outputs:
        iid = image["id"]
        if isinstance(iid, str) and iid.startswith("i") and iid[1:].isdigit():
            iid = int(iid[1:])
        if type(iid) is not int or not 0 <= iid < len(pool):
            raise ValueError(f"Unknown output image ID: {image['id']}")
        if image["cached_image_url"] != pool[iid]["cached_image_url"]:
            raise ValueError(f"Image ID/archive URL mismatch: {image['id']}")
        for key in ("image_caption", "detailed_image_caption", "cached_image_url"):
            if not isinstance(image[key], str):
                raise ValueError(f"Invalid output image field: {key}")
        image["id"] = iid
    return result


def archived_image(url, image_root):
    if not isinstance(url, str) or not url.startswith(IMAGE_PREFIX):
        raise ValueError("Unexpected archive URL prefix")
    root = image_root.resolve()
    path = (root / url[len(IMAGE_PREFIX) :]).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Archive path escapes the image directory")
    return path


def check_run(run, image_root=None, require_complete=False):
    image_root = image_root or ROOT / "data/images"
    manifest = json.loads((run / "manifest.json").read_text())
    ids = manifest["query_ids"]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate query IDs in manifest")
    report = {
        "scope": "offline_input_validation_not_quality_evaluation",
        "planned": len(ids),
        "attempted": 0,
        "valid_predictions": 0,
        "missing_predictions": [],
        "errors": [],
        "canonicalized_image_ids": 0,
        "images": {},
    }
    for qid in ids:
        file = run / f"{qid}.json"
        if not file.is_file():
            report["missing_predictions"].append(qid)
            continue
        report["attempted"] += 1
        try:
            raw = json.loads(file.read_text())
            if raw["id"] != qid:
                raise ValueError("Record/manifest query ID mismatch")
            data = canonical_record(raw)["result"]
            report["canonicalized_image_ids"] += sum(
                isinstance(i["id"], str) for i in raw["result"]["output_images"]
            )
            for image in data["output_images"]:
                url = image["cached_image_url"]
                if url in report["images"]:
                    continue
                path = archived_image(url, image_root)
                with Image.open(path) as picture:
                    picture.load()
                    size, fmt = picture.size, picture.format
                    picture.thumbnail(
                        (512, 512)
                    )  # Same decode/resize needed by the original judge.
                report["images"][url] = {
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "size": size,
                    "format": fmt,
                }
            report["valid_predictions"] += 1
        except (ValueError, KeyError, TypeError, OSError) as error:
            report["errors"].append({"id": qid, "error": f"{type(error).__name__}: {error}"})
    report["complete"] = report["valid_predictions"] == len(ids)
    report["passed"] = not report["errors"] and (report["complete"] or not require_complete)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run_directory", type=Path)
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args()
    report = check_run(args.run_directory.resolve(), require_complete=args.require_complete)
    file = ROOT / "runs/input-preflight" / (args.run_directory.name + ".json")
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps(report, indent=2))
    print(json.dumps({k: v for k, v in report.items() if k != "images"}, indent=2))
    print(f"Validated archive images: {len(report['images'])}; report: {file}")
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
