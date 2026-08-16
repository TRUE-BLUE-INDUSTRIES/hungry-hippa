"""Forgetting (§10) — memory-management operations, not mere deletion.

Forms implemented:
  1. access decay     — retrieval ranking decays with age (in retrieval.py);
                        long-unused active items may be archived (config-gated,
                        OFF by default).
  2. importance decay — low/medium items slowly lose importance to a floor.
  3. compression      — near-duplicate episodes merge into one generalized
                        episode; originals kept with status='compressed'.
  4. supersession     — handled by semantic.py (old rows retained).
  5. archival         — status='archived'; excluded from default retrieval
                        but still queryable.
  6. purge            — only via explicit policy; structured memory is never
                        auto-purged by default. Raw evidence is never purged
                        unless raw-media retention is enabled.

High-value items are never automatically destroyed (§10 rule).
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from . import db as _db

_FLOOR = 0.05


def _age_days(iso: Optional[str]) -> float:
    if not iso:
        return 0.0
    try:
        dt = datetime.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
        return max(0.0, (time.time() - dt.timestamp()) / 86400.0)
    except Exception:
        return 0.0


class ForgettingPolicy:
    def __init__(self, database: _db.Database, config: Dict,
                 episodic=None, semantic=None):
        self.db = database
        self.cfg = config.get("forgetting", {})
        self.episodic = episodic
        self.semantic = semantic

    # ------------------------------------------------------------ policy

    def pass_(self, session_id: str = "") -> tuple:
        """One forgetting pass. Returns (actions_taken, messages)."""
        actions = 0
        msgs: List[str] = []

        # 5. archival of long-unused active items (OFF by default)
        unused_days = int(self.cfg.get("auto_archival_after_unused_days", 0))
        if unused_days > 0 and self.episodic is not None:
            n = self._archive_unused(unused_days, session_id)
            actions += n
            if n:
                msgs.append(f"forgetting: archived {n} unused episodes")

        # 2. importance decay for low/medium items (no floor for 'low')
        if self.cfg.get("importance_decay_enabled", True) and self.episodic is not None:
            n = self._decay_importance(session_id)
            actions += n
            if n:
                msgs.append(f"forgetting: importance decay applied to {n} episodes")

        # 3. compression of near-duplicate episodes
        if self.cfg.get("compression_enabled", True) and self.episodic is not None:
            n = self._compress_duplicates(session_id)
            actions += n
            if n:
                msgs.append(f"forgetting: compressed {n} episode groups")

        return actions, msgs

    def _archive_unused(self, unused_days: int, session_id: str) -> int:
        def _q(conn) -> List[Dict[str, Any]]:
            rows = conn.execute(
                "SELECT episode_id, last_accessed, importance FROM episodes"
                " WHERE status = 'active'"
            ).fetchall()
            return [dict(r) for r in rows]

        rows = self.db._run(_q) or []
        archived = 0
        for r in rows:
            # high-value items are never auto-archived
            if float(r["importance"]) >= 0.7:
                continue
            if _age_days(r["last_accessed"]) > unused_days:
                self.episodic.update_status(r["episode_id"], "archived",
                                            "unused beyond retention policy", session_id)
                self.db.log_mutation("forget", "episode", r["episode_id"],
                                     "action=archival reason=unused", session_id)
                archived += 1
        return archived

    def _decay_importance(self, session_id: str) -> int:
        """Slow multiplicative decay for medium items; low items to floor.

        Decay factor per month: ~0.85 for medium, ~0.7 for low. High items
        are untouched. Applied at most once per day per item (updated_at).
        """
        def _q(conn) -> List[Dict[str, Any]]:
            rows = conn.execute(
                "SELECT episode_id, importance, status, updated_at FROM episodes"
                " WHERE status = 'active' AND importance < 0.7"
            ).fetchall()
            return [dict(r) for r in rows]

        rows = self.db._run(_q) or []
        decayed = 0
        for r in rows:
            if _age_days(r["updated_at"]) < 1.0:
                continue
            imp = float(r["importance"])
            factor = 0.85 if imp >= 0.35 else 0.70
            new_imp = max(_FLOOR, imp * factor)
            if new_imp >= imp:
                continue

            def _upd(conn, eid=r["episode_id"], v=new_imp) -> None:
                conn.execute(
                    "UPDATE episodes SET importance = ?, updated_at = ? WHERE episode_id = ?",
                    (v, _db.now_iso(), eid),
                )

            self.db._run(_upd, write=True)
            decayed += 1
        return decayed

    def _compress_duplicates(self, session_id: str) -> int:
        """Merge groups of highly-similar active episodes per project."""
        def _q(conn) -> List[Dict[str, Any]]:
            rows = conn.execute(
                "SELECT * FROM episodes WHERE status = 'active'"
            ).fetchall()
            return [dict(r) for r in rows]

        rows = self.db._run(_q) or []
        groups: Dict[str, List[Dict[str, Any]]] = {}
        for r in rows:
            key = (r["project"] or "", (r["context"] or "").strip()[:50])
            groups.setdefault(key, []).append(r)

        compressed = 0
        for key, eps in groups.items():
            if len(eps) < 3:
                continue
            # group by outcome; compress the largest homogeneous subgroup
            by_outcome: Dict[str, List[Dict[str, Any]]] = {}
            for e in eps:
                by_outcome.setdefault(e["outcome"], []).append(e)
            for outcome, group in by_outcome.items():
                if len(group) < 3:
                    continue
                merged = self.episodic.compress(
                    [e["episode_id"] for e in group],
                    {
                        "context": f"Generalized: {key[1] or key[0] or 'task'} "
                                   f"({len(group)} similar {outcome} episodes)",
                        "outcome": outcome if outcome in
                                   {"success", "failure", "mixed"} else "unknown",
                        "importance": max(float(e["importance"]) for e in group),
                        "project": key[0],
                    },
                    session_id=session_id,
                )
                if merged.get("episode_id"):
                    compressed += 1
        return compressed

    # ------------------------------------------------------------- explicit

    def archive(self, kind: str, target_id: str, reason: str = "",
                session_id: str = "") -> bool:
        """Explicit archival: memory leaves active retrieval but stays accessible."""
        ok = False
        if kind == "episode" and self.episodic is not None:
            ok = self.episodic.update_status(target_id, "archived", reason, session_id)
        elif kind == "belief" and self.semantic is not None:
            def _upd(conn) -> bool:
                cur = conn.execute(
                    "UPDATE beliefs SET status = 'archived', updated_at = ? WHERE belief_id = ?",
                    (_db.now_iso(), target_id),
                )
                return cur.rowcount > 0

            ok = bool(self.db._run(_upd, write=True))
        if ok:
            self.db.log_mutation("forget", kind, target_id,
                                 f"action=archival reason={reason}", session_id)
        return bool(ok)
