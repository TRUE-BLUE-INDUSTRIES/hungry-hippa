"""Visual episodic memory (§7, Phase 4) — event segmentation interface.

Continuous perception is NOT continuous recording. The Meta Fury pipeline
(the glasses -> phone -> host transport) calls into this module at attention
events; only structured summaries and selected keyframes are retained, and
everything is gated by the privacy config (§20).

Raw media is never copied into the DB — only paths/metadata, governed by
raw_media_retention / keyframe_retention policy.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from . import db as _db

EVENT_TRIGGERS = ("user_pointed", "user_asked", "new_object", "problem",
                  "task_begin", "result")


class VisualEventMemory:
    def __init__(self, database: _db.Database, config: Dict, controller=None):
        self.db = database
        self.cfg = config
        self.privacy = config.get("privacy", {})
        self.ctrl = controller
        self._open: Dict[str, Dict[str, Any]] = {}

    # ------------------------------------------------------------ privacy

    def enabled(self, channel: str) -> bool:
        if channel == "vision":
            return bool(self.privacy.get("vision_memory_enabled", False))
        if channel == "audio":
            return bool(self.privacy.get("audio_memory_enabled", False))
        return False

    def _allowed_keyframes(self) -> int:
        return max(0, int(self.privacy.get("keyframe_retention", 3)))

    # ------------------------------------------------------------ events

    def open_episode(self, trigger: str, *, context: str = "",
                     session_id: str = "") -> Dict[str, Any]:
        """Open an attention-driven visual episode (§7 target flow)."""
        if trigger not in EVENT_TRIGGERS:
            return {"error": f"unknown trigger {trigger}"}
        if not (self.enabled("vision") or self.enabled("audio")):
            return {"error": "vision/audio memory disabled by privacy config"}
        eid = self.ctrl.session_id or session_id or _db.now_iso().replace(":", "")
        self._open[eid] = {
            "trigger": trigger, "context": context,
            "observations": [], "keyframes": [],
            "ts_start": _db.now_iso(),
        }
        return {"open": True, "handle": eid, "trigger": trigger}

    def observe(self, handle: str, text: str, *, keyframe_path: str = "",
                channel: str = "vision") -> Dict[str, Any]:
        """Record a structured observation + optional keyframe path."""
        ep = self._open.get(handle)
        if ep is None:
            return {"error": "no open episode"}
        if not self.enabled(channel):
            return {"error": f"{channel} memory disabled"}
        ep["observations"].append({"ts": _db.now_iso(), "channel": channel,
                                   "text": text[:1000]})
        if keyframe_path and len(ep["keyframes"]) < self._allowed_keyframes():
            if os.path.exists(keyframe_path):
                ep["keyframes"].append(keyframe_path)
        return {"observed": True, "observations": len(ep["observations"])}

    def close_episode(self, handle: str, *, outcome: str = "unknown",
                      result: str = "") -> Dict[str, Any]:
        """Close and store the episode through the attention gate (§7)."""
        ep = self._open.pop(handle, None)
        if ep is None:
            return {"error": "no open episode"}
        observations = ep["observations"]
        if not observations:
            return {"discarded": True, "reason": "no observations"}
        text = " ".join(o["text"] for o in observations)
        keyframes = ep["keyframes"]
        signals = []
        if ep["trigger"] == "problem":
            signals.append("problem_discovered")
        if ep["trigger"] == "user_asked":
            signals.append("user_asked")
        if ep["trigger"] == "new_object":
            signals.append("novel_object")
        if ep["trigger"] == "result":
            signals.append("unexpected_result")
        importance = self.ctrl.attention.base_importance(signals) if self.ctrl else 0.35
        tier = self.ctrl.attention.tier(importance) if self.ctrl else "medium"
        if tier == "low":
            return {"discarded": True, "reason": "low importance", "tier": tier}
        stored = {"discarded": False, "tier": tier}
        if self.ctrl:
            r = self.ctrl.remember_episode(
                context=f"[{ep['trigger']}] {ep['context']}"[:200],
                visual_entities=text[:800],
                audio_transcript=text[:800] if any(
                    o["channel"] == "audio" for o in observations) else "",
                outcome=outcome, result=result[:400],
                importance=importance,
                source_refs=[f"keyframe:{os.path.basename(k)}" for k in keyframes],
                embed=True,
            )
            stored["episode_id"] = r.get("episode_id", "")
        return stored
