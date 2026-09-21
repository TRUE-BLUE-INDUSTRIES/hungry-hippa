# Project state

Updated 2026-09-20. Git is authoritative for code; no live store or deployed MCP
configuration was changed during this implementation cycle.

## Autonomous maintenance — 2026-09-20

Current worktree/branch: `hungry-hippa-maintenance` / `automation/hh-maintenance`,
starting at `3cddd2adcd85362fba6627dedb87ac431aa7e518` (also fetched `origin/main`).
The sections below describe the historical September 18 ingestion cycle, not the
current checkout. Extraction/reconciliation, Hermes import, vectors and Hippo-Pot
are now present in the integrated baseline; their earlier ledger entries need an
acceptance-level audit rather than blindly reimplementing the old plan.

Fixed the demonstrated growth-recall defect: negative SQLite BM25 scores were
ignored by the positive relevance maximum. Preserve the existing weights and
scale, but invert the BM25 sign. Synthetic growth recall changed from **0/3 to
3/3** at 100/500/2,000 episodes. This is not a general retrieval-quality claim.
A new failing-then-passing regression verifies durable second-process recall,
source provenance and the context budget. All 30 shared gate steps passed;
four optional live-model checks skipped for unavailable configured services.
See [measurement and limitations](docs/maintenance-retrieval-2026-09-20.md).
No schema, trust policy, production store or installed plugin changed.

Next: audit integrated extraction/reconciliation against the pending trust and
checkpoint acceptance criteria; reproduce any remaining P1 defect before fixing.


## Compact handoff for the next cycle

Work in the existing `codex/first-usable-ingestion` worktree. Read `AGENTS.md`
and `tasks.json`; preserve other checkouts and live memory stores. The safe-import
increment is pushed through `8e66ec4` with four-version CI green. Logo adoption
uses the exact approved file in `assets/branding/`; see the section below.

Next engineering task: repair and integrate the existing extraction prototype,
starting with migration-ID collisions, malformed-response checkpointing and prompt
truncation. Keep candidates quarantined until review; reconciliation must not
strengthen or supersede approved facts from unapproved evidence. Then address
recorded growth-recall failures. Full import-to-recall remains unfinished.
Routine reversible implementation, tests, documentation and verified pushes remain
authorized by the original brief. Financial/legal steps and destructive or
sensitive publication actions require the owner's involvement.

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
Code/docs commit `8f99431471df8fb149676227401f0567763c8474` was pushed and
independently matched by both `git ls-remote` and the GitHub connector branch API.
[CI run 35384714272](https://github.com/TRUE-BLUE-INDUSTRIES/hungry-hippa/actions/runs/35384714272)
completed successfully for that exact commit on **all four Python versions**.
The subsequent publication commit contains documentation and recorded results only;
it does not change the measured runtime or verification code.

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

## Reproducible measurements

Clean-tree results at `8f99431` are committed in [ingest-results.json](eval/ingest-results.json)
and the refreshed [memory challenge](eval/REPORT.md). Ingestion medians are
15,594 / 16,664 / 16,393 messages/sec at 100 / 1,000 / 5,000 synthetic messages,
three runs each. All provenance/duplicate/backup checks passed. Existing memory
challenge growth recall remains 0/3; that failure is retained, not removed from
raw results. These runs do not establish real-export quality or a system ranking.

## Approved logo — 2026-09-18

The maintainer-provided artwork is preserved unchanged as
[hungry-hippa-logo.png](assets/branding/hungry-hippa-logo.png) and displayed in the
README, demo guide and support page. [Brand guidance](assets/branding/README.md)
records its integrity hash and makes it the reference for future UI/demo assets.
Logo adoption changes presentation only; runtime and benchmark code are unchanged.
