# Living Cortex baseline (Hungry Hippa Phase 1)

Date: 2026-09-14.
Repository: `/home/djr/Work/living-cortex`
Branch at audit: `main` @ `3886aa6da8340764ad6a84140a8e8940623e736c`
Audit branch: `feat/hungry-hippa`
Remote at audit time: `https://github.com/TRUE-BLUE-INDUSTRIES/living-cortex.git`;
the repository was later renamed and now pushes to
`https://github.com/TRUE-BLUE-INDUSTRIES/hungry-hippa.git`.

This document records what the existing Living Cortex system actually does, what is only documented, and the measurements taken before any Hungry Hippa restructuring. Hungry Hippa is spelled exactly this way. This is an agent-memory and context-engineering system, not model training.

Private production memory contents are not reproduced here. Counts, sizes, and schema names only.

## 1. What this system is

Living Cortex is a local Hermes Agent `MemoryProvider` plugin. It stores episodes, immutable evidence, a temporal knowledge graph, semantic beliefs with provenance, contradictions, consolidation, forgetting, and procedural candidates in a SQLite database.

It is **not**:

- An MCP server
- A Grok CLI plugin
- A machine-learning trainer or weight-update system
- A healthcare-compliance product

The `neural.py` module is an explicit stub for future learned rankers/priors. V1 does not train models or update foundation-model weights.

## 2. Repository map

Flat plugin layout (Hermes loads top-level `.py` files). No `pyproject.toml`, `requirements.txt`, pytest config, or CI.

| File | Role | Status |
|---|---|---|
| `__init__.py` | `LivingCortexProvider` + `register(ctx)` | Implemented |
| `plugin.yaml` | name `living-cortex` v0.1.0; hook metadata | Implemented (metadata only) |
| `config.py` | defaults, Hermes config + sidecar + `LIVING_CORTEX_DB` | Implemented |
| `schema.py` | reversible migrations v1–v2 | Implemented |
| `db.py` | WAL SQLite, mutation log, FTS, evidence hashing | Implemented |
| `controller.py` | central API | Implemented |
| `episodic.py` | episodes | Implemented |
| `graph.py` | temporal entities/relationships | Implemented |
| `semantic.py` | beliefs, supersession, contradictions | Implemented |
| `procedural.py` | procedures + outcomes | Implemented |
| `retrieval.py` | hybrid FTS + optional vectors + graph | Implemented |
| `vectors.py` | local Ollama embeddings, fail-closed | Implemented |
| `attention.py` | importance scoring | Implemented (see defects) |
| `consolidation.py` | deterministic “sleep” pass | Implemented |
| `forgetting.py` | decay / compress / archive / explicit purge | Implemented |
| `tools.py` | single `cortex` tool, action enum | Implemented |
| `cli.py` | `hermes living-cortex …` | Implemented |
| `observability.py` | why / changed / forgotten / export | Implemented |
| `vision.py` | visual episodes | Code present, privacy-gated OFF |
| `neural.py` | learned-ranker adapter | Stub (`enabled = False`) |
| `tests/test_acceptance.py` | T1–T10 custom runner | Implemented, passing |
| `scripts/seed_initial.py` | generic seed example | Implemented |
| `scripts/record_build_session.py` | records the build as episodes | Implemented; machine-specific |
| `docs/INSPECTION.md` | Phase 0 Hermes-install inspection (2026-08-16) | Historical |
| `LICENSE` | MIT, True Blue Industries 2026 | Present |

Stdlib-only Python. Optional runtime dependency: local Ollama at `http://127.0.0.1:11434` for embeddings. No third-party Python packages are imported.

## 3. Architecture

```
Hermes MemoryManager
  prefetch(query)  -> RetrievalRouter -> <memory-context> fence
  sync_turn(...)   -> turn_staging
  on_session_end   -> close_session() -> episodes + light consolidation
  on_memory_write  -> semantic beliefs (mirror)
  get_tool_schemas -> cortex tool
        |
        v
MemoryController
  episodic | graph | semantic | procedural | vectors
  retrieval | consolidation | forgetting | attention
        |
        v
SQLite WAL  ($HERMES_HOME/living_cortex.db)
  evidence (immutable, sha256)
  mutation_log
  memory_fts (FTS5)
```

Cognitive loop as documented and wired:

```
PERCEIVE → ATTEND → RECALL → REASON → ACT → OBSERVE
    ↑                                          ↓
    └── CHANGE ← CONSOLIDATE ← FORGET ← LEARN ← REMEMBER
```

Automatic recall is `prefetch()` injected as `<memory-context>`. Explicit recall is the `cortex` tool `action=recall`. Episodes are assembled at session end from staged turns, not on every turn.

### 3.1 Provider contract

`LivingCortexProvider` is duck-typed (not a hard subclass of Hermes `MemoryProvider`) so it still loads if the host ABC changes.

Implemented: `is_available`, `initialize`, `shutdown` (no-op), `system_prompt_block`, `prefetch`, `recall_status`, `on_turn_start` (no-op), `sync_turn`, `on_session_end`, `on_session_switch`, `on_pre_compress`, `on_delegation`, `on_memory_write`, `get_tool_schemas`, `handle_tool_call`, `get_config_schema`, `save_config`, `backup_paths` (returns `[]`).

Not overridden: `queue_prefetch` (host default no-op).

Writes are skipped when `agent_context != "primary"` or a parent session id is set. That is a coarse primary-vs-subagent gate, not caller-permissioned retrieval.

### 3.2 Storage

Path resolution, highest wins:

1. `cfg.db_path`
2. env `LIVING_CORTEX_DB`
3. `$HERMES_HOME/living_cortex.db` inside Hermes
4. `./living_cortex.db` standalone

Migrations: v1 initial schema, v2 rebuild `memory_fts` as a contentful FTS5 table. `CURRENT_VERSION = 2`. Config still contains unused `"schema_version": 1`. Down-SQL is stored in `schema_migrations`; there is no rollback CLI.

Evidence rows are append-only and sha256-hashed. Mutations are logged in application code, not triggers.

### 3.3 Retrieval ranking (actual formula)

Transparent heuristic in `retrieval.py`:

```
score = (0.35 * importance
       + 0.25 * recency
       + 0.25 * max(vector_score, fts_score/10, term_hits*0.12)
       + 0.15 * (1 if any term hit else 0))
      * (1 + 0.05 * min(10, reinforcement_count))
```

Recency is exponential with `recency_half_life_days=45`. Context is rendered to a character budget (`max_context_chars=1500`, `max_items=6`). There is no token-budget compiler, no ranking explanation debug mode, no sensitivity filter, and no caller ACL on recall.

### 3.4 Cortex tool surface

One tool named `cortex` with action enum:

`recall`, `remember_episode`, `relate`, `graph`, `episodes`, `add_belief`, `update_belief`, `contradict`, `procedures`, `reinforce`, `forget`, `consolidate`, `why`, `changed`, `forgotten`, `status`, `export`.

CLI: `hermes living-cortex {status,recall,episodes,graph,why,consolidate,learned,changed,forgotten,export,selftest}`.

## 4. Working features (verified)

Verified by running code, not by README claims:

| Feature | Evidence |
|---|---|
| Episode create + FTS | T1 PASS |
| Visual episode (when privacy enabled in test) | T2 PASS |
| Graph multi-hop | T3 PASS |
| Temporal supersession of relationships | T4 PASS |
| Contradiction + user-explicit wins | T5 PASS |
| Procedural candidate from repeated episodes | T6 PASS |
| Provenance `why` | T7 PASS |
| Importance decay + archival; high-value preserved | T8 PASS |
| Consolidation duplicate merge; evidence intact | T9 PASS |
| Provider prefetch auto-recall | T10 PASS |
| Hermes provider active | `hermes memory status`: Provider living-cortex, installed, available |
| Hermes CLI | `hermes living-cortex status` and `selftest` work |
| Live DB schema | migrations 1 and 2 applied |

## 5. Documented or partial — not fully productized

| Claim | Reality |
|---|---|
| Neural / learned ranking | Stub only |
| Vision/audio memory | Code exists; defaults OFF; no glasses/transport pipeline in this repo |
| Skill promotion | Status flag; does not write Hermes skill files |
| Nightly consolidation cron `0 4 * * *` | Config default; no cron job installed (`~/.hermes/cron/` empty of jobs) |
| `sensitive_context_exclusion` | Config list `["medical","financial","credentials"]` never referenced in code |
| `backup_paths()` | Empty list |
| MCP / Grok CLI memory runtime | Not implemented |
| Cross-agent authorization | Primary-vs-subagent write gate only |
| Quarantine / untrusted candidates | Not implemented |
| Sensitivity labels on rows | Not implemented |
| Encryption-at-rest | Not implemented (OS disk encryption would be an operating requirement) |
| Input-size / rate limits | Partial truncation in staging; no global request limits |
| Ranking debug mode | Scores stored on items as `_score` internally; not exposed as an explanation API |
| Token-budget context compiler | Character cap only |
| `plugin.yaml` hooks | Manifest metadata; `register()` does not register generic Hermes hooks. Lifecycle methods run because `MemoryManager` calls the provider |

## 6. Hermes / Grok CLI integration

### Hermes (working baseline)

- Plugin copy: `/home/djr/.hermes/plugins/living-cortex/`
- Work tree vs install copy: `diff -rq` (excluding `.git` / `__pycache__`) differs only by a gitignored `living_cortex.db` in the work tree. Source files match.
- `hermes config get memory.provider` → `living-cortex`
- `memory_enabled: true` on this host
- Built-in MEMORY.md / USER.md remain active; Cortex mirrors writes
- Sidecar `/home/djr/.hermes/living_cortex_config.json` is not present (defaults apply)
- Operator debug skill (outside repo): `~/.hermes/skills/software-development/living-cortex-debugging/`

This is the integration that must keep working: new Hermes sessions must still load the provider, prefetch, stage turns, expose `cortex`, and serve `hermes living-cortex`.

### Grok CLI (honest status)

There is **no Living Cortex code, MCP server, or Grok plugin** in this repository.

On this machine:

- `grok` is installed and is the development agent for this repo
- `~/.grok/config.toml` has no `[memory]` section and no living-cortex MCP server
- `GROK_MEMORY` is unset (Grok’s own markdown memory is experimental and disabled by default)
- Grok native memory, when enabled, is `~/.grok/memory/*.md` plus an SQLite index — a separate system

“Works with Grok CLI” today means: Grok can operate on this repository, run tests, and call the Python API. It does **not** mean Grok currently retrieves Living Cortex memories. Hungry Hippa Phase 4 must add a local MCP server so Grok and other MCP clients can use the same runtime without claiming they were tested until they actually are.

## 7. Test status

Custom runner, not pytest.

```
$ python tests/test_acceptance.py
PASS  T1_episode_creation
PASS  T2_visual_recall
PASS  T3_graph_relationship
PASS  T4_temporal_change
PASS  T5_contradiction
PASS  T6_procedural_learning
PASS  T7_provenance
PASS  T8_forgetting
PASS  T9_consolidation
PASS  T10_automatic_use
10/10 passed
```

`hermes living-cortex selftest` also reported all ten passed on a throwaway DB.

`--embed` (live Ollama) was **not** run in this audit. Vector health at audit time: `enabled: true`, `reachable: null` (not probed). `vectors` table count on the live DB is 0.

No pytest, no CI, no packaging tests.

## 8. Baseline measurements (2026-09-14)

Live DB path (not dumped): `$HERMES_HOME/living_cortex.db`

| Metric | Value | Notes |
|---|---|---|
| Live DB size | 397312 bytes | WAL/SHM not always present |
| schema version | 1 and 2 applied | |
| episodes | 8 | COUNT only |
| beliefs | 3 | |
| evidence | 3 | |
| belief_evidence | 3 | |
| entities | 0 | |
| relationships | 0 | |
| procedures | 0 | |
| vectors | 0 | embeddings unused in live DB |
| mutation_log | 15 | |
| retrieval_log | 49 | |
| turn_staging | 49 | many may be unprocessed (crash-fragile assembly) |
| forget_log | 0 | |
| consolidation_runs | 1 | |
| memory_fts rows | 11 | |
| Recall latency | 2.50 ms | throwaway DB, FTS-only, 1 hit, 127 context chars |
| Default context cap | 1500 chars / 6 items | |
| Work-tree gitignored DB | 212992 bytes | not committed |

Cross-session recall on the live production DB was **not** exercised with real queries in this audit, to avoid printing private memories. T10 proves prefetch recall on a throwaway DB.

## 9. Security and migration risks

No hardcoded API keys, tokens, or passwords in the repository.

| Risk | Location | Severity for Hungry Hippa |
|---|---|---|
| `export` writes caller-chosen path and dumps full tables including evidence | `observability.py`, `cortex` action `export` | High — bulk extraction + path write |
| `forget mode=purge` deletes episodes/beliefs | `controller.forget`, tool/CLI | High if exposed to untrusted MCP clients |
| `LIVING_CORTEX_DB` / `db_path` arbitrary file | `config.py`, `db.py` | Medium — path control |
| `is_available()` opens the live DB and applies migrations | `__init__.py` | Medium — discovery is not read-only |
| FTS `MATCH` query language from user text | `db.py` `fts_search` | Medium — parameterized SQL, but FTS syntax injection |
| Configurable `ollama_url` POST of memory text | `vectors.py` | Medium if URL is not loopback |
| No request size / rate limits | tool handle | Medium DoS |
| No caller identity on recall | retrieval | High for cross-agent |
| No sensitivity / quarantine | schema | High for poisoning / leakage |
| Work-tree vs install-copy drift | two trees | Operational |
| Public GitHub origin | `TRUE-BLUE-INDUSTRIES/living-cortex` | Do not push Hungry Hippa work without approval |

Parameterized queries are the norm. Table-name f-strings exist only over internal allowlists (`episode`/`belief`, known tables). That is not arbitrary SQL.

## 10. Known defects (already in the tree)

Confirmed in code; not fixed in this phase:

1. **Builtin-memory mirror** (`on_memory_write`) dedupes by exact claim string. A builtin `replace` that grows a profile writes a new belief instead of superseding.
2. **Consolidation similarity** is Jaccard `intersection / max(len)`. Expanding paraphrases fall below `_SIMILARITY_MIN = 0.6` and do not merge.
3. **Episode assembly** runs only on clean `on_session_end`. Crash/abrupt exit orphans `turn_staging` (`processed=0`). Live DB has 49 staging rows vs 8 episodes.
4. **Attention weights** are 20–35 points added to `base_importance` 0.35 then clamped to `[0,1]`, so any single positive signal saturates at 1.0. T1 only asserts `>= 0.55`.
5. **Graph `relate`** does not dedupe identical active edges.
6. **FTS** is insert-on-create; claim/episode updates can leave stale FTS text.
7. **`record_build_session.py`** is machine-specific, unlike the generic seed example.

## 11. What must not be destroyed

Until compatibility wrappers and migration tests exist:

- Hermes `MemoryProvider` registration and lifecycle
- `cortex` tool (may gain aliases, must not vanish)
- SQLite schema v1–v2 data
- Reversible migrations
- Acceptance tests T1–T10
- `hermes living-cortex` CLI (may gain `hippa` alias)
- Fail-closed vector path
- Evidence immutability and mutation_log
- Privacy defaults (vision/audio/location/faces OFF)

## 12. Duplicate / abandoned code

- Duplicate install tree under `$HERMES_HOME/plugins/living-cortex/` (currently matching sources).
- `neural.py` is an intentional stub, not abandoned.
- `docs/INSPECTION.md` describes a Windows Hermes 0.20.0 install; this host is Linux with a current Hermes CLI.
- No unused duplicate retrieval engines.

## 13. Git status at audit start

- Branch `main`, clean, tracking `origin/main`
- User work: none uncommitted
- New branch `feat/hungry-hippa` created for this transformation
- No push
