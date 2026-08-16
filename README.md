# Living Cortex

**A persistent hybrid cognitive memory system for Hermes Agent.**

Episodic memory, a temporal knowledge graph, hybrid vector+graph recall, provenance tracking, contradiction handling, consolidation ("sleep"), controlled forgetting, and procedural learning — integrated as a native `MemoryProvider` plugin that runs inside Hermes' normal cognitive loop.

Not a vector database. Not chat-history search. Not a bigger MEMORY.md. It's a memory *system* with a learning loop:

```
PERCEIVE → ATTEND → RECALL → REASON → ACT → OBSERVE
    ↑                                          ↓
    └── CHANGE ← CONSOLIDATE ← FORGET ← LEARN ← REMEMBER
```

## What it does

| Memory class | Implementation |
|---|---|
| **Episodic** | Structured episodes (context, actions, tools, decisions, outcome, importance) with attention-gated retention tiers |
| **Evidence** | Immutable, sha256-hashed raw evidence rows — never silently rewritten |
| **Temporal knowledge graph** | Entities + relationships with `valid_from`/`valid_until`; supersession preserves history ("what do we use now?" *and* "what did we use before?") |
| **Semantic beliefs** | Facts/beliefs/hypotheses with `source_class` provenance (user_explicit > tool_result > inference) |
| **Contradictions** | Conflicting claims preserved and cross-linked; cluster resolution — explicit user corrections win |
| **Hybrid retrieval** | Local vector embeddings (Ollama `nomic-embed-text`) + FTS5 + graph traversal, ranked by importance × recency × match |
| **Consolidation** | Deterministic "sleep" pass: entity resolution, dedupe, relationship extraction, contradiction analysis, pattern discovery, confidence updates |
| **Forgetting** | Memory-management operations, not deletion: access/importance decay, compression, archival. High-value items never auto-destroyed |
| **Procedural memory** | Experience → procedural belief → validated procedure → skill promotion (requires explicit user approval) |
| **Neural interface** | Stubbed adapter for future learned rankers/priors with a verify-against-evidence contract |

## How it integrates

The plugin implements Hermes' `MemoryProvider` ABC, which hooks into the agent lifecycle:

| Hook | Cortex behavior |
|---|---|
| `prefetch(query)` | Automatic hybrid recall before every turn; injected as a fenced `<memory-context>` block |
| `sync_turn(user, asst)` | Post-turn staging (per-turn episodic writing) |
| `on_session_end(messages)` | Attention-gated episode assembly + light consolidation |
| `on_memory_write(...)` | Mirrors built-in memory writes into the Cortex with provenance |
| `on_delegation(task, result)` | Subagent observations become episodes |
| `get_tool_schemas()` | Exposes the `cortex` tool (single tool, action enum) |
| `recall_status()` | Deterministic "⟡ recalled N" indicator |

Storage is a local SQLite database (WAL, FTS5, reversible migrations) with optional local Ollama embeddings. No external services, no credentials, no uploads.

## Install

```bash
# Copy the plugin into the user plugins directory
cp -r living-cortex "$HERMES_HOME/plugins/"

# Enable it as the active memory provider
hermes config set memory.provider living-cortex

# Verify
hermes memory status          # Provider: living-cortex — installed, available
hermes living-cortex status   # database health + counts
```

The provider activates in new sessions (the built-in MEMORY.md/USER.md memory stays active alongside it).

## The `cortex` tool

One tool, action-based (mirrors the accepted `fact_store` pattern to avoid schema bloat):

- `recall` — hybrid recall before answering questions about the past
- `remember_episode` — store significant events (with `importance_signals`)
- `relate` — connect people/projects/devices/problems/solutions
- `graph` — query edges (with `include_history` for superseded states)
- `add_belief` / `update_belief` / `contradict` — semantic memory with provenance
- `why` — trace a belief to its evidence
- `consolidate` / `forget` / `reinforce` / `episodes` / `procedures` / `status` / `export`

## Observability CLI

```bash
hermes living-cortex status      # health, counts, vector status
hermes living-cortex recall "<q>"
hermes living-cortex episodes    # --project, --status
hermes living-cortex graph --src X [--rel R] [--dst Y] [--history]
hermes living-cortex why <id>    # provenance trace
hermes living-cortex learned     # procedural candidates
hermes living-cortex changed     # mutation audit log
hermes living-cortex forgotten   # decay/archive history
hermes living-cortex export      # full JSON export
hermes living-cortex selftest    # acceptance tests on a throwaway DB
```

## Acceptance tests

10 spec-mandated acceptance tests (`tests/test_acceptance.py`), all passing:

1. Episode creation → 6. Procedural learning → 10. Automatic use
2. Visual recall → 7. Provenance (mandatory)
3. Graph relationships → 8. Forgetting
4. Temporal change → 9. Consolidation
5. Contradiction

```bash
python tests/test_acceptance.py          # FTS + graph only
python tests/test_acceptance.py --embed  # + live Ollama vector search
```

## Design principles

- **Extend, don't duplicate** — built on the `MemoryProvider` ABC; user-plugin path; survives `hermes update`
- **Provenance first** — every derived memory answers *where did this come from, how certain am I, stated or inferred*
- **Never silently rewrite history** — supersede, contradict, compress — never delete without explicit instruction
- **Conservative forgetting** — structured memory is never auto-purged; raw evidence is never auto-purged
- **Privacy by default** — vision/audio memory, location, and face identity memory are all OFF until explicitly enabled
- **Fail safely** — every subsystem degrades gracefully (Ollama down → FTS fallback; DB error → empty recall)
- **Transparent heuristics** — attention scoring and consolidation are deterministic and configurable, with interfaces designed so learned policies can replace them later

## Layout

```
living-cortex/
├── __init__.py      # LivingCortexProvider (MemoryProvider ABC)
├── controller.py    # central memory controller (§14 capabilities)
├── episodic.py      # episodes + event segmentation
├── graph.py         # temporal knowledge graph
├── semantic.py      # beliefs, provenance, contradictions
├── procedural.py    # procedural learning + validation
├── retrieval.py     # hybrid retrieval pipeline
├── vectors.py       # local embeddings (Ollama, fail-safe)
├── consolidation.py # "sleep" pass
├── forgetting.py    # decay/compression/archival policy
├── attention.py     # configurable importance scoring
├── vision.py        # visual episodic memory (privacy-gated)
├── neural.py        # neural-memory interface (stub)
├── observability.py # why/what-changed/forgotten/export
├── tools.py         # cortex tool schema + dispatch
├── cli.py           # hermes living-cortex CLI
├── schema.py        # SQLite schema + reversible migrations
├── db.py            # connection layer + mutation log + FTS reindex
├── config.py        # config resolution + privacy defaults
├── scripts/         # seed example, build recording
└── tests/           # acceptance tests (T1-T10)
```

## License

MIT
