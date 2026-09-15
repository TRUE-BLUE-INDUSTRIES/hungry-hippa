"""Attention / importance scoring (§6).

Configurable scoring system — the numeric weights are defaults in config.py
and may be tuned per installation. Signals are summed, clamped to [0, 1],
and mapped to a retention tier:

    high    >= attention.high_threshold   -> full episode + graph/semantic
    medium  >= attention.medium_threshold -> episodic storage
    low     otherwise                      -> brief metadata row only
"""

from __future__ import annotations

from typing import Dict, List, Optional


class AttentionScorer:
    def __init__(self, config: Dict):
        self.att = config.get("attention", {})
        self._signal_names = {
            "novel_object": "novel object observed",
            "user_asked": "user asked about it",
            "problem_discovered": "problem discovered",
            "decision_made": "decision made",
            "physical_action": "physical action taken",
            "unexpected_result": "unexpected result",
            "project_relevance": "important project relation",
            "background_repeated": "background repeated event",
            "irrelevant_environmental": "irrelevant environmental detail",
            "duplicate_observation": "duplicate observation",
        }

    # -- signal capture -----------------------------------------------------

    def signal_names(self) -> Dict[str, str]:
        return dict(self._signal_names)

    def base_importance(self, signals: Optional[List[str]] = None,
                        user_attention: bool = False) -> float:
        """Score an event from its signals. Signals are the config key names."""
        att = self.att
        total = float(att.get("base_importance", 0.35))
        for sig in signals or []:
            total += float(att.get(sig, 0.0))
        if user_attention and "user_asked" not in (signals or []):
            total += float(att.get("user_asked", 30.0))
        return max(0.0, min(1.0, total))

    def tier(self, importance: float) -> str:
        if importance >= float(self.att.get("high_threshold", 0.70)):
            return "high"
        if importance >= float(self.att.get("medium_threshold", 0.35)):
            return "medium"
        return "low"

    # -- outcome scoring for episode closure --------------------------------

    def score_episode_fields(self, fields: Dict) -> Dict:
        """Return {importance, signals} for an episode's field dict."""
        signals: List[str] = []
        if fields.get("outcome") == "unexpected":
            signals.append("unexpected_result")
        req = (fields.get("user_request") or "").strip()
        if req:
            signals.append("user_asked")
        if fields.get("problem") or fields.get("problem_detected"):
            signals.append("problem_discovered")
        if (fields.get("decisions") or "").strip():
            signals.append("decision_made")
        if (fields.get("actions_taken") or "").strip():
            signals.append("physical_action")
        if fields.get("project"):
            signals.append("project_relevance")
        importance = self.base_importance(signals)
        return {"importance": importance, "signals": signals}
