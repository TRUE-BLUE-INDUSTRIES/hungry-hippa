"""Memory controller (§14) — the central abstraction.

Capabilities (spec §14): remember_episode, recall, relate, retrieve_graph,
retrieve_similar, update_belief, add_evidence, contradict, supersede,
consolidate, reinforce, archive, forget, create_procedure — plus the
transparent-heuristic decisions (importance tiering, staging, session closure)
that a learned policy can later replace through the same interface.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import db as _db
from . import limits as _limits
from . import policy as _policy
from .attention import AttentionScorer
from .consolidation import Consolidator
from .episodic import EpisodicMemory
from .forgetting import ForgettingPolicy
from .graph import KnowledgeGraph
from .procedural import ProceduralMemory
from .retrieval import RetrievalRouter
from .semantic import SemanticMemory
from .vectors import VectorStore


class MemoryController:
    def __init__(self, config: Dict, db_path: Optional[str] = None):
        self.cfg = config
        self.db = _db.Database(db_path or self._resolve_db())
        self.attention = AttentionScorer(config)
        self.episodic = EpisodicMemory(self.db, config)
        self.graph = KnowledgeGraph(self.db, config)
        self.semantic = SemanticMemory(self.db, config)
        self.procedural = ProceduralMemory(self.db, config)
        self.vectors = VectorStore(self.db, config)
        self.forgetting = ForgettingPolicy(self.db, config,
                                           episodic=self.episodic,
                                           semantic=self.semantic)
        self.retrieval = RetrievalRouter(
            self.db, config,
            episodic=self.episodic, graph=self.graph,
            semantic=self.semantic, procedural=self.procedural,
            vectors=self.vectors,
        )
        self.consolidator = Consolidator(
            self.db, config,
            episodic=self.episodic, graph=self.graph,
            semantic=self.semantic, procedural=self.procedural,
            forgetting=self.forgetting, vectors=self.vectors,
        )
        self.session_id = ""
        self.platform = ""
        self.agent_context = "primary"
        self.actor_id = _policy.DEFAULT_ACTOR
        self.writes_enabled = True

    def _resolve_db(self) -> str:
        from .config import resolve_db_path

        return resolve_db_path(self.cfg)

    # ------------------------------------------------------------- lifecycle

    def bind_session(self, session_id: str = "", platform: str = "",
                     agent_context: str = "primary",
                     parent_session_id: str = "",
                     actor_id: str = "") -> None:
        self.session_id = session_id
        self.platform = platform
        self.agent_context = agent_context or "primary"
        self.actor_id = _policy.normalize_actor(actor_id or self.agent_context)
        self.writes_enabled = (
            self.agent_context == "primary" and not parent_session_id
        )

    # ------------------------------------------------------------- §14 API

    def remember_episode(self, *, embed: bool = True, **fields: Any) -> Dict[str, Any]:
        """Create an episode (attention-gated by the caller via importance).

        Actor policy: writes from a non-owner actor are stored quarantined so
        an untrusted caller cannot inject a memory into normal recall.
        """
        if not self.writes_enabled:
            return {"error": "writes disabled for this agent context"}
        importance = fields.pop("importance", None)
        signals = fields.pop("importance_signals", None)
        if importance is None:
            scored = self.attention.score_episode_fields(fields)
            importance = scored["importance"]
            signals = scored["signals"]
        fields["importance"] = importance
        # actor_id is forwarded; quarantine is decided by the write layer
        # (episodic/semantic) so every path obeys the same rule.
        fields["actor_id"] = _policy.normalize_actor(
            fields.get("actor_id") or self.actor_id)
        fields["session_id"] = self.session_id
        result = self.episodic.remember_episode(**fields)
        eid = result.get("episode_id")
        if eid and embed:
            body = " ".join(str(fields.get(k, "")) for k in
                            ("context", "user_request", "actions_taken",
                             "decisions", "result", "project"))
            if body.strip():
                self.vectors.store("episode", eid, body)
        return result

    def recall(self, query: str, *, project: str = "",
               limit: Optional[int] = None, actor_id: str = "",
               explain: bool = False, include_quarantined: bool = False,
               max_context_chars: Optional[int] = None) -> Dict[str, Any]:
        """Hybrid recall under actor policy.

        Quarantined rows are excluded for everyone by default; only the owner
        may ask for them while reviewing, and an untrusted actor never sees
        rows it did not write.
        """
        actor = _policy.normalize_actor(actor_id or self.actor_id)
        if include_quarantined and not _policy.is_owner(actor):
            include_quarantined = False
        out = self.retrieval.recall(query, project=project, limit=limit,
                                    session_id=self.session_id, actor_id=actor,
                                    explain=explain,
                                    include_quarantined=include_quarantined,
                                    max_context_chars=max_context_chars)

        def _log(conn) -> None:
            conn.execute(
                "INSERT INTO retrieval_log(ts, query, recalled, session_id) VALUES (?,?,?,?)",
                (_db.now_iso(), _limits.redact(query)[:500],
                 _db.jdump([it.get("episode_id") or it.get("belief_id") or it.get("rel_id")
                            for it in out.get("items", [])]),
                 self.session_id),
            )

        self.db._run(_log, write=True)
        return out

    def build_context(self, query: str, **kwargs: Any) -> Dict[str, Any]:
        """Recall and return the compiled context package (Phase 3 compiler).

        ``{items, rendering, token_estimate, excluded}`` plus the recall
        metadata. Kept separate from ``recall`` so callers that only want the
        package (MCP ``hippa_build_context``) do not have to unpack a recall.
        ``max_chars`` is accepted as an alias for ``max_context_chars``.
        """
        if "max_chars" in kwargs and "max_context_chars" not in kwargs:
            kwargs["max_context_chars"] = kwargs.pop("max_chars")
        out = self.recall(query, **kwargs)
        pkg = dict(out.get("context_package") or {})
        pkg["sources"] = out.get("sources", [])
        pkg["entities"] = out.get("entities", [])
        pkg["actor_id"] = out.get("actor_id", self.actor_id)
        if out.get("error"):
            pkg["error"] = out["error"]
        return pkg

    def relate(self, src: str, rel: str, dst: str, **kwargs: Any) -> Dict[str, Any]:
        return self.graph.relate(src, rel, dst, session_id=self.session_id, **kwargs)

    def retrieve_graph(self, src: str = "", rel: str = "", dst: str = "",
                       include_history: bool = False,
                       limit: int = 30) -> List[Dict[str, Any]]:
        return self.graph.query(src=src or None, rel=rel or None, dst=dst or None,
                                include_history=include_history, limit=limit)

    def retrieve_similar(self, query: str, kinds: Optional[List[str]] = None,
                         top_k: int = 8) -> List[Dict[str, Any]]:
        return self.vectors.search(query, kinds=kinds, top_k=top_k)

    def update_belief(self, belief_id: str, *, new_claim: str = "",
                      confidence_delta: Optional[float] = None,
                      confidence: Optional[float] = None,
                      kind: str = "", source_class: str = "",
                      reason: str = "") -> Dict[str, Any]:
        b = self.semantic.get_belief(belief_id)
        if not b:
            return {"error": f"unknown belief {belief_id}"}
        if new_claim and new_claim.strip() != b["claim"]:
            return self.semantic.supersede(
                belief_id, new_claim, reason=reason or "updated belief",
                keep_confidence=confidence, source_class=source_class or b["source_class"],
                session_id=self.session_id,
            )
        if confidence_delta is not None:
            return self.semantic.reinforce(belief_id, confidence_delta,
                                           self.session_id) or {}
        if confidence is not None:
            def _upd(conn) -> None:
                conn.execute(
                    "UPDATE beliefs SET confidence = ?, updated_at = ? WHERE belief_id = ?",
                    (max(0.0, min(0.98, confidence)), _db.now_iso(), belief_id),
                )

            self.db._run(_upd, write=True)
            return self.semantic.get_belief(belief_id) or {}
        return {"error": "no update specified"}

    def add_evidence(self, content: str, kind: str = "hermes_inference",
                     source_ref: str = "") -> str:
        return self.db.add_evidence(content, kind, source_ref, self.session_id)

    def contradict(self, belief_id: str, counter_claim: str, **kwargs: Any) -> Dict[str, Any]:
        return self.semantic.contradict(belief_id, counter_claim,
                                        session_id=self.session_id, **kwargs)

    def supersede(self, belief_id: str, replacement_claim: str, **kwargs: Any) -> Dict[str, Any]:
        return self.semantic.supersede(belief_id, replacement_claim,
                                       session_id=self.session_id, **kwargs)

    def consolidate(self, reason: str = "manual") -> Dict[str, Any]:
        return self.consolidator.run(reason=reason, session_id=self.session_id)

    def reinforce(self, kind: str, target_id: str) -> bool:
        if kind == "episode":
            self.episodic.touch(target_id, self.session_id)
            return True
        if kind == "belief":
            return bool(self.semantic.reinforce(target_id, 0.05, self.session_id))
        if kind == "relationship":
            self.graph.reinforce(target_id, self.session_id)
            return True
        return False

    def archive(self, kind: str, target_id: str, reason: str = "") -> bool:
        return self.forgetting.archive(kind, target_id, reason, self.session_id)

    def forget(self, kind: str, target_id: str, *, mode: str = "archival",
               reason: str = "") -> Dict[str, Any]:
        """forget() — memory-management operation, never silent deletion.

        ``purge`` (irreversible delete) is owner-only; untrusted actors get
        archival at most. Over MCP, purge is denied unless explicitly
        confirmed by an owner (see mcp_server.py).
        """
        if mode == "purge":
            if not _policy.may_purge(self.actor_id):
                return {"error": "purge denied for this actor",
                        "actor_id": self.actor_id, "target": target_id}
            if kind == "episode":
                ok = self.episodic.purge(target_id, self.session_id)
            elif kind == "belief":
                ok = self.semantic.remove_belief(target_id, self.session_id)
            else:
                return {"error": f"purge unsupported for {kind}"}
            return {"purged": bool(ok), "target": target_id}
        ok = self.forgetting.archive(kind, target_id, reason or "manual forget",
                                     self.session_id)
        return {"archived": bool(ok), "target": target_id}

    def create_procedure(self, name: str, **kwargs: Any) -> Dict[str, Any]:
        return self.procedural.create_procedure(name, session_id=self.session_id, **kwargs)

    def record_outcome(self, procedure_id: str, success: bool) -> Optional[Dict[str, Any]]:
        return self.procedural.record_outcome(procedure_id, success, self.session_id)

    def promote_to_skill(self, procedure_id: str) -> Dict[str, Any]:
        return self.procedural.promote_to_skill(procedure_id, self.session_id)

    # ------------------------------------------------------------ staging

    def stage_turn(self, turn_number: int, user_content: str,
                   assistant_content: str, tools_used: List[str],
                   outcome: str = "unknown",
                   importance_signals: Optional[List[str]] = None) -> None:
        if not self.writes_enabled:
            return
        def _stage(conn) -> None:
            conn.execute(
                """INSERT INTO turn_staging(session_id, turn_number, ts, user_content,
                     assistant_content, tools_used, outcome, importance_signals)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (self.session_id, turn_number, _db.now_iso(),
                 user_content[:4000], assistant_content[:8000],
                 _db.jdump(tools_used or []), outcome,
                 _db.jdump(importance_signals or [])),
            )

        self.db._run(_stage, write=True)

    def close_session(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        """Assemble episodes from staged turns + run light consolidation.

        Called from the provider's on_session_end. Attention-gates: only
        turns with signals become episodes; low-value turns stay as metadata.
        """
        session_id = session_id or self.session_id
        if not session_id:
            return {"error": "no session id"}
        auto = self.cfg.get("provider", {}).get("auto_episode_on_session_end", True)
        if not auto or not self.writes_enabled:
            return {"error": "auto-episode disabled"}

        def _q(conn) -> List[Dict[str, Any]]:
            rows = conn.execute(
                "SELECT * FROM turn_staging WHERE session_id = ? AND processed = 0"
                " ORDER BY turn_number", (session_id,),
            ).fetchall()
            return [dict(r) for r in rows]

        turns = self.db._run(_q) or []
        created: List[str] = []
        if not turns:
            return {"episodes_created": created}

        # Simple task-arc segmentation: a turn with a substantive user request
        # opens an arc; following turns merge into it until the next request.
        arcs: List[Dict[str, Any]] = []
        current = None
        for t in turns:
            req = (t["user_content"] or "").strip()
            is_request = len(req) > 12 and not req.startswith(("/", "!", "?"))
            if is_request and (current is None or current["turns"]):
                if current is not None:
                    arcs.append(current)
                current = {"turns": [], "request": req[:300],
                           "tools": [], "outcomes": [],
                           "signals": []}
            if current is None:
                current = {"turns": [], "request": req[:300],
                           "tools": [], "outcomes": [], "signals": []}
            current["turns"].append(t)
            current["tools"].extend(_db.jload(t["tools_used"], []) or [])
            if t["outcome"] != "unknown":
                current["outcomes"].append(t["outcome"])
            current["signals"].extend(_db.jload(t["importance_signals"], []) or [])
        if current is not None:
            arcs.append(current)

        for arc in arcs:
            if not arc["turns"]:
                continue
            signals = list(dict.fromkeys(arc["signals"]))[:8]
            importance = self.attention.base_importance(
                signals, user_attention=bool(arc["request"]))
            tier = self.attention.tier(importance)
            if tier == "low" and not signals:
                continue  # discard -> brief metadata only (§7)
            outcome = self._mode_outcome(arc["outcomes"])
            final = arc["turns"][-1]
            created.append(self.remember_episode(
                context=f"session {session_id}: {arc['request'][:140]}",
                user_request=arc["request"],
                actions_taken=final["assistant_content"][:500],
                tools_used=", ".join(dict.fromkeys(arc["tools"]))[:300],
                outcome=outcome, importance=importance,
                source_refs=[f"session:{session_id}"],
                embed=True,
            ).get("episode_id", ""))

        # mark staged turns processed
        def _mark(conn) -> None:
            conn.execute(
                "UPDATE turn_staging SET processed = 1 WHERE session_id = ? AND processed = 0",
                (session_id,),
            )

        self.db._run(_mark, write=True)

        if created and self.cfg.get("consolidation", {}).get("on_session_end", True):
            self.consolidator.run(reason="session_end", session_id=session_id)
        return {"episodes_created": created}

    @staticmethod
    def _mode_outcome(outcomes: List[str]) -> str:
        if not outcomes:
            return "unknown"
        if "failure" in outcomes:
            return "failure"
        if outcomes.count("success") >= len(outcomes) / 2:
            return "success"
        if "mixed" in outcomes:
            return "mixed"
        return "unknown"

    # ------------------------------------------------------------ status

    def status(self) -> Dict[str, Any]:
        health = self.db.health()
        health["vectors"] = self.vectors.health()
        health["writes_enabled"] = self.writes_enabled
        health["session_id"] = self.session_id
        health["actor_id"] = self.actor_id
        health["policy"] = _policy.policy_summary()
        return health
