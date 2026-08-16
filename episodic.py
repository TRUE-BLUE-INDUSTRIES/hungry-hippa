"""Episodic memory (§3B) — create, close, recall, reinforce, compress.

An episode records what happened: context, participants, actions, tools,
decisions, outcome, and — crucially — provenance links to immutable
evidence rows. Nothing is rewritten in place except status/importance;
history is preserved via mutation_log.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import db as _db

VALID_OUTCOMES = {"success", "failure", "mixed", "unknown", "unexpected"}


class EpisodicMemory:
    def __init__(self, database: _db.Database, config: Dict):
        self.db = database
        self.cfg = config

    # -------------------------------------------------------------- create

    def remember_episode(self, *, context: str = "", participants: str = "",
                         location: str = "", visual_entities: str = "",
                         audio_transcript: str = "", user_request: str = "",
                         actions_taken: str = "", tools_used: str = "",
                         files_used: str = "", decisions: str = "",
                         result: str = "", outcome: str = "unknown",
                         importance: Optional[float] = None,
                         confidence: Optional[float] = None,
                         project: str = "", related_entities: Optional[List[str]] = None,
                         source_refs: Optional[List[str]] = None,
                         evidence_ids: Optional[List[str]] = None,
                         ts_start: Optional[str] = None, ts_end: Optional[str] = None,
                         session_id: str = "") -> Dict[str, Any]:
        if outcome not in VALID_OUTCOMES:
            outcome = "unknown"
        episode_id = self.db.next_id("episode")
        now = _db.now_iso()
        ts_start = ts_start or now
        ts_end = ts_end or now
        if importance is None:
            importance = self._field_importance(dict(
                outcome=outcome, user_request=user_request, decisions=decisions,
                actions_taken=actions_taken, project=project))
        confidence = confidence if confidence is not None else 0.8
        rel = _db.jdump([e for e in (related_entities or []) if e])
        refs = _db.jdump([r for r in (source_refs or []) if r])

        def _insert(conn) -> None:
            conn.execute(
                """INSERT INTO episodes(
                     episode_id, ts_start, ts_end, context, participants, location,
                     visual_entities, audio_transcript, user_request, actions_taken,
                     tools_used, files_used, decisions, result, outcome, importance,
                     confidence, project, related_entities, source_refs, status,
                     created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (episode_id, ts_start, ts_end, context, participants, location,
                 visual_entities, audio_transcript, user_request, actions_taken,
                 tools_used, files_used, decisions, result, outcome, importance,
                 confidence, project, rel, refs, "active", now, now),
            )

        ok = self.db._run(_insert, write=True)
        if ok is None:
            return {"error": "insert failed", "episode_id": ""}

        if evidence_ids:
            self.db.link_evidence("episode", episode_id, evidence_ids, session_id)
        self.db.fts_insert("episode", episode_id, self._fts_body(
            context, user_request, actions_taken, decisions, result, project,
            visual_entities, audio_transcript, participants))
        self.db.log_mutation("remember_episode", "episode", episode_id,
                             f"importance={importance:.2f} outcome={outcome} project={project}",
                             session_id)
        return {"episode_id": episode_id, "importance": importance, "outcome": outcome}

    def _field_importance(self, fields: Dict) -> float:
        # kept local to avoid circular import with attention; the provider
        # passes explicit importance in the normal path.
        base = 0.35
        if fields.get("outcome") == "unexpected":
            base += 0.35
        if (fields.get("user_request") or "").strip():
            base += 0.30
        if fields.get("project"):
            base += 0.25
        return max(0.0, min(1.0, base))

    def _fts_body(self, *parts: str) -> str:
        return " ".join(p for p in parts if p).strip()

    # ---------------------------------------------------------------- read

    def get_episode(self, episode_id: str) -> Optional[Dict[str, Any]]:
        def _get(conn) -> Optional[Dict[str, Any]]:
            row = conn.execute("SELECT * FROM episodes WHERE episode_id = ?", (episode_id,)).fetchone()
            if not row:
                return None
            d = dict(row)
            d["related_entities"] = _db.jload(d["related_entities"], [])
            d["source_refs"] = _db.jload(d["source_refs"], [])
            ev = conn.execute(
                "SELECT evidence_id FROM episode_evidence WHERE episode_id = ?", (episode_id,)
            ).fetchall()
            d["evidence_ids"] = [r["evidence_id"] for r in ev]
            return d

        return self.db._run(_get)

    def list_episodes(self, project: str = "", status: str = "active",
                      limit: int = 20) -> List[Dict[str, Any]]:
        def _list(conn) -> List[Dict[str, Any]]:
            sql = "SELECT episode_id, ts_start, context, user_request, result, outcome, importance, project, status FROM episodes WHERE status = ?"
            params: List[Any] = [status]
            if project:
                sql += " AND project = ?"
                params.append(project)
            sql += " ORDER BY ts_start DESC LIMIT ?"
            params.append(limit)
            return [dict(r) for r in conn.execute(sql, params)]

        return self.db._run(_list) or []

    def list_episodes_full(self, project: str = "", status: str = "active",
                           limit: int = 500) -> List[Dict[str, Any]]:
        """All columns — for consolidation passes that need full rows."""
        def _list(conn) -> List[Dict[str, Any]]:
            sql = "SELECT * FROM episodes WHERE status = ?"
            params: List[Any] = [status]
            if project:
                sql += " AND project = ?"
                params.append(project)
            sql += " ORDER BY ts_start DESC LIMIT ?"
            params.append(limit)
            return [dict(r) for r in conn.execute(sql, params)]

        return self.db._run(_list) or []

    # ------------------------------------------------------------- mutate

    def touch(self, episode_id: str, session_id: str = "") -> None:
        """Mark as accessed (reinforcement) — boosts retrieval ranking."""
        def _touch(conn) -> None:
            conn.execute(
                "UPDATE episodes SET last_accessed = ?, reinforcement_count = reinforcement_count + 1,"
                " updated_at = ? WHERE episode_id = ?",
                (_db.now_iso(), _db.now_iso(), episode_id),
            )

        self.db._run(_touch, write=True)

    def update_status(self, episode_id: str, status: str,
                      reason: str = "", session_id: str = "") -> bool:
        def _upd(conn) -> bool:
            cur = conn.execute(
                "UPDATE episodes SET status = ?, updated_at = ? WHERE episode_id = ?",
                (status, _db.now_iso(), episode_id),
            )
            return cur.rowcount > 0

        ok = self.db._run(_upd, write=True)
        if ok:
            self.db.log_mutation(f"episode_{status}", "episode", episode_id, reason, session_id)
        return bool(ok)

    # --------------------------------------------------------- compression

    def compress(self, episode_ids: List[str], summary_episode: Dict[str, Any],
                 session_id: str = "") -> Dict[str, Any]:
        """Compress several similar episodes into one generalized episode (§10.3).

        Originals are kept with status='compressed'; the new episode links them
        via derived_from-style source_refs. Original evidence is never altered.
        """
        merged = self.remember_episode(
            source_refs=[f"episode:{e}" for e in episode_ids],
            session_id=session_id,
            **summary_episode,
        )
        if "episode_id" not in merged or not merged["episode_id"]:
            return merged
        for eid in episode_ids:
            self.update_status(eid, "compressed",
                               f"compressed into {merged['episode_id']}", session_id)
        merged["compressed_from"] = episode_ids
        return merged

    def purge(self, episode_id: str, session_id: str = "") -> bool:
        """Explicit deletion (never automatic; config-gated purge policy only)."""
        def _purge(conn) -> bool:
            conn.execute("DELETE FROM episode_evidence WHERE episode_id = ?", (episode_id,))
            cur = conn.execute("DELETE FROM episodes WHERE episode_id = ?", (episode_id,))
            return cur.rowcount > 0

        ok = self.db._run(_purge, write=True)
        if ok:
            self.db.fts_delete("episode", episode_id)
            self.db.log_mutation("episode_purged", "episode", episode_id,
                                 "explicit purge", session_id)
        return bool(ok)
