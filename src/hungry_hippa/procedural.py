"""Procedural memory (§12) — learning procedures from outcomes.

Ladder: experience (episodes) -> procedural belief -> validated procedure ->
host-registered skill (only with explicit user approval; we never auto-write skills).

Validation thresholds are configurable. Weak evidence produces a *candidate*
with low confidence, never an executable artifact.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import db as _db


class ProceduralMemory:
    def __init__(self, database: _db.Database, config: Dict):
        self.db = database
        self.cfg = config

    def create_procedure(self, name: str, *, description: str = "",
                         steps: Optional[List[str]] = None,
                         prerequisites: Optional[List[str]] = None,
                         applicability: str = "", confidence: float = 0.5,
                         status: str = "candidate",
                         derived_from: Optional[List[str]] = None,
                         session_id: str = "") -> Dict[str, Any]:
        name = (name or "").strip()
        if not name:
            return {"error": "empty procedure name"}
        if status not in {"candidate", "validated", "skill_promoted"}:
            status = "candidate"
        procedure_id = self.db.next_id("procedure")
        now = _db.now_iso()

        def _insert(conn) -> None:
            conn.execute(
                """INSERT INTO procedures(
                     procedure_id, name, description, steps, prerequisites,
                     applicability, confidence, status, derived_from, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (procedure_id, name, description, _db.jdump(steps or []),
                 _db.jdump(prerequisites or []), applicability, confidence,
                 status, _db.jdump(derived_from or []), now, now),
            )

        ok = self.db._run(_insert, write=True)
        if ok is None:
            return {"error": "insert failed"}
        self.db.fts_insert("procedure", procedure_id, f"{name} {description} {applicability}")
        self.db.log_mutation("create_procedure", "procedure", procedure_id,
                             f"{name} [{status}] c={confidence:.2f}", session_id)
        return {"procedure_id": procedure_id, "status": status, "confidence": confidence}

    def get_procedure(self, procedure_id: str) -> Optional[Dict[str, Any]]:
        def _get(conn) -> Optional[Dict[str, Any]]:
            row = conn.execute(
                "SELECT * FROM procedures WHERE procedure_id = ?", (procedure_id,)
            ).fetchone()
            if not row:
                return None
            d = dict(row)
            d["steps"] = _db.jload(d["steps"], [])
            d["prerequisites"] = _db.jload(d["prerequisites"], [])
            d["derived_from"] = _db.jload(d["derived_from"], [])
            return d

        return self.db._run(_get)

    def list_procedures(self, status: str = "", limit: int = 30) -> List[Dict[str, Any]]:
        def _list(conn) -> List[Dict[str, Any]]:
            sql = "SELECT * FROM procedures"
            params: List[Any] = []
            if status:
                sql += " WHERE status = ?"
                params.append(status)
            sql += " ORDER BY updated_at DESC LIMIT ?"
            params.append(limit)
            out = []
            for r in conn.execute(sql, params):
                d = dict(r)
                d["steps"] = _db.jload(d["steps"], [])
                d["prerequisites"] = _db.jload(d["prerequisites"], [])
                d["derived_from"] = _db.jload(d["derived_from"], [])
                out.append(d)
            return out

        return self.db._run(_list) or []

    def record_outcome(self, procedure_id: str, success: bool,
                       session_id: str = "") -> Optional[Dict[str, Any]]:
        """Feed a real outcome into a procedure's validation counters."""
        def _upd(conn) -> Optional[Dict[str, Any]]:
            col = "success_count" if success else "failure_count"
            conn.execute(
                f"""UPDATE procedures SET {col} = {col} + 1, updated_at = ?
                    WHERE procedure_id = ?""",
                (_db.now_iso(), procedure_id),
            )
            return None

        self.db._run(_upd, write=True)
        p = self.get_procedure(procedure_id)
        if p:
            self._reevaluate(p, session_id)
            # return the post-reevaluation snapshot, not the stale pre-write copy
            p = self.get_procedure(procedure_id) or p
        return p

    def _reevaluate(self, p: Dict[str, Any], session_id: str = "") -> None:
        cfg = self.cfg.get("consolidation", {})
        total = p["success_count"] + p["failure_count"]
        if total < int(cfg.get("procedural_min_episodes", 3)):
            return
        ratio = p["success_count"] / total if total else 0.0
        if ratio >= float(cfg.get("procedural_min_success_ratio", 0.6)):
            new_conf = min(0.95, 0.5 + 0.15 * min(total, 4) + 0.1 * ratio)
        else:
            new_conf = max(0.1, p["confidence"] - 0.2)
        new_status = p["status"]
        if new_conf >= float(cfg.get("procedural_promote_confidence", 0.85)) \
                and p["status"] == "candidate":
            new_status = "validated"
        if new_conf != p["confidence"] or new_status != p["status"]:
            def _upd(conn) -> None:
                conn.execute(
                    "UPDATE procedures SET confidence = ?, status = ?, updated_at = ?"
                    " WHERE procedure_id = ?",
                    (new_conf, new_status, _db.now_iso(), p["procedure_id"]),
                )

            self.db._run(_upd, write=True)
            self.db.log_mutation(
                "procedure_reevaluated", "procedure", p["procedure_id"],
                f"confidence {p['confidence']:.2f}->{new_conf:.2f} status {p['status']}->{new_status}",
                session_id,
            )

    def promote_to_skill(self, procedure_id: str, session_id: str = "") -> Dict[str, Any]:
        """Mark a validated procedure as promoted to a host skill.

        The actual skill file is created by the agent with user approval —
        this only records the promotion so the lineage is preserved.
        """
        p = self.get_procedure(procedure_id)
        if not p:
            return {"error": f"unknown procedure {procedure_id}"}
        if p["status"] != "validated":
            return {"error": f"procedure not validated (status={p['status']})"}

        def _upd(conn) -> None:
            conn.execute(
                "UPDATE procedures SET status = 'skill_promoted', updated_at = ?"
                " WHERE procedure_id = ?",
                (_db.now_iso(), procedure_id),
            )

        self.db._run(_upd, write=True)
        self.db.log_mutation("promote_to_skill", "procedure", procedure_id,
                             f"{p['name']} promoted to host skill", session_id)
        return {"procedure_id": procedure_id, "status": "skill_promoted"}
