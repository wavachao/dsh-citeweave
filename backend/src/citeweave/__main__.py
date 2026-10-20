import argparse
import json


def main():
    p = argparse.ArgumentParser(prog="citeweave")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("audit")
    t = sub.add_parser("train-ranker")
    t.add_argument("--epochs", type=int, default=100)
    t.add_argument("--seed", type=int, default=42)
    c = sub.add_parser("train-crossencoder")
    c.add_argument("--epochs", type=int, default=3)
    c.add_argument("--seed", type=int, default=42)
    b = sub.add_parser("benchmark")
    b.add_argument(
        "--method",
        choices=["reference-single", "reference-multi", "citeweave"],
        default="reference-single",
    )
    b.add_argument("--limit", type=int, default=10, help="0 runs all eligible samples")
    b.add_argument("--level", type=int, choices=[0, 1, 2, 3], default=1)
    b.add_argument("--adapter")
    b.add_argument("--name")
    b.add_argument(
        "--include-pilot",
        action="store_true",
        help="Include known engineering/demo queries; not a held-out comparison",
    )
    d = sub.add_parser("diagnostics")
    d.add_argument("path")
    s = sub.add_parser("serve")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8765)
    args = p.parse_args()
    from .resources import gpu_session

    if args.command == "audit":
        from . import config
        from .data import audit

        report = audit(
            config.DATA / "benchmark/dev_set.jsonl",
            config.DATA / "training/data/llm/raw.jsonl",
        )
        config.RUNS.mkdir(exist_ok=True)
        (config.RUNS / "data-audit.json").write_text(json.dumps(report, indent=2))
        print(json.dumps(report, indent=2))
    elif args.command == "train-ranker":
        from .train import train

        with gpu_session():
            train(args.epochs, args.seed)
    elif args.command == "benchmark":
        from .benchmark import run

        with gpu_session():
            print(
                run(
                    args.method, args.limit, args.level, args.adapter, args.name, args.include_pilot
                )
            )
    elif args.command == "train-crossencoder":
        from .train_crossencoder import train_crossencoder

        with gpu_session():
            train_crossencoder(args.epochs, args.seed)
    elif args.command == "diagnostics":
        from .benchmark import structural_report

        print(json.dumps(structural_report(args.path), indent=2))
    else:
        from . import config

        if args.host not in ("127.0.0.1", "localhost", "::1") and not config.ACCESS_TOKEN:
            p.error("Network binding requires CITEWEAVE_ACCESS_TOKEN (at least 32 characters)")
        import uvicorn

        uvicorn.run("citeweave.app:app", host=args.host, port=args.port, proxy_headers=False)


if __name__ == "__main__":
    main()
