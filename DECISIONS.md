# Engineering decisions

## Nested episode archival audit persistence (2026-10-29)

Verify the episode helper's audit immediately after update_status within explicit
archival's existing transaction rather than altering all standalone status writes.
Snapshot max audit ID before calling the helper, require one fresh row with exact
redacted/capped fields and nonempty timestamp, and route failures through _run to
poison caller transactions. This keeps bool compatibility and quarantine rejection's
transaction ownership; no logger, schema or authorization changes are needed.

Real MCP silent IGNORE reproduced RED 15/16; final MCP 16/16, quarantine 15/15,
independent QA/security review and 31-step gate success (two deliberate live-chat
SKIPs). Regression covers malformed/extra/missing audits, historic matching rows,
rollback, fresh-process evidence recall/retry, outer caught-error poisoning, CLI
rejection and nested reason redaction/capping. This is immediate persistence, not
validation after later audit triggers, protection from privileged SQLite tampering,
authorization race safety, standalone retention guarantees or historical repair.

## Explicit archival audit persistence (2026-10-25)

Verify the explicit forget audit in the existing archival final readback instead
of changing the standalone logger or importing CLI-only checks. Under the writer
lock, snapshot max audit ID after nested helper effects, then require one new row
with exact redacted/capped fields and a nonempty timestamp. Route failure through
_run so caught failures poison caller transactions; standalone bool compatibility
remains unchanged. Silent IGNORE reproduced committed archival (MCP RED 15/16).

Final MCP 16/16 covers both kinds, missing/altered/extra audits, historical matching
rows, exact rollback and fresh-process evidence recall/retry. QA's coverage requests
added exact retry audit, redacted oversized reason and caught audit failure under
caller ownership. A test assumption about the default reason failed and was corrected
to the controller's actual manual-forget default. Quarantine 15/15, independent QA
and security review, and all 31 gate steps passed (two deliberate live-chat SKIPs).
This does not verify nested episode audit insertion, arbitrary nonempty timestamps,
later caller effects, concurrent authorization or historical repair.

## Explicit archival transaction ownership (2026-10-25)

The immediate UPDATE check cannot detect later audit-trigger changes. Real MCP
probes reproduced success with active, evidence-recallable rows after a forget-audit
trigger reversed status. Explicit ForgettingPolicy.archive now owns a writer
transaction unless the current thread already owns one on that same Database;
then it reuses caller ownership without introducing nested transaction semantics.
Status changes, nested episode audit, forget audit and final readback share that
connection. Final verification uses _run so a caught failure still poisons outer
commit. Standalone failures retain the bool API; existing callers own rollback.

Regression RED 14/15 then GREEN; final MCP 16/16 covers audit reversal/removal,
audit ABORT, caller rollback and caught-error poisoning, plus existing UPDATE faults
and evidence-linked fresh-process recall/retry. Quarantine 15/15 passes. QA repeated
initial targeted suites; security static review found no blocker and its coverage
requests were added before the passing 31-step gate (two intentional chat SKIPs).
This does not promise atomic authorization, independent silent audit persistence,
automatic-retention correctness, arbitrary later outer effects or historical repair.
Helpers must share the same Database object, as the controller already ensures.

## Immediate archival status readback (2026-10-25)

Verify the archival UPDATE on its existing connection before commit instead of
introducing nested transaction support. Both belief archival and episode archived
status updates reject a missing/nonarchived result; the existing `_run` rollback
handles standalone use and poisons an existing outer transaction. Quarantine
rejection already owns a transaction, so layering another would break that path.
Nonarchival episode transitions, authorization, audit helpers and purge are unchanged.

Real MCP probes showed ok=true/archived=true with active persisted rows and retained
evidence-linked recall after AFTER UPDATE reversal. Expanded regression RED 14/15,
GREEN 15/15 includes reversal/removal plus IGNORE/ABORT for both kinds. Quarantine
15/15 proves outer-scope compatibility. QA independently repeated both suites;
security static review found no blocker. All 31 gate steps succeeded with temporary
chat-offline configuration and two environmental chat SKIPs; live embedding checks pass.
Immediate status readback is not operation-wide integrity: later audit-trigger mutation,
independent audit suppression, authorization races and purge require separate work.

## MCP archival result envelope (2026-10-24)

Treat controller `archived=false` as an MCP application failure, even without an
error key. Keep the existing error/authorization branch first; do not conflate a
successful tool invocation with successful archival. Limit this change to archival
result translation, retaining purge behavior and standalone persistence helpers.
Regression uses real SDK subprocesses and SQLite IGNORE/ABORT for both kinds,
unchanged row/audit snapshots, evidence-linked recall and successful retry.
RED 14/15 demonstrated `ok=true, archived=false`; final 31-step gate passes with
two deliberate live-chat environmental skips. QA repeated the initial GREEN suite;
security reviewed denial ordering. Later exact-source assertions pass the final gate.
This is not a claim that a helper's true result proves durable archival: AFTER-trigger
reversal, independent audit suppression, races and purge reporting require separate
reproduction. Avoid nested transactions in any follow-up: quarantine rejection already
calls controller.forget inside a Database.transaction scope.

## Rejection guidance correction (2026-10-24)

The planned standalone CLI forget investigation had an invalid premise: there is
no such parser command. The direct rejection handler's purge refusal recommended
that nonexistent command. Correct the error to state archival-only semantics,
rather than implementing a destructive command to make an old message true.
Keep existing controller/MCP APIs and authorization unchanged. Extended existing
regression failed 14/15 on the original error, then passed 15/15 with unchanged
row and real parser rejection checks. All 31 gate steps passed with two deliberate
live-chat environmental skips. Investigate controller/MCP archival persistence
separately; no false-success fix is claimed for those surfaces in this change.

## Rejection audit persistence follow-up to ADR-012 (2026-10-24)

A BEFORE INSERT RAISE(IGNORE) on `quarantine_rejected` reproduced exit-zero
rejection without a new audit despite an exactly matching historical row.
Rejection now reuses the existing checked operator logger inside the archival
writer transaction. Require exactly one newer audit with expected action, target,
redacted/capped detail, session and nonempty timestamp. Failure rolls back archival
and transaction-local audits before returning the existing generic CLI error.
The helper's historical name is retained; no standalone logger, authorization,
MCP, schema, nested helper or denial-path changes are needed.

Regression RED 14/15 then GREEN 15/15 includes eighteen faults across both memory
kinds: IGNORE/ABORT, each checked field, empty timestamp and extra audit insertion.
Target-table/audit snapshots prove rollback; fresh CLI retries prove persisted
archival and new audit. Existing evidence recall and repeated rejection remain
green. QA repeated 15/15 twice and security independently passed 15/15; no blocker.
All 31 shared gate steps succeeded via temporary-XDG chat-offline wrapper, with two
intentional live-chat environmental SKIPs and both synthetic live embeddings PASS.

Scope is immediate explicit rejection-audit persistence, not nested-audit
verification, arbitrary nonempty timestamp corruption, later mutation protection,
or historical repair. Next: reproduce standalone CLI forget archival false success
under suppressed writes before extending these guarantees.

## Quarantine rejection persistence follow-up to ADR-012 (2026-10-24)

Reproduced ignored archival UPDATE returning exit zero with rejected=false, a
false archival note and rejection audit. CLI checked only error, not archived.
An AFTER trigger can also reverse status despite a successful helper return.

Resolve, existing per-record forget authorization, reversible archival, audit and
status readback now share one writer transaction. Require archived=true plus a
persisted archived row; emit success after commit. SQL errors, no-op archival,
missing rows and reversal fail with a generic error and rollback. Standalone
helpers, MCP, schema and provenance semantics are unchanged. Repeated rejection
of archived rows remains supported.

Regression RED 12/13 then GREEN 13/13 covers ten faults across beliefs/episodes,
exact row/audit rollback, fresh CLI retry, durable evidence and second-process
recall. QA independently repeated 13/13 and security 14/14. Security review found
conditional denial-audit rollback with restricted controllers: additional test
reproduced 13/14, then denial handling moved after commit for final 14/14.
All 31 gate steps succeeded via temporary-XDG chat-offline wrapper; two live-chat
checks SKIP/ENVIRONMENTAL, both synthetic live-embedding checks PASS.

This is archival-status persistence, not independent audit INSERT verification,
whole-database trigger integrity or historical repair. Next: reproduce silent
rejection audit suppression before extending that guarantee.


## Operator audit persistence follow-up to ADR-012 (2026-10-23)

An ignored `verify_provenance` audit INSERT reproduced exit-zero promotion without
its audit record. A transaction propagates SQL errors, but SQLite RAISE(IGNORE)
is not an error and the standalone logger has no persistence return value.

Keep that logger unchanged. A CLI-only checked wrapper, called by `verify` and
`quarantine approve` within their existing writer transactions, snapshots maximum
audit ID, calls the logger, and requires exactly one newer row with expected
redacted/capped fields and nonempty timestamp. Promotion readback remains after
this check. Refusal rolls back both promotion and audit with the existing generic
error/exit 1. No schema, MCP, authorization or standalone-helper changes.

Regression failed 11/12 before the fix; final 12/12 includes 27 audit faults across
verify-belief and approve-belief/episode, exact rollback, matching historical rows,
fresh CLI retry and redaction/length-cap compatibility. Existing fresh-process
recall/evidence checks remain green. QA independently ran initial 12/12 and
provenance 6/6; security review found no blocker. Reviewer coverage gaps were
addressed before the final gate: all 31 steps succeeded with chat intentionally
offline (two environmental live-chat skips; both synthetic live embeddings pass).

This checks immediate persistence, not protection against arbitrary SQLite owners,
nonempty timestamp corruption, later-trigger mutation, older audit tampering or
historical repair. Reject and nested helper audit effects remain separate. Next:
reproduce `quarantine reject` false-success behavior under suppressed archival
writes before changing that operator path.

## Standalone verification follow-up to ADR-012 (2026-10-23)

Reproduced `verify` exiting zero and reporting requested `document` provenance
with `rows_changed=0` after an ignored UPDATE. The standalone helper swallows SQL
failures outside transactions; CLI trusted its result and logged success anyway.

Use the existing writer transaction before lookup, preserve the shared promotion
helper, require one updated row, and read back verified/effective class, actor,
channel, original claimed class and unchanged quarantine/status after the audit
call. Commit before success; otherwise roll back and exit 1 with a generic error.
No new schema, capability, dependency, MCP surface or helper behavior change.

Eleven synthetic faults cover IGNORE/ABORT, field alteration, target disappearance
and audit-trigger reversal with row/audit snapshots and fresh CLI retry. Successful
retry audits, operator identity/channel, durable evidence and recall after separate
approval are checked. Active/archived/superseded nonquarantined beliefs support all
three allowed classes without changing lifecycle or quarantine. Repeat verify is
compatible. Independent audit INSERT suppression, arbitrary other metadata, later
mutations and historical repair remain outside this bounded fix.

## ADR-012 — Verify operator quarantine promotion before success (2026-10-22)

The CLI previously treated a failed/no-op promotion as a successful command,
logged `quarantine_approved`, and claimed recall visibility despite `approved=false`.
Episode approval also referenced the belief-only `source_class` column. Reuse
existing commit `8db7566b2dce6387e857d37885096a99af3e7a10` (episode SQL and test)
from `feat/dolphinbench-campaign`; do not duplicate that work or merge its branch.

Use the existing `Database.transaction` writer lock before resolving the row.
Keep operator capability/source-class validation and both promotion helpers;
require rowcount one and read back the expected promotion fields after logging.
Check quarantine, verified provenance, operator actor/channel, unchanged claimed
provenance, and belief effective source class. Commit before printing success.
On failure roll back promotion and audit and return a generic error/exit 1, without
printing database exceptions that could contain stored text. Repeat approvals
remain supported. Approval does not reactivate archived rows or override read policy.

Tests cover both memory kinds with BEFORE IGNORE/ABORT, AFTER individual field
alteration, target disappearance, and an audit-trigger quarantine reversal. Compare
target-table/audit snapshots, then retry and recall through new CLI processes with
durable evidence. This verifies promotion fields, not arbitrary metadata, all-table
integrity or independent audit INSERT suppression. The transaction uses the existing
SQLite locking behavior; no new independent concurrency-barrier test was added.
Standalone `verify`/reject and helper error semantics remain outside this change.
No schema/dependency/MCP additions, historical repairs or production-store access.

## Vector eligible-window follow-up to ADR-011 (2026-10-18)

Vector-only recall could return empty when the raw cosine top-k contained only
other-actor, sensitive, quarantined or retired records. FTS supplementation cannot
recover a query without lexical overlap. Retain raw vector top-k for historical
owner diagnostics and union a separately bounded eligible top-k before assembly.
Both windows share one embedding request and cosine scan. The optional internal
predicate receives joined status/actor/sensitivity/quarantine metadata and calls
existing `may_read`; fetched rows still undergo ordinary downstream authorization.
Orphan vectors remain compatible with raw search but never enter the supplement.
No identity, schema, dependency, MCP surface or stored vector changes.

For positive k, returned candidates are at most 2k, deduplicated by kind and ID.
This is not bounded scan memory/CPU: the existing full-store scan remains, with
additional indexed metadata joins, policy evaluations and an eligible sort.
No comparative timing or live-model relevance claim. Existing zero/negative k
semantics are unchanged, not newly validated. Normalized stored policy labels
work through shared policy rather than SQL-only label matching; this does not
change the existing FTS supplement's noncanonical-label limitation.

Regression proves eight fresh-process synthetic cases with evidence and exactly
one embedding call. Boundary coverage includes both memory kinds, positive-k
bounds/overlap/ties/kind filtering/orphans, owner/system privileges, untrusted
owner-label collisions, own versus third-party quarantine review, archived
exclusion, padded/quoted labels and post-selection sensitivity changes. A record
changed after selection is denied at fetch-time policy checks; this is not a
transactional snapshot guarantee for changes after that final authorization.

## Sensitivity selection follow-up to ADR-011 (2026-10-18)

Six same-actor internal/private/restricted matches could consume both bounded FTS
windows and leave an authorized unclassified memory absent from limit-one recall.
The supplemental query now optionally selects canonical `unclassified` sensitivity
before LIMIT, enabled only for non-owner/non-system callers. Historical search,
operator/system access, quarantine review semantics and downstream `may_read` stay
unchanged. No extra query, schema, dependency or trust promotion is introduced.

Exact stored-label matching is deliberate, as with the preceding actor filter.
Normal writers canonicalize sensitivity; direct-SQL noncanonical labels (including
unknown values normalized by policy to unclassified) retain historical-window
compatibility but are not guaranteed a supplemental slot. No labels are migrated.
This is candidate eligibility, not authorization: a forced sensitive supplemental
candidate is still denied without leaking identifiers or content. Owner and system
supplement-only reads and independent status/quarantine/actor/sensitivity flags
are covered for beliefs and episodes. Fresh-process recall retains evidence.

No general quality, timing-security or comparative performance claim. Vector
candidate limits and noncanonical-label starvation remain outside this change.
Next: reproduce noncanonical stored-label starvation and decide compatibility
semantics before extending selection or changing stored data.

## Actor selection follow-up to ADR-011 (2026-10-17)

Six active nonquarantined other-actor matches filled both FTS windows, hiding
an actor's own durable memory in fresh-process limit-one recall. Restrict the
existing supplemental query by exact actor label for non-owner/non-system
callers before LIMIT. Keep historical queries, owner/system selection, bounded
windows, quarantine review and final may_read authorization unchanged. This is
candidate selection, not a new identity or authorization mechanism.

The optional database actor_id defaults to None (no filter) and uses parameters,
not SQL interpolation. Normal writers normalize stored labels; recall normalizes
the caller using existing policy. Noncanonical labels created by direct SQL can
still miss this supplement despite normalized policy acceptance; historical
search compatibility remains tested. Do not silently migrate stored identities.

Regression covers durable belief/episode recall with evidence, independent flags,
quote-containing labels, padded/invalid callers, untrusted owner-label collisions,
owner/system and legacy identity exemptions, own quarantine review, and private
same-actor supplement-only denial. QA/security found no blocker; lead added their
boundary matrix before the full gate. Same-actor sensitivity crowding, vector
candidate limits, timing security and general recall-quality claims remain out
of scope. No extra query or comparative performance claim.

## Quarantine selection follow-up to ADR-011 (2026-10-16)

Six active quarantined matches filled both FTS windows and hid an approved fact
from fresh-process limit-one owner recall. Extend the existing supplemental query
with opt-in quarantine exclusion before LIMIT, enabled only for normal recall.
Keep its active predicate, historical diagnostic query, downstream actor policy,
review labeling and context budget unchanged. No additional query, schema change,
index deletion or duplicated SQL actor-authorization policy.

The database flag defaults off and is independent of active-only selection.
Regression verifies both kinds, durable fresh-process source provenance, owner
review with existing deduplication, and historical-search compatibility. QA and
security review found no blocker; their exact episode-source and independent-flag
coverage recommendations were added before the full gate. Other-actor/sensitivity
crowding, vector budgets, timing security and general retrieval quality remain
outside scope. No comparative performance claim.

## ADR-011 — Reserve an active FTS recall window (2026-10-13)

Reconciliation legitimately retains archived duplicate rows in the FTS history.
Filtering status only after the bounded FTS query allowed those rows to consume
all candidates and hide a durable active fact. Keep the historical query and its
owner-only exclusion diagnostics, then supplement with a second query selecting
active beliefs/episodes before LIMIT. Each window is bounded at twice recall's
limit; existing kind/id deduplication, policy partition, ranking and context budget
remain in force. The optional database query flag defaults off so semantic/graph
callers retain historical behavior. No index deletion or schema migration.

This pays for one additional FTS query rather than discarding diagnostics or
iterating unbounded history. It does not prevent active unauthorized/quarantined
matches from consuming the active window, change vectors, establish constant-time
non-enumeration, or claim measured performance improvement. Verify actual CLI
archival and second-process recall/evidence, episode status selection, historical
compatibility, external actor denial, quarantine review and overlapping-hit dedupe.

## Audit persistence follow-up to ADR-009 (2026-10-05)

Reproduced an ignored explicit reconciliation audit INSERT committing effects and
an applied decision. Keep Database.log_mutation and nested helper compatibility:
a reconciliation-only wrapper snapshots the maximum audit ID under the existing
writer lock and verifies exactly one new row, its expected redacted/capped fields,
and a nonempty timestamp. A historical matching row cannot satisfy this check.
Missing/altered/extra rows refuse and roll back the entire job, including earlier
candidates. Cover success and both denial paths (which target the matched belief),
IGNORE/ABORT, detail/session/timestamp faults, extra rows, fresh CLI retry, and
redaction compatibility. This is immediate verification of explicit reconciliation
logs only, not nested helper audit validation, later-trigger integrity or repair.

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
