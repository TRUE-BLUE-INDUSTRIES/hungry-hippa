"""Record the historical Living Cortex build session (2026-08-16).

The first real content in the store: the story of its own construction, with
provenance and evidence links. The episode text below is kept verbatim — it is a
record of that build, so it still says "Living Cortex" and still names the paths
and commands that existed then. Idempotent (skips if episodes exist).
"""

import sys
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent

try:                     # normal import: the package is installed
    import hungry_hippa  # noqa: F401
except ModuleNotFoundError:   # running from a clone: this checkout
    sys.path.insert(0, str(REPO_DIR / "src"))
    import hungry_hippa  # noqa: F401

from hungry_hippa.controller import MemoryController
from hungry_hippa.config import load_config

c = MemoryController(load_config())
c.bind_session(session_id="build-session", platform="cli")

# idempotence guard: skip if the build episodes already exist
existing = c.episodic.list_episodes(limit=100)
if any("Living Cortex" in (e.get("context") or "") for e in existing):
    print("build episodes already recorded — skipping")
    sys.exit(0)

# ---- evidence rows (immutable, hash-verified) ---------------------------
ev_test = c.add_evidence(
    "Acceptance tests: 10/10 passed twice (standalone and through the real "
    "hermes CLI), including T10 automatic recall. Vector path verified with "
    "local Ollama nomic-embed-text.",
    kind="tool_result", source_ref="hermes living-cortex selftest")
ev_backup = c.add_evidence(
    "Phase 0 backup: backups/living-cortex-phase0-20260816_090003/ "
    "(state.db snapshot via SQLite backup API, MEMORY.md, USER.md, config.yaml, SOUL.md).",
    kind="tool_result", source_ref="backup dir")
ev_commit = c.add_evidence(
    "Git commits: 2f4dc15 (v0.1 initial) and 43ffecb (FTS5 schema drift fix, "
    "migration v2 + self-healing reindex) in plugins/living-cortex.",
    kind="tool_result", source_ref="git log")

# ---- episodes -----------------------------------------------------------
e1 = c.remember_episode(
    context="Living Cortex Phase 0: inspected Hermes v0.20.0 installation, backed up all memory",
    user_request="Build the Hermes Living Cortex hybrid memory system from the spec",
    actions_taken="Recon of MemoryProvider ABC, plugin discovery, state.db schema, Ollama embeddings; consistent backup taken",
    decisions="Ship as user memory-provider plugin; SQLite+FTS5+local vectors; no external services",
    result="INSPECTION.md + full backup at backups/living-cortex-phase0-20260816_090003",
    outcome="success",
    importance_signals=["decision_made", "physical_action", "project_relevance"],
    project="Living Cortex", evidence_ids=[ev_backup], embed=True)
e2 = c.remember_episode(
    context="Living Cortex build: all phases implemented (episodes, graph, vectors, provenance, contradictions, consolidation, forgetting, procedures, neural stub)",
    user_request="Implement phases 1-9 with tests",
    actions_taken="Wrote 17 modules (~4k lines); fixed 6 real bugs (sqlite write semantics, contentless-FTS NULL reads, BFS hops, JSON hydration, contradiction clusters, live-DB schema drift via migration v2)",
    decisions="One cortex tool with action enum; heuristic attention/consolidation for V1; neural interface stubbed",
    result="10/10 acceptance tests (T1-T10), twice, incl. live embeddings",
    outcome="success",
    importance_signals=["physical_action", "project_relevance", "unexpected_result"],
    project="Living Cortex", evidence_ids=[ev_test], embed=True)
e3 = c.remember_episode(
    context="Living Cortex activation: provider enabled, seeded, cron + skill installed",
    user_request="Activate and use the Cortex",
    actions_taken="hermes config set memory.provider living-cortex; seeded 17 entities/17 relationships/12 beliefs; nightly consolidation cron; living-cortex skill saved",
    decisions="Seed from existing built-in memory as user_explicit facts; conservative privacy defaults (vision/audio memory off until Fury pipeline is wired)",
    result="Provider installed+available; hybrid recall verified live; cron at 04:00; skill guides future sessions",
    outcome="success",
    importance_signals=["decision_made", "physical_action", "project_relevance"],
    project="Living Cortex", evidence_ids=[ev_commit], embed=True)

# ---- graph --------------------------------------------------------------
c.graph.get_or_create_entity("Living Cortex", "project", session_id="build")
c.relate("Operator", "WORKS_ON", "Living Cortex")
c.relate("Living Cortex", "USES", "RTX 5070 Ti")

# ---- belief with provenance ----------------------------------------------
c.semantic.add_belief(
    "Living Cortex v0.1 was built and activated on 2026-08-16; it is the active "
    "memory provider with its database at $HERMES_HOME/living_cortex.db.",
    kind="fact", confidence=0.95, source_class="tool_result",
    derived_from=[f"episode:{e1['episode_id']}", f"episode:{e2['episode_id']}",
                  f"episode:{e3['episode_id']}"],
    importance=0.9, session_id="build")

print("recorded episodes:", e1["episode_id"], e2["episode_id"], e3["episode_id"])
print(c.status()["counts"])
