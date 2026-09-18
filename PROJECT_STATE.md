# PROJECT_STATE

Hungry Hippa persistent swarm board. Keep this short enough that a new agent can start from it.

**Current Version:** package `1.0.0` tagged at `9b9593f`. Ingest stack tip `feat/ingest-e2e` @ `f3f8861` (schema v8 in that branch; not merged to main). Live Grok MCP reports `1.0.0`. Hermes plugin id remains `living-cortex`.

**Current Commit (ingest tip):** `f3f88617637eba42d40c0d3edaff892f40364851` on `feat/ingest-e2e`. Main tag remains `v1.0.0`.

**Current Phase:** Original ten swarm tasks complete. Ingest pipeline exists on a branch stack, not on `main`. Next: review/merge stack, then optional real ChatGPT export (not in git).

**Current Architecture:** Local SQLite memory runtime. MCP stdio (6 tools). CLI `hungry-hippa`. Ingest layers on `feat/ingest-e2e`: raw archive + canonical turns (v6) → local extract quarantined hypotheses (v7) → reconcile (v8). Default recall still hides quarantined import extracts. Hippo-Pot profile. No control UI. No encryption at rest. Network off.

**Active Agents**

| Role | Actor | Model tier | Notes |
|---|---|---|---|
| Project Manager | Hermes Agent (`default`) | Tier 3 (Nous DeepSeek today) | Persistent orchestrator |
| Architecture / escalation | Grok | Tier 4 | This audit only unless Hermes files a packet |
| Implementation | Hermes profile `hh-impl` | Tier 2 | LM Studio `qwen3.8-27b` @ `http://127.0.0.1:1234/v1` (loaded) |
| Hard diagnosis | Hermes profile `hh-think` | Tier 2 | LM Studio `jinx-qwen3-30b-a3b-thinking-2507` — **do not load with hh-impl** on this 16GB GPU |
| Embeddings | nomic-embed-text-v1.5 | tools | LM Studio OpenAI-compat default on `feat/embeddings-lmstudio` (not yet in ingest tip) |
| Tier 1 cheap worker | **unfilled** | Tier 1 | No small local model installed; not downloaded |

**Active Tasks:** none on the original ten. Kanban board `hungry-hippa` is all done.

**Completed Tasks:** HH-01 through HH-10 (see kanban). Ingest E2E: synthetic ChatGPT export → 14 turns → 5 quarantined beliefs → recall `--quarantined` hit planted 52Nm in 54ms with evidence. Default recall hid it (quarantine holds).

**Blockers**

1. Branch stack not merged to `main` (embeddings vs ingest tips diverged).
2. Hermes `hh-impl` cannot start: 64k context required vs 8k that fits this 16GB GPU.
3. No small Tier-1 local model.
4. Three stores unmerged: grok-demo v5, hermes-live v6 (additive ingest tables empty), XDG default absent.
5. Extracted import memories stay quarantined until operator approve.

**Benchmark Results:** Fixture eval at `7edf59e` (embeddings off). HH-08 live extract recall **54ms** on throwaway DB, planted 52Nm supported by `EV-0004` + ingest turn id. Not a portable/public benchmark.

**Security Findings:** plaintext SQLite; uid-equivalent read; no hash-chained audit; ingest not yet hostile-archive-safe. Channel-bound identity, quarantine, framing, limits: present in 1.0.0.

**Open ADRs:** (A) closed — new ingest tables, not episodes. (B) LM Studio openai-compat on embeddings branch. (C) encryption at rest still open. (D) merge embeddings branch into ingest tip.

**Next Five Tasks**

1. Review and merge the ingest stack (`feat/ingest-e2e`) plus `feat/embeddings-lmstudio` and `docs/release-hygiene`.
2. Rebase embeddings onto ingest tip (or the reverse) so one tree has both.
3. Optional: operator-provided real ChatGPT export on a throwaway DB (never git).
4. Quarantine review UX so imported extracts can enter default recall.
5. Encryption-at-rest design (Grok-tier).

**Stores (do not merge without an explicit operator decision)**

| Name | Path | Schema | Notes |
|---|---|---|---|
| grok-demo | `/home/djr/.grok/hungry-hippa-demo/hungry_hippa.db` | v5 | Grok MCP `HUNGRY_HIPPA_DB`; 0600 |
| hermes-live | `/home/djr/.hermes/living_cortex.db` | v6 | Additive ingest tables empty; 17 episodes; 0600 |
| xdg-default | `~/.local/share/hungry-hippa/hungry_hippa.db` | — | not created |

Backups: `~/.local/state/hungry-hippa/pre-unify-backups/`

**Frontier Escalations:** this audit (2026-09-18). No open packet.

**Release Readiness:** tagged 1.0.0 on `main`. Ingest is real on `feat/ingest-e2e` but **not** on `main`. Do not call a GitHub release until the stack is merged and CI runs Hippo-Pot (that CI change is on `docs/release-hygiene`).
