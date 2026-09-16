"""Observability (§21) — human-readable answers to memory-system questions.

Supports: why do you believe / where did this come from / what changed /
what have you forgotten / what procedures have you learned / what entities
connect to X / what memories influenced an answer / how confident are you /
full export.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from . import db as _db
from . import semantic as _semantic


class Observability:
    def __init__(self, database: _db.Database, config: Dict,
                 controller=None):
        self.db = database
        self.cfg = config
        self.ctrl = controller

    # ------------------------------------------------------------ queries

    def why(self, belief_id: str) -> Dict[str, Any]:
        """Trace a belief back to its source evidence (Test 7)."""
        b = self.ctrl.semantic.get_belief(belief_id) if self.ctrl else None
        if not b:
            return {"error": f"unknown belief {belief_id}"}
        evidence = self.db.get_evidence(b["evidence_ids"])
        derived = _db.jload(b["derived_from"], []) or []
        episodes = []
        if self.ctrl:
            for d in derived:
                if str(d).startswith("episode:"):
                    e = self.ctrl.episodic.get_episode(str(d)[len("episode:"):])
                    if e:
                        episodes.append({
                            "episode_id": e["episode_id"],
                            "context": e["context"][:200],
                            "result": e["result"][:200],
                            "outcome": e["outcome"],
                        })
        return {
            "belief_id": b["belief_id"],
            "claim": b["claim"],
            "kind": b["kind"],
            "confidence": b["confidence"],
            "source_class": b.get("source_class"),
            # Provenance is inspectable on purpose: what the writer claimed, and
            # what the runtime was willing to believe (see trust.py).
            "claimed_source_class": b.get("claimed_source_class", ""),
            "verified_source_class": b.get("verified_source_class", ""),
            "source_actor": b.get("source_actor", ""),
            "ingestion_channel": b.get("ingestion_channel", ""),
            "contradictions": b["contradictions"],
            "derived_from": derived,
            "evidence": [{"evidence_id": e["evidence_id"], "kind": e["kind"],
                          "content": e["content"][:300]} for e in evidence],
            "source_episodes": episodes,
            "valid_from": b["valid_from"],
            "last_verified": b["last_verified"],
            "reinforcement_count": b["reinforcement_count"],
            "verdict": self._verdict(b),
        }

    @staticmethod
    def _verdict(b: Dict[str, Any]) -> str:
        src = b["source_class"]
        conf = float(b["confidence"])
        if src in ("user_explicit", "document", "tool_result") and conf >= 0.8:
            return "well-evidenced"
        if src == "derived_pattern" and conf >= 0.7:
            return "pattern-derived, verified"
        if src in ("agent_inference",) + tuple(_semantic.LEGACY_SOURCE_ALIASES):
            return "inference — treat as provisional until reinforced"
        return "moderate"

    def recent_changes(self, limit: int = 20) -> List[Dict[str, Any]]:
        def _q(conn) -> List[Dict[str, Any]]:
            return [dict(r) for r in conn.execute(
                "SELECT ts, action, target_kind, target_id, detail FROM mutation_log"
                " ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]

        return self.db._run(_q) or []

    def forgotten(self, limit: int = 20) -> List[Dict[str, Any]]:
        def _q(conn) -> List[Dict[str, Any]]:
            return [dict(r) for r in conn.execute(
                "SELECT ts, target_kind, target_id, action, reason FROM forget_log"
                " ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]

        return self.db._run(_q) or []

    def learned_procedures(self) -> List[Dict[str, Any]]:
        if not self.ctrl:
            return []
        out = []
        for p in self.ctrl.procedural.list_procedures(limit=50):
            out.append({
                "procedure_id": p["procedure_id"], "name": p["name"],
                "status": p["status"], "confidence": round(p["confidence"], 2),
                "successes": p["success_count"], "failures": p["failure_count"],
                "derived_from": p["derived_from"][:8],
            })
        return out

    def connected_to(self, entity_name: str, hop_limit: int = 2) -> List[Dict[str, Any]]:
        if not self.ctrl:
            return []
        out = []
        for e in self.ctrl.graph.traverse(entity_name, hop_limit=hop_limit):
            out.append({"src": e["src"], "rel": e["rel"], "dst": e["dst"],
                        "status": e["status"], "confidence": e["confidence"]})
        return out

    def recent_retrievals(self, limit: int = 10) -> List[Dict[str, Any]]:
        def _q(conn) -> List[Dict[str, Any]]:
            rows = [dict(r) for r in conn.execute(
                "SELECT ts, query, recalled, session_id FROM retrieval_log"
                " ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]
            for r in rows:
                r["recalled"] = _db.jload(r["recalled"], [])
            return rows

        return self.db._run(_q) or []

    def consolidation_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        def _q(conn) -> List[Dict[str, Any]]:
            return [dict(r) for r in conn.execute(
                "SELECT run_id, started_at, finished_at, summary FROM consolidation_runs"
                " ORDER BY started_at DESC LIMIT ?", (limit,)).fetchall()]

        return self.db._run(_q) or []

    # ------------------------------------------------------------ export

    def export(self, path: str, kind: str = "all") -> Dict[str, Any]:
        """Export memory as JSON (§19.13). kind: all|episodes|beliefs|graph."""
        def _q(conn) -> Dict[str, Any]:
            out: Dict[str, Any] = {}
            tables = {
                "episodes": ("episodes",), "beliefs": ("beliefs", "belief_evidence"),
                "graph": ("entities", "relationships"),
                "all": ("episodes", "evidence", "episode_evidence", "entities",
                        "relationships", "beliefs", "belief_evidence",
                        "procedures", "consolidation_runs", "forget_log",
                        "mutation_log"),
            }.get(kind, ("episodes", "beliefs", "entities", "relationships"))
            for t in tables:
                try:
                    out[t] = [dict(r) for r in conn.execute(f"SELECT * FROM {t}")]
                except Exception:
                    out[t] = []
            return out

        data = self.db._run(_q) or {}
        try:
            # Exports contain every memory row: create them owner-only, like the
            # database itself. (Plaintext either way — see docs/SECURITY.md.)
            parent = os.path.dirname(os.path.abspath(path))
            if parent:
                os.makedirs(parent, exist_ok=True)
            fd = os.open(path, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2, default=str)
            return {"exported": path, "tables": {k: len(v) for k, v in data.items()}}
        except Exception as e:
            return {"error": str(e)[:200]}
