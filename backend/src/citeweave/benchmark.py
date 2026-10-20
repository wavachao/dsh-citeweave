import copy
import hashlib
import json
import os
import time
from pathlib import Path

from . import config
from .data import rows
from .engine import Engine, to_markdown
from .generation import Generator
from .reference import REFERENCE_COMMIT, summarizer

# Engineering smoke/demo cases. Excluded from subsequent held-out comparisons.
PILOT_IDS = {"14v6kn", "1847u5", "18amxd", "2xhua3", "5ajwkl", "1zghby"}


def controlled_evidence(sample, ref):
    """Same official prefiltered candidate pool for the method comparison."""
    sample = copy.deepcopy(sample)
    pages = ref.filter_webpage_pieces([sample])
    aux = ref.remove_invalid_auxiliary_images([sample])
    pages, aux = ref.filter_images_and_reorganize_webpages(pages, aux)
    sources, images = [], []
    for page in pages:
        sid = f"s{len(sources)}"
        sources.append(
            {
                "id": sid,
                "url": page["url"],
                "title": page["title"],
                "text": page["content"].replace("<IMAGE_PLACEHOLDER>", ""),
            }
        )
        for image in page["images"]:
            images.append(
                {
                    "id": f"i{len(images)}",
                    "url": image["image_url"],
                    "caption": image["detailed_image_caption"],
                    "source_id": sid,
                    "source_url": page["url"],
                    "cached_image_url": image["cached_image_url"],
                    "caption_kind": "provided_dataset_caption",
                }
            )
    for image in aux:
        images.append(
            {
                "id": f"i{len(images)}",
                "url": image["image_url"],
                "caption": image["detailed_image_caption"],
                "source_id": None,
                "source_url": image.get("webpage_url", ""),
                "cached_image_url": image["cached_image_url"],
                "caption_kind": "provided_dataset_caption",
            }
        )
    return sources, images


def official_record(answer, sample, controlled):
    source_map = {s["id"]: s for s in answer["sources"]}
    image_map = {i["id"]: i for i in answer["images"]}
    text, output = [], []
    for b in answer["blocks"]:
        text.append(b["text"])
        if b["image_id"] in image_map:
            image = image_map[b["image_id"]]
            text.append("<IMAGE_PLACEHOLDER>")
            output.append(
                {
                    "id": image["id"],
                    "image_caption": b["image_caption"],
                    "detailed_image_caption": image["caption"],
                    "image_width": 60,
                    "image_url": image["url"],
                    "cached_image_url": image.get("cached_image_url", image["url"]),
                }
            )
    return {
        "user_query": sample["content"],
        "webpages": controlled[0],
        "aux_images": controlled[1],
        "model_input": None,
        "model_response": answer["raw_response"],
        "usage": answer["usage"],
        "processed_response": to_markdown(answer),
        "placeholder_response": "\n\n".join(text),
        "output_images": output,
        "num_output_images": len(output),
        "num_reference_webpages": len(source_map),
    }


def run(
    method="reference-single", limit=10, level=1, adapter=None, run_name=None, include_pilot=False
):
    if os.getenv("CITEWEAVE_BACKEND", "local") != "local":
        raise ValueError("Controlled Qwen comparisons require CITEWEAVE_BACKEND=local")
    dataset = config.DATA / "benchmark/dev_set.jsonl"
    samples = sorted(
        [
            r
            for r in rows(dataset)
            if (level == 0 or r["level"] == level)
            and (include_pilot or r["query_id"] not in PILOT_IDS)
        ],
        key=lambda r: r["query_id"],
    )
    if limit:
        samples = samples[:limit]
    out = config.RUNS / (run_name or f"{method}-level{level}-n{len(samples)}")
    out.mkdir(parents=True, exist_ok=True)
    manifest = {
        "method": method,
        "query_ids": [r["query_id"] for r in samples],
        "reference_commit": REFERENCE_COMMIT,
        "implementation_sha256": hashlib.sha256(
            b"".join(
                p.name.encode() + p.read_bytes() for p in sorted(Path(__file__).parent.glob("*.py"))
            )
        ).hexdigest(),
        "uv_lock_sha256": hashlib.sha256((config.ROOT / "uv.lock").read_bytes()).hexdigest(),
        "model": config.MODEL,
        "model_revision": json.loads((Path(config.MODEL) / "source.json").read_text()).get(
            "revision"
        )
        if (Path(config.MODEL) / "source.json").exists()
        else None,
        "backend": os.getenv("CITEWEAVE_BACKEND", "local"),
        "excluded_pilot_ids": [] if include_pilot else sorted(PILOT_IDS),
        "adapter": adapter,
        "adapter_revision": json.loads((Path(adapter) / "source.json").read_text()).get("revision")
        if adapter and (Path(adapter) / "source.json").exists()
        else None,
        "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
        "level": level,
        "max_input_tokens": config.MAX_INPUT,
        "max_new_tokens": config.MAX_NEW,
        "max_output_image_candidates": config.MAX_IMAGES,
        "precision": "bfloat16",
        "official_judge_completed": False,
        "candidate_protocol": "official score-filtered input pool; annotations not provided to generator",
    }
    if method == "citeweave":
        selection = config.RUNS / "crossencoder/selected.json"
        manifest["ranker"] = (
            json.loads(selection.read_text())
            if selection.exists()
            else {"architecture": "cosine_residual"}
        )
        weights = config.RUNS / "crossencoder/best/model.safetensors"
        if weights.exists():
            manifest["ranker_weights_sha256"] = hashlib.sha256(weights.read_bytes()).hexdigest()
    manifest_file = out / "manifest.json"
    if manifest_file.exists() and json.loads(manifest_file.read_text()) != manifest:
        raise ValueError("Existing run manifest differs; choose a new run name")
    manifest_file.write_text(json.dumps(manifest, indent=2))
    gen = Generator(adapter=adapter)
    ref = summarizer(gen, multi_stage=method == "reference-multi")
    engine = Engine(generator=gen)
    for sample in samples:
        path = out / (sample["query_id"] + ".json")
        if path.exists() and json.loads(path.read_text()).get("success"):
            continue
        t0 = time.monotonic()
        first_call = len(gen.calls)
        try:
            if method.startswith("reference"):
                result = ref.summarize([copy.deepcopy(sample)])
            else:
                sources, images = controlled_evidence(sample, ref)
                answer = engine.answer(sample["content"], sources, images)
                (out / (sample["query_id"] + ".answer.json")).write_text(
                    json.dumps(answer, ensure_ascii=False, indent=2)
                )
                pages = ref.filter_webpage_pieces([copy.deepcopy(sample)])
                aux = ref.remove_invalid_auxiliary_images([copy.deepcopy(sample)])
                filtered = ref.filter_images_and_reorganize_webpages(pages, aux)
                result = official_record(answer, sample, filtered)
            record = {
                "id": sample["query_id"],
                "success": True,
                "result": result,
                "seconds": time.monotonic() - t0,
                "calls": gen.calls[first_call:],
            }
        except Exception as e:
            record = {
                "id": sample["query_id"],
                "success": False,
                "error": f"{type(e).__name__}: {e}",
                "seconds": time.monotonic() - t0,
                "calls": gen.calls[first_call:],
                "last_response": gen.last_response,
            }
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(record, ensure_ascii=False, indent=2))
        temp.replace(path)
        print(
            json.dumps({k: v for k, v in record.items() if k not in ("result", "calls")}),
            flush=True,
        )
    return out


def structural_report(path):
    """Exact coverage diagnostics, NOT substitutes for the eight official metrics."""
    path = Path(path)
    records = [
        json.loads(p.read_text())
        for p in path.glob("*.json")
        if not p.name.endswith("answer.json")
        and p.name not in ("manifest.json", "diagnostics.json")
    ]
    successes = [r for r in records if r.get("success")]
    recalls, counts, seconds, truncations = [], [], [], []
    for r in successes:
        sample = r["result"]
        gold = {
            i["cached_image_url"]
            for w in sample["webpages"]
            for i in w["images"]
            if i.get("final_score") is not None and i["final_score"] >= 8
        }
        gold.update(
            i["cached_image_url"]
            for i in sample["aux_images"]
            if i.get("final_score") is not None and i["final_score"] >= 8
        )
        selected = {i["cached_image_url"] for i in r["result"]["output_images"]}
        recalls.append(len(gold & selected) / len(gold) if gold else 1.0)
        counts.append(len(selected))
        seconds.append(r["seconds"])
        truncations.append(sum(c.get("input_truncated", False) for c in r.get("calls", [])))
    import numpy as np

    report = {
        "status": "diagnostics_only_not_official_overall",
        "attempted": len(records),
        "successful": len(successes),
        "failed": len(records) - len(successes),
        "image_recall": float(np.mean(recalls)) if recalls else None,
        "mean_output_images": float(np.mean(counts)) if counts else None,
        "median_seconds": float(np.median(seconds)) if seconds else None,
        "truncated_calls": sum(
            c.get("input_truncated", False) for r in records for c in r.get("calls", [])
        ),
        "output_budget_reached_calls": sum(
            c.get("output_budget_reached", False) for r in records for c in r.get("calls", [])
        ),
    }
    (path / "diagnostics.json").write_text(json.dumps(report, indent=2))
    return report
