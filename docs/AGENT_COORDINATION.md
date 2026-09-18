> Historical coordination record. For current work, read [PROJECT_STATE.md](../PROJECT_STATE.md),
> [AGENTS.md](../AGENTS.md) and verified Git state. The assignments and checkout
> states below are not a current deployment inventory.

# Current follow-up ownership

Codex owns the remaining follow-up under the operator’s latest instruction.
Phases 1–9 are already on main. Pushing follow-up fixes to `feat/hungry-hippa`
and fast-forwarding `main` is explicitly authorized. Do not ask Grok to implement.
See [FOLLOWUP.md](FOLLOWUP.md) for verified results. The handoff below is historical.

# Agent coordination (Hungry Hippa)

Read this before creating `eval/`, `demo/`, or `docs/COMPARISON.md`.

## Operator brief (shared source of truth)

`/home/djr/Documents/masterP.txt`

## Checkouts

| Agent | Path | Branch | Status |
|---|---|---|---|
| Hermes | `/home/djr/Work/living-cortex` | `feat/hungry-hippa` | Phases 3–8 in this tree |
| Codex | `/home/djr/.grok/long-running-background-tasks/hungry-hippa-codex-wt` | `feat/hungry-hippa-eval` | Finished; do not push |
| Coordinator (Grok) | same as Hermes | `feat/hungry-hippa` | Merge + review only |

Do not push. Do not touch `/home/djr/.hermes/living_cortex.db` row contents.

## File ownership

Hermes owns (already committed on `feat/hungry-hippa`):

- Core runtime: `schema.py`, `db.py`, `controller.py`, `retrieval.py`, `episodic.py`, `semantic.py`, `tools.py`, `mcp_server.py`, `policy.py`, `limits.py`
- Tests: `tests/test_memory_architecture.py`, `tests/test_mcp_schema.py`, `tests/test_security.py`
- Hermes eval/demo: `eval/**`, `demo/**` as committed in `52a8597` and `b702972`
- Packaging (Phase 8, in progress): README, CHANGELOG, CONTRIBUTING, CI, TECHNICAL_REPORT

Codex owns (already committed on `feat/hungry-hippa-eval`, **not yet merged**):

- `eval/` (Phase 2 baseline harness: 6 pass / 1 budget fail / 3 unsupported)
- `demo/` (simpler scripted demo)
- `docs/COMPARISON.md` (`710b604`) — **Hermes: take this file instead of rewriting a second comparison from scratch.** Copy or cherry-pick; do not invent a conflicting matrix.

Coordinator will merge Codex `docs/COMPARISON.md` after Hermes finishes Phase 8. If you are Hermes and still on Phase 9, cherry-pick `710b604` or copy `docs/COMPARISON.md` from the Codex worktree rather than duplicating eval/demo again.

## Do not do twice

Eval and demo already exist in THIS checkout (`eval/harness.py`, `demo/demo.py`). Do not replace them with the Codex copies unless a review says the Codex version is better. Prefer keeping the Hermes versions that target quarantine/MCP APIs.

## Paths to re-read

- `/home/djr/Documents/masterP.txt`
- `/home/djr/Work/living-cortex/docs/MIGRATION_PLAN.md`
- `/home/djr/Work/living-cortex/docs/LIVING_CORTEX_BASELINE.md`
- `/home/djr/Work/living-cortex/docs/PHASE_STATUS.md`
