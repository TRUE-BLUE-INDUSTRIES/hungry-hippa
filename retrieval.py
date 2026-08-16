"""Hybrid graph + vector retrieval (§5).

Pipeline:
  query -> intent analysis (entity lookup + keyword/vector search in parallel)
        -> graph traversal around matched entities (bounded hops)
        -> rank by importance x recency x match score
        -> attach provenance (derived_from / evidence ids / relationships)
        -> emit a MINIMAL, useful context block (capped, §5 "avoid dumping").

Ranking is transparent and heuristic (§14) so a learned policy can replace it
later through the same interface.
"""

from __future__ import annotations

import math
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from . import db as _db


def _iso_to_epoch(iso: Optional[str]) -> float:
    if not iso:
        return 0.0
    try:
        return datetime.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S").replace(
            tzinfo=timezone.utc).timestamp()
    except Exception:
        return 0.0


class RetrievalRouter:
    def __init__(self, database: _db.Database, config: Dict,
                 episodic=None, graph=None, semantic=None,
                 procedural=None, vectors=None):
        self.db = database
        self.cfg = config
        self.ret = config.get("retrieval", {})
        self.episodic = episodic
        self.graph = graph
        self.semantic = semantic
        self.procedural = procedural
        self.vectors = vectors
        self.max_chars = int(self.ret.get("max_context_chars", 1500))
        self.max_items = int(self.ret.get("max_items", 6))
        self.hops = int(self.ret.get("graph_hop_limit", 2))
        self.half_life_days = float(self.ret.get("recency_half_life_days", 45))

    # ------------------------------------------------------------ scoring

    def _recency(self, iso: Optional[str]) -> float:
        if not iso:
            return 0.5
        age_days = (time.time() - _iso_to_epoch(iso)) / 86400.0
        return math.exp(-math.log(2) * max(0.0, age_days) / self.half_life_days)

    def _rank(self, items: List[Dict[str, Any]], query_terms: List[str]) -> List[Dict[str, Any]]:
        qset = set(t.lower() for t in query_terms if len(t) > 2)
        for it in items:
            text = " ".join(str(it.get(k, "")) for k in
                            ("context", "user_request", "claim", "result",
                             "name", "description")).lower()
            term_hits = sum(1 for t in qset if t in text)
            importance = float(it.get("importance", 0.5))
            recency = self._recency(it.get("ts_start") or it.get("created_at")
                                     or it.get("valid_from"))
            vector_score = float(it.get("vector_score", 0.0))
            fts_score = float(it.get("fts_score", 0.0))
            reinforce = 1.0 + 0.05 * min(10, int(it.get("reinforcement_count", 0)))
            it["_score"] = (
                0.35 * importance
                + 0.25 * recency
                + 0.25 * max(vector_score, fts_score / 10.0, term_hits * 0.12)
                + 0.15 * (1.0 if term_hits else 0.0)
            ) * reinforce
        items.sort(key=lambda x: -x["_score"])
        return items

    # ------------------------------------------------------------ pipeline

    def recall(self, query: str, *, project: str = "", limit: Optional[int] = None,
               session_id: str = "") -> Dict[str, Any]:
        """Run the full hybrid recall pipeline. Never raises."""
        limit = limit or self.max_items
        query = (query or "").strip()
        if not query:
            return {"items": [], "context": "", "sources": [], "count": 0}
        try:
            return self._recall(query, project=project, limit=limit,
                                session_id=session_id)
        except Exception as e:
            self.db.failures += 1
            return {"items": [], "context": "", "sources": [],
                    "count": 0, "error": str(e)[:200]}

    def _recall(self, query: str, *, project: str, limit: int,
                session_id: str) -> Dict[str, Any]:
        collected: Dict[str, Dict[str, Any]] = {}
        order: List[str] = []
        terms = [t for t in query.lower().replace("?", " ").split() if len(t) > 2]

        def add(key: str, item: Dict[str, Any]) -> None:
            if key not in collected:
                collected[key] = item
                order.append(key)

        # 1) entity lookup (graph entry points)
        entity_hits = []
        if self.graph is not None:
            entity_hits = self.graph.search_entities(query, limit=4)
        matched_entities = [e["name"] for e in entity_hits]

        # 2) vector search (episodes + beliefs) — degrades to [] offline
        vec_hits: List[Dict[str, Any]] = []
        if self.vectors is not None:
            vec_hits = self.vectors.search(query, kinds=["episode", "belief"])

        # 3) FTS keyword search
        fts_hits = self.db.fts_search(query, kinds=["episode", "belief"],
                                      limit=limit * 2)

        # 4) assemble items with hybrid scores
        for h in vec_hits:
            if h["kind"] == "episode" and self.episodic is not None:
                e = self.episodic.get_episode(h["target_id"])
                if e and e["status"] == "active":
                    e["_kind"] = "episode"
                    e["vector_score"] = h["score"]
                    add(f"episode:{e['episode_id']}", e)
            elif h["kind"] == "belief" and self.semantic is not None:
                b = self.semantic.get_belief(h["target_id"])
                if b and b["status"] == "active":
                    b["_kind"] = "belief"
                    b["vector_score"] = h["score"]
                    add(f"belief:{b['belief_id']}", b)
        for h in fts_hits:
            key = f"{h['target_kind']}:{h['target_id']}"
            if key in collected:
                collected[key]["fts_score"] = h["score"]
                continue
            if h["target_kind"] == "episode" and self.episodic is not None:
                e = self.episodic.get_episode(h["target_id"])
                if e and e["status"] == "active":
                    e["_kind"] = "episode"
                    e["fts_score"] = h["score"]
                    add(key, e)
            elif h["target_kind"] == "belief" and self.semantic is not None:
                b = self.semantic.get_belief(h["target_id"])
                if b and b["status"] == "active":
                    b["_kind"] = "belief"
                    b["fts_score"] = h["score"]
                    add(key, b)

        # 5) graph traversal around matched entities
        if self.graph is not None:
            for ent in matched_entities[:3]:
                for edge in self.graph.traverse(ent, hop_limit=self.hops, limit=8):
                    if edge["src"] != ent and edge["src"] not in matched_entities:
                        matched_entities.append(edge["src"])
                    if edge["dst"] != ent and edge["dst"] not in matched_entities:
                        matched_entities.append(edge["dst"])
                    add(f"rel:{edge['rel_id']}", {
                        "kind": "relationship",
                        "src": edge["src"], "rel": edge["rel"], "dst": edge["dst"],
                        "confidence": edge["confidence"],
                        "importance": edge["importance"],
                        "valid_from": edge["valid_from"],
                        "valid_until": edge["valid_until"],
                        "status": edge["status"],
                        "reinforcement_count": edge["reinforcement_count"],
                    })
            # current-state facts for matched entities ("what do we use now?")
            for ent in matched_entities[:4]:
                for edge in self.graph.query(src=ent, status="active", limit=4):
                    add(f"rel:{edge['rel_id']}", {
                        "kind": "relationship",
                        "src": edge["src"], "rel": edge["rel"], "dst": edge["dst"],
                        "confidence": edge["confidence"],
                        "importance": edge["importance"],
                        "valid_from": edge["valid_from"],
                        "valid_until": edge["valid_until"],
                        "status": edge["status"],
                        "reinforcement_count": edge["reinforcement_count"],
                    })

        # 6) rank + cap
        items = self._rank([collected[k] for k in order], terms)
        if project:
            items = [i for i in items if i.get("project", "") == project] + \
                    [i for i in items if i.get("project", "") != project]
        items = items[:limit]

        # 7) provenance for the top items
        sources: List[str] = []
        for it in items:
            derived = it.get("derived_from") or it.get("source_refs") or []
            if isinstance(derived, str):
                derived = _db.jload(derived, [])
            for d in derived[:4]:
                if d and str(d) not in sources:
                    sources.append(str(d))
            for ev in it.get("evidence_ids", [])[:2]:
                if ev and ev not in sources:
                    sources.append(ev)

        # 8) touch accessed items (reinforcement = retrieval boosts memory)
        for it in items:
            if it.get("_kind") == "episode":
                self.episodic.touch(it["episode_id"], session_id)

        context = self.render(items, query)
        return {"items": items, "context": context, "sources": sources,
                "count": len(items), "entities": matched_entities[:8]}

    # ------------------------------------------------------------ rendering

    def render(self, items: List[Dict[str, Any]], query: str = "") -> str:
        """Render minimal, useful context — capped at max_context_chars."""
        lines: List[str] = []
        used = 0
        budget = self.max_chars
        for it in items:
            if used >= budget:
                break
            kind = it.get("_kind") or it.get("kind", "")
            if kind == "episode":
                refs = _db.jload(it.get("source_refs"), []) or []
                block = (
                    f"[EPISODE {it['episode_id']} {it.get('ts_start', '')[:10]}] "
                    f"{it.get('context', '')} — outcome: {it.get('outcome', '?')}"
                )
                if it.get("result"):
                    block += f" | result: {it['result'][:200]}"
                if it.get("project"):
                    block += f" | project: {it['project']}"
                block += f" | importance {it.get('importance', 0):.2f}"
                if refs:
                    block += f" (src: {', '.join(str(r) for r in refs[:3])})"
            elif kind == "belief":
                derived = _db.jload(it.get("derived_from"), []) or []
                block = (f"[BELIEF {it['belief_id']} {it['kind']}/{it['source_class']} "
                         f"conf {it.get('confidence', 0):.2f}] {it.get('claim', '')}")
                if derived:
                    block += f" | derived_from: {', '.join(str(d) for d in derived[:4])}"
            elif kind == "relationship":
                valid = f" {it.get('valid_from', '?')}" + (
                    f"→{it.get('valid_until')}" if it.get("valid_until") else "→present")
                block = (f"[GRAPH {it['src']} -[{it['rel']}]-> {it['dst']}"
                         f" ({it.get('status', '?')}, conf {it.get('confidence', 0):.2f}){valid}]")
            else:
                block = f"[{kind} {it.get('episode_id', it.get('belief_id', '?'))}] {str(it)[:300]}"
            if used + len(block) > budget and lines:
                break
            lines.append(block)
            used += len(block) + 1
        return "\n".join(lines)
