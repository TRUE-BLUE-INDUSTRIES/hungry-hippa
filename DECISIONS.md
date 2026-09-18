# Engineering decisions

## ADR-001 — Reuse reviewed ingestion slices; defer model extraction (2026-09-18)

Evidence: main v1.0.0 only parses exports. Existing commits `1221b16` and `b25d715`
add canonical tables and explicit CLI writes. Later extraction checkpoints even
when malformed model output parses as an empty result and truncates each turn to
800 characters; reconciliation can strengthen or supersede memory before approval.

Decision: reuse the two foundational commits and harden their boundaries. Keep
later branches intact for repair; do not release their end-to-end claims. No model
provider replacement or broad architecture rewrite. Success means repeatable,
verified import and recovery on synthetic evidence, measured independently of recall.

## ADR-002 — Retain exact bytes and archive membership in SQLite (2026-09-18)

Evidence: the prototype parsed, hashed and copied through separate file opens;
conversation upsert changed the archive pointer while first-write-wins turns kept
old contents. A path/hash pointer alone cannot recover a removed export or ensure
that normalized rows came from the hashed bytes.

Decision: read one bounded immutable byte snapshot; parse, hash and validate that
snapshot; transactionally store it in a separate raw table. Preserve per-export
conversation snapshots and many-to-many turn/archive membership. Reject conflicting
canonical identities instead of silently discarding either claim. Existing archive
reimports are no-ops; the latest distinct import controls the current branch view.

Migration: additive schema v7; v6 rows are not silently trusted/backfilled. Reimport
original bytes to verify them. Later experimental branches already use their own
v7/v8; rebase those migrations before integration. Never mix those branch databases.
Costs: source bytes increase database/backup size. Enforce input/lineage/storage
budgets, benchmark bytes per message and throughput. Tests cover file replacement,
transaction rollback, multiple sources, tampering, migration and SQLite recovery.
Hashes prove consistency, not provider authenticity or same-user tamper resistance.

## ADR-003 — One verification runner and measured claims (2026-09-18)

Evidence: CI's duplicated list omitted the Hippo-Pot suite and orphan-test guard.
The published synthetic eval does not represent imported-history QA; growth recall
has failures and its historical clean-tree note disagrees with its dirty flag.

Decision: CI invokes the shared runner; validate an installed wheel outside the
checkout. Add a separate deterministic ingestion benchmark with all runs, commit,
code digest, dirty status, hardware and limits. Keep dataset-backed recall evaluation
as explicit future work. Do not present smoke tests as proof of general security or
state-of-the-art memory quality.
