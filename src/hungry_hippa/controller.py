"""Memory controller (§14) — the central abstraction.

Capabilities (spec §14): remember_episode, recall, relate, retrieve_graph,
retrieve_similar, update_belief, add_evidence, contradict, supersede,
consolidate, reinforce, archive, forget, create_procedure — plus the
transparent-heuristic decisions (importance tiering, staging, session closure)
that a learned policy can later replace through the same interface.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from . import db as _db
from . import limits as _limits
from . import policy as _policy
from . import trust as _trust
from .attention import AttentionScorer
from .consolidation import Consolidator
from .episodic import EpisodicMemory
from .forgetting import ForgettingPolicy
from .graph import KnowledgeGraph
from .manager import LocalManager
from .procedural import ProceduralMemory
from .retrieval import RetrievalRouter
from .semantic import SemanticMemory
from .semantic import protection_reason as _protection_reason
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
        # Identity/provenance come from the channel (see trust.py), never from a
        # request field. An unbound controller is in-process code, i.e. the
        # operator's own, so it starts as owner/user.
        self.identity = _trust.OWNER
        self.provenance = _trust.PROVENANCE_USER
        self.channel = _trust.CHANNEL_LOCAL
        self._binding_explicit = False
        self.writes_enabled = True
        # Manager: optional local LLM intent proposer. Not authoritative —
        # Hungry Hippa validates and executes all actions.
        self.manager = LocalManager(config)

    def _resolve_db(self) -> str:
        from .config import resolve_db_path

        return resolve_db_path(self.cfg)

    # ------------------------------------------------------------- lifecycle

    def bind_session(self, session_id: str = "", platform: str = "",
                     agent_context: str = "primary",
                     parent_session_id: str = "",
                     actor_id: str = "",
                     trust: Any = None) -> None:
        """Bind a session, and with it the caller's identity and provenance.

        ``trust`` is a :class:`trust.Binding` resolved by the *server* for the
        channel the call arrived on. When it is omitted the binding is derived
        once, from the channel: an MCP platform is untrusted (the MCP server
        always passes an explicit binding anyway), anything in-process is the
        operator's own code. A later rebind that carries no binding keeps the
        existing one, so a session switch cannot silently change trust.
        """
        self.session_id = session_id
        self.platform = platform
        self.agent_context = agent_context or "primary"
        if trust is not None:
            self.identity = _trust.normalize_identity(getattr(trust, "identity", None))
            self.provenance = _trust.normalize_provenance(
                getattr(trust, "provenance", None))
            self.channel = str(getattr(trust, "channel", "") or _trust.CHANNEL_LOCAL)
            self.actor_id = _policy.normalize_actor(
                getattr(trust, "actor_id", "") or actor_id or self.agent_context)
            self._binding_explicit = True
        elif not self._binding_explicit:
            if str(platform or "").strip().lower() == _trust.CHANNEL_MCP:
                self.identity = _trust.UNTRUSTED
                self.provenance = _trust.PROVENANCE_EXTERNAL
                self.channel = _trust.CHANNEL_MCP
            else:
                self.identity = _trust.OWNER
                self.provenance = _trust.PROVENANCE_USER
                self.channel = _trust.CHANNEL_LOCAL
            self.actor_id = _policy.normalize_actor(actor_id or self.agent_context)
            if (self.identity != _trust.OWNER
                    and self.actor_id in _policy.OWNER_ACTORS):
                self.actor_id = _policy.UNTRUSTED_ACTOR
        elif actor_id:
            self.actor_id = _policy.normalize_actor(actor_id)
        self.writes_enabled = (
            self.agent_context == "primary" and not parent_session_id
        )

    @property
    def is_owner(self) -> bool:
        """Owner identity, decided by the channel — not by the actor label."""
        return _policy.is_owner_identity(self.identity)

    def binding(self) -> Dict[str, Any]:
        return {"actor_id": self.actor_id, "identity": self.identity,
                "provenance": self.provenance, "channel": self.channel}
    # ------------------------------------------------------------- §14 API

    def remember_episode(self, *, embed: bool = True, **fields: Any) -> Dict[str, Any]:
        """Create an episode (attention-gated by the caller via importance).

        Actor policy: writes from a non-owner actor are stored quarantined so
        an untrusted caller cannot inject a memory into normal recall.
        """
        if not self.writes_enabled:
            return {"error": "writes disabled for this agent context"}
        allowed, quota = _limits.check_write_quota(self.db, self.actor_id)
        if not allowed:
            self.db.log_mutation("write_quota_exceeded", "episode", "",
                                 f"actor={self.actor_id} used={quota['used']} "
                                 f"limit={quota['limit']}", self.session_id)
            return {"error": "write quota exceeded for this actor this hour",
                    "quota": quota}
        importance = fields.pop("importance", None)
        signals = fields.pop("importance_signals", None)
        if importance is None:
            scored = self.attention.score_episode_fields(fields)
            importance = scored["importance"]
            signals = scored["signals"]
        fields["importance"] = importance
        # actor_id is forwarded; quarantine is decided by the write layer
        # (episodic/semantic) so every path obeys the same rule. The *identity*
        # travels with the call: a caller cannot lift quarantine by naming
        # itself "primary".
        fields["actor_id"] = _policy.normalize_actor(
            fields.get("actor_id") or self.actor_id)
        fields["identity"] = self.identity
        fields["provenance"] = self.provenance
        fields["channel"] = self.channel
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

        Manager integration: the manager proposes intent (non-binding). Hungry
        Hippa validates and executes. If the manager is unavailable, recall
        continues normally.
        """
        actor = _policy.normalize_actor(actor_id or self.actor_id)
        if include_quarantined and not self.is_owner:
            include_quarantined = False

        # --- Manager intent proposal (non-authoritative) ---
        manager_intent = None
        try:
            if self.manager.is_configured:
                manager_intent = self.manager.propose_intent(
                    query, conversation_history=[])
                # Validate: only allow known actions, never let the model
                # override the actual HH operation.
                if manager_intent.action not in LocalManager.ALLOWED_ACTIONS:
                    manager_intent.action = "no_op"
        except Exception as e:
            # Manager failure must not break recall
            manager_intent = None

        # --- Deterministic HH recall (always runs) ---
        out = self.retrieval.recall(query, project=project, limit=limit,
                                    session_id=self.session_id, actor_id=actor,
                                    explain=explain,
                                    include_quarantined=include_quarantined,
                                    max_context_chars=max_context_chars,
                                    identity=self.identity)

        def _log(conn) -> None:
            conn.execute(
                "INSERT INTO retrieval_log(ts, query, recalled, session_id) VALUES (?,?,?,?)",
                (_db.now_iso(), _limits.redact(query)[:500],
                 _db.jdump([it.get("episode_id") or it.get("belief_id") or it.get("rel_id")
                            for it in out.get("items", [])]),
                 self.session_id),
            )

        self.db._run(_log, write=True)

        # Include manager's proposal in response metadata (observability only)
        if manager_intent is not None:
            out["manager_intent"] = {
                "action": manager_intent.action,
                "reason": manager_intent.reason[:200],
                "confidence": manager_intent.confidence,
                "needs_escalation": manager_intent.needs_escalation,
            }

        return out

    def propose_intent(self, user_message: str,
                       conversation_history: Optional[List[Dict]] = None) -> Dict[str, Any]:
        """Get a validated manager intent proposal.

        The manager proposes intent; Hungry Hippa validates. This is the
        deterministic validation boundary — the model output is never trusted
        directly.

        Returns: {action, reason, parameters, confidence, needs_escalation,
                  valid: bool}
        """
        intent = self.manager.propose_intent(user_message, conversation_history)
        # Validate against allowed actions (already done in propose_intent,
        # but defense-in-depth here at the controller boundary)
        valid = intent.action in LocalManager.ALLOWED_ACTIONS
        if not valid and intent.action != "no_op":
            intent.action = "no_op"
            intent.reason = f"disallowed action rejected: {intent.reason}"
        return {
            "action": intent.action,
            "reason": intent.reason,
            "parameters": intent.parameters,
            "confidence": intent.confidence,
            "needs_escalation": intent.needs_escalation,
            "valid": valid,
        }

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
                actor_id=self.actor_id, identity=self.identity,
                provenance=self.provenance, channel=self.channel,
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

    def add_evidence(self, content: str, kind: str = "agent_inference",
                     source_ref: str = "") -> str:
        return self.db.add_evidence(content, kind, source_ref, self.session_id)

    def contradict(self, belief_id: str, counter_claim: str, **kwargs: Any) -> Dict[str, Any]:
        # The calling channel's provenance always travels with the write; a
        # caller may not override it through kwargs.
        kwargs.setdefault("identity", self.identity)
        kwargs.setdefault("provenance", self.provenance)
        kwargs.setdefault("channel", self.channel)
        kwargs.setdefault("actor_id", self.actor_id)
        return self.semantic.contradict(belief_id, counter_claim,
                                        session_id=self.session_id, **kwargs)

    def supersede(self, belief_id: str, replacement_claim: str, **kwargs: Any) -> Dict[str, Any]:
        kwargs.setdefault("identity", self.identity)
        kwargs.setdefault("provenance", self.provenance)
        kwargs.setdefault("channel", self.channel)
        kwargs.setdefault("actor_id", self.actor_id)
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
        allowed, _reason = self._may_forget(kind, target_id)
        if not allowed:
            return False
        return self.forgetting.archive(kind, target_id, reason, self.session_id)

    def _may_forget(self, kind: str, target_id: str) -> Tuple[bool, str]:
        """Per-record authorization for archival/forget.

        Forget is a write to *another actor's* memory if the caller cannot read
        that record, so the read policy is applied first: an actor may archive
        only a row it is allowed to read (its own unclassified rows, its own
        quarantined rows, or anything when it is the owner). This closes the
        hole where an untrusted caller could remove a private row from recall
        without ever being able to read it.
        """
        if kind == "episode":
            row = self.episodic.get_episode(target_id)
        elif kind == "belief":
            row = self.semantic.get_belief(target_id)
        else:
            return False, f"forget unsupported for {kind}"
        if not row:
            return False, f"{kind} {target_id} not found"
        allowed, reason = _policy.may_read(row, self.actor_id,
                                           include_quarantined=True,
                                           identity=self.identity)
        if not allowed:
            return False, reason
        # Reversible or not, forgetting takes a memory out of recall, so a
        # protected row needs the operator channel (capability ladder).
        protected = _protection_reason(row) if kind == "belief" else ""
        if not _policy.may_capability(_policy.CAP_FORGET,
                                      provenance=self.provenance,
                                      identity=self.identity,
                                      protected=bool(protected)):
            return False, (f"protected:{protected}" if protected
                           else "capability denied for this channel")
        return True, ""

    def forget(self, kind: str, target_id: str, *, mode: str = "archival",
               reason: str = "") -> Dict[str, Any]:
        """forget() — memory-management operation, never silent deletion.

        ``purge`` (irreversible delete) is owner-only; untrusted actors get
        archival at most. Over MCP, purge is denied unless explicitly
        confirmed by an owner (see mcp_server.py). Archival is also
        authorized per record: an actor may archive only what it may read.
        """
        if mode == "purge":
            # Purge needs owner identity AND an operator channel: a model tool
            # call is not an operator decision (capability ladder, policy.py).
            if not (_policy.may_purge(self.actor_id, self.identity)
                    and _policy.may_capability(_policy.CAP_PURGE,
                                               provenance=self.provenance,
                                               identity=self.identity)):
                self.db.log_mutation("purge_denied", kind, target_id,
                                     f"actor={self.actor_id} provenance={self.provenance}",
                                     self.session_id)
                return {"error": "purge denied for this actor",
                        "actor_id": self.actor_id, "target": target_id}
            if kind == "episode":
                ok = self.episodic.purge(target_id, self.session_id)
            elif kind == "belief":
                ok = self.semantic.remove_belief(target_id, self.session_id)
            else:
                return {"error": f"purge unsupported for {kind}"}
            return {"purged": bool(ok), "target": target_id}
        allowed, why = self._may_forget(kind, target_id)
        if not allowed:
            self.db.log_mutation("forget_denied", kind, target_id,
                                 f"actor={self.actor_id} reason={why}",
                                 self.session_id)
            return {"error": "forget denied for this actor",
                    "actor_id": self.actor_id, "target": target_id,
                    "reason": why}
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
