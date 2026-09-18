# PROJECT_STATE

Hungry Hippa persistent swarm board. Keep this short enough that a new agent can start from it.

**Current Version:** package `1.0.0` at `9b9593f`. Live Grok MCP `hippa_status.server_version` is now `1.0.0`. Hermes plugin id remains `living-cortex`; the adapter imports the 1.0.0 package. See `docs/current-state-audit.md`.

**Current Commit:** `9b9593f62b76c044470f9bc5684656aadb3f07d9` (`origin/main`, tag `v1.0.0`). Swarm notes on `docs/swarm-baseline`.

**Current Phase:** Phase 0b operational unification in progress (HH-01/HH-10 done). Next: embeddings (HH-02) + ingest Slice 2 (HH-03).

**Current Architecture:** Local SQLite memory runtime (schema v5): episodic, semantic, temporal graph, procedural, optional vectors. MCP stdio (6 tools, official SDK). CLI `hungry-hippa`. ChatGPT export parser only (no DB writes). Hippo-Pot systemd profile. No control UI. No encryption at rest. Network off.

**Active Agents**

| Role | Actor | Model tier | Notes |
|---|---|---|---|
| Project Manager | Hermes Agent (`default`) | Tier 3 (Nous DeepSeek today) | Persistent orchestrator |
| Architecture / escalation | Grok | Tier 4 | This audit only unless Hermes files a packet |
| Implementation | Hermes profile `hh-impl` | Tier 2 | LM Studio `qwen3.8-27b` @ `http://127.0.0.1:1234/v1` (loaded) |
| Hard diagnosis | Hermes profile `hh-think` | Tier 2 | LM Studio `jinx-qwen3-30b-a3b-thinking-2507` — **do not load with hh-impl** on this 16GB GPU |
| Embeddings | nomic-embed-text-v1.5 | tools | Loaded in LM Studio; runtime still talks to down Ollama (HH-02) |
| Tier 1 cheap worker | **unfilled** | Tier 1 | No small local model installed; not downloaded |

**Active Tasks:** first ten — see below and Hermes kanban board `hungry-hippa`.

**Completed Tasks:** prior Living Cortex → Hungry Hippa phases 1–9 + Hippo-Pot on `main`; ChatGPT parse Slice 1; quarantine CLI; official MCP SDK; **HH-01** live MCP/Hermes on 1.0.0; **HH-10** LM Studio server + `hh-impl`/`hh-think` profiles (default Nous profile unchanged).

**Blockers**

1. Vector path still targets Ollama `:11434` (down) while nomic is loaded in LM Studio — HH-02.
2. No small Tier-1 local model (not downloaded; 27B is the cheapest LLM on disk).
3. ChatGPT ingest cannot write — HH-03/HH-04.
4. Three stores remain unmerged (operator decision still required): grok-demo, hermes-live, XDG default (absent).

**Benchmark Results:** `eval/REPORT.md` at commit `7edf59e` (not HEAD), embeddings off, fixture recall 1.0 vs 0.143 baseline. Not an imported-history benchmark.

**Security Findings:** plaintext SQLite; uid-equivalent read; no hash-chained audit; ingest not yet hostile-archive-safe. Channel-bound identity, quarantine, framing, limits: present in 1.0.0.

**Open ADRs:** none numbered. Pending decisions: (A) persist canonical conversations as new tables vs reuse episodes; (B) embeddings via LM Studio OpenAI-compat vs revive Ollama; (C) when to encrypt at rest.

**Next Five Tasks**

1. HH-02 wire embeddings to LM Studio nomic.
2. HH-03 persist canonical conversations + raw archive pointers.
3. HH-09 CI Hippo-Pot + CHANGELOG/README hygiene (parallel).
4. HH-04 ChatGPT `--apply` write path.
5. HH-08 E2E ChatGPT export → recall with evidence.

**Stores (do not merge without an explicit operator decision)**

| Name | Path | Schema | Notes |
|---|---|---|---|
| grok-demo | `/home/djr/.grok/hungry-hippa-demo/hungry_hippa.db` | v5 | Grok MCP `HUNGRY_HIPPA_DB`; 0600 |
| hermes-live | `/home/djr/.hermes/living_cortex.db` | v5 | Hermes provider default via legacy discovery; 0600 |
| xdg-default | `~/.local/share/hungry-hippa/hungry_hippa.db` | — | not created |

Backups: `~/.local/state/hungry-hippa/pre-unify-backups/`

**Frontier Escalations:** this audit (2026-09-18). No open packet.

**Release Readiness:** tagged 1.0.0 / CI green on `tests` workflow; live Grok MCP reports 1.0.0; Hippo-Pot suite still not in GitHub Actions; ingest still parse-only. Do not call ingest “done.”
