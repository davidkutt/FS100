"""Retrieval metrics over `gains`: per ranked hit, 1 if it finds a not yet found relevant label."""

import math
from collections.abc import Sequence


def hit_at(gains: Sequence[int], k: int) -> float:
    return float(any(gains[:k]))


def reciprocal_rank(gains: Sequence[int], k: int) -> float:
    return next((1 / rank for rank, gain in enumerate(gains[:k], 1) if gain), 0.0)


def ndcg(gains: Sequence[int], relevant_count: int, k: int) -> float:
    dcg = sum(gain / math.log2(rank + 1) for rank, gain in enumerate(gains[:k], 1))
    ideal = sum(1 / math.log2(rank + 1) for rank in range(1, min(relevant_count, k) + 1))
    return dcg / ideal if ideal else 0.0


def percentile(values: Sequence[float], p: float) -> float:
    """Nearest-rank percentile."""
    ordered = sorted(values)
    return ordered[max(math.ceil(p / 100 * len(ordered)) - 1, 0)]


def balanced_accuracy(
    answerable: Sequence[float], unanswerable: Sequence[float], threshold: float
) -> float:
    """How well a top-1 score cut-off keeps answerable and rejects unanswerable questions."""
    kept = sum(score >= threshold for score in answerable) / len(answerable)
    rejected = sum(score < threshold for score in unanswerable) / len(unanswerable)
    return (kept + rejected) / 2


def calibrate_threshold(
    answerable: Sequence[float], unanswerable: Sequence[float]
) -> tuple[float, float]:
    """Top-1 score cut-off that best separates answerable from unanswerable questions.

    Returns (threshold, balanced accuracy); ties go to the lowest threshold (keeps recall).
    """

    def accuracy(threshold: float) -> float:
        return balanced_accuracy(answerable, unanswerable, threshold)

    best = max(sorted({*answerable, *unanswerable}), key=accuracy)
    return best, accuracy(best)
