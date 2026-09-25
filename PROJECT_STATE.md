# Project state

Updated 2026-09-24. Git is authoritative for code; no live store or deployed MCP
configuration was changed during this implementation cycle.

## Autonomous maintenance — text-field validation, 2026-09-24

Started clean at `f938d5a45a4689179977632f20edaae86c3f63b8` on
`automation/hh-maintenance`; fetched main remained an ancestor. Reproduced P1
malformed candidate text fields being coerced or silently filtered while extraction
advanced its checkpoint. Supplied type/claim/context/user_request/result/source_class
must now be strings before content filtering. Missing fields, empty-string defaults,
episode fallbacks, source remapping and control filtering retain their behavior.

Regression failed before the fix and passed afterward. Added 60 malformed-field
HTTP/persistence/retry cases plus parser filter-order/default/fallback assertions.
Read-only QA and Security found no blockers; QA independently exercised fresh CLI
refusal, valid nonempty retry, evidence links and duplicate prevention.

Baseline extraction suite: 19 PASS, optional live chat FAIL/ENVIRONMENTAL (HTTP 400,
configured model failed to load). Full unchanged 30-step gate then passed using a
temporary XDG sidecar with chat explicitly offline: two live-chat SKIPs, both live
embedding checks PASS. Includes MCP/security, ingestion/reconciliation/E2E,
second-process recall with provenance, backup and clean wheel install. No live
config/server, production store, plugin, schema or main changes. Python 3.14.7;
Linux 7.2.5-3-omarchy x86_64; AMD Ryzen 9 9950X3D, 32 logical CPUs. Measured on this
shift's diff over the starting SHA with invented stores; no performance claim.

Next: reproduce whether concurrent extraction jobs can duplicate candidates or
misadvance progress against one invented shared database before changing locking.
Oversized-turn chunking and historical partial-write repair remain unsupported.

## Autonomous maintenance — citation validation, 2026-09-24

Started clean at `ce233d6c4c97266370a2c51304df18a4a5637f01` on
`automation/hh-maintenance`; fetched main remained an ancestor. Reproduced P1
malformed citation fields advancing extraction progress. Supplied `turn_ids` now
must be a list of strings before content filtering: no dictionary-key iteration,
string iteration or non-string coercion. Missing/empty/unknown citations retain
existing filtering; source remapping and ordered deduplication are unchanged.

Added 22 malformed-citation HTTP/checkpoint cases, fresh-process pending/retry
assertions and parser compatibility/filter-order coverage. Read-only QA and security
found no blocking regression. Other candidate-field coercion remains open.

Verification: the regression failed before the fix and passed afterward. Default
`.venv/bin/python scripts/check_all.py` exited 1: 29 steps succeeded, extraction's
optional live chat completion failed because LM Studio could not load its configured
model (HTTP 400); E2E live chat skipped for the same reason. This is environmental,
not a passing check. Re-ran the unchanged 30-step gate with a temporary XDG sidecar
pointing chat at a reserved non-listening loopback port: exit 0, all 30 steps, two
live-chat SKIPs. Both live embedding checks passed. Includes second-process recall
with provenance, offline ingestion E2E, MCP/security, backup and clean wheel install.
No live config/server, production store, plugin or main changes. Python 3.14.7;
Linux 7.2.5-3-omarchy x86_64; AMD Ryzen 9 9950X3D, 32 logical CPUs; invented stores
and this shift's diff over the starting SHA. No comparative performance claim.

Next: reproduce malformed claim/context/type fields becoming persisted text or
successful empty batches, then narrowly validate without weakening control filters.

## Autonomous maintenance — 2026-09-24

Started clean at `7f27eb7eea5e31dfc9cb8c2c3c611cc4d6aadb9c` on
`automation/hh-maintenance`; fetched main remained an ancestor. Reproduced P1
silent successful extraction/checkpointing for non-object candidate members.
The parser now rejects the entire batch instead of skipping such members.
Regression coverage includes null, boolean, number, string and array members,
alone and after a valid candidate, with real HTTP extraction, unchanged persistence,
fresh-process CLI pending counts and successful explicit-empty retries.

Validation: targeted extraction suite passed 19 actual checks with one live-model
SKIP. Full `.venv/bin/python scripts/check_all.py` passed all 30 steps, with four
optional live-model checks SKIP/ENVIRONMENTAL, including cross-process recall and
provenance, ingestion E2E, MCP/security, backup and clean wheel install. Read-only QA
independently verified CLI refusal/retry and fresh-process recall/evidence; security
review found no blocking regression. Python 3.14.7; Linux 7.2.5-3-omarchy x86_64;
AMD Ryzen 9 9950X3D, 32 logical CPUs. Synthetic temporary stores/loopback fixtures,
measured on this shift's diff over the starting SHA; no quality/performance claim.

Remaining: malformed fields inside candidate objects still undergo coercion or
filtering. Next: reproduce malformed object fields advancing progress and define
fail-closed validation without changing deliberate source remapping/control filters.
No schema, trust promotion, installed plugin, live-store or main changes.

## Autonomous maintenance — 2026-09-21

Started clean at `22066f77d76bd1169290a8d50cce22d9c77994f8` on
`automation/hh-maintenance`; fetched main was already an ancestor. Reproduced P1
silent checkpoint advancement after candidate SQL failure and write-quota refusal.
Added opt-in strict Database transactions and atomic per-batch extraction writes.
Evidence, candidates, links, indexes/audit, progress and job counts now commit or
roll back together; model calls stay outside the writer lock. Job creation is checked.
QA exposed silent insert suppression and Security exposed failed job creation;
regressions reproduce both and now pass with persisted-row/link and rowcount checks.
No schema, trust promotion, main, installed plugin or live-store changes.

Validation: extraction suite 19 actual PASS plus one live-model SKIP; E2E suite four
PASS plus one live-model SKIP. Full `.venv/bin/python scripts/check_all.py`: all 30
steps passed, with four optional live checks SKIP/ENVIRONMENTAL (not passes),
including cross-process recall/provenance, MCP, security and clean wheel install.
The extraction suite includes 16 SQL-abort/silent-no-op fault cases, quota rollback,
earlier-batch preservation, fresh-process CLI pending/retry and thread isolation.
Python 3.14.7; Linux 7.2.5-3-omarchy x86_64; AMD Ryzen 9 9950X3D, 32 logical CPUs.
Measured on this shift's diff over the clean starting SHA with invented temporary
stores and loopback fixtures. No performance or general extraction-quality claim.

Remaining: malformed candidate members, concurrent extraction-job coordination,
lossless oversized-turn chunking, and historical partial-write repair. Failed-job
status reporting remains best-effort if the store refuses updates. Next: reproduce
malformed candidate-member output advancing progress and fail closed. See ADR-006.

## Autonomous maintenance — 2026-09-20

Latest shift began at `47c94b43d18c5e5897c968fb7de761130b6fa8e7`, clean on
`automation/hh-maintenance`; fetched main was already an ancestor. The previous
commit fixed malformed response envelopes. This shift reproduced silent loss of
the end of an 801-character extraction turn and replaced prefix truncation with
explicit refusal before POST/checkpointing. Boundary and fresh-process CLI tests
verify intact 800-character Unicode bodies and durable pending oversized turns.
QA independently verified earlier-batch progress survives refusal and retry.
Chunking remains unsupported; existing NUL normalization remains unchanged.
Malformed candidate members and nontransactional candidate/evidence/checkpoint
writes remain open. Next: reproduce candidate-write failure advancing progress
and make batch persistence atomic. No live store/plugin or main branch changed.
Validation: `.venv/bin/python scripts/check_all.py` passed all 30 steps (including
cross-process growth recall/provenance, MCP and clean-wheel installation); four
optional live-model checks were environmental skips. Targeted extraction and E2E
suites also passed, with their live checks skipped. Measured on Python 3.14.7,
Linux 7.2.5-3-omarchy, AMD Ryzen 9 9950X3D (32 logical CPUs), with this shift's
six-file diff over the clean starting SHA. Tests used synthetic temporary stores
and loopback fixture servers; no performance comparison is claimed.

### Earlier retrieval shift

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
