"""Hungry Hippa configuration.

Hungry Hippa is a standalone local-first package: it owns its own locations and
does not read another application's configuration. Resolved in this order
(highest wins):

  1. Environment overrides: ``HUNGRY_HIPPA_DB`` (path) and the deprecated
     ``LIVING_CORTEX_DB`` (path only; warns).
  2. Optional sidecar ``$XDG_CONFIG_HOME/hungry-hippa/config.json``.
  3. Built-in defaults below.

Locations:

  * database: ``$XDG_DATA_HOME/hungry-hippa/hungry_hippa.db``
    (``~/.local/share/hungry-hippa/`` when ``XDG_DATA_HOME`` is unset)
  * state (owner token): ``$XDG_STATE_HOME/hungry-hippa/owner.token``

A database written by the former Hermes-hosted plugin is still *found* — read
only, never written — so memories are not stranded; see ``legacy_db_paths()``.

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
    "db_path": "",                 # empty -> $XDG_DATA_HOME/hungry-hippa/hungry_hippa.db
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
        "agent_inference": 0.45,
        "hermes_inference": 0.45,   # legacy name for agent_inference (old rows)
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
        "embedding_backend": "openai-compat",  # openai-compat | ollama
        "embedding_model": "text-embedding-nomic-embed-text-v1.5",
        "embed_url": "http://127.0.0.1:1234/v1",  # OpenAI-compat base (LM Studio)
        "embed_api_key": "lm-studio",            # Bearer token; empty disables header
        "ollama_url": "http://127.0.0.1:11434",  # used when backend is ollama
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
        # bounded work per run: consolidation is O(rows scanned), so the scan is
        # capped rather than the runtime racing a growing database
        "max_beliefs_scan": 500,
        "max_episodes_scan": 500,
    },
    # --- procedural learning (§12) ---
    "procedural": {
        "skill_promotion_requires_user": True,  # never auto-write host skills
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
    # --- operator snapshots (§ box / unattended hosts) ---
    "backup": {
        "dir": "",                  # empty -> $XDG_DATA_HOME/hungry-hippa/backups
        "keep": 7,                  # snapshots to retain; 0 disables rotation
    },
    # --- provider behavior ---
    "provider": {
        "auto_episode_on_session_end": True,
        "prefetch_enabled": True,
        "mirror_builtin_memory_writes": True,
        "staging_max_turns": 200,
    },
    # --- ingest extraction (local LM Studio only; never Grok/Nous) ---
    "ingest_extract": {
        "chat_url": "http://127.0.0.1:1234/v1",
        "chat_model": "qwen/qwen3.8-27b",
        "api_key": "lm-studio",
        "timeout_s": 90,
        "max_tokens": 2048,
        "batch_turns": 4,
        "batch_chars": 2400,
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
    """Load Hungry Hippa config: env > optional XDG sidecar > defaults."""
    cfg: Dict[str, Any] = _deep_merge(DEFAULTS, {})
    try:  # optional local sidecar: $XDG_CONFIG_HOME/hungry-hippa/config.json
        import json

        sidecar = config_dir() / "config.json"
        if sidecar.exists():
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


APP_DIR_NAME = "hungry-hippa"


def data_dir() -> Path:
    """``$XDG_DATA_HOME/hungry-hippa`` (``~/.local/share/hungry-hippa``)."""
    base = os.environ.get("XDG_DATA_HOME", "").strip()
    root = Path(base) if base else Path(os.path.expanduser("~")) / ".local" / "share"
    return root / APP_DIR_NAME


def config_dir() -> Path:
    """``$XDG_CONFIG_HOME/hungry-hippa`` (``~/.config/hungry-hippa``)."""
    base = os.environ.get("XDG_CONFIG_HOME", "").strip()
    root = Path(base) if base else Path(os.path.expanduser("~")) / ".config"
    return root / APP_DIR_NAME


def legacy_db_paths() -> List[str]:
    """Databases written by earlier releases, checked only for *migration*.

    Hungry Hippa is a local-first package and owns its own XDG locations; these
    paths exist so a database written by the former Hermes-hosted plugin is still
    found rather than orphaned. They are never written to.
    """
    home = Path(os.path.expanduser("~"))
    return [str(home / ".hermes" / "living_cortex.db"),
            str(home / ".hermes" / "hungry_hippa.db")]


def discover_default_db_path(home: Union[str, Path] = "") -> str:
    """Resolve where the database lives.

    Order: an existing XDG database, then a legacy database found only for
    migration, then the XDG location to create. ``home`` is accepted for
    backwards compatibility with callers that passed a directory explicitly.
    """
    if home:
        home_path = Path(home)
        candidates = [home_path / "hungry_hippa.db", home_path / "living_cortex.db"]
        for candidate in candidates:
            if candidate.exists():
                return str(candidate)
        return str(home_path / "hungry_hippa.db")
    current = data_dir() / "hungry_hippa.db"
    if current.exists():
        return str(current)
    for legacy in legacy_db_paths():
        if Path(legacy).exists():
            return legacy
    return str(current)


def resolve_db_path(cfg: Dict[str, Any]) -> str:
    """Resolve the SQLite database path from config."""
    if cfg.get("db_path"):
        return str(cfg["db_path"])
    return discover_default_db_path()


def get(cfg: Dict[str, Any], dotted: str, default: Any = None) -> Any:
    """Read a dotted key from the config dict."""
    node: Any = cfg
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node
