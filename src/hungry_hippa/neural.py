"""Neural memory interface (§13, Phase 9) — safe adapter stub.

V1 does NOT modify foundation-model weights and does not train anything.
This module defines the seam future adaptive components plug into:

  - learned embeddings / personalized representations
  - adaptive memory ranking
  - memory-controller models
  - recurrent state / lightweight adapters
  - learned preference models

Contract: every neural output is a *suggestion/prior* tagged with its own
confidence and must be VERIFIED against explicit graph + evidence before use.
Neural memory never silently overrides explicit verified evidence (§13).
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional


class NeuralMemoryInterface:
    """Registry for optional learned components. All default to off."""

    def __init__(self):
        self._rankers: Dict[str, Callable] = {}
        self._priors: Dict[str, Callable] = {}
        self.enabled = False

    # ------------------------------------------------------------ registry

    def register_ranker(self, name: str, fn: Callable[[List[Dict[str, Any]], Dict], List[Dict[str, Any]]]) -> None:
        """fn(items, context) -> reranked items. Learned ranking replaces
        the transparent heuristic score while keeping the same signature."""
        self._rankers[name] = fn

    def register_prior(self, name: str, fn: Callable[[str, Dict], Optional[Dict[str, Any]]]) -> None:
        """fn(query, context) -> {value, confidence, kind} suggestion or None."""
        self._priors[name] = fn

    # ------------------------------------------------------------ use

    def rank(self, items: List[Dict[str, Any]], context: Optional[Dict] = None) -> List[Dict[str, Any]]:
        if not self.enabled or not self._rankers:
            return items
        out = items
        for name, fn in self._rankers.items():
            try:
                out = fn(out, context or {})
            except Exception:
                continue
        return out

    def priors(self, query: str, context: Optional[Dict] = None) -> List[Dict[str, Any]]:
        """Collect suggestion-priors; the caller MUST tag them as such."""
        if not self.enabled:
            return []
        out = []
        for name, fn in self._priors.items():
            try:
                p = fn(query, context or {})
                if isinstance(p, dict):
                    p.setdefault("kind", name)
                    p.setdefault("source", "neural_prior")
                    out.append(p)
            except Exception:
                continue
        return out

    def verify_against(self, prior: Dict[str, Any], explicit: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Check a prior against explicit graph/evidence results.

        Returns {confirmed: bool, confidence: float, matched: list}. Callers
        must downgrade or drop unconfirmed priors — never override evidence.
        """
        value = str(prior.get("value", "")).lower()
        matched = [e for e in explicit if value and value in str(e).lower()]
        confirmed = bool(matched)
        return {
            "confirmed": confirmed,
            "confidence": float(prior.get("confidence", 0.0)) if confirmed else 0.0,
            "matched": matched[:3],
        }
