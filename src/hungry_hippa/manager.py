"""Hippo-Pot local manager abstraction.

A replaceable small LLM responsible for lightweight interpretation/routing.
The manager proposes intent; Hungry Hippa validates and executes it.

Supported providers (anything OpenAI-compatible):
  - llama.cpp (server mode)
  - Ollama
  - LM Studio
  - vLLM
  - any OpenAI-compatible endpoint

The manager is optional. When not configured, Hungry Hippa operates in
degraded-manager mode: core memory functions work, the manager status shows
OFFLINE, and the system is otherwise healthy.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("hungry_hippa.manager")


@dataclass
class ManagerHealth:
    """Health state of the local manager."""
    configured: bool = False
    reachable: bool = False
    model: str = "not configured"
    endpoint: str = ""
    last_error: str = ""
    latency_ms: float = 0.0
    last_check: str = ""

    def status_label(self) -> str:
        if not self.configured:
            return "NOT CONFIGURED"
        if self.reachable:
            return "ONLINE"
        return "OFFLINE"

    def as_dict(self) -> Dict[str, Any]:
        return {
            "configured": self.configured,
            "reachable": self.reachable,
            "status": self.status_label(),
            "model": self.model,
            "endpoint": self.endpoint,
            "last_error": self.last_error,
            "latency_ms": round(self.latency_ms, 1),
            "last_check": self.last_check,
        }


@dataclass
class ManagerIntent:
    """A validated intent proposal from the manager model.

    This is NOT an authority — Hungry Hippa code validates the action
    against its own policy before execution.
    """
    action: str = ""          # recall, remember, relate, consolidate, etc.
    reason: str = ""          # model's reasoning (for logging)
    parameters: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    needs_escalation: bool = False  # route to stronger model?
    raw: str = ""             # raw model output (for debugging)


class LocalManager:
    """Thin client for a local OpenAI-compatible manager model.

    The manager performs lightweight reasoning:
    - classify intent
    - determine whether retrieval is required
    - choose an allowed HH operation
    - decide whether a request should be escalated

    The model does NOT own the database, schema, evidence, provenance,
    access control, or destructive operations.
    """

    # Actions the manager may propose. Anything else is rejected.
    ALLOWED_ACTIONS = frozenset({
        "recall", "remember_episode", "remember_belief",
        "relate", "consolidate", "no_op", "escalate",
    })

    def __init__(self, config: Dict[str, Any]):
        mgr_cfg = config.get("manager", {})
        self.enabled = bool(mgr_cfg.get("enabled", False))
        self.provider = mgr_cfg.get("provider", "openai-compatible")
        self.endpoint = mgr_cfg.get("endpoint", "http://127.0.0.1:8080/v1").rstrip("/")
        self.model = mgr_cfg.get("model", "local-manager")
        self.temperature = float(mgr_cfg.get("temperature", 0.1))
        self.context_window = int(mgr_cfg.get("context_window", 8192))
        self.timeout = float(mgr_cfg.get("timeout", 10))
        self.api_key = os.environ.get("HUNGRY_HIPPA_MANAGER_API_KEY", "none")
        self._health = ManagerHealth()

    @property
    def is_configured(self) -> bool:
        return self.enabled and bool(self.endpoint) and bool(self.model)

    def health(self) -> ManagerHealth:
        """Check manager health by hitting the models endpoint."""
        if not self.is_configured:
            self._health.configured = False
            self._health.model = self.model or "not configured"
            self._health.endpoint = self.endpoint
            return self._health

        self._health.configured = True
        self._health.model = self.model
        self._health.endpoint = self.endpoint

        start = time.monotonic()
        try:
            req = urllib.request.Request(
                f"{self.endpoint}/models",
                headers={"Authorization": f"Bearer {self.api_key}"},
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            elapsed = (time.monotonic() - start) * 1000
            self._health.reachable = True
            self._health.latency_ms = elapsed
            self._health.last_error = ""
        except Exception as e:
            self._health.reachable = False
            self._health.last_error = str(e)[:200]
            self._health.latency_ms = 0.0
            logger.debug("manager health check failed: %s", e)

        from datetime import datetime, timezone
        self._health.last_check = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return self._health

    def propose_intent(self, user_message: str,
                       conversation_history: Optional[List[Dict]] = None) -> ManagerIntent:
        """Send a user message to the manager model and get an intent proposal.

        Returns ManagerIntent with action/parameters the model proposes.
        The caller (HH) validates and executes — the model has no direct write path.
        """
        intent = ManagerIntent()

        if not self.is_configured:
            intent.action = "no_op"
            intent.reason = "manager not configured"
            return intent

        history = conversation_history or []
        messages = self._build_messages(user_message, history)

        payload = json.dumps({
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": 512,
            "response_format": {"type": "json_object"},
        }).encode("utf-8")

        req = urllib.request.Request(
            f"{self.endpoint}/chat/completions",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            choice = data.get("choices", [{}])[0]
            content = choice.get("message", {}).get("content", "")
            intent.raw = content

            parsed = self._parse_intent(content)
            if parsed:
                intent.action = parsed.get("action", "no_op")
                intent.reason = parsed.get("reason", "")[:500]
                intent.parameters = parsed.get("parameters", {})
                intent.confidence = float(parsed.get("confidence", 0.0))
                intent.needs_escalation = bool(parsed.get("needs_escalation", False))
            else:
                intent.action = "no_op"
                intent.reason = "could not parse manager response"

        except Exception as e:
            intent.action = "no_op"
            intent.reason = f"manager error: {str(e)[:200]}"
            logger.warning("manager propose_intent failed: %s", e)

        # Safety: only allow known actions
        if intent.action not in self.ALLOWED_ACTIONS:
            intent.action = "no_op"
            intent.reason = f"disallowed action: {intent.action}"

        return intent

    def _build_messages(self, user_message: str,
                        history: List[Dict]) -> List[Dict[str, str]]:
        """Build the message list for the manager."""
        system = (
            "You are a lightweight memory router for Hungry Hippa. "
            "Your job is to classify the user's intent and propose a single action. "
            "You do NOT have authority to directly modify memory, evidence, or the database. "
            "You propose intent; Hungry Hippa validates and executes. "
            "Respond in JSON: {\"action\": <action>, \"reason\": <why>, "
            "\"parameters\": {...}, \"confidence\": <0-1>, \"needs_escalation\": <bool>}. "
            f"Allowed actions: {', '.join(sorted(self.ALLOWED_ACTIONS))}. "
            "If unsure, use 'no_op' or 'escalate'."
        )
        messages = [{"role": "system", "content": system}]
        # Include limited recent history for context
        for turn in history[-6:]:
            role = turn.get("role", "user")
            content = turn.get("content", "")[:1000]
            messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": user_message})
        return messages

    def _parse_intent(self, content: str) -> Optional[Dict[str, Any]]:
        """Parse a JSON intent from the model output."""
        if not content:
            return None
        try:
            # Handle markdown-fenced JSON
            text = content.strip()
            if text.startswith("```"):
                lines = text.split("\n")[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                text = "\n".join(lines)
            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return None

    def as_dict(self) -> Dict[str, Any]:
        """Configuration summary for status output."""
        return {
            "provider": self.provider,
            "endpoint": self.endpoint,
            "model": self.model,
            "temperature": self.temperature,
            "context_window": self.context_window,
            "enabled": self.enabled,
            "configured": self.is_configured,
        }