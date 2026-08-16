"""Living Cortex — MemoryProvider plugin for Hermes.

Implements the agent.memory_provider.MemoryProvider ABC so the Cortex joins
the normal cognitive loop:

  prefetch(query)          — automatic recall, injected before each turn
                             (<memory-context> block). Test 10.
  sync_turn(user, asst)    — per-turn staging (post-turn episodic writing)
  on_session_end(messages) — attention-gated episode assembly + consolidation
  on_session_switch(...)   — session rotation handling
  on_delegation(task,res)  — subagent observation episodes
  on_memory_write(...)     — mirror built-in memory writes with provenance
  get_tool_schemas()       — the `cortex` tool
  recall_status()          — deterministic "⟡ recalled N" indicator

All writes are skipped for non-primary agent contexts (subagents, cron
system prompts) so user representations are never corrupted.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from typing import Any, Dict, List, Optional

from .config import load_config, resolve_db_path
from .controller import MemoryController
from .neural import NeuralMemoryInterface
from .observability import Observability
from .tools import CORTEX_SCHEMA, handle as _handle_tool
from .vision import VisualEventMemory

logger = logging.getLogger("living_cortex")

TRIVIAL_RE = re.compile(
    r'^(yes|no|ok|okay|sure|thanks|thank you|y|n|yep|nope|yeah|nah|'
    r'hi|hey|hello|yo|sup|continue|go ahead|do it|proceed|got it|cool|'
    r'nice|great|done|next|lgtm|k)[\s!?.:;,~]*$', re.IGNORECASE)


def _is_trivial(text: Optional[str]) -> bool:
    if not text:
        return True
    stripped = text.strip()
    if not stripped or stripped.startswith("/"):
        return True
    try:
        from agent.memory_provider import is_trivial_prompt
        return bool(is_trivial_prompt(text))
    except Exception:
        return bool(TRIVIAL_RE.match(stripped))


class LivingCortexProvider:
    """MemoryProvider-compatible plugin class.

    Kept duck-typed (not hard-subclassed) so the plugin loads even if the
    host's ABC changes shape; the loader's register() pattern is the contract.
    """

    name = "living-cortex"
    glyph = "⟡"

    def __init__(self):
        self._ctrl: Optional[MemoryController] = None
        self._observability: Optional[Observability] = None
        self._vision: Optional[VisualEventMemory] = None
        self._neural = NeuralMemoryInterface()
        self._cfg: Dict[str, Any] = load_config()
        self._last_status = None
        self._prefetch_enabled = True
        self._mirror = True
        self._auto_episode = True
        self._lock = threading.Lock()
        self._db_path = ""
        self._init_error = ""

    # ------------------------------------------------------- availability

    def is_available(self) -> bool:
        try:
            cfg = self._cfg
            path = resolve_db_path(cfg)
            ctrl = MemoryController(cfg, db_path=path)
            ctrl.status()
            self._db_path = path
            return True
        except Exception as e:
            self._init_error = str(e)[:300]
            return False

    def unavailable_reason(self) -> str:
        return self._init_error or "could not open the Cortex database"

    # --------------------------------------------------------- lifecycle

    def initialize(self, session_id: str, **kwargs: Any) -> None:
        cfg = self._cfg
        path = kwargs.get("db_path") or resolve_db_path(cfg)
        self._ctrl = MemoryController(cfg, db_path=path)
        self._db_path = path
        platform = str(kwargs.get("platform", "cli"))
        agent_context = str(kwargs.get("agent_context", "primary"))
        parent = str(kwargs.get("parent_session_id", "") or "")
        self._ctrl.bind_session(session_id=session_id, platform=platform,
                                agent_context=agent_context,
                                parent_session_id=parent)
        self._observability = Observability(self._ctrl.db, cfg, controller=self._ctrl)
        self._vision = VisualEventMemory(self._ctrl.db, cfg, controller=self._ctrl)
        prov = cfg.get("provider", {})
        self._prefetch_enabled = bool(prov.get("prefetch_enabled", True))
        self._mirror = bool(prov.get("mirror_builtin_memory_writes", True))
        self._auto_episode = bool(prov.get("auto_episode_on_session_end", True))
        logger.info("living-cortex initialized session=%s db=%s context=%s",
                    session_id, path, agent_context)

    def shutdown(self) -> None:
        pass  # SQLite connections are per-call; nothing to close

    # --------------------------------------------------------- system prompt

    def system_prompt_block(self) -> str:
        return (
            "Living Cortex persistent memory (⟡) is active. Before answering "
            "questions about past work, projects, people, devices, or prior "
            "decisions, call the `cortex` tool with action=recall. After "
            "significant events (problems found, decisions, outcomes, things "
            "that worked or failed), call `cortex` with action=remember_episode "
            "or action=add_belief (with source_class). Use action=why to trace "
            "a belief to its evidence before asserting it as fact. Keep "
            "inferred facts as hypothesis with low confidence until reinforced."
        )

    # ------------------------------------------------------------- recall

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        if not self._prefetch_enabled or self._ctrl is None:
            return ""
        if not self._ctrl.writes_enabled or self._ctrl.agent_context != "primary":
            return ""
        if _is_trivial(query):
            return ""
        try:
            out = self._ctrl.recall(query)
            context = out.get("context", "")
            count = out.get("count", 0)
            self._last_status = {"provider_label": self.name, "count": count,
                                 "glyph": self.glyph}
            return context
        except Exception as e:
            logger.debug("prefetch recall failed: %s", e)
            return ""

    def recall_status(self):
        status = self._last_status
        if not status:
            return None
        try:
            from agent.memory_provider import RecallStatus
            return RecallStatus(**status)
        except Exception:
            from types import SimpleNamespace
            return SimpleNamespace(**status)

    # ----------------------------------------------------------- per-turn

    def on_turn_start(self, turn_number: int, message: str, **kwargs: Any) -> None:
        pass

    def sync_turn(self, user_content: str, assistant_content: str, *,
                  session_id: str = "", messages: Optional[List[Dict[str, Any]]] = None,
                  **kwargs: Any) -> None:
        """Post-turn episodic writing: stage the turn (cheap, local)."""
        c = self._ctrl
        if c is None or not c.writes_enabled:
            return
        if _is_trivial(user_content):
            return
        tools_used: List[str] = []
        signals: List[str] = []
        for m in (messages or [])[-12:]:
            role = m.get("role", "")
            if role == "assistant":
                for tc in m.get("tool_calls", []) or []:
                    fn = (tc.get("function") or {}).get("name", "")
                    if fn and fn not in tools_used:
                        tools_used.append(fn)
            elif role == "tool":
                content = str(m.get("content", ""))[:500]
                low = content.lower()
                if any(w in low for w in ("error", "exception", "traceback",
                                          "failed", "failure", "denied")):
                    if "problem_discovered" not in signals:
                        signals.append("problem_discovered")
        if tools_used:
            signals.append("physical_action")
        outcome = "unknown"
        c.stage_turn(len(tools_used) and 1 or 0, user_content, assistant_content,
                     tools_used, outcome=outcome, importance_signals=signals)

    # ----------------------------------------------------------- session

    def on_session_end(self, messages: List[Dict[str, Any]]) -> None:
        c = self._ctrl
        if c is None or not self._auto_episode:
            return
        try:
            c.close_session()
        except Exception as e:
            logger.debug("close_session failed: %s", e)

    def on_session_switch(self, new_session_id: str, *,
                          parent_session_id: str = "", reset: bool = False,
                          rewound: bool = False, **kwargs: Any) -> None:
        c = self._ctrl
        if c is None:
            return
        old = c.session_id
        if reset and old and old != new_session_id:
            try:
                c.close_session(old)
            except Exception:
                pass
        c.bind_session(session_id=new_session_id, platform=c.platform,
                       agent_context=c.agent_context,
                       parent_session_id=parent_session_id)

    def on_pre_compress(self, messages: List[Dict[str, Any]]) -> str:
        """Capture insights from messages about to be compressed."""
        c = self._ctrl
        if c is None or not c.writes_enabled:
            return ""
        try:
            parts = []
            for m in messages:
                if m.get("role") == "user" and len(str(m.get("content", ""))) > 40:
                    parts.append(f"user: {str(m['content'])[:300]}")
            if not parts:
                return ""
            ev = c.db.add_evidence(
                "context-compression capture:\n" + "\n".join(parts[-8:]),
                kind="hermes_inference",
                source_ref=f"compress:{c.session_id}", session_id=c.session_id)
            return f"cortex evidence {ev}: prior user requests preserved"
        except Exception:
            return ""

    # --------------------------------------------------------- delegation

    def on_delegation(self, task: str, result: str, *,
                      child_session_id: str = "", **kwargs: Any) -> None:
        c = self._ctrl
        if c is None or not c.writes_enabled:
            return
        try:
            c.remember_episode(
                context=f"delegated subtask: {task[:160]}",
                user_request=task[:300],
                actions_taken="subagent executed",
                result=result[:600],
                outcome="unknown",
                importance_signals=["physical_action"],
                source_refs=[f"child_session:{child_session_id}"],
                embed=False,
            )
        except Exception as e:
            logger.debug("on_delegation failed: %s", e)

    # ---------------------------------------------------- builtin mirror

    def on_memory_write(self, action: str, target: str, content: str,
                        metadata: Optional[Dict[str, Any]] = None) -> None:
        """Mirror built-in memory writes into the Cortex with provenance."""
        c = self._ctrl
        if c is None or not c.writes_enabled or not self._mirror:
            return
        try:
            src = "user_explicit" if target == "user" else "hermes_inference"
            if action == "remove":
                for b in c.semantic.list_beliefs(status="active", limit=100):
                    if b["claim"].strip() == content.strip():
                        c.semantic.supersede(
                            b["belief_id"], b["claim"],
                            reason="removed from builtin memory",
                            keep_confidence=0.2,
                            source_class="hermes_inference",
                            session_id=c.session_id)
                return
            # dedupe: reinforce an identical active belief instead of duplicating
            for b in c.semantic.list_beliefs(status="active", limit=200):
                if b["claim"].strip() == content.strip():
                    c.semantic.reinforce(b["belief_id"], 0.05, c.session_id)
                    return
            ev = c.add_evidence(content, kind=src,
                                source_ref=f"builtin-{target}-memory")
            c.semantic.add_belief(
                content, kind="fact",
                confidence=c.semantic.default_confidence(src),
                importance=0.7, source_class=src,
                source_ref=f"builtin-{target}-memory",
                evidence_ids=[ev] if ev else [],
                session_id=c.session_id)
        except Exception as e:
            logger.debug("on_memory_write mirror failed: %s", e)

    # ------------------------------------------------------------- tools

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        if self._ctrl is None or not self._ctrl.writes_enabled:
            return []
        return [CORTEX_SCHEMA]

    def handle_tool_call(self, tool_name: str, args: Dict[str, Any], **kwargs: Any) -> str:
        if tool_name != "cortex" or self._ctrl is None:
            return json.dumps({"error": f"unhandled tool {tool_name}"})
        return _handle_tool(self._ctrl, self._observability,
                            args.get("action", ""), args or {})

    # ------------------------------------------------------------ config

    def get_config_schema(self) -> List[Dict[str, Any]]:
        return [
            {"key": "db_path", "description": "SQLite database path (default: $HERMES_HOME/living_cortex.db)",
             "type": "text", "required": False, "default": ""},
            {"key": "privacy.vision_memory_enabled",
             "description": "Store structured visual-episode memory (glasses events)", "type": "boolean", "default": False},
            {"key": "privacy.audio_memory_enabled",
             "description": "Store structured audio-episode memory", "type": "boolean", "default": False},
            {"key": "retrieval.vectors_enabled",
             "description": "Use local Ollama embeddings for semantic recall", "type": "boolean", "default": True},
            {"key": "retrieval.embedding_model",
             "description": "Ollama embedding model name", "type": "text", "default": "nomic-embed-text"},
            {"key": "consolidation.cron_schedule",
             "description": "Daily consolidation schedule (cron)", "type": "text", "default": "0 4 * * *"},
        ]

    def save_config(self, values: Dict[str, Any], hermes_home: str) -> None:
        """Persist non-secret config to a sidecar JSON (never hand-edit config.yaml)."""
        sidecar = os.path.join(hermes_home, "living_cortex_config.json")
        merged = dict(values)
        try:
            if os.path.exists(sidecar):
                with open(sidecar, "r", encoding="utf-8") as f:
                    merged = {**json.load(f), **merged}
            with open(sidecar, "w", encoding="utf-8") as f:
                json.dump(merged, f, indent=2)
        except Exception as e:
            logger.warning("save_config failed: %s", e)

    def backup_paths(self) -> List[str]:
        return []


# ---------------------------------------------------------------- register

def register(ctx) -> None:
    provider = LivingCortexProvider()
    ctx.register_memory_provider(provider)
