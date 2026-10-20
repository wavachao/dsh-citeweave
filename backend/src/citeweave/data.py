import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlparse


def rows(path):
    with Path(path).open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def split_key(query):
    return int(hashlib.sha256(query.strip().lower().encode()).hexdigest()[:8], 16) % 10


def training_groups(path):
    """Teacher-selected images are weak labels, never benchmark annotations."""
    seen = set()
    for row in rows(path):
        prompt = row["model_input"]
        question = re.search(r"# Question\n(.*?)\n\n# Webpages", prompt, re.S)
        if not question:
            continue
        query = question[1].strip()
        if query in seen:
            continue
        seen.add(query)
        matches = re.findall(
            r"!\[([^\]]*?)\]\((images/\d+\.[a-zA-Z]+)\)", prompt[question.end() :], re.S
        )
        selected = set(re.findall(r"!\[.*?\]\((images/\d+\.[a-zA-Z]+)\)", row["model_response"]))
        candidates = list(
            {
                image: {
                    "id": image,
                    "caption": re.sub(r"\s+", " ", caption),
                    "label": int(image in selected),
                }
                for caption, image in matches
            }.values()
        )
        if (
            candidates
            and any(x["label"] for x in candidates)
            and any(not x["label"] for x in candidates)
        ):
            yield {
                "id": row["id"],
                "query": query,
                "candidates": candidates,
                "split": "validation" if split_key(query) == 0 else "train",
            }


def snapshot_groups(snapshot, benchmark):
    """Use original TRAINING element relevance annotations, not output inclusion.

    Positive >=8, negative <=3; ambiguous examples are excluded. No evaluation
    rationales or numeric scores enter the encoder inputs.
    """
    import gzip
    from collections import defaultdict

    from bson import decode_file_iter

    snapshot = Path(snapshot)
    held_out = list(rows(benchmark))
    benchmark_ids = {r["query_id"] for r in held_out}
    benchmark_queries = {r["content"].strip().lower() for r in held_out}
    queries = {}
    with gzip.open(snapshot / "queries.bson.gz", "rb") as f:
        for d in decode_file_iter(f):
            query = d.get("query_content", "").strip()
            if d["query_id"] not in benchmark_ids and query.lower() not in benchmark_queries:
                queries[d["query_id"]] = query
    candidates = defaultdict(dict)
    for collection in ("images", "aux_images"):
        with gzip.open(snapshot / (collection + ".bson.gz"), "rb") as f:
            for d in decode_file_iter(f):
                qid, caption, score = d["query_id"], d.get("caption"), d.get("final_score")
                if qid not in queries or not d.get("valid") or not caption or score is None:
                    continue
                if 3 < score < 8:
                    continue
                candidates[qid][caption.strip().lower()] = {
                    "id": d["image_url"],
                    "caption": caption,
                    "label": int(score >= 8),
                }
    seen_queries = set()
    for qid in sorted(candidates):
        query = queries[qid]
        values = list(candidates[qid].values())
        if (
            query.lower() in seen_queries
            or not any(c["label"] for c in values)
            or not any(not c["label"] for c in values)
        ):
            continue
        seen_queries.add(query.lower())
        yield {
            "id": qid,
            "query": query,
            "candidates": values,
            "split": "validation" if split_key(query) == 0 else "train",
        }


def benchmark_evidence(sample):
    sources, images = [], []
    for page in sample["webpages"]:
        sid = f"s{len(sources)}"
        pieces = sorted(
            page.get("cleaned_webpage_splits") or [], key=lambda p: p.get("split_id", 0)
        )
        # Scores and evaluator rationales are withheld from learned inference.
        sources.append(
            {
                "id": sid,
                "title": page["title"],
                "url": page["url"],
                "text": "\n".join(
                    re.sub(r"<IMAGE_PLACEHOLDER>\[\d+\]", "", p["text"]) for p in pieces
                ),
            }
        )
        for image in page.get("images", []):
            if image.get("valid") and image.get("detailed_image_caption"):
                images.append(_image(image, sid, page["url"]))
    for image in sample.get("aux_images", []):
        if image.get("valid") and image.get("detailed_image_caption"):
            images.append(_image(image, None, image.get("webpage_url", "")))
    for i, image in enumerate(images):
        image["id"] = f"i{i}"
    return sources, images


def _image(image, sid, source_url):
    cached = image.get("cached_image_url", "")
    relative = urlparse(cached).path.lstrip("/")
    return {
        "url": image["image_url"],
        "cached_image_url": cached,
        "local_path": str(Path("data/images") / relative),
        "caption": image["detailed_image_caption"],
        "source_id": sid,
        "source_url": source_url,
        "caption_kind": "provided_dataset_caption",
    }


def audit(benchmark, training):
    from collections import Counter

    bench = list(rows(benchmark))
    snapshot = Path(training).parents[2] / "snapshot"
    groups = (
        list(snapshot_groups(snapshot, benchmark))
        if snapshot.exists()
        else list(training_groups(training))
    )
    bench_queries = {r["content"].strip().lower() for r in bench}
    overlap = [g["id"] for g in groups if g["query"].strip().lower() in bench_queries]
    if overlap:
        raise ValueError(f"Train/benchmark query overlap: {overlap}")
    return {
        "benchmark_rows": len(bench),
        "levels": dict(Counter(r["level"] for r in bench)),
        "training_rows": sum(1 for _ in rows(training)),
        "usable_ranker_queries": len(groups),
        "ranker_splits": dict(Counter(g["split"] for g in groups)),
        "query_overlap": len(overlap),
        "benchmark_sha256": hashlib.sha256(Path(benchmark).read_bytes()).hexdigest(),
        "training_sha256": hashlib.sha256(Path(training).read_bytes()).hexdigest(),
        "label_source": "training snapshot VLM element-relevance annotations"
        if snapshot.exists()
        else "distilled output selections",
        "snapshot_sha256": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(snapshot.glob("*.bson.gz"))
        }
        if snapshot.exists()
        else {},
    }
