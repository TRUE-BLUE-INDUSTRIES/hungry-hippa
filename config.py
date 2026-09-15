"""Hungry Hippa (formerly Living Cortex) configuration.

Resolved in this order (highest wins):
  1. config.yaml ``plugins.living-cortex`` section (read via hermes cfg_get when
     running inside Hermes; silently unavailable in standalone use).
  2. Environment override ``HUNGRY_HIPPA_DB`` (path only).
  3. Deprecated environment override ``LIVING_CORTEX_DB`` (path only; warns).
  4. Built-in defaults below.

New installs default to ``hungry_hippa.db``. An existing ``living_cortex.db``
in the same home directory is still discovered so memories are not stranded.

Privacy defaults are conservative (§20): vision/audio episode storage OFF,
raw media retention minimal, location/face identity memory OFF, no automatic
purge of structured memory.
"""

from __future__ import annotations

import os
import warnings
from pathlib import Path
from typing import Any, Dict, Union

DEFAULTS: Dict[str, Any] = {
    # --- storage ---
    "db_path": "",                 # empty -> $HERMES_HOME/living_cortex.db (or ./living_cortex.db standalone)
    "schema_version": 1,
    # --- attention / importance (§6) ---
    "attention": {
        "novel_object": 20,
        "user_asked": 30,
        "problem_discovered": 25,
        "decision_made": 20,
        "physical_action": 20,
        "unexpected_result": 35,
        "project_relevance": 25,
        "background_repeated": -30,
        "irrelevant_environmental": -40,
        "duplicate_observation": -30,
        "base_importance": 0.35,
        "high_threshold": 0.70,     # -> graph + semantic consolidation
        "medium_threshold": 0.35,   # -> episodic storage
        # below medium_threshold -> metadata-only (brief) storage
    },
    # --- provenance / confidence (§8) ---
    "source_confidence": {
        "user_explicit": 0.95,
        "document": 0.85,
        "tool_result": 0.80,
        "visual_observation": 0.70,
        "audio_observation": 0.65,
        "external_source": 0.60,
        "hermes_inference": 0.45,
        "derived_pattern": 0.50,
        # assigned by the runtime when the writer is the model, not the user
        "agent_reported": 0.55,
    },
    # --- retrieval (§5) ---
    "retrieval": {
        "max_context_chars": 1500,
        "max_items": 6,
        "vector_top_k": 8,
        "graph_hop_limit": 2,
        "recency_half_life_days": 45,
        "embedding_model": "nomic-embed-text",
        "ollama_url": "http://127.0.0.1:11434",
        "vectors_enabled": True,
        "embed_timeout_s": 10,
    },
    # --- contradiction (§9) ---
    "contradiction": {
        "confidence_gap_to_contradict": 0.20,
        "resolution": {
            "explicit_user_correction_wins": True,
            "newer_timestamp_wins": True,
            "direct_observation_beats_inference": True,
        },
    },
    # --- forgetting (§10) ---
    "forgetting": {
        "access_decay_enabled": True,
        "importance_decay_enabled": True,
        "compression_enabled": True,
        "auto_archival_after_unused_days": 0,   # 0 = disabled
        "auto_purge_structured": False,         # structured memory is never auto-deleted by default
        "raw_media_retention_days": 7,          # raw media only; structured summaries unaffected
    },
    # --- consolidation (§11) ---
    "consolidation": {
        "enabled": True,
        "on_session_end": True,
        "cron_schedule": "0 4 * * *",           # daily 04:00 local
        "procedural_min_episodes": 3,
        "procedural_min_success_ratio": 0.6,
        "procedural_promote_confidence": 0.85,
        "belief_min_confidence_for_knowledge": 0.70,
    },
    # --- procedural learning (§12) ---
    "procedural": {
        "skill_promotion_requires_user": True,  # never auto-write Hermes skills
        "validation_min_confidence": 0.80,
    },
    # --- privacy (§20) ---
    "privacy": {
        "vision_memory_enabled": False,
        "audio_memory_enabled": False,
        "raw_media_retention": False,
        "keyframe_retention": 3,
        "location_memory_enabled": False,
        "face_identity_memory_enabled": False,
        "automatic_episode_storage": True,      # structured summaries, not raw media
        "sensitive_context_exclusion": ["medical", "financial", "credentials"],
        "retention_period_days": 0,             # 0 = keep structured memory indefinitely
    },
    # --- provider behavior ---
    "provider": {
        "auto_episode_on_session_end": True,
        "prefetch_enabled": True,
        "mirror_builtin_memory_writes": True,
        "staging_max_turns": 200,
    },
}


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config() -> Dict[str, Any]:
    """Load plugin config: hermes config.yaml section > env > defaults."""
    cfg: Dict[str, Any] = _deep_merge(DEFAULTS, {})
    try:  # inside Hermes — read the plugins.living-cortex section
        from hermes_cli.config import cfg_get

        if cfg_get is not None:
            section = cfg_get(None, "plugins", "living-cortex")
            if isinstance(section, dict):
                cfg = _deep_merge(cfg, section)
    except Exception:
        pass
    try:  # sidecar written by save_config() (never hand-edit config.yaml)
        from hermes_constants import get_hermes_home

        home = get_hermes_home()
        for name in ("living_cortex_config.json", "hungry_hippa_config.json"):
            sidecar = home / name
            if sidecar.exists():
                import json

                with open(sidecar, "r", encoding="utf-8") as f:
                    cfg = _deep_merge(cfg, json.load(f) or {})
    except Exception:
        pass
    env_old = os.environ.get("LIVING_CORTEX_DB")
    if env_old:
        warnings.warn(
            "LIVING_CORTEX_DB is deprecated; use HUNGRY_HIPPA_DB. "
            "Hungry Hippa was formerly Living Cortex.",
            DeprecationWarning,
            stacklevel=2,
        )
        cfg["db_path"] = env_old
    env_db = os.environ.get("HUNGRY_HIPPA_DB")
    if env_db:
        cfg["db_path"] = env_db
    return cfg


def discover_default_db_path(home: Union[str, Path]) -> str:
    """Prefer an existing Living Cortex DB; otherwise use hungry_hippa.db."""
    home_path = Path(home)
    old = home_path / "living_cortex.db"
    new = home_path / "hungry_hippa.db"
    if old.exists() and not new.exists():
        return str(old)
    return str(new)


def resolve_db_path(cfg: Dict[str, Any]) -> str:
    """Resolve the SQLite database path from config."""
    if cfg.get("db_path"):
        return str(cfg["db_path"])
    try:
        from hermes_constants import get_hermes_home

        return discover_default_db_path(get_hermes_home())
    except Exception:
        return discover_default_db_path(os.getcwd())


def get(cfg: Dict[str, Any], dotted: str, default: Any = None) -> Any:
    """Read a dotted key from the config dict."""
    node: Any = cfg
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node
