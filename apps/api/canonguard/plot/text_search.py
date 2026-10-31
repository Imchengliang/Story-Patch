"""Shared text-scoring primitives: tokenisation, BM25, cosine, RRF.

Kept separate from any index so the scene backend (and the archived PlotUnit
backend) can share the same maths.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Sequence
from typing import Protocol

ENGLISH_TOKEN = re.compile(r"[a-zA-Z][a-zA-Z0-9_'-]+")
CHINESE_RUN = re.compile(r"[\u4e00-\u9fff]+")


class Embedder(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


def tokenize(text: str) -> list[str]:
    tokens = [match.group(0).lower() for match in ENGLISH_TOKEN.finditer(text)]
    for match in CHINESE_RUN.finditer(text):
        run = match.group(0)
        if len(run) == 1:
            tokens.append(run)
        else:
            tokens.extend(run[index : index + 2] for index in range(len(run) - 1))
    return tokens


def cosine(left: Sequence[float], right: Sequence[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=False))
    norm_left = math.sqrt(sum(a * a for a in left))
    norm_right = math.sqrt(sum(b * b for b in right))
    if not norm_left or not norm_right:
        return 0.0
    return dot / (norm_left * norm_right)


def bm25_scores(
    query_tokens: list[str],
    docs_tokens: list[list[str]],
    k1: float = 1.5,
    b: float = 0.75,
    *,
    document_frequency: Counter[str] | None = None,
    average_length: float | None = None,
) -> list[float]:
    """BM25 over pre-tokenised docs.

    ``document_frequency`` / ``average_length`` are corpus-level and fixed, so a
    persistent index can pass them in instead of recomputing on every query.
    """
    total = len(docs_tokens)
    if not total:
        return []
    if average_length is None:
        average_length = sum(len(doc) for doc in docs_tokens) / total or 1.0
    if document_frequency is None:
        document_frequency = Counter()
        for doc in docs_tokens:
            document_frequency.update(set(doc))

    scores: list[float] = []
    for doc in docs_tokens:
        frequencies = Counter(doc)
        score = 0.0
        for term in query_tokens:
            frequency = frequencies.get(term, 0)
            if not frequency:
                continue
            idf = math.log(
                1 + (total - document_frequency[term] + 0.5) / (document_frequency[term] + 0.5)
            )
            denominator = frequency + k1 * (1 - b + b * len(doc) / average_length)
            score += idf * frequency * (k1 + 1) / denominator
        scores.append(score)
    return scores


def ranks(scores: list[float]) -> list[int]:
    return sorted(range(len(scores)), key=lambda index: scores[index], reverse=True)


def rrf(rank_lists: list[list[int]], k: int = 60) -> dict[int, float]:
    fused: dict[int, float] = {}
    for ranks in rank_lists:
        for rank, index in enumerate(ranks, start=1):
            fused[index] = fused.get(index, 0.0) + 1.0 / (k + rank)
    return fused
