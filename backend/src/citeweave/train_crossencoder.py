"""Joint query-caption relevance fine-tuning on training-only VLM labels."""

import json
import random

import numpy as np
import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from . import config
from .data import audit, snapshot_groups
from .train import ndcg


def train_crossencoder(epochs=3, seed=42):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    output = config.RUNS / "crossencoder"
    output.mkdir(parents=True, exist_ok=True)
    base = config.ROOT / "models/ms-marco-MiniLM-L-6-v2"
    tokenizer = AutoTokenizer.from_pretrained(base, local_files_only=True)
    model = AutoModelForSequenceClassification.from_pretrained(base, local_files_only=True).cuda()
    report = audit(
        config.DATA / "benchmark/dev_set.jsonl", config.DATA / "training/data/llm/raw.jsonl"
    )
    groups = list(
        snapshot_groups(config.DATA / "training/snapshot", config.DATA / "benchmark/dev_set.jsonl")
    )
    validation = [g for g in groups if g["split"] == "validation"]
    training = [g for g in groups if g["split"] == "train"]
    prior = config.RUNS / "ranker/report.json"
    prior_report = json.loads(prior.read_text()) if prior.exists() else {}
    if prior_report.get("snapshot_sha256") == report["snapshot_sha256"]:
        cosine_baseline = prior_report["cosine_validation_ndcg5"]
    else:
        from .ranking import Ranker

        encoder = Ranker(checkpoint=output / "unused.pt")
        baseline_values = []
        for group in validation:
            vectors = encoder.encode([group["query"], *[c["caption"] for c in group["candidates"]]])
            baseline_values.append(
                ndcg([c["label"] for c in group["candidates"]], vectors[1:] @ vectors[0])
            )
        cosine_baseline = float(np.mean(baseline_values))
    val_queries, val_captions, val_labels, spans = [], [], [], []
    for group in validation:
        start = len(val_labels)
        for candidate in group["candidates"]:
            val_queries.append(group["query"])
            val_captions.append(candidate["caption"])
            val_labels.append(candidate["label"])
        spans.append((start, len(val_labels)))
    history = []
    best = -1
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-5, weight_decay=0.01)
    loss_fn = torch.nn.BCEWithLogitsLoss()

    def encode(queries, captions):
        return tokenizer(
            queries, captions, padding=True, truncation=True, max_length=256, return_tensors="pt"
        ).to("cuda")

    for epoch in range(epochs + 1):
        losses = []
        if epoch:
            model.train()
            pairs = []
            for group in training:
                positive = [c["caption"] for c in group["candidates"] if c["label"]]
                negative = [c["caption"] for c in group["candidates"] if not c["label"]]
                for _ in range(min(4, len(positive) * len(negative))):
                    pairs.append((group["query"], random.choice(positive), random.choice(negative)))
            random.shuffle(pairs)
            for start in range(0, len(pairs), 16):
                batch = pairs[start : start + 16]
                queries = [p[0] for p in batch] * 2
                captions = [p[1] for p in batch] + [p[2] for p in batch]
                optimizer.zero_grad(set_to_none=True)
                logits = model(**encode(queries, captions)).logits.flatten()
                positive, negative = logits[: len(batch)], logits[len(batch) :]
                loss = torch.nn.functional.softplus(negative - positive).mean()
                loss += 0.1 * (
                    loss_fn(positive, torch.ones_like(positive))
                    + loss_fn(negative, torch.zeros_like(negative))
                )
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1)
                optimizer.step()
                losses.append(float(loss.detach()))
        model.eval()
        scores = []
        with torch.inference_mode():
            for start in range(0, len(val_queries), 32):
                logits = model(
                    **encode(val_queries[start : start + 32], val_captions[start : start + 32])
                ).logits
                scores.extend(logits.sigmoid().flatten().cpu().tolist())
        values = [ndcg(val_labels[start:end], scores[start:end]) for start, end in spans]
        score = float(np.mean(values))
        row = {
            "epoch": epoch,
            "validation_ndcg5": score,
            "training_loss": float(np.mean(losses)) if losses else None,
        }
        history.append(row)
        print(json.dumps(row), flush=True)
        if score > best:
            best = score
            probs, gold = np.array(scores), np.array(val_labels, dtype=bool)
            threshold, best_f1 = 0.5, -1
            for candidate in np.arange(0.1, 0.91, 0.05):
                pred = probs >= candidate
                tp = np.sum(pred & gold)
                f1 = float(2 * tp / max(1, np.sum(pred) + np.sum(gold)))
                if f1 > best_f1:
                    threshold, best_f1 = float(candidate), f1
            model.save_pretrained(output / "best", safe_serialization=True)
            tokenizer.save_pretrained(output / "best")
            selected = {
                "architecture": "crossencoder",
                "path": str((output / "best").relative_to(config.ROOT)),
                "threshold": threshold,
                "validation_ndcg5": best,
                "selected_epoch": epoch,
                "deploy": best >= cosine_baseline,
                "max_length": 256,
            }
            (output / "selected.json").write_text(json.dumps(selected, indent=2))
            np.save(output / "validation_scores.npy", np.array(scores))
    report.update(
        {
            "seed": seed,
            "epochs": epochs,
            "history": history,
            "best_validation_ndcg5": best,
            "cosine_validation_ndcg5": cosine_baseline,
            "model": str(base),
            "label_source": "training-only VLM relevance annotations",
            "evaluation_scope": "training-set validation queries, not official benchmark",
        }
    )
    (output / "report.json").write_text(json.dumps(report, indent=2))
    return report
