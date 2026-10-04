# Engineering decisions

## Contradiction persistence follow-up to ADR-009 (2026-10-04)

Reproduced a silent candidate contradictions UPDATE committing an applied decision.
Keep standalone semantic helper compatibility: reconciliation reads back both full
lists against its existing writer-locked snapshots after the helper returns.
Do not require an UPDATE count because already-linked pairs legitimately tolerate
ignored redundant updates. Missing links or prior-entry loss must roll back the
whole job, including earlier candidates. Test both rows with ABORT/IGNORE and
AFTER-trigger reversal/prior loss, plus CLI refusal/retry and asymmetric/prelinked
compatibility. This is immediate effect verification, not final commit-time
integrity against later triggers, audit validation or historical repair.

## ADR-010 — Reuse the existing demo portability fix (2026-09-27)

The scratch-TMPDIR transcript mismatch reproduced on maintenance at 414d4b7.
Another branch already contained a narrow fix (75b4e85) and its shared-resolver
correction (test-only portion of 953d6e8). Integrate those changes only, retaining
the original golden transcript and scratch location. Do not merge unrelated
runtime, model-default, version or encryption work to unblock a demo gate.
The normalizer self-check is wired into the common test runner. The full 31-step
gate succeeds with temporary-XDG chat explicitly offline; two live-chat checks
remain environmental skips, not evidence of live extraction success.

## ADR-009 — Serialize reconciliation checks, effects and decisions (2026-09-25)

The ADR-008 residual race reproduced at 935ab8e: approving a target after its
snapshot read still allowed unreviewed reinforcement/supersession. Reuse the
existing strict Database transaction, starting BEGIN IMMEDIATE before pending and
comparison reads and holding it through the whole job. Public apply_decision locks
its own fresh reads/effects and requires semantic/graph helpers to share that exact
Database instance. The internal locked helper avoids nested transactions.

A whole-job transaction is intentionally smaller than adding per-candidate refresh,
reservation or retry machinery. It contains no model/network calls. Concurrent
writers wait or receive SQLite busy errors; no throughput improvement is claimed.
Dry-run is advisory. SQL exceptions roll back all effects and the job row, so failure
status is not durable. Decision IDs are read back before commit: reviewers and the
lead reproduced silent RAISE(IGNORE) insertion committing effects without a decision;
missing persistence now raises and rolls back, including earlier candidates.

Follow-up job fault tests reproduced success despite suppressed INSERT or completion
UPDATE. Require creation row existence and exact completion fields inside that same
transaction. ABORT/IGNORE on both writes must restore the pre-job snapshot, including
prior running-job status, and fresh CLI retry must produce one completed job with
matching decisions/counts. Do not change standalone helper error behavior or add a
separate failure-status transaction; failed jobs still roll back entirely.

A further status-write regression reproduced success despite ignored archival.
Keep the fix scoped to reconciliation's status helper: require one affected row
and read back the requested status before proceeding. Duplicate/reinforcement
archival and unprotected supersession share this check. ABORT, IGNORE and
AFTER-trigger reversal fixtures must restore earlier job effects and support fresh
CLI retry. This does not change standalone semantic helpers or promise detection
of every suppressed graph/evidence/metadata write.

Evidence-link follow-up reproduced false success when the second reinforcement
link INSERT was ignored. Wrap only reconciliation's link calls with expected-ID
membership readback in the same writer transaction. Do not require positive INSERT
rowcount: duplicate links legitimately already exist. ABORT/IGNORE regressions
must restore earlier links and whole-job effects, refuse in a fresh CLI process,
and retry idempotently. This preserves standalone helper compatibility and trust
checks. Immediate readback does not detect later triggers removing checked links
or validate every confidence, graph, audit or metadata effect.

Reinforcement follow-up (2026-09-28) reproduced false success on an ignored
confidence/count UPDATE. Check the shared helper's persisted row against the
pre-write confidence (capped at 0.98) and count plus one in reconciliation only.
The helper returning a row is not proof it changed. ABORT/IGNORE and independent
AFTER-trigger field reversals must roll back the whole job; capped confidence
still requires a count increment. Fresh CLI refusal/retry and idempotency preserve
standalone compatibility. Timestamp writes, later-trigger changes, graph/audit
suppression and historical repair remain outside this check.

Relationship-INSERT follow-up (2026-09-28) reproduced ignored graph writes being
reported as applied. Read back the allocated relationship ID and expected endpoints,
type, confidence, status, provenance and validity fields within reconciliation's
existing transaction. Route SUPERSEDES creation through the same wrapper while
preserving its explicit valid_from. Keep the shared graph API and graph=None behavior
unchanged. Four classification paths cover ABORT/IGNORE/AFTER provenance alteration,
including the second contradiction edge, whole-job rollback and fresh CLI retry.
This is immediate row verification, not final commit-time integrity: entity writes,
retirement UPDATEs, other metadata/audit suppression and later mutations are deferred.

Derivation metadata follow-up (2026-10-04) reproduced successful supersession with
an ignored derived_from UPDATE. Read back the whole expected list, not only the new
link: prior provenance must survive too. Permit ignored idempotent UPDATEs when the
expected list already exists. Update/supersession fault tests cover IGNORE, ABORT,
AFTER reversal and loss of prior entries, whole-job rollback and fresh CLI retry.
Keep this inside the existing transaction and reconciliation helper. It does not
repair historical rows or detect later writes invalidating earlier checks.

Tests cover four cross-process approval interleavings, approval committed first via
CLI, split-Database helper rejection, ABORT/IGNORE on the second decision, complete
row rollback and fresh-process CLI retry. Existing import/extract/CLI/recall tests
retain visible evidence. No schema, dependency, MCP, live-store or plugin changes.
This closes the demonstrated approval race, not every reconciliation trust issue:
contradiction/update metadata, historical contamination, arbitrary trusted-Python
classification construction, silent suppression of other writes and large-job lock
contention remain separate work.

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
