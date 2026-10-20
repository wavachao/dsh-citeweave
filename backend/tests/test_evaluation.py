import copy
import importlib.util
from pathlib import Path

import pytest
from PIL import Image

spec = importlib.util.spec_from_file_location(
    "preflight", Path(__file__).parents[1] / "scripts/preflight_evaluation.py"
)
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)


def record():
    image = {
        "id": "i0",
        "image_caption": "Visible diagram",
        "detailed_image_caption": "Visible diagram",
        "cached_image_url": preflight.IMAGE_PREFIX + "ELI5/dev_set/a/0.jpeg",
    }
    return {
        "id": "a",
        "success": True,
        "result": {
            "webpages": [{"images": [image]}],
            "aux_images": [],
            "user_query": "Why?",
            "placeholder_response": "Explanation<IMAGE_PLACEHOLDER>",
            "num_output_images": 1,
            "output_images": [image],
        },
    }


def test_preflight_export_keeps_raw_record_and_canonical_image_identity():
    raw = record()
    before = copy.deepcopy(raw)
    exported = preflight.canonical_record(raw)
    assert raw == before
    assert exported["result"]["output_images"][0]["id"] == 0
    raw["result"]["output_images"][0]["id"] = "i9"
    with pytest.raises(ValueError, match="Unknown"):
        preflight.canonical_record(raw)


def test_preflight_rejects_escaping_or_unexpected_archive_urls(tmp_path):
    for url in [preflight.IMAGE_PREFIX + "../secret", "https://example.com/private.jpg"]:
        with pytest.raises(ValueError):
            preflight.archived_image(url, tmp_path)


def test_preflight_requires_complete_predictions_and_decodable_images(tmp_path):
    import json

    run = tmp_path / "run"
    run.mkdir()
    (run / "manifest.json").write_text(json.dumps({"query_ids": ["a", "b"]}))
    (run / "a.json").write_text(json.dumps(record()))
    image_root = tmp_path / "images"
    image = preflight.archived_image(
        record()["result"]["output_images"][0]["cached_image_url"], image_root
    )
    image.parent.mkdir(parents=True)
    Image.new("RGB", (20, 30)).save(image)
    report = preflight.check_run(run, image_root, require_complete=True)
    assert not report["passed"] and report["valid_predictions"] == 1
    assert report["missing_predictions"] == ["b"]
    image.write_bytes(b"corrupt image")
    report = preflight.check_run(run, image_root)
    assert not report["passed"] and report["valid_predictions"] == 0 and report["errors"]


def test_outer_fence_repair_keeps_unwrapped_prose_and_inner_code():
    spec = importlib.util.spec_from_file_location(
        "repair", Path(__file__).parents[1] / "scripts/repair_reference_exports.py"
    )
    repair = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(repair)
    prose = "An explanation.\n\n```markdown\n![Diagram](images/0.jpeg)"
    assert repair.unwrap_outer_fence(prose) == prose
    assert repair.unwrap_outer_fence("```markdown\nA complete answer.\n```") == "A complete answer."
    assert repair.unwrap_outer_fence("```markdown\nAn unclosed wrapper.") == "An unclosed wrapper."


def test_reference_duplicate_control_preserves_prose_and_first_valid_image(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "scripts"))
    from repair_reference_exports import remove_repeated_image_markers

    text = "A ![First](images/0.jpeg) B ![First](images/0.jpeg) C ![New](images/0.jpeg) D ![Unknown](images/9.jpeg) E ![Other](images/1.jpeg)"
    clean, removed = remove_repeated_image_markers(text, 2)
    assert removed == 2
    assert (
        clean
        == "A ![First](images/0.jpeg) B  C  D ![Unknown](images/9.jpeg) E ![Other](images/1.jpeg)"
    )
    assert remove_repeated_image_markers(clean, 2) == (clean, 0)


def load_quality(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "scripts"))
    import official_quality_report

    return official_quality_report


def judge_fixture(quality, number, precision):
    prediction = record()
    template = prediction["result"]["output_images"][0]
    images = [
        {
            **template,
            "id": i,
            "cached_image_url": preflight.IMAGE_PREFIX + f"ELI5/dev_set/a/{i}.jpeg",
            "final_score": 8,
        }
        for i in range(number)
    ]
    prediction["result"].update(
        webpages=[{"content": "Source explanation", "images": images}],
        output_images=copy.deepcopy(images),
        num_output_images=number,
        placeholder_response="Explanation" + "<IMAGE_PLACEHOLDER>" * number,
    )
    rows = [
        {
            "id": "text-" + metric,
            "success": True,
            "result": {
                "score": 1 if metric in ("context_precision", "faithfulness") else 10,
                "normed_score": 1,
            },
        }
        for metric in quality.TEXT
    ]
    rows += [
        {
            "id": f"multi_modal-{metric}-{i}",
            "success": True,
            "result": {"score": precision * 10, "normed_score": precision},
        }
        for metric in quality.PRECISION
        for i in range(number)
    ]
    return prediction, rows


def test_original_precision_pooling_and_duplicate_recall_denominator(monkeypatch):
    import numpy as np

    quality = load_quality(monkeypatch)
    a, ar = judge_fixture(quality, 1, 1)
    b, br = judge_fixture(quality, 3, 0)
    ass, ac = quality.query_statistics(a, ar)
    bs, bc = quality.query_statistics(b, br)
    values = quality.aggregate(np.array([ass, bs]), np.array([ac, bc]))
    assert np.allclose(values[4:7], 0.25)  # Four images, not an average of two query scores.
    duplicate = copy.deepcopy(a["result"]["webpages"][0]["images"][0])
    duplicate["id"] = 1
    a["result"]["webpages"][0]["images"].append(duplicate)
    assert (
        quality.query_statistics(a, ar)[0][7] == 0.5
    )  # Original code counts the duplicate in its denominator.


def test_missing_nonfinite_or_incorrectly_normalized_judge_metrics_fail(monkeypatch):
    quality = load_quality(monkeypatch)
    prediction, rows = judge_fixture(quality, 1, 1)
    with pytest.raises(ValueError, match="Missing"):
        quality.query_statistics(prediction, [r for r in rows if r["id"] != "text-faithfulness"])
    with pytest.raises(ValueError, match="Nonfinite"):
        quality.finite_score(
            {
                "id": "synthetic-nan",
                "success": True,
                "result": {"score": float("nan"), "normed_score": 1},
            }
        )
    with pytest.raises(ValueError, match="normalization"):
        quality.finite_score(
            {"id": "synthetic-mismatch", "success": True, "result": {"score": 5, "normed_score": 1}}
        )


def test_paired_bootstrap_recomputes_pooling_and_is_zero_for_identical_runs(monkeypatch):
    import numpy as np

    quality = load_quality(monkeypatch)
    a, ar = judge_fixture(quality, 1, 1)
    b, br = judge_fixture(quality, 3, 0)
    ass, ac = quality.query_statistics(a, ar)
    bs, bc = quality.query_statistics(b, br)
    stats = np.array([ass, bs]), np.array([ac, bc])
    report = quality.bootstrap_difference(stats, stats, iterations=1200)
    assert report["undefined_resamples"] == 0 and not report["positive_overall_interval"]
    assert report["intervals"]["overall"] == [0, 0]


def test_judge_cache_rejects_a_different_protocol_or_prediction(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "scripts"))
    from evaluate_official import check_cache_identity

    keys = (
        "generation_manifest",
        "prediction_sha256",
        "judge_input_sha256",
        "judge_protocol_sha256",
        "judge_image_archive",
    )
    requested = {k: "same" for k in keys}
    check_cache_identity(copy.deepcopy(requested), requested)
    for key in ("judge_protocol_sha256", "prediction_sha256"):
        previous = {**requested, key: "different"}
        with pytest.raises(ValueError, match="judge cache differs"):
            check_cache_identity(previous, requested)


def test_clash_proxy_normalization_keeps_http_connect_and_no_proxy():
    env = {
        "HTTPS_PROXY": "http://127.0.0.1:7890",
        "HTTP_PROXY": "http://127.0.0.1:7890",
        "ALL_PROXY": "socks5://127.0.0.1:7891",
        "NO_PROXY": "127.0.0.1,localhost",
    }
    result = preflight.http_proxy_environment(env)
    assert result["ALL_PROXY"] == env["HTTPS_PROXY"] and result["NO_PROXY"] == env["NO_PROXY"]
    assert env["ALL_PROXY"].startswith("socks5:")  # Original environment untouched.
    socks_only = {"ALL_PROXY": "socks5://127.0.0.1:7891"}
    assert preflight.http_proxy_environment(socks_only) == socks_only  # No direct-route fallback.


def test_prepare_only_without_key_stages_canonical_inputs_and_never_starts_judge(
    tmp_path, monkeypatch
):
    import json
    import sys

    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "scripts"))
    import evaluate_official as bridge

    run = tmp_path / "runs/example"
    run.mkdir(parents=True)
    (run / "manifest.json").write_text(json.dumps({"query_ids": ["a"]}))
    original = json.dumps(record())
    (run / "a.json").write_text(original)
    config = tmp_path / "reference/M2RAG/src/config/evaluate_custom.yaml"
    config.parent.mkdir(parents=True)
    config.write_text("evaluator_config:\n  params:\n    log_dir: unused\n")
    monkeypatch.setattr(bridge, "ROOT", tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(bridge, "version", lambda name: "offline-test")
    monkeypatch.setattr(
        bridge,
        "check_run",
        lambda *a, **kw: {"passed": True, "complete": True, "images": {}},
    )
    monkeypatch.setattr(
        bridge.subprocess,
        "check_output",
        lambda *a, **kw: "ea6b9977f5a153215b38cd9a6aa3e4702ffbda22\n",
    )
    monkeypatch.setattr(bridge.subprocess, "run", lambda *a, **kw: None)

    def forbid_judge(*args, **kwargs):
        pytest.fail("Preparation must never start the evaluator or an API client")

    monkeypatch.setattr(bridge.subprocess, "Popen", forbid_judge)
    monkeypatch.setattr(sys, "argv", ["evaluate_official.py", str(run), "--prepare-only"])
    bridge.main()
    staged = json.loads((tmp_path / "work/official/example/a.json").read_text())
    assert staged["result"]["output_images"][0]["id"] == 0
    assert (run / "a.json").read_text() == original
    request = json.loads(
        (tmp_path / "runs/official-evaluation/example/request-manifest.json").read_text()
    )
    assert request["input_preflight_complete"] and not request["official_judge_completed"]
    assert not (tmp_path / "runs/official-evaluation/example/official-summary.log").exists()


def test_paired_pilot_selection_is_shared_and_copies_parent_bytes(tmp_path, monkeypatch):
    import json

    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "scripts"))
    from prepare_paired_subset import prepare

    parents = [tmp_path / name for name in ("left", "right")]
    for parent in parents:
        parent.mkdir()
        (parent / "manifest.json").write_text(json.dumps({"query_ids": ["a", "b", "c"]}))
        for qid in ("a", "b", "c"):
            (parent / (qid + ".json")).write_text(json.dumps({"id": qid, "success": True}))
    report = prepare(*parents, count=2)
    assert len(report["query_ids"]) == 2
    for parent, name in zip(parents, report["runs"]):
        output = Path(name)
        assert (
            json.loads((output / "manifest.json").read_text())["query_ids"] == report["query_ids"]
        )
        for qid in report["query_ids"]:
            assert (output / (qid + ".json")).read_bytes() == (
                parent / (qid + ".json")
            ).read_bytes()
    with pytest.raises(ValueError, match="distinct and new"):
        prepare(*parents, count=2)


def test_official_report_rejects_proxy_judge_identity_even_if_cache_is_copied(
    tmp_path, monkeypatch
):
    import json

    quality = load_quality(monkeypatch)
    monkeypatch.setattr(quality, "ROOT", tmp_path)
    run = tmp_path / "runs/example"
    run.mkdir(parents=True)
    manifest = {"query_ids": []}
    (run / "manifest.json").write_text(json.dumps(manifest))
    cache = tmp_path / "runs/official-evaluation/example"
    cache.mkdir(parents=True)
    (cache / "request-manifest.json").write_text(
        json.dumps({"generation_manifest": manifest, "judge_kind": "deepseek"})
    )
    with pytest.raises(ValueError, match="Judge kind"):
        quality.load_run(run)
