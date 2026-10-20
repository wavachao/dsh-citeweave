"""Train a compact relevance head on official TRAINING captions only."""

import json
import random

import numpy as np

from . import config
from .data import audit, snapshot_groups
from .ranking import Ranker, make_head


def ndcg(labels, scores, k=5):
    order = np.argsort(-np.asarray(scores), kind="stable")[:k]
    ideal = sorted(labels, reverse=True)[:k]
    discount = 1 / np.log2(np.arange(len(order)) + 2)
    denominator = float(np.sum(np.asarray(ideal) * discount))
    return float(np.sum(np.asarray(labels)[order] * discount) / denominator) if denominator else 1.0


def train(epochs=100, seed=42):
    import torch

    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.use_deterministic_algorithms(True, warn_only=True)
    output = config.RUNS / "ranker"
    output.mkdir(parents=True, exist_ok=True)
    training = config.DATA / "training/data/llm/raw.jsonl"
    report = audit(config.DATA / "benchmark/dev_set.jsonl", training)
    groups = list(
        snapshot_groups(config.DATA / "training/snapshot", config.DATA / "benchmark/dev_set.jsonl")
    )
    if not groups or not any(g["split"] == "validation" for g in groups):
        raise ValueError("Insufficient independent train/validation groups")
    cache = output / "features.npz"
    spans_file = output / "groups.json"
    metadata_file = output / "feature-metadata.json"
    metadata = {
        "snapshots": report["snapshot_sha256"],
        "encoder": json.loads((config.ROOT / "models/bge-small-en-v1.5/source.json").read_text()),
    }
    cached_spans = json.loads(spans_file.read_text()) if spans_file.exists() else []
    if (
        cache.exists()
        and metadata_file.exists()
        and json.loads(metadata_file.read_text()) == metadata
        and [g["id"] for g in cached_spans] == [g["id"] for g in groups]
    ):
        data = np.load(cache)
        features, labels, spans = data["features"], data["labels"], cached_spans
    else:
        ranker = Ranker(checkpoint=output / "not-loaded.pt")
        xs, ys, spans, offset = [], [], [], 0
        for group in groups:
            vectors = ranker.encode([group["query"], *[c["caption"] for c in group["candidates"]]])
            x = ranker.features(vectors[0], vectors[1:])
            labels = np.array([c["label"] for c in group["candidates"]], dtype=np.float32)
            xs.append(x)
            ys.append(labels)
            spans.append(
                {
                    "start": offset,
                    "end": offset + len(labels),
                    "split": group["split"],
                    "id": group["id"],
                    "cosine": (vectors[1:] @ vectors[0]).tolist(),
                }
            )
            offset += len(labels)
        features, labels = np.concatenate(xs), np.concatenate(ys)
        np.savez_compressed(cache, features=features, labels=labels)
        spans_file.write_text(json.dumps(spans, indent=2))
        metadata_file.write_text(json.dumps(metadata, indent=2))
    train_ids = np.concatenate(
        [np.arange(g["start"], g["end"]) for g in spans if g["split"] == "train"]
    )
    val_ids = np.concatenate(
        [np.arange(g["start"], g["end"]) for g in spans if g["split"] == "validation"]
    )
    x = torch.from_numpy(features).cuda()
    y = torch.from_numpy(labels).cuda()
    model = make_head(x.shape[1]).cuda()
    opt = torch.optim.AdamW(model.parameters(), lr=5e-4, weight_decay=0.05)
    loss_fn = torch.nn.BCEWithLogitsLoss()
    best, history = -1.0, []
    validation = [g for g in spans if g["split"] == "validation"]
    base = [ndcg(labels[g["start"] : g["end"]], g["cosine"]) for g in validation]
    pairs = []
    for group in spans:
        if group["split"] != "train":
            continue
        ids = np.arange(group["start"], group["end"])
        pos, neg = ids[labels[ids] > 0], ids[labels[ids] == 0]
        pairs.extend(
            (int(np.random.choice(pos)), int(np.random.choice(neg)))
            for _ in range(min(20, len(pos) * len(neg)))
        )
    pairs = torch.tensor(pairs, device="cuda")
    for epoch in range(epochs + 1):
        losses = [0.0]
        if epoch:
            model.train()
            losses = []
            for batch in pairs[torch.randperm(len(pairs), device="cuda")].split(256):
                opt.zero_grad(set_to_none=True)
                positive = model(x[batch[:, 0]]).flatten()
                negative = model(x[batch[:, 1]]).flatten()
                loss = torch.nn.functional.softplus(negative - positive).mean()
                loss += 0.05 * (
                    loss_fn(positive, torch.ones_like(positive))
                    + loss_fn(negative, torch.zeros_like(negative))
                )
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                opt.step()
                losses.append(float(loss.detach()))
        model.eval()
        with torch.inference_mode():
            scores = model(x).sigmoid().flatten().cpu().numpy()
            val_loss = float(loss_fn(model(x[val_ids]).flatten(), y[val_ids]))
        values = [
            ndcg(labels[g["start"] : g["end"]], scores[g["start"] : g["end"]]) for g in validation
        ]
        score = float(np.mean(values))
        history.append(
            {
                "epoch": epoch,
                "loss": float(np.mean(losses)),
                "val_loss": val_loss,
                "ndcg5": score,
            }
        )
        if score > best:
            best = score
            # Calibrate abstention using validation labels only.
            best_threshold, best_f1 = 0.5, -1
            for threshold in np.arange(0.2, 0.76, 0.05):
                pred = scores[val_ids] >= threshold
                gold = labels[val_ids] > 0
                tp = int(np.sum(pred & gold))
                f1 = 2 * tp / max(1, int(np.sum(pred) + np.sum(gold)))
                if f1 > best_f1:
                    best_threshold, best_f1 = float(threshold), f1
            torch.save(
                {
                    "state_dict": model.state_dict(),
                    "feature_dim": x.shape[1],
                    "threshold": best_threshold,
                    "seed": seed,
                    "architecture": "residual",
                },
                output / "best.pt",
            )
            np.save(output / "validation_scores.npy", scores[val_ids])
        if epoch % 10 == 0:
            print(json.dumps(history[-1]), flush=True)
    report.update(
        {
            "seed": seed,
            "epochs": epochs,
            "train_pairs": len(train_ids),
            "validation_pairs": len(val_ids),
            "cosine_validation_ndcg5": float(np.mean(base)),
            "trained_validation_ndcg5": best,
            "architecture": "cosine residual with pairwise ranking loss",
            "label_source": "original training VLM relevance: >=8 positive, <=3 negative; weak labels, not human gold",
            "evaluation_scope": "training-set held-out queries; not official M2RAG benchmark",
            "history": history,
        }
    )
    (output / "report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({k: v for k, v in report.items() if k != "history"}, indent=2))
    return report
