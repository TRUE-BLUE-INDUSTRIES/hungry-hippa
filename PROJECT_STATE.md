# Project state

Updated 2026-09-18. Git is authoritative for code; no live store or deployed MCP
configuration was changed during this implementation cycle.

## Verified baseline and branch

- Repository: https://github.com/TRUE-BLUE-INDUSTRIES/hungry-hippa
- Released main/tag: v1.0.0 at `9b9593f62b76c044470f9bc5684656aadb3f07d9`.
- Baseline verification: 21 local steps passed; main CI run `35313692350` succeeded.
- Active branch: `codex/first-usable-ingestion`, isolated worktree. Original
  checkouts and other unmerged branches were preserved. See [baseline inspection](docs/baseline-2026-09-18.md).
- Code increments: reuse canonical store/CLI commits `1221b16` / `b25d715`;
  hardening `f283a97`; CI/benchmark tooling `4f945e0`. These are unreleased.

## Delivered in this cycle

Bounded ChatGPT JSON import, explicit destination, exact raw bytes in SQLite,
per-export conversation snapshots and turn provenance, conflict rejection,
idempotence, `ingest show`, and `ingest verify`. Schema v7 is additive to the
prototype v6; original v5 memories remain intact. Verified SQLite backup recovery
includes original export bytes. Derived beliefs/episodes and recall are unchanged.

All **25 verification steps** passed locally on Python 3.14.7 / MCP 2.2.0,
including **12 new adversarial/integrity tests**, existing MCP/security suites,
synthetic benchmark smoke and a freshly installed wheel exercised outside the
checkout. CI now uses that same runner and checks Python 3.10/3.12/3.13/3.14.
Final remote verification and measured artifacts are recorded below after push.

## Known limits and next work

1. The complete import → extract/review → recall workflow is **not complete**.
   Reuse extraction/reconcile branches only after fixing malformed-response
   checkpointing, prompt truncation and unapproved memory changes.
2. Experimental extraction branches have conflicting v7/v8 migrations. Rebase
   them before integration; do not combine branch databases.
3. Only ChatGPT JSON is supported in this increment. Real-account export diversity,
   other adapters and private development-history dogfooding remain unverified.
4. Existing growth-recall fixture failures/BM25 ranking weakness remain; capture
   a regression before changing retrieval. Public-dataset QA is unmeasured.
5. Stores/backups are plaintext; same-user processes can read them. No encrypted
   backup, revocable client scope, tamper-evident audit or hardened network API.
6. Backup recovery is exercised through SQLite APIs; operator restore/correction/
   deletion UX still needs completion. No production data was deleted or merged.

[Task ledger](tasks.json), [roadmap](ROADMAP.md), [architecture](ARCHITECTURE.md),
[decisions](DECISIONS.md), [benchmarks](BENCHMARKS.md) and [security](SECURITY.md)
carry the next cycle. Sponsors material is prepared; enrollment is an account-owner
financial/legal step, documented in [SUPPORT.md](SUPPORT.md). No funding URL invented.
