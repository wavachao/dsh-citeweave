import hashlib
import os
import re
from pathlib import Path

import numpy as np

from . import config


class Ranker:
    def __init__(self, checkpoint=None):
        self.encoder = None
        self.head = None
        self.checkpoint = checkpoint or config.RANKER
        self.threshold = 0.5
        self.cross_encoder = None
        self.cross_tokenizer = None
        self.device = os.getenv("CITEWEAVE_RANKER_DEVICE", "cuda")

    def load(self):
        if self.encoder is None:
            from sentence_transformers import SentenceTransformer

            self.encoder = SentenceTransformer(
                config.EMBEDDING_MODEL, device=self.device, local_files_only=True
            )
        if self.head is None and Path(self.checkpoint).exists():
            import torch

            saved = torch.load(self.checkpoint, map_location=self.device, weights_only=True)
            self.head = (
                make_head(saved["feature_dim"], saved.get("architecture", "mlp"))
                .to(self.device)
                .eval()
            )
            self.head.load_state_dict(saved["state_dict"])
            self.threshold = saved["threshold"]

    def encode(self, texts):
        self.load()
        return self.encoder.encode(
            texts,
            batch_size=64,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )

    def unload(self):
        import gc

        import torch

        self.encoder = self.head = self.cross_encoder = self.cross_tokenizer = None
        gc.collect()
        torch.cuda.empty_cache()

    @staticmethod
    def features(query, docs):
        q = np.broadcast_to(query, docs.shape)
        return np.concatenate([q, docs, q * docs, np.abs(q - docs)], axis=1).astype(np.float32)

    def score(self, query, captions):
        if not captions:
            return np.array([]), np.empty((0, 384))
        vectors = self.encode([query, *captions])
        selected_file = config.RUNS / "crossencoder/selected.json"
        if selected_file.exists():
            import json

            selected = json.loads(selected_file.read_text())
            if selected.get("deploy"):
                import torch
                from transformers import (
                    AutoModelForSequenceClassification,
                    AutoTokenizer,
                )

                if self.cross_encoder is None:
                    checkpoint = config.RUNS / "crossencoder/best"
                    if not checkpoint.exists():
                        checkpoint = config.ROOT / selected["path"]
                    self.cross_tokenizer = AutoTokenizer.from_pretrained(
                        checkpoint, local_files_only=True
                    )
                    self.cross_encoder = (
                        AutoModelForSequenceClassification.from_pretrained(
                            checkpoint, local_files_only=True
                        )
                        .to(self.device)
                        .eval()
                    )
                self.threshold = selected["threshold"]
                scores = []
                with torch.inference_mode():
                    for start in range(0, len(captions), 32):
                        batch = captions[start : start + 32]
                        tokens = self.cross_tokenizer(
                            [query] * len(batch),
                            batch,
                            padding=True,
                            truncation=True,
                            max_length=selected["max_length"],
                            return_tensors="pt",
                        ).to(self.device)
                        scores.extend(
                            self.cross_encoder(**tokens).logits.sigmoid().flatten().cpu().tolist()
                        )
                return np.array(scores), vectors[1:]
        if self.head is None:
            return vectors[1:] @ vectors[0], vectors[1:]
        import torch

        with torch.inference_mode():
            x = torch.from_numpy(self.features(vectors[0], vectors[1:])).to(self.device)
            return self.head(x).sigmoid().flatten().cpu().numpy(), vectors[1:]

    def select(self, query, images, limit=None):
        if not images:
            return []
        scores, vectors = self.score(query, [i["caption"] for i in images])
        available = list(range(len(images)))
        chosen = []
        seen = set()
        limit = config.MAX_IMAGES if limit is None else limit
        while available and len(chosen) < limit:
            # Moderate redundancy penalty preserves individually useful images.
            def utility(i):
                redundancy = max((float(vectors[i] @ vectors[j]) for j in chosen), default=0)
                return float(scores[i]) - 0.15 * max(0, redundancy - 0.75)

            best = max(available, key=utility)
            available.remove(best)
            image = images[best]
            fingerprint = hashlib.sha256(
                re.sub(r"\W+", "", image["caption"].lower()).encode()
            ).hexdigest()
            if image["url"] in seen or fingerprint in seen:
                continue
            if (self.head is not None or self.cross_encoder is not None) and scores[
                best
            ] < self.threshold:
                continue
            seen.update([image["url"], fingerprint])
            chosen.append(best)
        return [{**images[i], "relevance_score": float(scores[i])} for i in chosen]


def make_head(dim, architecture="residual"):
    import torch

    layers = torch.nn.Sequential(
        torch.nn.Linear(dim, 128),
        torch.nn.GELU(),
        torch.nn.Dropout(0.15),
        torch.nn.Linear(128, 1),
    )
    if architecture == "mlp":
        return layers
    torch.nn.init.zeros_(layers[-1].weight)
    torch.nn.init.zeros_(layers[-1].bias)

    class ResidualRanker(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.residual = layers

        def forward(self, x):
            d = x.shape[1] // 4
            cosine = x[:, 2 * d : 3 * d].sum(dim=1, keepdim=True)
            return 8 * (cosine - 0.55) + 0.5 * self.residual(x)

    return ResidualRanker()
