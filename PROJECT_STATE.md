# PROJECT_STATE

Hungry Hippa persistent swarm board. Keep this short enough that a new agent can start from it.

**Current Version:** package `1.0.0` at `9b9593f`. Live Grok/Hermes MCP still reports plugin `0.2.0`. See `docs/current-state-audit.md`.

**Current Commit:** `9b9593f62b76c044470f9bc5684656aadb3f07d9` (`origin/main`, tag `v1.0.0`)

**Current Phase:** Phase 0 complete (this audit). Next: operational unification + ingestion Slice 2.

**Current Architecture:** Local SQLite memory runtime (schema v5): episodic, semantic, temporal graph, procedural, optional vectors. MCP stdio (6 tools, official SDK). CLI `hungry-hippa`. ChatGPT export parser only (no DB writes). Hippo-Pot systemd profile. No control UI. No encryption at rest. Network off.

**Active Agents**

| Role | Actor | Model tier | Notes |
|---|---|---|---|
| Project Manager | Hermes Agent (`default`) | Tier 3 (Nous DeepSeek today) | Persistent orchestrator |
| Architecture / escalation | Grok | Tier 4 | This audit only unless Hermes files a packet |
| Implementation | local Qwen3.8-27B | Tier 2 | LM Studio; server currently OFF |
| Hard diagnosis | local Jinx-Qwen3-30B-A3B-Thinking | Tier 2 | LM Studio |
| Embeddings | nomic-embed-text-v1.5 | tools | Installed in LM Studio; runtime still points at down Ollama |
| Tier 1 cheap worker | **unfilled** | Tier 1 | No small local model installed |

**Active Tasks:** first ten — see below and Hermes kanban board `hungry-hippa`.

**Completed Tasks:** prior Living Cortex → Hungry Hippa phases 1–9 + Hippo-Pot on `main`; ChatGPT parse Slice 1; quarantine CLI; official MCP SDK.

**Blockers**

1. Grok MCP and Hermes plugin are not the 1.0.0 package.
2. LM Studio server is off; Ollama is off; vector search is dark.
3. No small Tier-1 local model.
4. ChatGPT ingest cannot write.

**Benchmark Results:** `eval/REPORT.md` at commit `7edf59e` (not HEAD), embeddings off, fixture recall 1.0 vs 0.143 baseline. Not an imported-history benchmark.

**Security Findings:** plaintext SQLite; uid-equivalent read; no hash-chained audit; ingest not yet hostile-archive-safe. Channel-bound identity, quarantine, framing, limits: present in 1.0.0.

**Open ADRs:** none numbered. Pending decisions: (A) persist canonical conversations as new tables vs reuse episodes; (B) embeddings via LM Studio OpenAI-compat vs revive Ollama; (C) when to encrypt at rest.

**Next Five Tasks**

1. Point live MCP/Hermes at package 1.0.0.
2. Start LM Studio server; wire embeddings to nomic via a local OpenAI-compatible URL.
3. Persist canonical conversation + raw-archive pointers (ingest Slice 2).
4. Idempotent ChatGPT write path into evidence/episodes with provenance.
5. End-to-end test: import a real export, recall a dated fact, show `why`.

**Frontier Escalations:** this audit (2026-09-18). No open packet.

**Release Readiness:** tagged 1.0.0 / CI green on `tests` workflow, but Hippo-Pot suite not in GitHub Actions; live clients on 0.2.0; ingest not a product feature yet. Do not call ingest “done.”
