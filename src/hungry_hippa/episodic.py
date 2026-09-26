"""Episodic memory (§3B) — create, close, recall, reinforce, compress.

An episode records what happened: context, participants, actions, tools,
decisions, outcome, and — crucially — provenance links to immutable
evidence rows. Nothing is rewritten in place except status/importance;
history is preserved via mutation_log.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import db as _db
from . import policy as _policy
from . import trust as _trust

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
                         sensitivity: str = "unclassified",
                         quarantined: bool = False,
                         actor_id: str = "",
                         identity: Optional[str] = None,
                         provenance: Optional[str] = None,
                         claimed_source_class: str = "",
                         channel: str = "",
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
        sens = _policy.normalize_sensitivity(sensitivity)
        actor = _policy.normalize_actor(actor_id)
        # Quarantine is decided at this layer so no caller can bypass it by
        # writing episodic memory directly instead of through the controller.
        # ``identity`` is the channel-resolved identity; when present it decides,
        # so the actor label cannot lift quarantine.
        quarantined = _policy.write_quarantine(actor, quarantined, identity)
        # Episodes have no legacy source_class column, so the claim arrives as an
        # explicit argument; the verified class is channel-derived either way.
        provenance = _trust.resolve_provenance(provenance, identity)
        claimed = str(claimed_source_class or "").strip()
        verified = _trust.verified_source_class(claimed or "agent_inference",
                                                provenance)

        def _insert(conn) -> None:
            conn.execute(
                """INSERT INTO episodes(
                     episode_id, ts_start, ts_end, context, participants, location,
                     visual_entities, audio_transcript, user_request, actions_taken,
                     tools_used, files_used, decisions, result, outcome, importance,
                     confidence, project, related_entities, source_refs, status,
                     sensitivity, quarantined, actor_id,
                     claimed_source_class, verified_source_class, source_actor,
                     ingestion_channel, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (episode_id, ts_start, ts_end, context, participants, location,
                 visual_entities, audio_transcript, user_request, actions_taken,
                 tools_used, files_used, decisions, result, outcome, importance,
                 confidence, project, rel, refs, "active",
                 sens, 1 if quarantined else 0, actor,
                 claimed, verified, actor, channel or (identity or ""), now, now),
            )

        ok = self.db._run(_insert, write=True)
        if ok is None:
            return {"error": "insert failed", "episode_id": ""}

        if evidence_ids:
            self.db.link_evidence("episode", episode_id, evidence_ids, session_id)
        self.db.fts_insert_passages("episode", episode_id, self._fts_body(
            context, user_request, actions_taken, decisions, result, project,
            visual_entities, audio_transcript, participants))
        self.db.log_mutation("remember_episode", "episode", episode_id,
                             f"importance={importance:.2f} outcome={outcome} project={project}"
                             f" actor={actor} sensitivity={sens}"
                             f"{' quarantined' if quarantined else ''}",
                             session_id)
        return {"episode_id": episode_id, "importance": importance,
                "outcome": outcome, "quarantined": bool(quarantined),
                "sensitivity": sens, "actor_id": actor,
                "claimed_source_class": claimed, "verified_source_class": verified}

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
                      limit: int = 20, include_quarantined: bool = False) -> List[Dict[str, Any]]:
        def _list(conn) -> List[Dict[str, Any]]:
            sql = "SELECT episode_id, ts_start, context, user_request, result, outcome, importance, project, status, quarantined, actor_id FROM episodes WHERE status = ?"
            params: List[Any] = [status]
            if not include_quarantined:
                sql += " AND quarantined = 0"
            if project:
                sql += " AND project = ?"
                params.append(project)
            sql += " ORDER BY ts_start DESC LIMIT ?"
            params.append(limit)
            return [dict(r) for r in conn.execute(sql, params)]

        return self.db._run(_list) or []

    def list_episodes_full(self, project: str = "", status: str = "active",
                           limit: int = 500,
                           include_quarantined: bool = False) -> List[Dict[str, Any]]:
        """All columns — for consolidation passes that need full rows.

        Quarantined episodes are excluded by default so an untrusted write
        cannot be laundered into a derived belief by the consolidation pass.
        """
        def _list(conn) -> List[Dict[str, Any]]:
            sql = "SELECT * FROM episodes WHERE status = ?"
            params: List[Any] = [status]
            if not include_quarantined:
                sql += " AND quarantined = 0"
            if project:
                sql += " AND project = ?"
                params.append(project)
            sql += " ORDER BY ts_start DESC LIMIT ?"
            params.append(limit)
            return [dict(r) for r in conn.execute(sql, params)]

        return self.db._run(_list) or []

    # ------------------------------------------------------------- mutate

    # ------------------------------------------------------ quarantine review

    def list_quarantined(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Episodes held in quarantine, newest first — an operator review view.

        Read-only; quarantined episodes stay excluded from default recall.
        """
        def _list(conn) -> List[Dict[str, Any]]:
            return [dict(r) for r in conn.execute(
                "SELECT episode_id, context, outcome, actor_id, claimed_source_class,"
                " verified_source_class, sensitivity, created_at"
                " FROM episodes WHERE quarantined = 1"
                " ORDER BY created_at DESC LIMIT ?", (int(limit),))]

        return self.db._run(_list) or []

    def set_verified_class(self, episode_id: str, source_class: str, *,
                           source_actor: str = "",
                           clear_quarantine: bool = False) -> int:
        """Promote an episode's verified provenance, optionally leaving quarantine.

        Episodes carry the same provenance columns as beliefs, so approval reuses
        the same rule (``trust.verified_source_class``) rather than inventing one.
        """
        fields = ["source_class = ?", "verified_source_class = ?", "source_actor = ?",
                  "ingestion_channel = ?"]
        actor = str(source_actor or _policy.DEFAULT_ACTOR)
        params: List[Any] = [source_class, source_class, actor, _trust.CHANNEL_CLI]
        if clear_quarantine:
            fields.append("quarantined = 0")
        fields.append("updated_at = ?")
        params.append(_db.now_iso())
        params.append(episode_id)
        sql = f"UPDATE episodes SET {', '.join(fields)} WHERE episode_id = ?"

        def _upd(conn) -> int:
            return conn.execute(sql, params).rowcount

        return self.db._run(_upd, write=True) or 0

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
