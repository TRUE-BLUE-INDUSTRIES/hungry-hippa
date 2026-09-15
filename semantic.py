"""Semantic memory (§2, §8, §9) — facts, beliefs, hypotheses with provenance.

  - source_class records where a belief came from; hermes_inference starts at
    a lower confidence and must be reinforced before it is treated as fact.
  - Beliefs are revised via supersede/contradict; the old row is retained
    with status 'superseded'/'contradicted' so history survives.
  - Every belief can link to immutable evidence rows (belief_evidence).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import db as _db
from . import policy as _policy

KINDS = {"fact", "belief", "hypothesis", "procedural_belief"}
SOURCE_CLASSES = {
    "user_explicit", "document", "tool_result", "visual_observation",
    "audio_observation", "external_source", "hermes_inference", "derived_pattern",
}

# Confidence bonus by source quality — used to resolve contradiction clusters
# (§9): explicit user correction > direct observation > inference.
_SOURCE_PRIORITY = {
    "user_explicit": 0.30,
    "document": 0.15,
    "tool_result": 0.15,
    "visual_observation": 0.10,
    "audio_observation": 0.10,
    "external_source": 0.05,
    "hermes_inference": 0.0,
    "derived_pattern": 0.05,
}


class SemanticMemory:
    def __init__(self, database: _db.Database, config: Dict):
        self.db = database
        self.cfg = config
        self.src_conf = config.get("source_confidence", {})

    def default_confidence(self, source_class: str) -> float:
        return float(self.src_conf.get(source_class, 0.5))

    # --------------------------------------------------------------- write

    def add_belief(self, claim: str, *, kind: str = "belief",
                   confidence: Optional[float] = None, importance: float = 0.5,
                   source_class: str = "hermes_inference", source_ref: str = "",
                   related_entities: Optional[List[str]] = None,
                   derived_from: Optional[List[str]] = None,
                   evidence_ids: Optional[List[str]] = None,
                   valid_from: Optional[str] = None,
                   sensitivity: str = "unclassified",
                   quarantined: bool = False,
                   actor_id: str = "",
                   session_id: str = "") -> Dict[str, Any]:
        claim = (claim or "").strip()
        if not claim:
            return {"error": "empty claim"}
        if kind not in KINDS:
            kind = "belief"
        if source_class not in SOURCE_CLASSES:
            source_class = "hermes_inference"
        if confidence is None:
            confidence = self.default_confidence(source_class)
        belief_id = self.db.next_id("belief")
        now = _db.now_iso()
        sens = _policy.normalize_sensitivity(sensitivity)
        actor = _policy.normalize_actor(actor_id)

        def _insert(conn) -> None:
            conn.execute(
                """INSERT INTO beliefs(
                     belief_id, kind, claim, confidence, importance, status,
                     derived_from, related_entities, valid_from, source_class,
                     contradictions, sensitivity, quarantined, actor_id,
                     created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (belief_id, kind, claim, confidence, importance, "active",
                 _db.jdump(derived_from or []), _db.jdump(related_entities or []),
                 valid_from or now, source_class, "[]", sens,
                 1 if quarantined else 0, actor, now, now),
            )

        ok = self.db._run(_insert, write=True)
        if ok is None:
            return {"error": "insert failed", "belief_id": ""}
        if evidence_ids:
            self.db.link_evidence("belief", belief_id, evidence_ids, session_id)
        self.db.fts_insert("belief", belief_id, claim)
        self.db.log_mutation("add_belief", "belief", belief_id,
                             f"[{kind}|{source_class}|c={confidence:.2f}] {claim[:160]}"
                             f" actor={actor} sensitivity={sens}"
                             f"{' quarantined' if quarantined else ''}",
                             session_id)
        return {"belief_id": belief_id, "confidence": confidence,
                "source_class": source_class, "quarantined": bool(quarantined),
                "sensitivity": sens, "actor_id": actor}

    # ---------------------------------------------------------------- read

    def get_belief(self, belief_id: str) -> Optional[Dict[str, Any]]:
        def _get(conn) -> Optional[Dict[str, Any]]:
            row = conn.execute("SELECT * FROM beliefs WHERE belief_id = ?", (belief_id,)).fetchone()
            if not row:
                return None
            d = dict(row)
            d["derived_from"] = _db.jload(d["derived_from"], [])
            d["related_entities"] = _db.jload(d["related_entities"], [])
            d["contradictions"] = _db.jload(d["contradictions"], [])
            ev = conn.execute(
                "SELECT evidence_id FROM belief_evidence WHERE belief_id = ?", (belief_id,)
            ).fetchall()
            d["evidence_ids"] = [r["evidence_id"] for r in ev]
            return d

        return self.db._run(_get)

    def search_beliefs(self, query: str, status: str = "active",
                       limit: int = 10, actor_id: str = "primary",
                       include_quarantined: bool = False) -> List[Dict[str, Any]]:
        hits = self.db.fts_search(query, kinds=["belief"], limit=limit)
        out = []
        for h in hits:
            b = self.get_belief(h["target_id"])
            if not b or b["status"] != status:
                continue
            allowed, _reason = _policy.may_read(b, actor_id,
                                                include_quarantined=include_quarantined)
            if not allowed:
                continue
            b["score"] = h["score"]
            out.append(b)
        return out

    def list_beliefs(self, kind: str = "", status: str = "active",
                     limit: int = 30, actor_id: str = "primary",
                     include_quarantined: bool = False) -> List[Dict[str, Any]]:
        def _list(conn) -> List[Dict[str, Any]]:
            sql = "SELECT * FROM beliefs WHERE status = ?"
            params: List[Any] = [status]
            if not include_quarantined:
                sql += " AND quarantined = 0"
            if kind:
                sql += " AND kind = ?"
                params.append(kind)
            sql += " ORDER BY updated_at DESC LIMIT ?"
            params.append(limit)
            return [dict(r) for r in conn.execute(sql, params)]

        rows = self.db._run(_list) or []
        return [r for r in rows
                if _policy.may_read(r, actor_id,
                                    include_quarantined=include_quarantined)[0]]

    # -------------------------------------------------------------- revise

    def reinforce(self, belief_id: str, delta: float = 0.05,
                  session_id: str = "") -> Optional[Dict[str, Any]]:
        """Nudge confidence up (capped at 0.98) and stamp verification."""
        def _r(conn) -> Optional[Dict[str, Any]]:
            conn.execute(
                """UPDATE beliefs SET
                     confidence = MIN(0.98, confidence + ?),
                     reinforcement_count = reinforcement_count + 1,
                     last_verified = ?, updated_at = ?
                   WHERE belief_id = ? AND status = 'active'""",
                (delta, _db.now_iso(), _db.now_iso(), belief_id),
            )
            return None

        self.db._run(_r, write=True)
        return self.get_belief(belief_id)

    def supersede(self, belief_id: str, replacement_claim: str, *,
                  reason: str = "", keep_confidence: Optional[float] = None,
                  source_class: str = "hermes_inference",
                  session_id: str = "") -> Dict[str, Any]:
        """Mark an old belief superseded and add the new one, linking history.

        The old row stays queryable (status='superseded') — 'what we believed
        before' remains answerable (§4, §9).
        """
        old = self.get_belief(belief_id)
        if not old:
            return {"error": f"unknown belief {belief_id}"}
        now = _db.now_iso()

        def _upd(conn) -> None:
            conn.execute(
                "UPDATE beliefs SET status = 'superseded', updated_at = ? WHERE belief_id = ?",
                (now, belief_id),
            )

        self.db._run(_upd, write=True)
        self.db.log_mutation("supersede_belief", "belief", belief_id,
                             f"{reason}: {old['claim'][:120]} -> {replacement_claim[:120]}",
                             session_id)
        new_confidence = keep_confidence if keep_confidence is not None else \
            max(0.6, self.default_confidence(source_class))
        return self.add_belief(
            replacement_claim,
            kind=old["kind"], confidence=new_confidence,
            importance=old["importance"], source_class=source_class,
            related_entities=old["related_entities"],
            derived_from=old["derived_from"] + [f"supersedes:{belief_id}"],
            session_id=session_id,
        )

    def contradict(self, belief_id: str, counter_claim: str, *,
                   confidence: Optional[float] = None,
                   source_class: str = "hermes_inference",
                   session_id: str = "") -> Dict[str, Any]:
        """Record a contradiction: all claims are preserved and cross-linked.

        The whole connected cluster of contradicting claims is re-resolved:
        each member scores confidence + source priority, the winner stays
        'active' and the rest become 'contradicted' (never deleted).
        Explicit user corrections therefore win by default (§9).
        """
        old = self.get_belief(belief_id)
        if not old:
            return {"error": f"unknown belief {belief_id}"}
        new_conf = confidence if confidence is not None else \
            self.default_confidence(source_class)
        new = self.add_belief(counter_claim, kind="hypothesis",
                              confidence=new_conf, importance=old["importance"],
                              source_class=source_class,
                              related_entities=old["related_entities"],
                              session_id=session_id)
        if "belief_id" not in new or not new["belief_id"]:
            return new
        new_id = new["belief_id"]
        cluster = [belief_id]
        for cid in (old["contradictions"] or []):
            if cid not in cluster:
                cluster.append(cid)
        if new_id not in cluster:
            cluster.append(new_id)

        def _resolve(conn) -> None:
            rows = conn.execute(
                f"SELECT belief_id, confidence, source_class, status FROM beliefs"
                f" WHERE belief_id IN ({','.join('?' for _ in cluster)})",
                cluster,
            ).fetchall()
            members = {r["belief_id"]: r for r in rows}
            scored = []
            for cid in cluster:
                m = members.get(cid)
                if not m or m["status"] == "superseded":
                    continue
                score = float(m["confidence"]) + _SOURCE_PRIORITY.get(
                    m["source_class"], 0.0)
                scored.append((score, cid))
            scored.sort(reverse=True)
            winner = scored[0][1] if scored else new_id
            others = [cid for cid in cluster if cid != winner]
            now = _db.now_iso()
            for cid in cluster:
                m = members.get(cid)
                if not m:
                    continue
                if cid == winner:
                    conn.execute(
                        "UPDATE beliefs SET status = 'active', contradictions = ?,"
                        " updated_at = ? WHERE belief_id = ?",
                        (_db.jdump(others), now, cid))
                elif m["status"] != "superseded":
                    conn.execute(
                        "UPDATE beliefs SET status = 'contradicted', contradictions = ?,"
                        " updated_at = ? WHERE belief_id = ?",
                        (_db.jdump(others), now, cid))

        self.db._run(_resolve, write=True)
        self.db.log_mutation("contradict", "belief", belief_id,
                             f"cluster={len(cluster)} counter={new_id} (c={new_conf:.2f})",
                             session_id)
        new["contradicts"] = belief_id
        return new

    def remove_belief(self, belief_id: str, session_id: str = "") -> bool:
        """Explicit removal (correct individual memories, §19.14)."""
        def _rm(conn) -> bool:
            conn.execute("DELETE FROM belief_evidence WHERE belief_id = ?", (belief_id,))
            cur = conn.execute("DELETE FROM beliefs WHERE belief_id = ?", (belief_id,))
            return cur.rowcount > 0

        ok = self.db._run(_rm, write=True)
        if ok:
            self.db.fts_delete("belief", belief_id)
            self.db.log_mutation("belief_removed", "belief", belief_id,
                                 "explicit removal", session_id)
        return bool(ok)
