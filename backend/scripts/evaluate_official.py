"""Run the unchanged M2RAG evaluator with its original judge configuration.

Usage: uv run --group official python scripts/evaluate_official.py RUN_DIRECTORY --allow-paid-evaluation
The judges consume paid API tokens. No replacement judge is labeled official.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path

import yaml
from dotenv import load_dotenv
from preflight_evaluation import canonical_record, check_run, http_proxy_environment

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def check_cache_identity(previous, requested):
    for key in (
        "generation_manifest",
        "prediction_sha256",
        "judge_input_sha256",
        "judge_protocol_sha256",
        "judge_image_archive",
    ):
        if previous.get(key) != requested.get(key):
            raise ValueError(
                f"Existing judge cache differs in {key}; use a separate evaluation run"
            )


def main():
    p = argparse.ArgumentParser()
    p.add_argument("run_directory", type=Path, nargs="?")
    p.add_argument("--judge-protocol", choices=["original", "deepseek"], default="original")
    p.add_argument("--budget-usd", type=str)
    p.add_argument("--budget-batch", help="Shared spending ledger name for paired DeepSeek runs")
    p.add_argument(
        "--check-environment",
        action="store_true",
        help="Validate original evaluator imports without calling any API",
    )
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--allow-paid-evaluation", action="store_true")
    mode.add_argument(
        "--prepare-only",
        action="store_true",
        help="Validate and stage all original judge inputs without a key or any API requests",
    )
    args = p.parse_args()
    proxy = args.judge_protocol == "deepseek"
    if args.check_environment:
        sys.path.insert(0, str(ROOT / "reference/M2RAG"))
        from src.evaluator.few_shot_evaluator import LangchainLLMWrapper, SingleTurnSample

        if SingleTurnSample is None or LangchainLLMWrapper is None:
            raise RuntimeError("Original RAGAS evaluator imports failed")
        print("Original evaluator imports ready; no API requests made")
        return
    if args.run_directory is None:
        p.error("run_directory is required for evaluation")
    if not args.prepare_only and not args.allow_paid_evaluation:
        p.error(
            "Official evaluation consumes API credits; explicitly supply --allow-paid-evaluation"
        )
    key_name = "DEEPSEEK_API_KEY" if proxy else "OPENAI_API_KEY"
    if not args.prepare_only and not os.getenv(key_name):
        p.error(f"{key_name} is required for this judge protocol")
    if proxy and not args.prepare_only:
        if (
            not args.budget_usd
            or not args.budget_batch
            or not args.budget_batch.replace("-", "").isalnum()
        ):
            p.error("DeepSeek calls require --budget-usd and an alphanumeric/hyphen --budget-batch")
        from deepseek_proxy_entry import Budget

        Budget(ROOT / "runs/deepseek-budgets" / (args.budget_batch + ".json"), args.budget_usd)
    run = args.run_directory.resolve()
    manifest = json.loads((run / "manifest.json").read_text())
    preflight = check_run(run, require_complete=True)
    if not preflight["passed"]:
        report = ROOT / "runs/input-preflight" / (run.name + ".json")
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(preflight, indent=2))
        raise ValueError(f"Input preflight failed; no API calls made. See {report}")
    selected = []
    for qid in manifest["query_ids"]:
        file = run / f"{qid}.json"
        if not file.exists() or not json.loads(file.read_text()).get("success"):
            raise ValueError(
                f"Missing/failed prediction: {qid}. Complete predictions before official evaluation."
            )
        selected.append(file)
    reference = ROOT / "reference/M2RAG"
    expected = "ea6b9977f5a153215b38cd9a6aa3e4702ffbda22"
    rev = subprocess.check_output(
        ["git", "-C", str(reference), "rev-parse", "HEAD"], text=True
    ).strip()
    if rev != expected:
        raise ValueError("Unexpected reference revision")
    subprocess.run(
        [
            "git",
            "-C",
            str(reference),
            "diff",
            "--exit-code",
            "HEAD",
            "--",
            "src/evaluator",
            "src/model",
            "src/utils",
            "evaluate.py",
        ],
        check=True,
    )
    work = ROOT / "work" / ("deepseek-proxy" if proxy else "official")
    evaluation_root = (
        ROOT / "runs" / ("deepseek-proxy-evaluation" if proxy else "official-evaluation")
    )
    staging = work / run.name
    staging.mkdir(parents=True, exist_ok=True)
    if {p.name for p in staging.iterdir()} - {p.name for p in selected}:
        raise ValueError("Official staging directory contains unexpected files")
    prediction_hashes, judge_inputs = {}, {}
    for file in selected:
        prediction_hashes[file.name] = hashlib.sha256(file.read_bytes()).hexdigest()
        judge_inputs[file.name] = json.dumps(
            canonical_record(json.loads(file.read_text())), ensure_ascii=False
        )
    config = yaml.safe_load((reference / "src/config/evaluate_custom.yaml").read_text())
    if proxy:
        for name in ("model_config", "langchain_model_config"):
            config["evaluator_config"]["params"][name]["params"]["model"] = "deepseek-flash"
        config["evaluator_config"]["params"]["multi_thread_config"]["num_threads"] = 1
        config["multi_thread_config"]["num_threads"] = 1
    # Keep the original prompts, judge IDs, normalization, and metric aggregation.
    config["evaluator_config"]["params"]["log_dir"] = str(evaluation_root / run.name)
    cfg = work / (run.name + ".yaml")
    cfg_text = yaml.safe_dump(config)
    env = {
        **http_proxy_environment(os.environ),
        "IMAGE_ROOT": str(ROOT / "data/images"),
        "IMAGE_URL": "http://0.0.0.0:65535/",
        "PYTHONPATH": str(reference),
    }
    endpoint = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    if proxy:
        endpoint = "https://api.deepseek.com"
        env.update(OPENAI_API_KEY=os.getenv("DEEPSEEK_API_KEY", ""), OPENAI_BASE_URL=endpoint)
        if not args.prepare_only:
            env.update(
                CITEWEAVE_PROXY_BUDGET_USD=args.budget_usd,
                CITEWEAVE_PROXY_BUDGET_FILE=str(
                    ROOT / "runs/deepseek-budgets" / (args.budget_batch + ".json")
                ),
            )
    log_dir = evaluation_root / run.name
    log_dir.mkdir(parents=True, exist_ok=True)
    packages = {
        name: version(name)
        for name in (
            "ragas",
            "openai",
            "langchain-openai",
            "langchain-core",
            "datasets",
            "pyarrow",
            "numpy",
            "tiktoken",
            "pillow",
        )
    }
    protocol = json.loads(json.dumps(config))
    protocol["evaluator_config"]["params"].pop("log_dir", None)
    protocol = {
        "configuration": protocol,
        "reference_commit": expected,
        "packages": packages,
        "endpoint_sha256": hashlib.sha256(endpoint.encode()).hexdigest(),
    }
    if proxy:
        protocol["proxy_adapter"] = {
            "scope": "deepseek_proxy_not_original_judges",
            "source_sha256": hashlib.sha256(
                (ROOT / "scripts/deepseek_proxy_entry.py").read_bytes()
            ).hexdigest(),
            "thinking": "disabled",
            "max_output_tokens": 8192,
            "sdk_retries": 0,
            "tokenizer": "original fallback cl100k_base for context trimming",
            "documented_model_version": "DeepSeek-V4.1-Flash-1017 as documented 2026-10-19; alias may change",
            "docs": "https://api-docs.deepseek.com/guides/vision/",
        }
    requested = {
        "reference_commit": expected,
        "generation_manifest": manifest,
        "prediction_sha256": prediction_hashes,
        "judge_input_sha256": {
            name: hashlib.sha256(text.encode()).hexdigest() for name, text in judge_inputs.items()
        },
        "judge_config_sha256": hashlib.sha256(cfg_text.encode()).hexdigest(),
        "judge_protocol": protocol,
        "judge_protocol_sha256": hashlib.sha256(
            json.dumps(protocol, sort_keys=True).encode()
        ).hexdigest(),
        "bridge_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "preflight_sha256": hashlib.sha256(
            (Path(__file__).parent / "preflight_evaluation.py").read_bytes()
        ).hexdigest(),
        "judge_image_archive": preflight["images"],
        "export_note": "String iN image IDs become original numeric IDs; text/captions/URLs preserved",
        "input_preflight_complete": preflight["complete"],
        "official_judge_completed": False,
        "judge_kind": args.judge_protocol,
    }
    requested = json.loads(json.dumps(requested))
    request_file = log_dir / "request-manifest.json"
    if request_file.exists():
        check_cache_identity(json.loads(request_file.read_text()), requested)
    else:
        if (log_dir / "evaluate").exists():
            raise ValueError("Unattested judge cache exists; use a separate evaluation run")
        request_file.write_text(json.dumps(requested, indent=2))
    cfg.write_text(cfg_text)
    for name, text in judge_inputs.items():
        destination = staging / name
        temporary = destination.with_suffix(".tmp")
        temporary.write_text(text)
        temporary.replace(destination)
    if args.prepare_only:
        print(
            json.dumps(
                {
                    "scope": "prepared_deepseek_proxy_inputs_not_official_scores"
                    if proxy
                    else "prepared_inputs_not_quality_evaluation",
                    "predictions": len(selected),
                    "used_image_files": len(preflight["images"]),
                    "staging_directory": str(staging),
                    "request_manifest": str(request_file),
                    "external_judge_requests": 0,
                },
                indent=2,
            )
        )
        return
    result = subprocess.Popen(
        [
            sys.executable,
            str(ROOT / "scripts/deepseek_proxy_entry.py" if proxy else reference / "evaluate.py"),
            "--summarize-log-dir",
            str(staging),
            "--config-file",
            str(cfg),
        ],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    with (log_dir / ("proxy-summary.log" if proxy else "official-summary.log")).open("w") as log:
        for line in result.stdout:
            print(line, end="", flush=True)
            log.write(line)
            log.flush()
    code = result.wait()
    if code == 0:
        from official_quality_report import summarize

        summary = summarize(run, judge_protocol=args.judge_protocol)
        (log_dir / "validated-summary.json").write_text(
            json.dumps(summary, indent=2, allow_nan=False)
        )
        request = json.loads(request_file.read_text())
        request.update(
            official_judge_completed=not proxy,
            proxy_judge_completed=proxy,
            quality_report_sha256=hashlib.sha256(
                (Path(__file__).parent / "official_quality_report.py").read_bytes()
            ).hexdigest(),
        )
        request_file.write_text(json.dumps(request, indent=2))
    raise SystemExit(code)


if __name__ == "__main__":
    main()
