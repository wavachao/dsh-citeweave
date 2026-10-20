"""Aggregate original judge logs and bootstrap paired queries using original pooling.

No API calls. Synthetic unit tests never enter real evaluation directories.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from preflight_evaluation import archived_image, canonical_record

ROOT = Path(__file__).resolve().parents[1]
TEXT = ("fluency", "response_relevancy", "context_precision", "faithfulness")
PRECISION = ("image_coherence", "image_helpfulness", "image_reference")
METRICS = (*TEXT, *PRECISION, "image_recall")


def finite_score(row, upper_bound=10):
    if not row.get("success"):
        raise ValueError(f"Judge task failed: {row.get('id')}")
    score = row["result"]["score"]
    normalized = row["result"]["normed_score"]
    if not math.isfinite(score) or not math.isfinite(normalized) or not 0 <= normalized <= 1:
        raise ValueError(f"Nonfinite/invalid judge score: {row.get('id')}")
    expected = max(0, min(upper_bound, score)) / upper_bound
    if not math.isclose(normalized, expected, abs_tol=1e-12):
        raise ValueError(f"Judge normalization mismatch: {row.get('id')}")
    return float(normalized)


def query_statistics(prediction, judge_rows):
    """Return sums/counts; image precision is pooled per image, not per query."""
    data = canonical_record(prediction)["result"]
    if not data["placeholder_response"].strip():
        raise ValueError("Empty answer is an invalid comparison case; do not drop it silently")
    selected = {}
    for row in judge_rows:
        key = row["id"]
        # RAGAS reuses the first successful row; the task manager uses the last
        # row for other metrics. Preserve these original cache conventions.
        if key in ("text-context_precision", "text-faithfulness"):
            if row.get("success") and key not in selected:
                selected[key] = row
        else:
            selected[key] = row
    sums, counts = np.zeros(8), np.zeros(8)
    for j, metric in enumerate(TEXT):
        key = "text-" + metric
        if key not in selected:
            raise ValueError(f"Missing judge metric: {key}")
        sums[j], counts[j] = (
            finite_score(
                selected[key], 1 if metric in ("context_precision", "faithfulness") else 10
            ),
            1,
        )
    for j, metric in enumerate(PRECISION, start=4):
        for i in range(len(data["output_images"])):
            key = f"multi_modal-{metric}-{i}"
            if key not in selected:
                raise ValueError(f"Missing judge metric: {key}")
            sums[j] += finite_score(selected[key])
            counts[j] += 1
    pool = [i for page in data["webpages"] for i in page["images"]] + data["aux_images"]
    positives = [i["cached_image_url"] for i in pool if i["final_score"] >= 8]
    outputs = {i["cached_image_url"] for i in data["output_images"]}
    # The original denominator is the positive-image LIST length, even when
    # duplicate URLs occur. Coverage-only diagnostics use a distinct definition.
    sums[7] = len(set(positives) & outputs) / len(positives) if positives else 1.0
    counts[7] = 1
    return sums, counts


def aggregate(sums, counts):
    denominator = np.asarray(counts).sum(axis=-2)
    return np.divide(
        np.asarray(sums).sum(axis=-2),
        denominator,
        out=np.full_like(denominator, np.nan, dtype=float),
        where=denominator > 0,
    )


def score_dict(values):
    if not np.isfinite(values).all():
        raise ValueError("Original metric pooling is undefined for this set of outputs")
    return {**dict(zip(METRICS, map(float, values))), "overall": float(np.mean(values))}


def evaluation_directory(run, judge_protocol):
    folder = {"original": "official-evaluation", "deepseek": "deepseek-proxy-evaluation"}[
        judge_protocol
    ]
    return ROOT / "runs" / folder / run.name


def load_run(run, judge_protocol="original"):
    manifest = json.loads((run / "manifest.json").read_text())
    evaluation = evaluation_directory(run, judge_protocol)
    request = json.loads((evaluation / "request-manifest.json").read_text())
    if request.get("judge_kind", "original") != judge_protocol:
        raise ValueError(
            "Judge kind does not match the requested report; proxy scores are not official"
        )
    if manifest != request["generation_manifest"]:
        raise ValueError("Prediction manifest changed since judging")
    sums, counts = [], []
    for qid in manifest["query_ids"]:
        prediction = run / (qid + ".json")
        if (
            hashlib.sha256(prediction.read_bytes()).hexdigest()
            != request["prediction_sha256"][prediction.name]
        ):
            raise ValueError(f"Prediction changed since judging: {qid}")
        logfile = evaluation / "evaluate" / run.name / (qid + ".jsonl")
        judge_rows = [json.loads(line) for line in logfile.read_text().splitlines() if line.strip()]
        a, b = query_statistics(json.loads(prediction.read_text()), judge_rows)
        sums.append(a)
        counts.append(b)
    for url, metadata in request["judge_image_archive"].items():
        image = archived_image(url, ROOT / "data/images")
        if hashlib.sha256(image.read_bytes()).hexdigest() != metadata["sha256"]:
            raise ValueError("Judge image archive changed since judging")
    return manifest, request, np.array(sums), np.array(counts)


def summarize(run, judge_protocol="original"):
    manifest, _, sums, counts = load_run(run, judge_protocol)
    values = aggregate(sums, counts)
    result = {
        "status": "validated_deepseek_proxy_metrics_not_original"
        if judge_protocol == "deepseek"
        else "validated_original_judge_metrics",
        "queries": len(manifest["query_ids"]),
        "scores": score_dict(values),
        "output_images": int(counts[:, 4].sum()),
        "queries_without_images": int(np.sum(counts[:, 4] == 0)),
    }
    # Cross-check our aggregation with the unchanged original evaluate.py output.
    log = (
        evaluation_directory(run, judge_protocol)
        / ("proxy-summary.log" if judge_protocol == "deepseek" else "official-summary.log")
    ).read_text()
    marker = log.rfind("Scores\n")
    if marker < 0:
        raise ValueError("Original evaluator did not print its final score table")
    original, _ = json.JSONDecoder().raw_decode(log[marker + 7 :].lstrip())
    original_values = [original["text"][m] for m in TEXT] + [
        original["multi_modal"][m] for m in (*PRECISION, "image_recall")
    ]
    if not np.allclose(values, original_values, rtol=0, atol=1e-9) or not math.isclose(
        float(values.mean()), original["overall"], abs_tol=1e-9
    ):
        raise ValueError("Original evaluator table and per-task log aggregation disagree")
    return result


def bootstrap_difference(left, right, iterations=10000, seed=42):
    ls, lc = left
    rs, rc = right
    if ls.shape != rs.shape or ls.shape[1] != 8:
        raise ValueError("Paired statistics have incompatible dimensions")
    observed = aggregate(rs, rc) - aggregate(ls, lc)
    rng = np.random.default_rng(seed)
    samples = []
    for start in range(0, iterations, 500):
        ids = rng.integers(0, len(ls), size=(min(500, iterations - start), len(ls)))
        samples.append(aggregate(rs[ids], rc[ids]) - aggregate(ls[ids], lc[ids]))
    samples = np.concatenate(samples)
    valid = np.isfinite(samples).all(axis=1)
    report = {
        "seed": seed,
        "resamples": iterations,
        "undefined_resamples": int(np.sum(~valid)),
        "difference": score_dict(observed),
        "intervals": {},
    }
    if not np.any(valid):
        raise ValueError("All bootstrap draws have undefined pooled metrics")
    samples = samples[valid]
    values = np.column_stack([samples, samples.mean(axis=1)])
    for j, name in enumerate((*METRICS, "overall")):
        report["intervals"][name] = np.quantile(values[:, j], [0.025, 0.975]).tolist()
    report["positive_overall_interval"] = bool(
        np.all(valid) and report["intervals"]["overall"][0] > 0
    )
    return report


def compare(left, right, judge_protocol="original"):
    lm, lreq, ls, lc = load_run(left, judge_protocol)
    rm, rreq, rs, rc = load_run(right, judge_protocol)
    for key in (
        "query_ids",
        "dataset_sha256",
        "model_revision",
        "adapter_revision",
        "max_input_tokens",
        "max_new_tokens",
        "precision",
        "candidate_protocol",
    ):
        if lm.get(key) != rm.get(key):
            raise ValueError(f"Paired comparison differs: {key}")
    if not lreq.get("judge_protocol_sha256") or lreq["judge_protocol_sha256"] != rreq.get(
        "judge_protocol_sha256"
    ):
        raise ValueError("Judge protocol fingerprints differ or are missing")
    # Require both original evaluator summary tables to match their task logs.
    left_summary, right_summary = summarize(left, judge_protocol), summarize(right, judge_protocol)
    return {
        "scope": "paired_deepseek_proxy_not_original_judge_comparison"
        if judge_protocol == "deepseek"
        else "paired_original_judge_quality_comparison",
        "left": str(left),
        "right": str(right),
        "left_summary": left_summary,
        "right_summary": right_summary,
        "bootstrap": bootstrap_difference((ls, lc), (rs, rc)),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("left", type=Path)
    parser.add_argument("right", type=Path, nargs="?")
    parser.add_argument("--judge-protocol", choices=["original", "deepseek"], default="original")
    args = parser.parse_args()
    result = (
        compare(args.left.resolve(), args.right.resolve(), args.judge_protocol)
        if args.right
        else summarize(args.left.resolve(), args.judge_protocol)
    )
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
