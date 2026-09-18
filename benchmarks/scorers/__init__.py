"""Scoring primitives — the metrics we actually report."""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

WORD_RE = re.compile(r"\w+", re.UNICODE)


def exact_match(prediction: str, reference: str) -> float:
    """1.0 if the normalized answer equals the reference, else 0.0."""
    return float(_normalize(prediction) == _normalize(reference))


def token_f1(prediction: str, reference: str) -> float:
    """Token-level F1 between prediction and reference."""
    pred_tokens = _tokenize(prediction)
    ref_tokens = _tokenize(reference)
    if not pred_tokens or not ref_tokens:
        return float(pred_tokens == ref_tokens)
    common = sum((collections.Counter(pred_tokens) & collections.Counter(ref_tokens)).values())
    if common == 0:
        return 0.0
    precision = common / len(pred_tokens)
    recall = common / len(ref_tokens)
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def contains_answer(prediction: str, reference: str) -> float:
    """1.0 if the reference string appears in the prediction, else 0.0."""
    return float(_normalize(reference) in _normalize(prediction))


def _normalize(text: str) -> str:
    return " ".join(_tokenize(text))


def _tokenize(text: str) -> List[str]:
    return WORD_RE.findall(text.lower())


@dataclass(frozen=True)
class ClassifiedFailure:
    category: str
    detail: str
    example: Dict[str, Any]


def classify_failure(category: str, detail: str, **example: Any) -> ClassifiedFailure:
    return ClassifiedFailure(category=category, detail=detail, example=example)


# imports kept local to avoid a top-level collections dependency in the module
import collections  # noqa: E402


def median(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    return float(statistics.median(values))


def p95(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    sorted_v = sorted(values)
    idx = int(len(sorted_v) * 0.95)
    return float(sorted_v[min(idx, len(sorted_v) - 1)])


def p99(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    sorted_v = sorted(values)
    idx = int(len(sorted_v) * 0.99)
    return float(sorted_v[min(idx, len(sorted_v) - 1)])


def stdev(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    return float(statistics.stdev(values))


def recall_at_k(retrieved: Iterable[str], relevant: Iterable[str], k: int) -> float:
    rel = set(relevant)
    if not rel:
        return 0.0
    hits = sum(1 for x in list(retrieved)[:k] if x in rel)
    return hits / len(rel)


def mean_reciprocal_rank(ranked: Iterable[str], relevant: Iterable[str]) -> float:
    rel = set(relevant)
    for i, item in enumerate(ranked, 1):
        if item in rel:
            return 1.0 / i
    return 0.0


def f1_score(precision: float, recall: float) -> float:
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def top_k_accuracy(predictions: Sequence[str], references: Sequence[str], k: int = 1) -> float:
    if not predictions or not references:
        return 0.0
    k = min(k, len(predictions))
    return float(any(predictions[i] == references[i] for i in range(k)))
