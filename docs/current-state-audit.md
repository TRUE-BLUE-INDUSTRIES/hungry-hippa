# Hungry Hippa — current-state audit

**Auditor:** Grok 4.6 (swarm-design specialist), 2026-09-18.
**Directive:** Hungry Hippa Swarm Master Build Prompt.
**Method:** live git/GitHub inspection of this checkout, file reads, MCP `hippa_status` against the configured Grok server, LM Studio `lms ls`, Hermes `memory status` / `kanban` / `profile list`. Tests were **not** re-run locally in this pass; GitHub Actions and the annotated `v1.0.0` tag message are the verification evidence.

Nothing below is a marketing claim. If a fact could not be verified, it is marked unverified.

---

## 1. Identity and Git state

| Item | Verified value |
|---|---|
| Repository | https://github.com/TRUE-BLUE-INDUSTRIES/hungry-hippa |
| Local checkout | `/home/djr/Work/living-cortex` (directory name is historical; package is `hungry-hippa`) |
| Default branch | `main` (`origin/HEAD` → `origin/main`) |
| Inspected HEAD | `9b9593f62b76c044470f9bc5684656aadb3f07d9` |
| HEAD subject | `feat: post-reboot acceptance verifier for Hippo-Pot` |
| HEAD author | Hermes Builder `<hermes@local>` 2026-09-16 20:49:31 -0700 |
| Audit branch | `docs/swarm-baseline` (created from `origin/main` for this document) |
| Local `main` | `0be23e5` — **behind** `origin/main` by 4 commits |
| Local `feat/hungry-hippa` | `12a1a27` — **behind** `origin/feat/hungry-hippa` (`7f175a9`) |
| `feat/hungry-hippa-eval` | `710b604` (Codex worktree; never merged into `main`) |
| Tags | only `v1.0.0` (annotated `5e6cb94` → commit `9b9593f`) |
| GitHub release | [Hungry Hippa v1.0.0](https://github.com/TRUE-BLUE-INDUSTRIES/hungry-hippa/releases/tag/v1.0.0) published 2026-09-18T08:44:30Z |
| Working tree at inspection | clean on `origin/main` before this audit; gitignored `living_cortex.db` exists in the checkout and is **not** tracked |

---

## 2. Verified version number

**Canonical package version: `1.0.0`.**

Evidence that agrees:

- `pyproject.toml` `version = "1.0.0"`
- `src/hungry_hippa/version.py` `__version__ = "1.0.0"`
- `src/hungry_hippa.egg-info/PKG-INFO` `Version: 1.0.0`
- git tag `v1.0.0` and GitHub release both point at HEAD `9b9593f`
- `mcp_server.server_version()` in **this package** reads `__version__`

Evidence that disagrees (must not be papered over):

| Source | Reports | Why it is not the package version |
|---|---|---|
| Live Grok MCP `hippa_status` | `server_version: "0.2.0"` | Grok is launched against `/home/djr/.hermes/plugins/living-cortex/mcp_server.py`, whose `plugin.yaml` is `version: 0.2.0` |
| Hermes memory provider | plugin id `living-cortex` | Same installed plugin, not the `src/hungry_hippa` package |
| `CHANGELOG.md` | ingest / quarantine / src-layout listed under **Unreleased** | Those commits (`e9254e8`, `3a68467`, `7f175a9`) **are ancestors of** tagged `v1.0.0` |
| `CHANGELOG.md` | “Versions are the `version:` field in `plugin.yaml`” | `plugin.yaml` was removed from the package; stale sentence |
| `pyproject.toml` classifier | `Development Status :: 4 - Beta` | Conflicts with a `1.0.0` tag in spirit, not in the version string |
| `config.DEFAULTS["schema_version"]` | `1` | Live SQLite schema is `CURRENT_VERSION = 5`. The config key is unused by migrations |
| README test-count | “16 steps, 14 suites” | `scripts/check_all.py` has **21** STEPS; tag message says 21 steps / 133 checks / 15 suites |

**Live clients are not running the tagged 1.0.0 package.** The repository is 1.0.0; the process Grok is talking to is the 0.2.0 Hermes plugin. That is the most important operational fact in this audit.

The `hungry-hippa` distribution is **not** installed in system Python (`PackageNotFoundError`). A checkout venv exists at `.venv/`.

---

## 3. Package metadata

| Field | Value |
|---|---|
| PyPI/project name | `hungry-hippa` |
| Import package | `hungry_hippa` (src layout) |
| Python | `>=3.10` |
| Runtime dependency | `mcp>=2.2,<3` only |
| Console scripts | `hungry-hippa` → `hungry_hippa.cli:main`; `hungry-hippa-mcp` → `hungry_hippa.mcp_server:main` |
| In-process adapter | `HungryHippaProvider` / `register()`; alias `LivingCortexProvider` |
| Default DB | `$XDG_DATA_HOME/hungry-hippa/hungry_hippa.db` |
| Env | `HUNGRY_HIPPA_DB` wins; `LIVING_CORTEX_DB` deprecated with warning |

---

## 4. CI and tests

**CI:** `.github/workflows/test.yml`, name `tests`, Python 3.12 and 3.13, `ubuntu-latest`.

Latest run on `main` @ `9b9593f`: GitHub Actions run [35313692350](https://github.com/TRUE-BLUE-INDUSTRIES/hungry-hippa/actions/runs/35313692350) — `completed` / `success` (2026-09-18T06:09:30Z, ~1m54s). Recent listed `tests` runs on `main` and `feat/hungry-hippa` were also success.

**Local runner:** `python scripts/check_all.py` — 21 STEPS, including Hippo-Pot.

**CI vs local gap (file-verified):** `test_hippo_pot.py` is in `check_all.py` and **absent** from `.github/workflows/test.yml`. A green GitHub run therefore does not prove Hippo-Pot tests passed.

**Test files present (20 `test_*.py`):** acceptance, backup_rotation, chatgpt_ingest, confused_deputy, existence_oracle, file_permissions, hippo_pot, import_hygiene, injection_framing, mcp_integration, memory_architecture, migration, provenance, quarantine_cli, resource_limits, security, supersession, trust_boundary, trust_token. Plus `tests/_package.py` and `tests/mcp_harness.py`.

**Eval:** `eval/harness.py` writes `eval/results.json`. Latest committed report: generated `2026-09-15T20:52:41Z` at commit `7edf59e` (not HEAD), embeddings **disabled**, deterministic controller (no LLM judge). Comparable-arm recall 1.0 vs 0.143 session-transcript baseline. This is a fixture challenge, not a ChatGPT-archive torture test.

This audit did **not** re-run `check_all.py`. Tag annotation claims it was green at `9b9593f`.

---

## 5. Database schema

`schema.py` `CURRENT_VERSION = 5` (max of migrations 1–5). Migrations store `down_sql`. Auto-applied on `Database.__init__`; non-empty DBs are copied to `{path}.pre-migration-{UTC}.bak` first.

| Ver | What it added |
|---|---|
| 1 | episodes, evidence, graph, beliefs, procedures, vectors, consolidation, forgetting, retrieval, mutation_log, FTS |
| 2 | rebuild `memory_fts` as readable (non-contentless) FTS5 |
| 3 | `product_meta` (Hungry Hippa, formerly Living Cortex) |
| 4 | `sensitivity`, `quarantined`, `actor_id` on episodes and beliefs |
| 5 | `claimed_source_class`, `verified_source_class`, `source_actor`, `ingestion_channel` |

Tables: `schema_migrations`, `counters`, `mutation_log`, `episodes`, `evidence`, `episode_evidence`, `entities`, `relationships`, `beliefs`, `belief_evidence`, `procedures`, `vectors`, `consolidation_runs`, `forget_log`, `retrieval_log`, `turn_staging`, `memory_fts`, `product_meta`.

There is **no CLI rollback command**; rollback is documented SQL + pre-migration backup.

---

## 6. Architecture map (what exists)

Hungry Hippa is a **local-first memory runtime**, not a chatbot. Core loop in the README is implemented as Python modules over one SQLite file.

```
clients: MCP stdio | in-process adapter | CLI
            ↓
     MemoryController  (policy, limits, trust)
            ↓
  episodic | semantic | graph | procedural | vectors(optional)
            ↓
     RetrievalRouter (FTS5 + graph + optional vectors → ranked context)
```

| Layer | Implementation | Status |
|---|---|---|
| Episodic | `episodic.py` structured episodes | present, tested |
| Semantic | `semantic.py` facts/beliefs/hypotheses, supersession, contradictions | present, tested |
| Entity / temporal graph | `graph.py` `valid_from`/`valid_until`, SUPERSEDES | present, tested |
| Procedural | `procedural.py` candidate → validated → skill (user approval) | present, tested |
| Evidence | sha256 insert-only `evidence` rows | present, tested |
| Hybrid retrieval | FTS5 + graph + optional vectors; decomposed `explain=True` | present, tested |
| Context compiler | `compile_context` character budget, framing as data | present, tested |
| Consolidation | deterministic “sleep” pass | present, tested |
| Forgetting | decay, compression, archival; purge owner+confirm | present, tested |
| MCP | six `hippa_*` tools, official SDK, stdio only | present, tested |
| CLI | operator commands including quarantine, backup, ingest dry-run, Hippo-Pot | present |
| ChatGPT parser | `ingest/chatgpt.py` lossless tree parse | present; **writes nothing** |
| Hippo-Pot | systemd user units, doctor, post-reboot verifier | present; manager is a **placeholder** |
| Vectors | Ollama `nomic-embed-text` at `127.0.0.1:11434` | code present; **Ollama is not running**; LM Studio has the same embed model unused |
| Neural ranker | `neural.py` stub, disabled | not implemented |
| Control UI | none | missing |
| Network / device enrollment | default localhost; no mTLS, no Tailscale integration | missing (intentionally off) |
| Encryption at rest | none (documented; OS disk encryption recommended) | missing |
| Tamper-evident audit chain | `mutation_log` is ordinary SQLite, not a hash chain | missing (explicitly not claimed) |

### MCP tools (exactly six)

`hippa_remember`, `hippa_recall`, `hippa_build_context`, `hippa_record_outcome`, `hippa_forget`, `hippa_status`.

No SQL, path, export, or ingest tool over MCP.

### CLI commands

`init start stop restart doctor uninstall status selftest owner-token fix-permissions verify migrate recall episodes graph why consolidate learned changed forgotten quarantine backup ingest chatgpt export`.

Directive names `hippa status|doctor|storage|security|benchmark|version`. Actual binary is `hungry-hippa`. `doctor` exists (Hippo-Pot diagnostics). There is **no** `hungry-hippa storage`, `security`, `benchmark`, or `version` subcommand. `status` prints counts; package version is not a first-class CLI command.

---

## 7. Ingestion (the first practical target)

**Slice 1 only.** `docs/INGESTION.md` is explicit.

- Parser: ChatGPT `conversations.json` → frozen `NormalizedTurn` / `ParsedConversation`.
- Preserves provider node ids, parent ids, `branch_path`, all regenerated/edited branches, `current_path_turn_ids`.
- CLI: `hungry-hippa ingest chatgpt <file> --dry-run`. Without `--dry-run` it **refuses**.
- No raw-archive store, no normalized conversation tables, no evidence write, no memory extraction, no idempotent re-import, no progress UI, no zip/streaming of huge exports.
- No Claude, Gemini, Grok, Hermes, Markdown, JSONL, or auto adapters.

Canonical conversation format exists as Python dataclasses, not as a persisted schema.

Hermes sessions live under `~/.hermes/sessions/` and are **not** imported.

---

## 8. Retrieval and memory quality

Ranking weights (code): 0.30 salience + 0.22 recency + 0.22 relevance + 0.13 term-hit + 0.13 confidence, times reinforcement. Recency half-life 45 days. Default context budget 1500 chars / 6 items.

Vectors: fail-open to FTS+graph when Ollama is down. Live `hippa_status` on the demo DB: `"vectors": {"enabled": true, "model": "nomic-embed-text", "url": "http://127.0.0.1:11434", "reachable": null}` and `vectors` count 0. LM Studio has `text-embedding-nomic-embed-text-v1.5` locally; the runtime does not talk to LM Studio.

Live Grok MCP demo DB (`HUNGRY_HIPPA_DB=/home/djr/.grok/hungry-hippa-demo/hungry_hippa.db`): 4 episodes, 1 quarantined, 0 beliefs/entities/relationships/evidence/vectors. That is a demo sliver, not years of conversation history.

---

## 9. Security controls (actual)

Documented in `docs/SECURITY.md` and `docs/THREAT_MODEL.md`. Honest about what is not provided.

| Control | Present? |
|---|---|
| Actor + policy (owner vs untrusted); `actor_id` is a label | yes |
| Channel-bound identity; owner token in **server env**, not tool args | yes (package 1.0.0) |
| Quarantine untrusted writes; CLI approve/reject; MCP cannot approve | yes |
| Recalled text framed as data; neutralization of role-play prefixes | yes (`test_injection_framing.py`) |
| Existence-oracle protection for untrusted callers | yes |
| Request caps, call budget, write quota, DB size, backup space | yes |
| File mode 0600 on new DBs; `fix-permissions` | yes |
| Confused-deputy / protected user_explicit facts | yes |
| Encryption at rest / separate key management | **no** |
| Capability tokens, mTLS, device enrollment, revocation | **no** |
| Append-only hash-chained audit log | **no** (`mutation_log` is rewriteable SQLite) |
| Sandboxed importer (zip bombs, path traversal of archives) | **n/a** — ingest does not unpack archives or write |
| Network default OFF | yes (stdio MCP; Hippo-Pot bind default `127.0.0.1`) |

Store is **plaintext SQLite**. Any process with the operator uid can read it. The product says this out loud.

Prior 2026-09-15 audits (`/home/djr/Work/hungry-hippa-audit/`) found identity and oracle bugs that later commits closed. Personal-name fixtures (`Dennis` / `Voxvil` / `Prusa_XL`) are **gone** from current tests. Absolute `/home/djr/...` paths remain in historical docs (`PHASE_STATUS.md`, `AGENT_COORDINATION.md`, `FOLLOWUP.md`, etc.).

---

## 10. Documentation

Present and generally aligned with the code: README, SECURITY.md, THREAT_MODEL.md, MCP.md, INGESTION.md, MIGRATION.md, hippo-pot.md, COMPARISON.md, TECHNICAL_REPORT.md, RELEASE_CHECKLIST.md, CHANGELOG.md, CONTRIBUTING.md, eval/REPORT.md, RED_TEAM_REPORT.md.

Stale or historical (do not treat as current truth): `docs/PHASE_STATUS.md`, `docs/AGENT_COORDINATION.md` (“Do not ask Grok to implement”), `docs/FOLLOWUP.md` (plugin sync at older SHAs; “all seven steps”), README step counts, CHANGELOG Unreleased vs tag.

---

## 11. Directive coverage

Legend: **done** = implemented and tested at some level; **partial** = code exists but does not meet the directive; **missing**.

| Directive theme | Status | Evidence |
|---|---|---|
| Memory substrate, not a chatbot DB | **done** | runtime + MCP + CLI |
| Local-first / offline-capable core | **done** | SQLite; MCP stdio; no required network |
| Replaceable AI, persistent memory | **partial** | MCP clients can share a store; live Hermes/Grok still on 0.2.0 plugin |
| Hippo Pot appliance | **partial** | systemd profile exists; manager placeholder; not a general device server |
| Optional secure networking | **missing** | deliberately off; no enrollment/mTLS |
| Encryption at rest | **missing** | documented OS encryption only |
| Hybrid memory model (episodic/semantic/entity/procedural/temporal) | **done** | tables + tests |
| Preference / working memory as named layers | **partial** | preferences can be beliefs/graph; no dedicated working-memory store |
| Provenance first-class | **partial** | evidence hashes, claimed vs verified class, `why` CLI; ingest does not yet attach conversation/message ids into the store |
| Raw archive ≠ memory (5 layers) | **missing** | parser only; no archive, no persisted canonical store, no extraction, no ingest reconciliation |
| Universal ingestion | **partial** | ChatGPT parse-only; no other providers |
| Large-scale streaming ingest | **missing** | loads export via parser; no checkpoints/queues |
| Consolidation of repeated facts | **partial** | sleep pass on existing episodes/beliefs; not on imported chat history |
| Contradiction / supersession | **done** | graph + beliefs |
| Forgetting / deletion semantics | **partial** | archival + confirm purge; no “delete this import and all derived memories” |
| Correction UI | **missing** | CLI `verify` / `quarantine`; no user-facing control app |
| Retrieval benchmarks beyond fixtures | **partial** | eval harness exists; embeddings off; no imported-history benchmark |
| Context compiler + token efficiency metric | **partial** | compiler exists; `token_estimate` is chars/4 |
| MCP / API / SDK ecosystem | **partial** | MCP yes; no HTTP API; no multi-language SDK |
| `hippa doctor/storage/security/benchmark/version` | **partial** | `hungry-hippa doctor` + `status`; other names missing |
| Hardware profiles Light/Desktop/Server | **partial** | Hippo-Pot profile only |
| Swarm PM (Hermes) + cheap local workers | **missing** | Hermes is installed; one profile (`default` / DeepSeek via Nous); no Hungry Hippa kanban board before this work |
| Grok used sparingly | **n/a** | this audit is the intended Grok-tier architecture pass |

---

## 12. Architectural risks

1. **Split brain: 0.2.0 plugin vs 1.0.0 package.** Hermes and Grok are not exercising the tagged product. Memories written through Grok MCP land in `/home/djr/.grok/hungry-hippa-demo/hungry_hippa.db`. Hermes live DB is `~/.hermes/living_cortex.db`. Three stores, two codebases.
2. **Ingest stops at parse.** The first end-to-end milestone (drop ChatGPT export → retrieve a months-old fact with evidence) cannot succeed on current code.
3. **Embeddings configured against a dead Ollama** while LM Studio already has nomic-embed. Vector path is dark.
4. **Plaintext store + uid-equivalent threat.** Fine for a locked-down Hippo Pot with disk encryption; not fine if the directive’s “attackers target the memory store” is taken literally.
5. **No sandboxed archive importer** yet — the moment ingest grows to zip/tar, this becomes a security gate, not a feature.
6. **Eval is not the product benchmark.** 1.0 recall on synthetic fixtures with embeddings off does not measure imported-history quality.
7. **CI does not run Hippo-Pot tests.** Release tag claims 21/21 locally; GitHub does not.
8. **CHANGELOG / README drift** will cause agents to invent the wrong version story.
9. **Local swarm cannot run as specified today.** LM Studio server is OFF; Hermes default model is cloud DeepSeek; no small Tier-1 model is installed (only 27B dense + 30B-A3B MoE + embed).
10. **`feat/hungry-hippa-eval` still exists** unmerged. Do not revive it; `main` already has eval/demo.

---

## 13. LM Studio inventory (this machine)

| Model | Size | Role fit |
|---|---|---|
| `qwen/qwen3.8-27b` Q4_K_M | 17.74 GB, 262k ctx, tool-use, vision | Tier 2 implementation / tests / docs |
| `jinx-qwen3-30b-a3b-thinking-2507` Q4_K_M | 18.56 GB, 262k ctx, tool-use, thinking | Tier 2 hard coding / diagnosis |
| `text-embedding-nomic-embed-text-v1.5` Q4_K_M | 84 MB | embeddings (not wired) |

`lms ps`: nothing loaded. `lms status`: **Server: OFF**. Hardware: 60 GiB RAM, 32 threads — Hippo Desktop class, not Hippo Light.

**Tier 1 gap:** no small local model for formatting, mechanical refactors, or cheap retries. Do not spend 27B/30B on those tasks. A small Qwen/Llama 4–8B (or similar) should be downloaded before the swarm is considered staffed.

Hermes: v0.21.0, default `deepseek/deepseek-v4-flash-0731` via Nous. One profile: `default`. Kanban board before this work: `default` (empty). Memory provider: `living-cortex` plugin.

---

## 14. What this audit is not

- A rewrite plan. The existing runtime should be extended, not replaced.
- A claim that v1.0.0 is “finished.” Classifier is Beta; ingest is parse-only; live clients are on 0.2.0.
- A re-run of `scripts/check_all.py`. Treat the tag and GitHub Actions as the last green evidence, with the Hippo-Pot CI gap noted.

---

## 15. Immediate implications (for Hermes)

1. Freeze architecture: Hungry Hippa remains the memory substrate; do not add a second store.
2. First engineering work is **operational unification** (point Hermes + Grok at the 1.0.0 package) and **ingestion Slice 2** (persist canonical conversations + evidence, still no silent extraction).
3. Do not start a control UI, network mode, or encryption project until a ChatGPT export can be imported, inspected, and recalled with provenance.
4. Grok/frontier stays off the routine path. This document is the escalation-grade architecture snapshot; further Grok calls need an escalation packet.
