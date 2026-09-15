"""Temporal knowledge graph (§4) — entities, relationships, temporal logic.

Core rules:
  - Historical relationships are never overwritten. A change marks the old
    relationship superseded (status='superseded', valid_until=now) and inserts
    a new one with valid_from=now. "Tool_A REPLACED_BY Tool_B" is a
    relationship *between* the two states, not a rewrite of history.
  - Every relationship carries provenance: source_type/source_ref,
    confidence, importance, verification and reinforcement counters.
  - Entities are canonical by unique name; get_or_create resolves identity.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from . import db as _db

ENTITY_TYPES = {
    "person", "project", "device", "object", "concept", "goal", "decision",
    "event", "episode", "file", "skill", "procedure", "problem", "solution",
    "preference", "hypothesis", "fact", "location", "tool", "model", "outcome",
}

RELATIONSHIP_TYPES = {
    "OWNS", "USES", "WORKS_ON", "CREATED", "DEPENDS_ON", "PART_OF", "RELATED_TO",
    "CAUSED", "CAUSED_BY", "FAILED_BECAUSE", "HAD_PROBLEM", "SOLVED_BY",
    "REPLACED_BY", "SUPERSEDES", "PREFERS", "PREFERS_FOR", "REJECTED",
    "REQUIRES", "PRODUCED", "OBSERVED_IN", "SUPPORTED_BY", "CONTRADICTED_BY",
    "DERIVED_FROM", "LEARNED_FROM", "APPLIES_TO",
}


_MAX_HOPS = int(os.environ.get("HUNGRY_HIPPA_MAX_HOPS", "4") or 4)


class KnowledgeGraph:
    def __init__(self, database: _db.Database, config: Dict):
        self.db = database
        self.cfg = config

    # ------------------------------------------------------------ entities

    def get_or_create_entity(self, name: str, type_: str = "object",
                             properties: Optional[Dict] = None,
                             session_id: str = "") -> Dict[str, Any]:
        name = (name or "").strip()
        if not name:
            return {"error": "empty entity name"}
        if type_ not in ENTITY_TYPES:
            type_ = "object"
        existing = self.find_entity(name)
        if existing:
            return existing

        entity_id = self.db.next_id("entity")
        now = _db.now_iso()

        def _insert(conn) -> None:
            conn.execute(
                "INSERT INTO entities(entity_id, name, type, properties, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?)",
                (entity_id, name, type_, _db.jdump(properties or {}), now, now),
            )

        ok = self.db._run(_insert, write=True)
        if ok is None:
            return {"error": "insert failed"}
        self.db.fts_insert("entity", entity_id, name)
        self.db.log_mutation("entity_created", "entity", entity_id,
                             f"{name} [{type_}]", session_id)
        return {"entity_id": entity_id, "name": name, "type": type_}

    def find_entity(self, name: str) -> Optional[Dict[str, Any]]:
        def _find(conn) -> Optional[Dict[str, Any]]:
            row = conn.execute("SELECT * FROM entities WHERE name = ?", (name,)).fetchone()
            return dict(row) if row else None

        return self.db._run(_find)

    def get_entity(self, entity_id: str) -> Optional[Dict[str, Any]]:
        def _get(conn) -> Optional[Dict[str, Any]]:
            row = conn.execute("SELECT * FROM entities WHERE entity_id = ?", (entity_id,)).fetchone()
            return dict(row) if row else None

        return self.db._run(_get)

    def search_entities(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        hits = self.db.fts_search(query, kinds=["entity"], limit=limit)
        out = []
        for h in hits:
            e = self.get_entity(h["target_id"])
            if e:
                out.append({"entity_id": e["entity_id"], "name": e["name"],
                            "type": e["type"], "score": h["score"]})
        return out

    # -------------------------------------------------------- relationships

    def relate(self, src_name: str, rel: str, dst_name: str, *,
               confidence: float = 0.7, importance: float = 0.5,
               source_type: str = "agent_inference", source_ref: str = "",
               valid_from: Optional[str] = None, valid_until: Optional[str] = None,
               src_type: str = "object", dst_type: str = "object",
               session_id: str = "") -> Dict[str, Any]:
        """Create a relationship, auto-resolving/creating entity nodes."""
        rel = (rel or "").upper().replace(" ", "_")
        if rel not in RELATIONSHIP_TYPES:
            return {"error": f"unknown relationship type: {rel}"}
        a = self.get_or_create_entity(src_name, src_type, session_id=session_id)
        b = self.get_or_create_entity(dst_name, dst_type, session_id=session_id)
        if "error" in a or "error" in b:
            return a if "error" in a else b

        rel_id = self.db.next_id("relationship")
        now = _db.now_iso()

        def _insert(conn) -> None:
            conn.execute(
                """INSERT INTO relationships(
                     rel_id, src, rel, dst, valid_from, valid_until, confidence,
                     importance, source_type, source_ref, created_at, status)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (rel_id, a["name"], rel, b["name"], valid_from or now, valid_until,
                 confidence, importance, source_type, source_ref, now, "active"),
            )

        ok = self.db._run(_insert, write=True)
        if ok is None:
            return {"error": "insert failed"}
        self.db.log_mutation("relate", "relationship", rel_id,
                             f"{a['name']} -[{rel}]-> {b['name']}", session_id)
        return {"rel_id": rel_id, "src": a["name"], "rel": rel, "dst": b["name"]}

    def supersede_relationship(self, src: str, rel: str, dst: str, *,
                                reason: str = "", session_id: str = "") -> int:
        """End all active relationships matching (src, rel, dst) with valid_until=now.

        History is preserved: rows remain, status becomes 'superseded'.
        Returns the number of relationships superseded.
        """
        now = _db.now_iso()

        def _upd(conn) -> int:
            cur = conn.execute(
                """UPDATE relationships SET valid_until = ?, status = 'superseded'
                   WHERE src = ? AND rel = ? AND dst = ? AND status = 'active'""",
                (now, src, rel, dst),
            )
            return cur.rowcount

        n = self.db._run(_upd, write=True) or 0
        if n:
            self.db.log_mutation("supersede_relationship", "relationship", "",
                                 f"{src} -[{rel}]-> {dst}: {reason}", session_id)
        return n

    def supersede_relationships_from(self, src: str, rel: str, *,
                                      reason: str = "", session_id: str = "") -> int:
        """Supersede ALL active (src, rel, *) edges — 'what we use now' changes."""
        now = _db.now_iso()

        def _upd(conn) -> int:
            cur = conn.execute(
                """UPDATE relationships SET valid_until = ?, status = 'superseded'
                   WHERE src = ? AND rel = ? AND status = 'active'""",
                (now, src, rel),
            )
            return cur.rowcount

        n = self.db._run(_upd, write=True) or 0
        if n:
            self.db.log_mutation("supersede_relationships", "relationship", "",
                                 f"{src} -[{rel}]-> *: {reason}", session_id)
        return n

    def query(self, src: Optional[str] = None, rel: Optional[str] = None,
              dst: Optional[str] = None, *, status: str = "active",
              include_history: bool = False, limit: int = 30) -> List[Dict[str, Any]]:
        """Query edges. include_history=True also returns superseded/contradicted rows."""
        clauses = []
        params: List[Any] = []
        if not include_history:
            clauses.append("status = ?")
            params.append(status)
        if src:
            clauses.append("src = ?")
            params.append(src)
        if rel:
            clauses.append("rel = ?")
            params.append(rel)
        if dst:
            clauses.append("dst = ?")
            params.append(dst)
        sql = "SELECT * FROM relationships"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        def _q(conn) -> List[Dict[str, Any]]:
            return [dict(r) for r in conn.execute(sql, params)]

        return self.db._run(_q) or []

    def traverse(self, start_entity: str, hop_limit: int = 2,
                 limit: int = 30) -> List[Dict[str, Any]]:
        """BFS from an entity name across active edges, up to hop_limit hops.

        ``hop_limit`` is clamped to MAX_HOPS_MIN/MAX: traversal cost grows with
        the frontier, so an unbounded hop count from a caller is not offered.
        """
        hop_limit = max(1, min(int(hop_limit or 1), _MAX_HOPS))
        seen_edges: set = set()
        frontier = [start_entity]
        seen_nodes = {start_entity}
        results: List[Dict[str, Any]] = []

        def _bfs(conn) -> List[Dict[str, Any]]:
            for _hop in range(hop_limit + 1):
                if not frontier:
                    break
                current = frontier[:]
                frontier.clear()
                for node in current:
                    rows = conn.execute(
                        "SELECT * FROM relationships WHERE (src = ? OR dst = ?) AND status = 'active' LIMIT ?",
                        (node, node, limit),
                    ).fetchall()
                    for r in rows:
                        d = dict(r)
                        if d["rel_id"] in seen_edges:
                            continue
                        seen_edges.add(d["rel_id"])
                        results.append(d)
                        other = d["dst"] if d["src"] == node else d["src"]
                        if other not in seen_nodes:
                            seen_nodes.add(other)
                            frontier.append(other)
                if len(results) >= limit:
                    break
            return results[:limit]

        return self.db._run(_bfs) or []

    def reinforce(self, rel_id: str, session_id: str = "") -> None:
        def _r(conn) -> None:
            conn.execute(
                "UPDATE relationships SET reinforcement_count = reinforcement_count + 1,"
                " last_verified = ?, last_accessed = ? WHERE rel_id = ?",
                (_db.now_iso(), _db.now_iso(), rel_id),
            )

        self.db._run(_r, write=True)

    def remove_relationship(self, rel_id: str, session_id: str = "") -> bool:
        def _rm(conn) -> bool:
            cur = conn.execute("DELETE FROM relationships WHERE rel_id = ?", (rel_id,))
            return cur.rowcount > 0

        ok = self.db._run(_rm, write=True)
        if ok:
            self.db.log_mutation("relationship_removed", "relationship", rel_id,
                                 "explicit removal", session_id)
        return bool(ok)
