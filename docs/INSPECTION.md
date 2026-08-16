# Phase 0 — Installation Inspection Report

Date: 2026-08-16. Hermes Agent v0.20.0 (2026.8.3).
Source: `~\AppData\Local\hermes\hermes-agent` (git repo, branch `main`).
HERMES_HOME: `~\AppData\Local\hermes` (profile `default`).

## 1. What memory architecture already exists

| Component | Location | Notes |
|---|---|---|
| Built-in memory tool | `memories/MEMORY.md` + `USER.md` | Always-on compact store (2000-char each). Preserved, not replaced. |
| Session store | `state.db` (SQLite, WAL, FTS5 + trigram) | 119 MB. Tables: sessions, messages, messages_fts(+trigram), system_prompts, async_delegations, ... `session_search` tool reads this. NOT modified by the Cortex. |
| Memory provider plugins (bundled) | `plugins/memory/{hindsight,holographic,byterover,honcho,supermemory}` | **None active** — `memory.provider` is unset in config.yaml. `hindsight` = cloud/local graph+entity memory (needs its own daemon/Postgres). `holographic` = local SQLite fact store w/ FTS5 + trust scores (reusable pattern). |
| Skills | `skills/` (curated dirs) | Reusable procedures; procedural-memory promotion target (§12). |
| Cron | `cron/` (scheduler) | Consolidation scheduling surface. |
| Vision/audio | No in-core pipeline. Fury glasses route through external Android build (VisionClaw/DAT SDK skills) and phone (S25 Ultra). Camera test assets in `camera_tests/`. | Phase 4 integrates at the episode/event level, not the transport level. |
| Embeddings | Ollama `nomic-embed-text:latest` at 127.0.0.1:11434 | Local, no external service — vector backend for Phase 3. |

## 2. What can be reused

- **`MemoryProvider` ABC** (`agent/memory_provider.py`) — the official integration surface:
  `initialize / prefetch / queue_prefetch / recall_status / sync_turn / on_turn_start / on_session_end / on_session_switch / on_pre_compress / on_delegation / on_memory_write / get_tool_schemas / handle_tool_call / get_config_schema / save_config / backup_paths / shutdown`.
- **User-plugin discovery** (`plugins/memory/__init__.py`): user providers load from `$HERMES_HOME/plugins/<name>/` with `register(ctx)` or a `MemoryProvider` subclass; `plugin.yaml` carries metadata; `cli.py` may register a `hermes <name>` subcommand. Relative imports of top-level `.py` modules are auto-registered.
- **MemoryManager** fences prefetch output in `<memory-context>` blocks with an authoritative-data system note; injects provider tool schemas automatically; enforces one-external-provider limit (currently free — no provider configured).
- **`hermes backup`** walks HERMES_HOME → plugin state (DB under HERMES_HOME) is covered.
- **Ollama** local embeddings (privacy-safe).

## 3. Database/provider currently active

Built-in only. `memory.provider` unset. Session store = SQLite+WAL state.db.

## 4. Where the vision/audio pipeline enters Hermes

No in-core pipeline. Glasses→phone (DAT SDK app)→USB/ADB/Wi-Fi→this machine is the transport (assets in `camera_tests/`). The Cortex integrates at the **event layer**: explicit episode open/observe/close via the `cortex` tool + keyframe retention API (`vision.py`), privacy-gated.

## 5. Where memory recall hooks into reasoning

`MemoryManager.prefetch_all(user_message)` runs before each turn (run_agent.py) → provider `prefetch()`. Output is injected as `<memory-context>` with an authoritative-data note. This is the automatic-recall hook (Acceptance Test 10).

## 6. Where post-task episodic writing occurs

`MemoryManager.sync_all(user_msg, assistant_response)` after each turn → provider `sync_turn()` (per-turn staging). `on_session_end(messages)` at session boundaries → episode assembly + attention gating. `on_pre_compress()` captures before context compression. `on_memory_write()` mirrors built-in memory writes with provenance.

## 7. Where consolidation can run safely

- Cron job (scheduler in `cron/`) → `hermes living-cortex consolidate` (deterministic, offline).
- Opportunistically in `on_session_end` (light pass, no network).
- On-demand via the `cortex` tool / CLI.

## 8. How existing memories are preserved

- Phase 0 backup taken before any change: `backups/living-cortex-phase0-20260816_090003/` (consistent state.db snapshot via SQLite backup API, memories/, config.yaml, SOUL.md).
- The Cortex **adds** a provider and its own DB (`$HERMES_HOME/living_cortex.db`); it never writes to state.db, MEMORY.md, or USER.md.
- Built-in memory stays active (spec §15 core/hot memory).

## 9. Engineering decisions (from the actual installation)

1. Ship as a **user memory-provider plugin** at `$HERMES_HOME/plugins/living-cortex/` — no source-tree edits (survives `hermes update`; respects "plugins live in their own directory").
2. Storage: local SQLite (WAL) + FTS5 + optional Ollama vector table. No external services, no credentials required, no auto-upload (§19.8).
3. Flat module layout (loader registers top-level `.py` files only).
4. One `cortex` model tool (action enum) — mirrors the accepted `fact_store` pattern, avoids schema bloat.
5. Heuristic (transparent) attention/consolidation for V1; neural/learned-policy interfaces stubbed behind stable adapters (§13–14).
6. Every mutation logged (`mutation_log`), raw evidence immutable and hashed.
