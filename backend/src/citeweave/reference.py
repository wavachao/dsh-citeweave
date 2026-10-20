"""Execute the pinned official summarizer classes, without unrelated provider imports.

Only imports are replaced by their standard-library equivalents and build_model.
Prompts, filtering, stage logic, and output parsing are the original implementation.
"""

import ast
import copy
import re
import subprocess
from abc import abstractmethod
from itertools import accumulate
from typing import Dict, List, Tuple

from . import config

REFERENCE_COMMIT = "ea6b9977f5a153215b38cd9a6aa3e4702ffbda22"


class Registry:
    def register_module(self, cls):
        return cls


def summarizer(generator, multi_stage=False):
    root = config.ROOT / "reference/M2RAG"
    revision = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
    ).strip()
    if revision != REFERENCE_COMMIT:
        raise ValueError(f"Reference revision mismatch: {revision}")
    subprocess.run(
        ["git", "-C", str(root), "diff", "--exit-code", "HEAD", "--", "src/summarizer"],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    ns = dict(
        re=re,
        copy=copy,
        abstractmethod=abstractmethod,
        accumulate=accumulate,
        Dict=Dict,
        List=List,
        Tuple=Tuple,
        SUMMARIZER=Registry(),
        build_model=lambda _: generator,
    )
    files = ["base.py", "multi_modal/base.py", "multi_modal/end_to_end.py"]
    for name in files:
        path = root / "src/summarizer" / name
        tree = ast.parse(path.read_text())
        tree.body = [n for n in tree.body if not isinstance(n, (ast.Import, ast.ImportFrom))]
        exec(compile(tree, str(path), "exec"), ns)
    return ns["M2RAGLLMSummarizer"](
        max_pieces_per_sample=20,
        min_piece_score=3,
        max_tokens_per_sample=8192,
        max_images=10,
        max_images_per_sample=5,
        max_aux_images=5,
        min_image_score=3,
        multi_stage=multi_stage,
    )
