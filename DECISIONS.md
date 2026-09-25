# Engineering decisions

## ADR-008 — Refuse unapproved reconciliation effects on established beliefs (2026-09-25)

The integrated baseline's tests encoded two unsafe effects: a quarantined candidate
reinforced an operator-attested belief and attached unreviewed evidence; another
retired a nonquarantined lower-confidence belief. Corrected those assertions first
and observed both fail before adding narrow candidate/target quarantine checks.

Refuse reinforcement and supersession into nonquarantined targets while the source
candidate is quarantined. Keep the candidate active for review, retain evidence,
audit denial and persist classification with `applied=false`. Preserve classifier
counts, decision idempotency, operator correction APIs and quarantine-to-quarantine
aggregation. Approval promotes the candidate, not replay of an old denied effect.
No schema, migration, dependency, MCP or production-store changes.

Tests cover durable import/extract -> CLI reconciliation -> second-process recall
and visible evidence, plus a three-candidate quarantine-only chain. QA found no
blocking serial-path regression. Security identified an existing approval race;
the lead independently reproduced an operator approval between target read/write
followed by supersession using stale quarantine state. This shift does not claim
concurrent-approval safety: next work is atomic fresh checks/effects/decision writes
with an approval-interleaving regression. Avoid concurrent review and reconciliation
until then. Historical contamination, contradiction/update metadata effects and
broad reconciliation crash/concurrency semantics remain separate work.

## ADR-007 — Refuse stale overlapping extraction batches (2026-09-25)

Two independent extractors paused after reading the same pending turns both wrote
candidates and reported success when resumed in order. Per-batch atomicity did
not invalidate a pending snapshot read before a slow model call; the job-local
claim cache also missed the other process's writes. A stale smaller batch could
replace a later checkpoint with its own earlier endpoint.

Re-read source/session progress inside the existing BEGIN IMMEDIATE transaction,
before evidence/candidate writes. If progress covers the batch's first turn, reject
the whole stale batch with an explicit retry error. Do not silently trim the batch:
a candidate may cite both already-processed and remaining turns. The failed job
keeps earlier committed batches; retry recomputes pending work. Independent sessions
remain independent. No schema, lock file, dependency, trust or MCP changes.

This deliberately permits duplicate model calls, not duplicate persistence of the
same pending batch. It does not guarantee global claim deduplication across different
conversations or repair historical duplicates. Six regression cases use separate
processes and deterministic model barriers for both candidate kinds and equal,
shorter/longer batch overlaps; fresh CLI pending counts and retry verify durability.
Read-only QA additionally exercised earlier committed batches and disjoint sessions.

## ADR-006 — Commit extraction persistence per batch (2026-09-21)

Injected candidate-insert failure and a real write-quota refusal both reproduced
successful checkpoint advancement without the requested memory. Separate `_run`
connections committed evidence and candidates independently and swallowed SQL errors.

Add an opt-in, thread-local transaction scope on Database: one BEGIN IMMEDIATE
connection for existing read/write helpers, exceptions propagate, and a caught SQL
error still poisons the transaction. Other callers keep legacy standalone semantics.
Wrap each extraction batch's evidence, candidates, links, indexes, audit, progress
and job-count writes together; do not hold the writer lock over model requests.
Explicit candidate refusals abort instead of becoming successful skips. Job creation
runs in its own checked transaction. Verify persisted candidates and evidence links,
and require checkpoint/job updates to affect a row: a silent SQLite RAISE(IGNORE)
was independently shown to defeat exception-only checks.

No migration, dependency, trust promotion, production-store repair or deletion.
Earlier successful batches survive failure. Failed-job status is best-effort when
the database refuses all updates. Concurrent extraction-job coordination and malformed
candidate-member validation remain separate work; this is not a claim of exactly-once
processing across simultaneous extractors. Regression coverage includes both candidate
kinds, abort/no-op faults, quota refusal, retry, thread isolation, caught exceptions,
interrupt rollback and fresh-process pending counts.

## ADR-005 — Refuse oversized extraction turns without checkpointing (2026-09-20)

A synthetic 801-character turn reproduced successful extraction of only an
800-character prefix while checkpointing the entire turn. Replace truncation
with an explicit batch failure before the completion request. Preserve the
existing 800-character prompt-body limit (after existing NUL removal), canonical
content and turn-level evidence; do not introduce chunk IDs or schema changes.
Earlier successful batches remain checkpointed; the refused batch and later
turns remain pending across processes. Automatic lossless chunking is deferred,
so retries remain blocked at the same oversized turn. Do not edit original
history or clear checkpoints to work around this limitation. This does not
recover turns already checkpointed by older versions.


## ADR-004 — Correct BM25 polarity without retuning retrieval (2026-09-20)

The growth fixture reproduced 0/3 despite FTS returning the precise belief first.
SQLite BM25 is negative-is-better, so the relevance maximum discarded its score.
Invert the sign, retaining the existing /10 scale, weights, policy partition and
context budgets. Do not introduce corpus-dependent normalization or broaden the
candidate window without separate regression evidence. The growth regression
now passes through a second interpreter with durable provenance. Synthetic
results and limits are in `docs/maintenance-retrieval-2026-09-20.md`.


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
