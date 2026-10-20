"""Derive a parser-repaired single-stage control from unchanged raw predictions.

No model generation or API calls. The original run is never modified.
"""

import argparse
import copy
import hashlib
import json
import re
import time
from pathlib import Path

from citeweave.reference import summarizer

ROOT = Path(__file__).resolve().parents[1]


def unwrap_outer_fence(text):
    match = re.match(r"\A\s*```(?:markdown|md)?[ \t]*\n", text)
    if not match:
        return text
    content = text[match.end() :]
    closing = re.search(r"\n```\s*\Z", content)
    return content[: closing.start()].strip() if closing else content.strip()


def remove_repeated_image_markers(text, image_count):
    """Keep the first valid ID, matching the original parser's intended policy.

    Its global str.replace otherwise replaces every identical marker at once,
    producing more placeholders than recorded images.
    """
    seen = set()
    removed = 0

    def replace(match):
        nonlocal removed
        index = int(match[3])
        if index >= image_count:
            return match[0]  # Leave unknown IDs to the unchanged original handler.
        if index in seen:
            removed += 1
            return ""
        seen.add(index)
        return match[0]

    return re.sub(r"\!\[(.*?)\]\((.*?)(\d+)(.*?)\)", replace, text), removed


class ExportOnlyModel:
    name = "llm-export-only-no-generation"

    def chat(self, messages):
        raise RuntimeError("This control must never perform model generation")


def derive(parent, output, deduplicate_images=False):
    if parent.resolve() == output.resolve():
        raise ValueError("Derived control must use a separate directory")
    manifest = json.loads((parent / "manifest.json").read_text())
    if manifest["method"] != "reference-single":
        raise ValueError(
            "Only single-stage raw responses can be repaired without regenerating earlier stages"
        )
    output.mkdir(parents=True, exist_ok=True)
    derived = {
        **manifest,
        "method": "reference-single-parser-repaired",
        "parent_run": str(parent.resolve()),
        "derivation": {
            "scope": "postprocessing-only control; raw model responses and prompts unchanged",
            "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "parser": "unwrap only outer Markdown fences; preserve interior fences",
            "deduplicate_image_markers_before_original_handler": deduplicate_images,
        },
    }
    target = output / "manifest.json"
    if target.exists() and json.loads(target.read_text()) != derived:
        raise ValueError("Existing derived manifest differs; choose a new output name")
    target.write_text(json.dumps(derived, indent=2))
    ref = summarizer(ExportOnlyModel())
    count, changed, repaired_empty, repeated_markers = 0, 0, 0, 0
    for qid in manifest["query_ids"]:
        file = parent / (qid + ".json")
        if not file.exists():
            continue
        started = time.monotonic()
        original = json.loads(file.read_text())
        record = copy.deepcopy(original)
        if original.get("success"):
            data = record["result"]
            pool = [i for p in data["webpages"] for i in p["images"]] + data["aux_images"]
            text = unwrap_outer_fence(data["model_response"])
            if deduplicate_images:
                text, removed = remove_repeated_image_markers(text, len(pool))
                repeated_markers += removed
            parsed = ref.handle_output_images(text, pool)
            new_text = parsed["placeholder_response"]
            changed += new_text != data["placeholder_response"]
            repaired_empty += not data["placeholder_response"].strip() and bool(new_text.strip())
            data.update(
                processed_response=parsed["processed_response"],
                placeholder_response=new_text,
                output_images=parsed["output_images"],
                num_output_images=parsed["num_images"],
            )
        record["derivation_seconds"] = time.monotonic() - started
        record["parent_prediction_sha256"] = hashlib.sha256(file.read_bytes()).hexdigest()
        destination = output / file.name
        temporary = destination.with_suffix(".tmp")
        temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2))
        temporary.replace(destination)
        count += 1
    report = {
        "scope": "parser_repair_control_not_algorithm_quality_result",
        "planned": len(manifest["query_ids"]),
        "available": count,
        "postprocessed_changed": changed,
        "empty_outputs_recovered": repaired_empty,
        "repeated_image_markers_removed": repeated_markers,
        "generation_calls": 0,
        "complete": count == len(manifest["query_ids"]),
    }
    (output / "reports").mkdir(exist_ok=True)
    (output / "reports/derivation.json").write_text(json.dumps(report, indent=2))
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("parent", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--deduplicate-images", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            derive(args.parent.resolve(), args.output.resolve(), args.deduplicate_images),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
