"""Memory consolidation — the "sleep" pass (§11).

Deterministic, transparent heuristics for V1; the pipeline order follows the
spec: entity resolution -> duplicate detection -> relationship extraction ->
contradiction analysis -> pattern discovery -> confidence update ->
procedural candidates -> forgetting/compression.

Never summarizes summaries: every derived item links back to its source
episodes/evidence via derived_from / source_refs.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import config as _cfg
from . import db as _db
from . import trust as _trust

_NEGATIONS = (" no longer ", " not ", " never ", " doesn't ", " does not ",
              " won't ", " cannot ", " can't ", " stopped ", "isn't ", "aren't ",
              "wasn't ", "weren't ")

_SIMILARITY_MIN = 0.6


def _norm_claim(claim: str) -> str:
    return " ".join(claim.lower().split())


def _claims_similar(a: str, b: str) -> float:
    """Cheap token-overlap similarity for duplicate detection."""
    na, nb = _norm_claim(a), _norm_claim(b)
    if na == nb:
        return 1.0
    ta, tb = set(na.split()), set(nb.split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / max(len(ta), len(tb))


class Consolidator:
    def __init__(self, database: _db.Database, config: Dict,
                 episodic=None, graph=None, semantic=None,
                 procedural=None, forgetting=None, vectors=None):
        self.db = database
        self.cfg = config
        self.episodic = episodic
        self.graph = graph
        self.semantic = semantic
        self.procedural = procedural
        self.forgetting = forgetting
        self.vectors = vectors

    # ------------------------------------------------------------ main loop

    def run(self, *, reason: str = "scheduled", session_id: str = "") -> Dict[str, Any]:
        """Run the full consolidation pipeline. Returns a report dict."""
        run_id = self.db.next_id("consolidation")
        self._scan_beliefs = int(_cfg.get(self.cfg, "consolidation.max_beliefs_scan", 500))
        self._scan_episodes = int(_cfg.get(self.cfg, "consolidation.max_episodes_scan", 500))
        started = _db.now_iso()
        changes: List[str] = []
        counts: Dict[str, int] = {}

        steps = [
            ("entity_resolution", self._entity_resolution),
            ("duplicate_detection", self._duplicate_detection),
            ("relationship_extraction", self._relationship_extraction),
            ("contradiction_analysis", self._contradiction_analysis),
            ("pattern_discovery", self._pattern_discovery),
            ("confidence_update", self._confidence_update),
            ("forgetting", self._forgetting),
        ]
        for name, fn in steps:
            try:
                n, msgs = fn(session_id)
                counts[name] = n
                changes.extend(msgs)
            except Exception as e:
                counts[name] = -1
                changes.append(f"{name}: error {e}")

        summary = f"consolidation {run_id} ({reason}): " + \
                  ", ".join(f"{k}={v}" for k, v in counts.items())

        def _store(conn) -> None:
            conn.execute(
                "INSERT INTO consolidation_runs(run_id, started_at, finished_at, summary, changes)"
                " VALUES (?,?,?,?,?)",
                (run_id, started, _db.now_iso(), summary, _db.jdump(changes)),
            )

        self.db._run(_store, write=True)
        self.db.log_mutation("consolidate", "consolidation", run_id,
                             summary, session_id)
        return {"run_id": run_id, "summary": summary, "counts": counts,
                "changes": changes}

    # ------------------------------------------------------------- steps

    def _entity_resolution(self, session_id: str) -> tuple:
        """Link entity names found inside active beliefs/episodes to graph nodes."""
        if self.semantic is None or self.graph is None:
            return 0, []
        linked = 0
        entities = self._all_entity_names()
        if not entities:
            return 0, []
        for b in self.semantic.list_beliefs(status="active", limit=self._scan_beliefs):
            text = f"{b['claim']} {b.get('related_entities', '')}".lower()
            for name, etype in entities:
                if name.lower() in text:
                    rels = _db.jload(b["related_entities"], [])
                    if name not in rels:
                        rels.append(name)
                        self.db._run(
                            lambda conn, bid=b["belief_id"], r=_db.jdump(rels):
                            conn.execute("UPDATE beliefs SET related_entities = ?"
                                         " WHERE belief_id = ?", (r, bid)),
                            write=True,
                        )
                        linked += 1
        return linked, [f"entity_resolution: linked {linked} belief-entity refs"]

    def _all_entity_names(self) -> List[tuple]:
        def _q(conn) -> List[tuple]:
            return [(r["name"], r["type"]) for r in
                    conn.execute("SELECT name, type FROM entities").fetchall()]

        return self.db._run(_q) or []

    def _duplicate_detection(self, session_id: str) -> tuple:
        """Merge near-identical active beliefs (keep oldest, supersede rest)."""
        if self.semantic is None:
            return 0, []
        beliefs = self.semantic.list_beliefs(status="active", limit=self._scan_beliefs)
        merged = 0
        done: set = set()
        for i, a in enumerate(beliefs):
            if a["belief_id"] in done:
                continue
            for b in beliefs[i + 1:]:
                if b["belief_id"] in done:
                    continue
                if _claims_similar(a["claim"], b["claim"]) >= _SIMILARITY_MIN:
                    older, newer = (a, b) if a["created_at"] <= b["created_at"] else (b, a)
                    # A background merge is the runtime's own work, not an operator
                    # action: it is stamped with system identity and
                    # agent_consolidation provenance, so a merge can never inherit a
                    # CLI trust default and can never mint user_explicit provenance
                    # from content the model wrote.
                    outcome = self.semantic.supersede(
                        newer["belief_id"],
                        older["claim"],
                        reason="duplicate merged in consolidation",
                        keep_confidence=max(older["confidence"], newer["confidence"]),
                        source_class=older.get("verified_source_class")
                        or older["source_class"],
                        actor_id="system",
                        identity=_trust.SYSTEM,
                        provenance=_trust.PROVENANCE_AGENT_CONSOLIDATION,
                        channel=_trust.CHANNEL_CONSOLIDATION,
                        session_id=session_id,
                    )
                    if outcome.get("belief_id"):
                        done.add(newer["belief_id"])
                        merged += 1
                    # a refused merge (e.g. the row is operator-protected) simply
                    # stays as it is; consolidation never forces a rewrite
        return merged, [f"duplicate_detection: merged {merged} duplicate beliefs"]

    def _relationship_extraction(self, session_id: str) -> tuple:
        """Deterministic episode->graph edges: project links and decision links."""
        if self.episodic is None or self.graph is None:
            return 0, []
        added = 0
        for e in self.episodic.list_episodes_full(status="active", limit=self._scan_episodes):
            rels = _db.jload(e["related_entities"], []) or []
            for ent in rels:
                r = self.graph.relate(e["project"] or e["context"] or "session",
                                      "OBSERVED_IN", ent, source_type="derived_pattern",
                                      source_ref=f"episode:{e['episode_id']}",
                                      session_id=session_id)
                if "rel_id" in r:
                    added += 1
        return added, [f"relationship_extraction: added {added} edges"]

    def _contradiction_analysis(self, session_id: str) -> tuple:
        """Detect opposite-polarity active claims about the same subject."""
        if self.semantic is None:
            return 0, []
        beliefs = self.semantic.list_beliefs(status="active", limit=self._scan_beliefs)
        found = 0
        for i, a in enumerate(beliefs):
            for b in beliefs[i + 1:]:
                if _claims_similar(a["claim"], b["claim"]) < 0.45:
                    continue
                pa = any(neg in f" {_norm_claim(a['claim'])} " for neg in _NEGATIONS)
                pb = any(neg in f" {_norm_claim(b['claim'])} " for neg in _NEGATIONS)
                if pa != pb:
                    self.semantic.contradict(
                        a["belief_id"], b["claim"],
                        confidence=b["confidence"],
                        source_class=b.get("verified_source_class") or b["source_class"],
                        # background analysis: system identity, never user trust
                        actor_id="system", identity=_trust.SYSTEM,
                        provenance=_trust.PROVENANCE_AGENT_CONSOLIDATION,
                        channel=_trust.CHANNEL_CONSOLIDATION,
                        session_id=session_id)
                    found += 1
        return found, [f"contradiction_analysis: {found} contradictions cross-linked"]

    def _pattern_discovery(self, session_id: str) -> tuple:
        """Repeated outcomes per project -> procedural candidates (§12)."""
        if self.episodic is None or self.procedural is None:
            return 0, []
        cfg = self.cfg.get("consolidation", {})
        min_ep = int(cfg.get("procedural_min_episodes", 3))
        by_key: Dict[str, List[Dict[str, Any]]] = {}
        for e in self.episodic.list_episodes_full(status="active", limit=self._scan_episodes):
            key = (e["project"] or "", (e["context"] or "").strip()[:60])
            by_key.setdefault(key, []).append(e)
        created = 0
        for key, eps in by_key.items():
            if len(eps) < min_ep:
                continue
            successes = [e for e in eps if e["outcome"] in ("success", "mixed")]
            if not successes:
                continue
            ratio = len(successes) / len(eps)
            if ratio < float(cfg.get("procedural_min_success_ratio", 0.6)):
                continue
            name = f"{key[0] or 'task'}: {key[1][:50]}" if key[1] else f"{key[0]} workflow"
            steps = list({(s["actions_taken"] or "").strip() for s in successes
                          if (s["actions_taken"] or "").strip()})
            proc = self.procedural.create_procedure(
                name,
                description=f"Pattern derived from {len(eps)} episodes "
                            f"({len(successes)} successful, ratio {ratio:.2f}) in "
                            f"{key[0] or 'unspecified project'}",
                steps=steps[:8],
                applicability=(successes[0].get("context") or "")[:200],
                confidence=min(0.85, 0.4 + 0.15 * ratio + 0.05 * min(len(eps), 6)),
                status="candidate",
                derived_from=[f"episode:{e['episode_id']}" for e in eps],
                session_id=session_id,
            )
            if "procedure_id" in proc:
                created += 1
        return created, [f"pattern_discovery: {created} procedural candidates"]

    def _confidence_update(self, session_id: str) -> tuple:
        """Reinforce beliefs repeatedly observed in episodes."""
        if self.semantic is None or self.episodic is None:
            return 0, []
        updated = 0
        for b in self.semantic.list_beliefs(status="active", limit=self._scan_beliefs):
            derived = _db.jload(b["derived_from"], [])
            n_support = len([d for d in derived if str(d).startswith("episode:")])
            if n_support >= 3 and b["reinforcement_count"] < n_support:
                self.semantic.reinforce(b["belief_id"], 0.04, session_id)
                updated += 1
        return updated, [f"confidence_update: reinforced {updated} beliefs"]

    def _forgetting(self, session_id: str) -> tuple:
        if self.forgetting is None:
            return 0, []
        n, msgs = self.forgetting.pass_(session_id)
        return n, msgs
