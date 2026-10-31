# Project state

Updated 2026-10-31. Git is authoritative for code; no live store or deployed MCP
configuration was changed during this implementation cycle.

## Autonomous maintenance — atomic compression status, 2026-10-31

Started clean at `b8054b48fc025bae490f1a61dc6b807c12904a9a` on
`automation/hh-maintenance`; origin/main remains an ancestor. A refused second
source-status UPDATE reproduced false compression success (RED 19/20). Compression
now creates its summary and retires sources under one owned/reused writer transaction,
then checks summary existence/active status and all source updates/statuses after
audits. Standalone failure rolls back the group; caller-owned failures propagate
and poison commit. No schema or grouping-policy changes.

Final memory architecture 21/21; QA independently ran initial 20/20 and MCP 16/16.
Added QA-requested evidence fixtures, summary faults, post-audit mutations, caller
rollback/poisoning and independent-group progress. Security static review found no
introduced blocker. All 31 full-gate steps succeeded using the unchanged temporary-XDG
chat-offline wrapper; two live-chat checks SKIP/ENVIRONMENTAL. Gate covers CLI,
second-process durable evidence recall, MCP, ingestion, trust/security, backups,
vectors and wheel installation. Python 3.14.7; Linux 7.2.5-3-omarchy x86_64;
Ryzen 9 9950X3D, 32 logical CPUs. Gate ran the two code/test changes over starting SHA.
No live memory, plugin, server/config, cron or main changes.

This verifies group status persistence, not silent audit INSERT persistence,
eligibility races, later caller mutations or historical repair. Existing automatic
compression grouping ignores actor/quarantine/sensitivity metadata; security review
flagged a possible trust-boundary promotion. Highest-priority next action: reproduce
quarantined/restricted source content becoming a default-readable compression summary
on invented stores before designing a narrowly scoped isolation fix.

## Autonomous maintenance — decay ownership coverage, 2026-10-31

Started clean at `9afac72dde9429f86a05ab9e1fa47589afc0c4a9` on
`automation/hh-maintenance`; fetched origin/main remains an ancestor. Closed the
previous shift's unexecuted ownership probe with a permanent regression. No new
runtime failure reproduced: the existing transaction poisoning correctly rolls
back earlier decay when a caller catches a later persistence exception. Without
an outer transaction, the earlier independent decay remains committed. Retry and
repeat checks pass in both modes. No runtime or schema changes were needed.

Memory architecture baseline 18/18, expanded 19/19. All 31 broad-gate steps
succeeded via the unchanged temporary-XDG chat-offline wrapper, including MCP
16/16, cross-process durable evidence recall, CLI, ingestion and wheel installation.
Two live-chat checks SKIP/ENVIRONMENTAL, not PASS. Python 3.14.7; Linux
7.2.5-3-omarchy x86_64; Ryzen 9 9950X3D, 32 logical CPUs. Gate ran with only the
test file dirty over starting SHA. No production memory, live config or plugin
changes. Inline Python and execute_code were policy-blocked before execution;
ordinary script execution and all tests succeeded without changing approval policy.

This covers an AFTER-trigger importance reversal on the second episode, not
whole-pass atomicity without caller ownership or later caller mutation. Next:
reproduce automatic episode compression under a refused source-status update on
invented stores before deciding whether a runtime change is warranted.

## Autonomous maintenance — importance decay persistence, 2026-10-31

Started clean at `ee9f8c504fb99ed293ed0614fc547b5365f70950` on
`automation/hh-maintenance`; origin/main remains an ancestor. An AFTER UPDATE
importance reversal reproduced false decay success (RED 17/18). Rowcount alone
proved a matched UPDATE, not its persisted result. Read back importance, exact
update timestamp and active status inside the same write callback; mismatch raises
and rolls back instead of counting success. No schema or decay-factor change.

Memory architecture GREEN 18/18 and MCP 16/16 independently repeated by QA; no
in-scope blocker. All 31 gate steps succeeded with the unchanged temporary-XDG
chat-offline wrapper; two live-chat checks SKIP/ENVIRONMENTAL. Includes CLI,
cross-process durable evidence recall, ingestion, trust/security, backup/integrity,
vectors and clean wheel installation. Python 3.14.7; Linux 7.2.5-3-omarchy x86_64;
Ryzen 9 9950X3D, 32 logical CPUs. Gate ran code/tests over starting SHA with two
files dirty before bookkeeping; no live store/plugin/config or main modifications.

Regression covers IGNORE/ABORT, AFTER importance/timestamp/status reversal and row
removal, exact episode rollback, retry and repeat. QA's separate ownership probe
was policy-blocked; ownership propagation was inspected, not independently tested
for decay. Immediate readback is not protection against later trigger/caller
mutations, whole-pass atomicity or historical repair. Next: add a focused decay
caller-owned caught-error rollback regression before extending ownership claims.

## Autonomous maintenance — importance decay stale selection, 2026-10-30

Started clean at `8cd184975f86e777ef01e876415f10cf1e5f1665` on
`automation/hh-maintenance`; fetched origin/main remains an ancestor. Importance
decay overwrote a committed high-value promotion using its earlier selection
(RED 16/17). A conditional UPDATE now requires active status and unchanged
importance/update timestamp; unmatched updates are not counted. No schema,
authorization, decay-factor or live configuration change.

Memory architecture GREEN 17/17 and MCP 16/16 independently repeated by QA; no
in-scope blocker. All 31 gate steps succeeded through the unchanged temporary-XDG
chat-offline wrapper, with two live-chat checks SKIP/ENVIRONMENTAL. Gate includes
CLI, durable cross-process evidence recall, ingestion, trust/security, vectors,
backup/integrity and wheel installation. Python 3.14.7; Linux 7.2.5-3-omarchy x86_64;
Ryzen 9 9950X3D, 32 logical CPUs. Gate ran the two changed code/test files over
starting SHA before bookkeeping.

Regression uses independent committed SQLite connections to change high/medium
importance, timestamp and status after selection, verifies exact row preservation,
then retries and repeats. It is not a two-process competing-decay test or proof
of AFTER-trigger persistence, caller-owned rollback, compression safety or historical
repair. Next: reproduce decay success after an AFTER-update importance reversal
on an invented store before extending persistence guarantees.

## Autonomous maintenance — retention eligibility serialization, 2026-10-30

Started clean at `4bb9ffe2d09fb62e1053e42757d5ce83f538561f` on
`automation/hh-maintenance`; origin/main remains an ancestor. A committed importance
promotion after candidate selection was ignored and the high-value episode archived
(RED 14/15). Recheck active status, importance and last access under the existing
writer transaction before verified archival; preserve per-episode ownership and
caller-owned transaction reuse. No schema, trust-rule or live configuration change.

Final memory architecture 16/16 and MCP 16/16 pass in the full gate; QA independently
repeated both. Security static review found no blocker. All 31 gate steps succeeded
using the unchanged temporary-XDG chat-offline wrapper; two live-chat checks are
SKIP/ENVIRONMENTAL. Includes durable cross-process evidence recall, CLI, ingestion,
backup and wheel install. Python 3.14.7; Linux 7.2.5-3-omarchy x86_64; Ryzen 9 9950X3D,
32 logical CPUs. Gate ran implementation/tests over starting SHA, two files dirty.

Regression covers committed importance/access/status changes, no false audits,
retry/repeat, and second-process writer exclusion after the locked read in owned
and reused transactions, with recovery after commit. Lock starts one read earlier.
This is automatic archival eligibility, not whole-pass concurrency, later trigger
or outer-caller integrity, or historical repair. Next: reproduce importance decay
using stale eligibility after concurrent importance promotion on invented stores.

## Autonomous maintenance — automatic retention transactions, 2026-10-30

Started clean at `8df941fd7e39c3b287cb75a338ef5292ad88f67e` on
`automation/hh-maintenance`; origin/main remains an ancestor. Automatic retention
reported success after an audit trigger restored active status (RED 12/13).
Status and audit operations were separately committed. Retention now reuses the
existing verified archival transaction, with no new schema or permission path.

Targeted GREEN 14/14 covers both audit-trigger reversals, exact rollback, retry,
independent-item partial success and caller-owned caught-error rollback. QA repeated
initial 13/13 and MCP 16/16; its requested ownership regressions were added and
passed. Security source review found no blocker. All 31 gate steps succeeded via
unchanged temporary-XDG chat-offline wrapper: two live-chat checks intentionally
SKIP/ENVIRONMENTAL. Gate includes CLI, real MCP, cross-process durable evidence
recall, ingestion, backup and wheel installation. Python 3.14.7; Linux
7.2.5-3-omarchy x86_64; Ryzen 9 9950X3D, 32 logical CPUs. Gate ran code/tests over
starting SHA with two files dirty, before this bookkeeping.

Automatic archival remains opt-in. Each standalone episode commits independently;
caller-owned transactions propagate failure and roll back together. Nested audit
reason is now `unused` rather than `unused beyond retention policy`; explicit
forget audit detail is unchanged. No live store/plugin/main/config changes.
Selection still precedes locking; later caller effects, later mutations of earlier
verified audit rows and historical repair remain outside scope. Next: reproduce
retention eligibility changes between selection and archival using invented stores.

## Autonomous maintenance — automatic retention result counts, 2026-10-30

Started clean at `afd2eb30e8d93d96e371a5549166069c02582569` on
`automation/hh-maintenance`; fetched origin/main remains an ancestor. Automatic
retention ignored update_status's false return: SQLite IGNORE left an episode
active while the pass counted it and wrote a successful forget audit. Regression
RED 11/12 reproduced two claimed archives where only one persisted.

The retention loop now skips the success audit/count when the existing status
helper returns false. GREEN 12/12 covers IGNORE and ABORT, mixed success/failure,
unchanged high-value protection, retry and no-op repeat. All 31 gate steps succeeded
via the existing temporary-XDG chat-offline wrapper; two live-chat checks are
intentional SKIP/ENVIRONMENTAL, not live-chat passes. Gate includes real MCP and
fresh-process evidence recall, CLI, ingestion, backup and wheel-install checks.
Python 3.14.7; Linux 7.2.5-3-omarchy x86_64; Ryzen 9 9950X3D, 32 logical CPUs.
Gate ran code/tests over the starting SHA with those two files dirty, before this
bookkeeping. No specialist needed for this deterministic return-value guard.

Automatic archival remains opt-in and is not newly transactional with its audits.
This fix does not verify audit persistence, later-trigger integrity, retention
selection races or historical repair. No live store/plugin/main/config changes.
Next: reproduce automatic-retention audit-trigger status reversal before deciding
whether retention needs the explicit archival transaction path.

## Autonomous maintenance — archival authorization serialization, 2026-10-29

Started clean at `40e787b4c3aa813f7598bf6a8c66c27fb1f7ae89` on
`automation/hh-maintenance`; fetched origin/main remains an ancestor. A second
process promoted a belief after the agent's policy snapshot but before archival:
the protected belief was still archived (confused-deputy RED 6/7). Both controller
archival entry points now acquire BEGIN IMMEDIATE before authorization or reuse
an existing caller transaction. Purge and policy rules are unchanged.

GREEN 7/7 covers both APIs, owned/reused transactions, blocked competing promotion,
post-commit writer recovery and denial of prior promotion with unchanged row/audit.
MCP 16/16 and quarantine 15/15 include cross-process durable evidence recall and
fault rollback. Independent QA repeated all three; security source review found
no blocker. Added QA-requested outer-transaction denial coverage. All 31 gate steps
succeeded via unchanged temporary-XDG chat-offline wrapper: two intentional live-chat
SKIP/ENVIRONMENTAL checks; both live synthetic-embedding checks passed.
Python 3.14.7; Linux 7.2.5-3-omarchy x86_64; Ryzen 9 9950X3D, 32 logical CPUs.
Gate ran implementation/tests/docs over starting SHA before this bookkeeping.

No production store/plugin/main/config changes. Writer lock is held slightly earlier;
contention has the existing generic failure shape. This is not exhaustive policy-field
race coverage, later-trigger/outer-caller integrity, retention or historical repair.
Next: reproduce automatic-retention archival success counting under refused SQLite
updates on invented stores before selecting a follow-up fix.

## Autonomous maintenance — nested episode archival audit, 2026-10-29

Started clean at `55b8c573cc6c2c114c4b20db46a07aa057818eb9` on
`automation/hh-maintenance`; fetched origin/main remains an ancestor. Native flock
resolved the prior lock-launch blocker without changing unattended approval policy.
Real MCP regression reproduced committed episode archival when its nested audit
INSERT was silently ignored (RED 15/16). The transaction caught exceptions but
only verified the later explicit forget audit, not the episode helper's audit.

Explicit episode archival now checks one fresh intact nested audit inside the same
writer transaction. Standalone status helpers, automatic retention and authorization
are unchanged. MCP GREEN 16/16 and quarantine 15/15; independent QA repeated both,
security found no blocker. Added their requested nested caught-error transaction
poisoning, CLI rejection rollback and redacted/capped nested-reason readback checks.
Final 31-step gate succeeded through unchanged temporary-XDG chat-offline wrapper;
two optional live-chat checks SKIP/ENVIRONMENTAL. Gate includes cross-process durable
SQLite/evidence recall and retry, ingestion, install, security and backup suites.
Python 3.14.7, Linux 7.2.5-3-omarchy x86_64, Ryzen 9 9950X3D, 32 logical CPUs.
Gate ran code/tests/docs over starting SHA before state/decision bookkeeping.

No live memory/plugin/main/config changes. Immediate audit readback is not later
trigger integrity, timestamp authenticity, historical repair or an authorization
race fix. Next: reproduce concurrent authorization changes between archival policy
check and writer transaction using invented stores before selecting another fix.

## Autonomous maintenance — explicit archival audit persistence, 2026-10-25

Started clean at `48b50813ffc6cc82988791a06d2f9498b561677f` on
`automation/hh-maintenance`; fetched origin/main remains an ancestor. Real MCP
regression reproduced committed archival despite silently ignored forget-audit
INSERT (RED 15/16). The existing transaction caught exceptions but not no-op inserts.
Explicit archival now verifies one fresh audit with exact redacted/capped fields
and nonempty timestamp inside its existing final readback; failure rolls back.
Standalone logger, nested episode audit and authorization remain unchanged.

MCP GREEN 16/16 and quarantine 15/15; QA independently repeated both and security
repeated MCP with no blocker. Added QA-requested exact retry audit, reason redaction/
cap and caught audit-failure outer rollback coverage. Initial strengthened assertion
incorrectly expected an empty reason (15/16); corrected fixture and expectation to
actual `manual forget` default. Final MCP 16/16 and all 31 full-gate steps succeeded.
Temporary XDG chat-offline wrapper: two live-chat SKIP/ENVIRONMENTAL checks; both
synthetic live-embedding checks PASS. Baseline confused-deputy 6/6. Python 3.14.7,
Linux 7.2.5-3-omarchy x86_64, Ryzen 9 9950X3D, 32 logical CPUs. Gate tested code/tests
over starting SHA before docs updates. Only invented temporary stores used.

No live memory/plugin/main/config changes. Not tamper-proof logging or validation
of nested audit suppression, later caller effects, authorization races or historical
repair. Next: reproduce nested episode_archived audit suppression in explicit
archival before deciding whether that separately promised audit needs verification.

## Autonomous maintenance — archival audit effects, 2026-10-25

Started clean at `c95e042e2daf344d48fee5c89d35991be6984b84` on
`automation/hh-maintenance`; origin/main remains an ancestor. Real SDK probes on
invented stores reproduced both memory kinds returning archival success after a
forget-audit trigger restored active status; fresh processes still recalled evidence.
The prior UPDATE check ran before separately committed audit effects.

Explicit archival now owns one writer transaction or reuses its caller's existing
transaction, and verifies status after audit calls. Readback failure poisons outer
transactions even if caught. Standalone bool compatibility and quarantine rejection
are preserved; no schema, authorization, purge or automatic-retention changes.
MCP regression RED 14/15, initial GREEN 15/15; QA independently repeated MCP and
quarantine 15/15. Security static review found no blocker. Added their outer-rollback,
caught-failure poisoning and audit-ABORT coverage: final MCP 16/16. All 31 shared
gate steps succeeded using unchanged temporary-XDG chat-offline wrapper; two live-chat
checks SKIP/ENVIRONMENTAL, both synthetic live-embedding checks PASS. Baseline
confused-deputy 6/6. Python 3.14.7, Linux 7.2.5-3-omarchy x86_64, Ryzen 9 9950X3D,
32 logical CPUs. Gate ran implementation/tests over starting SHA before doc updates.

No live store/plugin/main/config changes. This assumes one shared Database object
(as controller construction ensures); it does not verify silent audit suppression,
concurrent authorization, later outer-caller effects or historical repair. Next:
reproduce silently suppressed forget audit insertion through MCP before extending
explicit archival audit-persistence guarantees.

## Autonomous maintenance — immediate archival persistence, 2026-10-25

Started clean at `849b72a63c05a309803cf49da1738ac86756851d` on
`automation/hh-maintenance`; fetched origin/main remains an ancestor. Invented-store
MCP probes reproduced both kinds returning ok=true/archived=true while AFTER UPDATE
triggers restored active status; fresh processes still recalled the evidence-linked
memories. UPDATE rowcount alone was incorrectly treated as proof of archival.

Both archival writers now read status back on the same connection before commit.
Missing/reversed rows raise and roll back via existing `_run`; existing outer
transactions remain supported without nested scopes. No schema or permission changes.
MCP regression RED 14/15, GREEN 15/15; quarantine 15/15; baseline confused-deputy 6/6.
Regression covers both kinds with IGNORE/ABORT/reversal/removal, exact row/audit
rollback, fresh-process provenance/evidence recall and successful retry. QA independently
passed both 15/15 suites; security static review found no blocker. All 31 gate steps
succeeded through the unchanged temporary-XDG chat-offline wrapper; two live-chat
checks SKIP/ENVIRONMENTAL, both synthetic live-embedding checks PASS. Configured live
chat not tested. Python 3.14.7, Linux 7.2.5-3-omarchy x86_64, Ryzen 9 9950X3D,
32 logical CPUs. Gate ran implementation/tests over starting SHA before docs updates.

This is immediate UPDATE-status verification, not later audit-trigger integrity,
audit insertion verification, concurrent authorization or purge correctness. No live
store/plugin/main/config changes. Next: reproduce later audit-trigger archival reversal
through MCP on invented stores before considering a wider atomic operation.

## Autonomous maintenance — MCP archival result honesty, 2026-10-24

Started clean at `14f3d87a1caac83c92c7f01522cb3d23bd70cf06` on
`automation/hh-maintenance`; fetched origin/main is an ancestor. Reproduced
`hippa_forget` returning `ok=true, archived=false` when SQLite ignored an archival
UPDATE. The controller correctly reports false, but MCP checked only error keys.
A three-line archival-only guard now returns the existing failure envelope.
No persistence, authorization, purge, schema, tool surface or live-install changes.

Baseline confused-deputy 6/6; regression RED 14/15; GREEN 15/15 with belief/episode
IGNORE/ABORT cases, unchanged target rows/audits, fresh MCP processes for remember,
recall with evidence and provenance, and retry. QA repeated 15/15 twice; security
static review found no blocker. Strengthened exact evidence/provenance assertions
after QA. Initial gate failed because that test assumed episode provenance was
`document`; corrected to compare with the actual remembered provenance (episodes
currently default to agent_inference). Final all 31 gate steps succeeded via
unchanged temporary-XDG chat-offline wrapper; two intentional live-chat environmental
SKIPs, both live embedding checks PASS. An earlier targeted run also exposed missing
fixture evidence, corrected by explicitly seeding/linking invented evidence.
Python 3.14.7; Linux 7.2.5-3-omarchy x86_64; Ryzen 9 9950X3D, 32 logical CPUs.
Gate tested implementation/tests over starting SHA before documentation updates.

This fixes the response envelope, not durable archival verification, audit integrity
or concurrent authorization. Next: reproduce AFTER-trigger status reversal through
the controller/MCP path before designing a transaction-compatible persistence fix.

## Autonomous maintenance — invalid rejection guidance, 2026-10-24

Started clean at `9cbe1c5340b1d82107086678ad5f212e5db58ac6` on
`automation/hh-maintenance`; origin/main remains an ancestor. The previous next
step assumed a standalone `forget` command, but parser help and source confirm
none exists. Direct quarantine rejection dispatch nevertheless recommended it
when refusing purge. Replaced that nonexistent-command guidance with an accurate
archival-only explanation; no command, permission or persistence behavior added.

Quarantine baseline 15/15, regression RED 14/15 on the misleading error, GREEN
15/15. Extended existing regression checks unchanged archived row and real parser
refusal of `forget --help`. All 31 shared gate steps succeeded via temporary-XDG
chat-offline wrapper; two live-chat environmental SKIPs, both synthetic live
embedding checks PASS. Existing source/evidence-linked fresh-process recall passes.
Python 3.14.7, Linux 7.2.5-3-omarchy x86_64, Ryzen 9 9950X3D (32 logical CPUs).
Simple deterministic wording fix: no specialists needed. No live store, plugin,
main or service configuration changes. The supposed standalone-forget P1 is not
reproducible at that nonexistent surface. Next: reproduce archive false success
through the existing controller/MCP path using invented stores before fixing it.

## Autonomous maintenance — rejection audit persistence, 2026-10-24

Started clean at `8f1cfb70db9eebbbe08808785e34b3750fa9be0a` on
`automation/hh-maintenance`; fetched main remains an ancestor. Reproduced exit-zero
rejection after silently suppressed `quarantine_rejected` audit INSERT. Rejection
now reuses the checked operator logger inside its existing writer transaction;
missing/altered/extra new audits roll back archival and exit 1. Standalone logging,
nested helpers, authorization, schema and MCP are unchanged.

Baseline 14/14; new regression RED 14/15, GREEN 15/15 includes eighteen faults
across both memory kinds, matching historical audits, exact row/audit rollback and
fresh CLI retries. Existing evidence-linked cross-process recall tests pass.
QA independently repeated 15/15 twice; security independently passed 15/15 with
no blocker. All 31 full-gate steps succeeded through temporary-XDG chat-offline
wrapper: two live-chat environmental SKIPs, both synthetic live-embedding checks
PASS. Configured live chat was not retested. Python 3.14.7, Linux 7.2.5-3-omarchy
x86_64, Ryzen 9 9950X3D (32 logical CPUs). Gate measured implementation diff over
starting SHA before documentation updates. No production memory/plugin/main/live
config changes. Immediate explicit audit persistence is not tamper-proof logging
or nested-audit verification. Next: reproduce standalone CLI forget archival
false-success behavior under suppressed writes before proposing a fix.

## Autonomous maintenance — quarantine rejection persistence, 2026-10-24

Started clean at `2c1fe62394ddbf19dfc015294a833343aab2c740` on
`automation/hh-maintenance`; fetched main remains an ancestor. Reproduced exit-zero
rejection with false archival note after ignored archival UPDATE. CLI now locks
resolve/authorize/archive/audit/readback, requires successful helper plus archived
row and commits before success. Failure rolls back with exit 1. Existing helpers,
authorization, reversible archival and MCP unchanged; denied actions retain audits.

Baseline 12/12; archival regression RED 12/13, GREEN 13/13, with ten faults across
both memory kinds, fresh CLI retry/recall and durable evidence. QA repeated 13/13
and security 14/14. Security review's restricted-controller denial-audit concern
reproduced 13/14; corrected and final targeted 14/14 PASS. Full 31-step gate PASS
via temporary-XDG chat-offline wrapper: two live-chat environmental SKIPs, both
synthetic live-embedding checks PASS. Configured live chat was not retested.
Python 3.14.7, Linux 7.2.5-3-omarchy x86_64, Ryzen 9 9950X3D (32 logical CPUs).
Gate measured implementation diff over starting SHA before documentation updates.
No production memory, plugin, main or live config changes. Independent silent audit
suppression and historical repair remain outside this bounded fix. Next: reproduce
rejection audit INSERT suppression; see ADR-012 follow-up.

## Autonomous maintenance — operator promotion audit persistence, 2026-10-23

Started clean at `860bcc72a02cf598cc0f5bea37fa69dd24c88be3` on
`automation/hh-maintenance`; fetched main remains an ancestor. Reproduced P1
standalone verify success despite ignored audit INSERT. Transactions catch SQL
errors but IGNORE silently suppresses insertion; the logger returns no proof.
A CLI-only wrapper now requires exactly one new intact audit under the existing
writer transaction in verify and quarantine approve; failed verification rolls
back promotion with exit 1. Standalone logger, authorization and MCP unchanged.

Baseline quarantine 11/11; new regression RED 11/12, initial GREEN 12/12. QA
independently passed initial 12/12 and provenance 6/6; security static review found
no blocker. Strengthened historical-row freshness, field mutation and redaction/
cap coverage from reviews. Final 12/12 includes 27 audit fault cases across both
memory kinds plus fresh CLI retries; existing cross-process evidence recall passes.

All 31 shared gate steps succeeded through temporary-XDG chat-offline wrapper;
two live-chat checks intentionally SKIP/ENVIRONMENTAL, both synthetic live embedding
checks PASS. Configured live chat not retested; prior model-load failure remains
unresolved. Python 3.14.7, Linux 7.2.5-3-omarchy x86_64, Ryzen 9 9950X3D (32 logical
CPUs). Gate ran implementation diff over starting SHA before documentation updates.
Invented scratch stores only; no live memory/plugin/main/config changes. Bounded
immediate persistence, not tamper-proof logging or historical repair; ADR-012 follow-up.
Next: reproduce quarantine rejection false success under suppressed archival writes.

## Autonomous maintenance — standalone verification persistence, 2026-10-23

Started clean at `84475c5fa4a25d5af17d3979290d5cce8d4c66de` on
`automation/hh-maintenance`; fetched main remains an ancestor. Reproduced P1
`verify` falsely reporting requested provenance with exit zero and rows_changed=0
after an ignored promotion UPDATE. No equivalent fix found in inspected all-ref
verify history. CLI now locks before lookup, uses the existing helper, checks
rowcount and persisted promotion fields after audit, and commits before success.
Failure rolls back with exit 1. Claimed provenance, quarantine and status stay
unchanged; standalone verification does not release or reactivate memory.

Baseline provenance 6/6, quarantine CLI 10/10 PASS. New regression RED 10/11,
then GREEN 11/11 with eleven promotion faults, snapshot rollback, fresh CLI retry
and separate-process recall retaining durable evidence after explicit approval.
QA independently passed initial 11/11 and provenance 6/6; security source review
found no blocker. Added their compatibility gaps: all allowed classes against
active/archived/superseded nonquarantined beliefs, plus successful retry audit and
actor/channel assertions. Final targeted 11/11 PASS.

All 31 shared gate steps succeeded using existing temporary-XDG chat-offline
wrapper; two live-chat checks intentionally SKIP/ENVIRONMENTAL, both synthetic
live embedding checks PASS. Configured live chat not retested; prior model-load
failure is not claimed resolved. Includes install, MCP/trust/security, ingestion,
reconciliation, migrations, vectors, backup, Hippo-Pot, demo and eval checks.
Python 3.14.7; Linux 7.2.5-3-omarchy x86_64; AMD Ryzen 9 9950X3D, 32 logical CPUs.
Gate measured implementation diff over starting SHA before documentation updates.
Invented scratch stores only; no live-memory/plugin/main/config changes.
Next: reproduce independent operator promotion audit INSERT suppression before
extending the guarantee; see standalone verification follow-up to ADR-012.


## Autonomous maintenance — quarantine approval persistence, 2026-10-22

Started clean at `1988f1df838c19dea9c59a9a6460060155712809` on
`automation/hh-maintenance`; fetched main remains an ancestor. Reproduced a P1
operator failure: suppressed promotion exits zero, writes an approval audit, and
claims recall visibility although the row remains quarantined. Ordinary episode
approval also failed because its SQL targeted a nonexistent `source_class` column.
Reused existing `8db7566` from `feat/dolphinbench-campaign` rather than reimplementing
that column fix and its regression.

Approval now locks before resolution, uses the existing promotion helper, requires
one updated row, and reads back quarantine/provenance after its audit, committing
before success output. Failure rolls back and returns exit 1 without database
exception text. The success note no longer promises archived rows become visible.
Standalone helpers, verify/reject, authorization and MCP surface remain unchanged.
See ADR-012 for the bounded guarantee and audit-suppression limitation.

Baseline quarantine 8/8 PASS; existing episode fix 9/9 PASS. New regression failed
9/10 on ignored belief UPDATE, then passed 10/10. Final coverage exercises 19
belief/episode faults, including missing rows and audit-trigger reversal requested
by QA, with row/audit rollback and fresh-process retry/recall retaining evidence.
QA independently passed the earlier 15-fault suite twice; security source review
found no blocker. Their supplemental command probes were policy-blocked, not passes.

Default full gate FAIL: configured live chat model returned HTTP 400/SIGABRT;
only extraction step failed (20/21), with live E2E extraction SKIP/ENVIRONMENTAL.
All 31 final gate steps succeeded through the existing temporary-XDG chat-offline
wrapper: two live-chat checks intentionally SKIP/ENVIRONMENTAL, both synthetic live
embedding checks PASS. Includes install/MCP/trust/limits/migrations/ingestion,
reconciliation 39/39, backup, Hippo-Pot and cross-process evidence paths.
Python 3.14.7; Linux 7.2.5-3-omarchy x86_64; AMD Ryzen 9 9950X3D, 32 logical CPUs.
Tests used invented scratch stores and the implementation diff over starting SHA;
no timing comparison, live configuration change, deployment or main modification.
Next: reproduce standalone `verify` reporting successful provenance after a
suppressed promotion UPDATE before extending the persistence boundary.

## Autonomous maintenance — vector eligible window, 2026-10-18

Started clean at `fc0c01c93b5021bf7a5adb935ce43b9386f037fd` on
`automation/hh-maintenance`; fetched main remains an ancestor, no existing vector
fix found in inspected all-ref history. Promoted the prior external reproducer:
new regression failed with empty fresh-process recall behind other-actor vectors
(11/12). Raw top-k selection happened before status/read-policy filtering.

Recall now unions historical and eligible vector windows, sharing one embedding
and cosine scan. Eligibility reuses status and existing read policy on joined
metadata; fetched records still undergo downstream authorization. Raw vector
search remains compatible. For positive k, at most 2k candidates are returned;
the full scan and additional metadata/policy/sort work are not bounded by k.
See the vector follow-up to ADR-011 for limits and compatibility.

Final vectors 13/13 and oracle 10/10 PASS. Eight synthetic belief/episode cases
verify second-process recall, evidence and one embedding call. QA independently
passed earlier vectors 12/12 twice, oracle 10/10, identity 6/6 and limits 8/8.
Security source review found no blocker. Added their boundary requests: bounded
union/dedup, orphan/tie/kind behavior, identity/review matrix, normalized labels
and actual post-selection restriction followed by downstream denial.
Reviewers' extra command probes were execution-policy-blocked, not passes.

Full unchanged 31-step gate PASS via temporary-XDG chat-offline wrapper; two
live-chat checks intentionally SKIP/ENVIRONMENTAL, both live synthetic embedding
checks PASS. Includes MCP/security, ingest/extract/reconcile/CLI/second-process
recall/provenance, migrations, backups, Hippo-Pot and clean wheel installation.
Configured live chat not retested. Python 3.14.7; Linux 7.2.5-3-omarchy x86_64;
AMD Ryzen 9 9950X3D, 32 logical CPUs. Gate measured implementation diff over starting
SHA before documentation updates, using invented temporary stores only. No timing
comparison, deployment, main, production-memory or installed-plugin changes.
Next: reproduce noncanonical stored-label FTS starvation before changing its
compatibility semantics. Vector zero/negative k behavior remains unqualified.

## Autonomous maintenance — sensitivity FTS candidate window, 2026-10-18

Started clean at `77f052a4a8ab75278c82959e34f35b5ae37af431` on
`automation/hh-maintenance`; fetched main remains an ancestor. No equivalent fix
found in inspected all-ref retrieval history. Reproduced a P1 failure: same-actor
sensitive rows crowd both FTS windows, hiding a durable unclassified fact from
fresh-process limit-one recall. Regression failed with empty items (oracle 8/9).

Supplemental selection now requires canonical unclassified sensitivity for
non-owner/non-system callers before LIMIT. Historical search, downstream policy,
quarantine review and privileged reads remain unchanged. No extra query or schema
change. Noncanonical direct-SQL labels remain a documented compatibility limit.

Baseline oracle 8/8 and architecture 11/11 PASS. Fixed oracle 9/9 and architecture
11/11 PASS. Read-only QA repeated oracle twice and passed architecture/security;
security source review found no authorization regression. Both identified stale
post-selection denial coverage. Added a forced-candidate negative control,
independent query-flag matrix, sensitive owner/system supplement-only reads and
noncanonical historical compatibility: final oracle 10/10 PASS.

Full shared gate: all 31 steps successful through temporary-XDG chat-offline
wrapper; two live-chat checks explicitly SKIP/ENVIRONMENTAL, both synthetic live
embedding checks PASS. Configured live chat not retested; prior environmental
load failure is not claimed resolved. Includes cross-process durable recall with
evidence, ingestion E2E, MCP/auth/security, migrations, backup and wheel install.
Tests used invented scratch stores. Python 3.14.7; Linux 7.2.5-3-omarchy x86_64;
AMD Ryzen 9 9950X3D, 32 logical CPUs. Gate measured the implementation diff over
starting SHA, before documentation updates; no comparative performance claim.
See ADR-011 sensitivity follow-up. Next: reproduce noncanonical stored-label
starvation before deciding compatibility semantics; vector limits are unchanged.

## Autonomous maintenance — cross-actor FTS candidate window, 2026-10-17

Started clean at `0238eb9d3d136a01bb7628670ebbe357d6113c7b` on
`automation/hh-maintenance`; fetched main remains an ancestor. No equivalent fix
found in inspected all-ref recent history. Reproduced a P1 failure: six active,
nonquarantined other-actor matches hide an actor's own durable fact from
fresh-process limit-one recall. The new regression failed with empty items.

Supplemental active FTS selection now restricts non-owner/non-system callers to
their normalized actor label before LIMIT. Owner/system callers, historical
search, quarantine review and downstream read authorization are unchanged.
No extra query, schema change or new dependencies. Exact stored-label matching
is intentional; noncanonical direct-SQL labels remain a compatibility limitation.

Baseline architecture 11/11 and oracle 6/6 PASS; reproduction oracle 6/7 FAIL;
fixed oracle 7/7 and architecture 11/11 PASS. QA independently repeated both twice;
security static review found no blocker. Added review-requested actor/identity,
independent query flags, quoted labels, quarantine review and supplement-only
sensitivity-denial coverage: final oracle 8/8 PASS. Both reviewers' extra inline
probes were execution-policy-blocked, not passing checks.

All 31 shared gate steps PASS via external temporary-XDG chat-offline wrapper;
two live-chat checks SKIP/ENVIRONMENTAL. Configured live chat was not retested.
Offline import/extract/CLI recall retains EV-0001; the new second-process
belief/episode test retains linked evidence and untrusted-data framing.
Python 3.14.7; Linux 7.2.5-3-omarchy x86_64; AMD Ryzen 9 9950X3D, 32 logical CPUs.
Gate measured the implementation diff over starting SHA, before documentation
updates, with invented scratch stores only. No comparative performance claim.
See ADR-011 actor follow-up. Next: reproduce same-actor sensitivity crowding
before extending candidate eligibility; vector limits remain unchanged.

## Autonomous maintenance — quarantine FTS candidate window, 2026-10-16

Started clean at `836194b7b43f274197f3af38b77acbbb1ed1abd3` on
`automation/hh-maintenance`; fetched main remains an ancestor. No equivalent fix
found in inspected all-ref history. Reproduced a P1 failure: six active quarantined
matches hide a durable approved fact from fresh-process limit-one owner recall.
The supplemental active FTS query now excludes quarantine before LIMIT for normal
recall; explicit review, historical diagnostics and downstream authorization stay.

New regression failed with empty recall before the fix. Follow-up fixture failures
were corrected: review legitimately deduplicates identical claims, and episode
provenance uses claimed_source_class/source_refs rather than source_class.
Final architecture 11/11, oracle 6/6 PASS. QA independently passed architecture,
oracle and quarantine CLI 8/8; security review passed architecture/oracle and found
no blocker. Added exact episode-source and independent query-flag coverage from
review before the gate. All 31 shared gate steps PASS via temporary-XDG chat-offline
wrapper; two live-chat checks SKIP/ENVIRONMENTAL, both synthetic live-embedding
checks PASS. Configured live chat not retested. Offline ingestion/CLI recall
retains EV-0001; new belief/episode second-process recall retains the manual source.

Python 3.14.7; Linux 7.2.5-3-omarchy x86_64; AMD Ryzen 9 9950X3D, 32 logical CPUs.
Invented temporary stores only; gate measured this shift's implementation diff over
starting SHA, before documentation updates. No performance comparison or live
configuration/plugin/store changes. See ADR-011 follow-up. Remaining active
other-actor/sensitivity crowding and vector limits are unchanged.
Next: reproduce nonquarantined cross-actor candidate starvation before changing
actor-aware selection.

## Autonomous maintenance — active FTS candidate window, 2026-10-13

Started clean at `0dee2b6a4dbdc7ff907f309a72573b39355a854a` on
`automation/hh-maintenance`; fetched main remains an ancestor. No equivalent fix
found in inspected all-ref history. Reproduced a P1 recall failure: six archived
reconciliation duplicates consume the FTS window, leaving limit-one recall empty
although the established fact and evidence remain durable.

Recall now supplements its historical FTS window with a separately bounded active
belief/episode window whose status predicate precedes LIMIT. Historical index rows,
low-level default search, owner exclusion diagnostics and downstream authorization
are preserved. No schema, reconciliation writes, main or live installation changes.

Targeted reconciliation 39/39, memory architecture 10/10 and existence oracle 6/6
PASS. CLI archival followed by second-process recall returns the fact and provenance.
QA independently passed the first two suites plus trust, supersession and prior
oracle coverage. Security source review found no bypass; its requested supplement-
only external-actor regression was added and passed. Reviewers' extra inline probes
were policy-blocked, not passing checks.

Full shared gate: all 31 steps PASS via external temporary-XDG chat-offline wrapper;
two live-chat checks SKIP/ENVIRONMENTAL, both synthetic live-embedding checks PASS.
Configured live chat was not retested. Python 3.14.7; Linux 7.2.5-3-omarchy x86_64;
AMD Ryzen 9 9950X3D, 32 logical CPUs. Invented temporary stores only; gate measured
this shift's diff over starting SHA. No comparative performance claim. One extra
bounded FTS query is a deliberate compatibility cost; see ADR-011.

Active quarantined/unauthorized matches can still consume the active candidate
window; vector candidate budgeting is unchanged. Next: reproduce active-policy
candidate starvation with an explicit actor before changing eligibility selection.

## Autonomous maintenance — reconciliation audit persistence, 2026-10-05

Started clean at `ba21830c555ef78b472816f9e25fdcbe042aafe3` on
`automation/hh-maintenance`; fetched main remains an ancestor and inspected all-ref
history contains no equivalent fix. Restored lock acquisition via a standalone
scratch holder after inline execution was policy-blocked. Baseline 36/36; new
regression reproduced ignored audit INSERT reporting success (36/37).
Reconciliation now verifies each explicit success/denial audit row under its
existing writer lock; standalone/nested helper logging remains unchanged.

Targeted 38/38 PASS; QA independently repeated earlier 37/37 twice. QA/security
coverage findings addressed: both matched-target denial paths, detail/session/empty
timestamp alteration, extra rows, and redaction/cap compatibility. Security source
review found no blocker; its independent test attempt was policy-blocked.
Full shared gate: all 31 steps PASS via temporary-XDG chat-offline wrapper, with
two optional live-chat checks SKIP/ENVIRONMENTAL (not pass). Cross-process durable
recall/provenance and offline ingestion/CLI recall evidence EV-0001 pass.
Configured live chat not retested; no production memory/config/server changes.

Tests use invented temporary stores only. Python 3.14.7; Linux 7.2.5-3-omarchy
x86_64; AMD Ryzen 9 9950X3D, 32 logical CPUs. Gate measured the implementation diff
over starting SHA; no performance comparison. No main, schema or trust changes.
Nested helper audit suppression, later-trigger mutation, FTS and historical repair
remain outside scope. Next: reproduce reconciliation FTS consistency under status
changes before extending checks.

## Autonomous maintenance — contradiction metadata persistence, 2026-10-04

Started clean at `405976127445e993302d55065af9dec350080ec4` on
`automation/hh-maintenance`; fetched main remains an ancestor. Baseline 34/34;
new regression reproduced successful reconciliation with an ignored candidate
contradiction-list UPDATE (34/35). Both complete lists are now read back against
locked snapshots in the existing writer transaction, retaining prior conflicts.
Standalone semantic APIs, schema, authority and quarantine rules are unchanged.

Targeted 35/35 PASS; QA repeated it twice and security review found no blocker.
Added their prelinked/asymmetric compatibility coverage before final full gate:
reconciliation 36/36 and all 31 steps PASS through temporary-XDG chat-offline
wrapper. Two optional live-chat checks SKIP/ENVIRONMENTAL; both synthetic
live-embedding checks PASS. Durable cross-process recall/provenance and offline
import/extract/recall evidence EV-0001 pass. Configured live chat not retested.

Regression covers both rows with IGNORE/ABORT/AFTER reversal/prior-entry loss,
whole-job rollback including earlier candidates, fresh CLI refusal/retry and
idempotency. Tests use invented temporary stores only. Python 3.14.7; Linux
7.2.5-3-omarchy x86_64; AMD Ryzen 9 9950X3D, 32 logical CPUs; gate measured the
dirty implementation diff over starting SHA. No comparative performance claim.
No main/live-store/plugin/config/server changes. Immediate readback cannot catch
later-trigger mutations; audit/FTS suppression and historical repair remain open.
Next: reproduce suppressed reconciliation audit writes before extending checks.

## Autonomous maintenance — derivation metadata persistence, 2026-10-04

Started clean at `2e61de25bfadb4d86a4116110f3c5fabb18c3d78` on
`automation/hh-maintenance`; fetched main remains an ancestor. No equivalent fix
found in inspected all-ref reconciliation history. Repository lock acquired using
a standalone scratch script after inline execution was policy-blocked.
Baseline 32/32; new regression reproduced supersession success despite an ignored
`derived_from` UPDATE (32/33). Reconciliation now reads back the full expected list
inside its existing writer transaction; missing rows/links or lost prior entries
raise and roll back the job. Existing-link idempotent UPDATE suppression is valid.

Targeted 34/34 PASS; read-only QA repeated the earlier 33/33 suite twice and its
prior-entry/compatibility coverage gaps were added before the gate. Security source
review found no blocker. Full shared 31-step gate PASS through temporary-XDG
chat-offline wrapper: two optional live-chat checks SKIP/ENVIRONMENTAL, both synthetic
live-embedding checks PASS. Cross-process durable recall/provenance and offline
import/extract/recall evidence EV-0001 pass. Configured live chat not retested.

Regression covers update/supersession IGNORE/ABORT/AFTER reversal and prior-entry
loss, whole-job rollback, fresh CLI refusal/retry/idempotency, and existing links.
Python 3.14.7; Linux 7.2.5-3-omarchy x86_64; AMD Ryzen 9 9950X3D, 32 logical CPUs.
Measured this shift's diff over starting SHA using invented temporary stores only.
No performance comparison, schema, main, live-store/plugin/config/server changes.
Immediate readback is not final commit-time integrity against later triggers;
contradiction metadata, other helper suppression and historical repair remain open.
Next: reproduce suppressed reconciliation contradiction metadata writes.

## Autonomous maintenance — reconciliation entity persistence, 2026-09-29

Started clean at `9e6dad32ce0d3a1d88c0cd426fcb3e3da15d1d2e` on
`automation/hh-maintenance`; fetched main remains an ancestor. No equivalent fix
found in inspected all-ref reconciliation history. Baseline 30/30; new regression
reproduced successful reinforcement with a missing entity after INSERT IGNORE
(30/31). Graph edges store endpoint names without foreign-key enforcement;
reconciliation checked the edge but not node existence. It now reads back both
endpoint names under its existing writer transaction, refusing dangling edges.
Standalone graph APIs, schema and trust rules remain unchanged.

Targeted suite reached 31/31; read-only QA independently repeated that twice and
found a misleading second-endpoint comment/fixture for contradiction. Corrected
the fixture and added existing differing-type/property node compatibility coverage.
Final shared gate: reconciliation 32/32, all 31 steps PASS via external temporary-XDG
chat-offline wrapper. Two optional live-chat checks SKIP/ENVIRONMENTAL; both
synthetic live-embedding checks PASS. Cross-process durable recall/provenance and
import/extract/CLI recall evidence EV-0001 pass. Configured live chat not retested.

Regression covers four graph paths with IGNORE/ABORT/AFTER name alteration,
whole-job rollback including earlier candidates and first node, fresh CLI
refusal/retry/idempotency, and exact preservation of existing node rows.
Python 3.14.7; Linux 7.2.5-3-omarchy x86_64; AMD Ryzen 9 9950X3D, 32 logical CPUs.
Measured this shift's diff over starting SHA using invented temporary stores only.
No performance comparison, main, live-store/plugin/config/server changes.
Entity metadata correctness, later-trigger mutations, other metadata/audit/FTS
suppression and historical repair remain outside scope.
Next: reproduce suppressed reconciliation contradiction/update metadata writes.

## Autonomous maintenance — relationship retirement persistence, 2026-09-29

Started clean at `4f4e6473af1748b670c2cc0b6233ed237e831fee` on
`automation/hh-maintenance`; fetched main remains an ancestor. Inspected all-ref
reconciliation history contains no equivalent fix. Baseline 29/29; new regression
reproduced false success when SQLite ignored the second matching edge retirement
UPDATE (29/30). Reconciliation now snapshots matching active edge IDs under its
existing writer transaction, requires the expected update count, and reads back
each edge's superseded status and nonempty valid_until. Empty matches remain valid;
standalone graph helpers, graph=None behavior and trust rules are unchanged.

Targeted 30/30 PASS covers IGNORE/ABORT and AFTER-trigger status/time reversal,
whole-job rollback including earlier candidates, fresh CLI refusal/retry and
idempotency. Read-only QA independently passed twice and identified a vacuous
untouched-row assertion; strengthened it to exact expected-row equality before
final gate. Full shared 31-step gate PASS through temporary-XDG chat-offline wrapper:
two live-chat checks SKIP/ENVIRONMENTAL; both synthetic live-embedding checks PASS.
Cross-process durable recall/provenance and ingestion evidence EV-0001 pass.
Configured live chat was not retested. No production stores/plugins touched.

Python 3.14.7; Linux 7.2.5-3-omarchy x86_64; AMD Ryzen 9 9950X3D, 32 logical CPUs.
Tested this shift's diff over starting SHA using invented temporary stores only.
No performance comparison, schema, main, installed-service or live-config changes.
Arbitrary nonempty timestamp corruption, later-trigger mutations, entity writes,
other metadata/audit suppression and historical repair remain outside scope.
Next: reproduce suppressed reconciliation entity creation before extending checks.

## Autonomous maintenance — relationship INSERT persistence, 2026-09-28

Started clean at `844ebe8b7eccbbeb04c069e6ec922b4f4493b883` on
`automation/hh-maintenance`; fetched main remains an ancestor. No equivalent fix
found in inspected all-ref reconciliation history. Baseline 28/28; new regression
reproduced ignored reinforcement relationship INSERT reporting success (28/29).
Reconciliation now verifies the newly allocated relationship row's expected fields
including source provenance, under its existing writer transaction. SUPERSEDES
creation shares the wrapper; standalone graph API and graph=None stay unchanged.

Targeted 29/29 PASS, covering four classification paths with ABORT/IGNORE/AFTER
provenance alteration, second contradiction edge rollback, full checked job snapshots,
fresh CLI refusal/retry and idempotency. Read-only QA independently passed twice;
security source review found no blocker. QA's additional inline probe was policy-
blocked, not a passing check. Full shared 31-step gate PASS through temporary-XDG
chat-offline wrapper: two optional live-chat SKIP/ENVIRONMENTAL; both synthetic
live-embedding checks PASS. Import/extract/CLI/second-process recall retains visible
EV-0001 evidence. Configured live chat was not retested.

Python 3.14.7; Linux 7.2.5-3-omarchy x86_64; AMD Ryzen 9 9950X3D, 32 logical CPUs.
Tested shift diff over starting SHA using invented temporary stores only. No
performance comparison, main/live-store/plugin/config/server/schema changes.
Entity writes, relationship retirement UPDATEs, other metadata/audit suppression,
later-trigger mutations and historical repair remain outside this bounded fix.
Next: reproduce suppressed reconciliation relationship retirement UPDATEs.

## Autonomous maintenance — reinforcement persistence, 2026-09-28

Started clean at `818ca25ad192779bbf555babc677c155a5a6ecb7` on
`automation/hh-maintenance`; fetched main remains an ancestor. No equivalent fix
found in inspected all-ref reconciliation history. Baseline 27/27; new regression
reproduced false success after SQLite ignored reinforcement UPDATE (27/28).
Reconciliation now requires persisted capped confidence and incremented count
before candidate archival; mismatch rolls back its existing whole-job transaction.
Shared semantic helper, schema and trust semantics remain unchanged.

Targeted suite 28/28 PASS, including ABORT/IGNORE, capped confidence, independent
AFTER-trigger field reversals, whole-job snapshots and fresh CLI refusal/retry.
Read-only QA independently passed 28/28 before the cap case; security review found
no blocker. QA's inline cap probe was policy-blocked; lead added the case to the
suite and verified it. Full shared 31-step gate PASS via external temporary-XDG
chat-offline wrapper: two live-chat SKIP/ENVIRONMENTAL, both synthetic live-embedding
checks PASS. Import/extract/CLI/second-process recall retains visible EV-0001.

Python 3.14.7; Linux 7.2.5-3-omarchy x86_64; AMD Ryzen 9 9950X3D, 32 logical CPUs.
Tested this shift's diff over starting SHA with invented temporary stores only.
No performance comparison or main/live-store/plugin/config/server changes.
Timestamps, later-trigger mutations, graph/audit suppression and historical repair
remain outside scope. Configured live chat not retested.
Next: reproduce suppressed reconciliation graph relationship writes before extending checks.

## Autonomous maintenance — reconciliation evidence-link persistence, 2026-09-27

Started clean at `18bc36be7222d98ba0be2449cef364d5c5ae8f05` on
`automation/hh-maintenance`; fetched main remains an ancestor. No equivalent fix
found in all-ref reconciliation history. Baseline 26/26; regression reproduced
false success when the second reinforcement evidence INSERT was ignored (26/27).

Reconciliation now reads back expected target evidence links within its existing
writer transaction before continuing duplicate/reinforcement effects. Missing links
raise and roll back the whole job. Standalone helpers and trust rules are unchanged.
ABORT/IGNORE fixtures check earlier effects/links, fresh CLI refusal/retry and
idempotency. Targeted suite 27/27 PASS; read-only QA independently passed twice;
security review found no blocker. QA's additional inline probe was policy-blocked,
not a passing check. Full shared 31-step gate PASS via external temporary-XDG
chat-offline wrapper: two live-chat checks SKIP, two synthetic live-embedding checks
PASS. Import/extract/CLI/second-process recall retains visible evidence EV-0001.

Python 3.14.7; Linux 7.2.5-3-omarchy x86_64; AMD Ryzen 9 9950X3D, 32 logical CPUs.
Measured this shift's diff over starting SHA with invented temporary stores only.
No performance comparison, schema, dependency, main, live-store or plugin changes.
This is immediate evidence-link readback, not proof against later trigger mutations
or every suppressed confidence/graph/audit/metadata write. Historical partial writes
are not repaired; configured live chat was not retested.
Next: reproduce suppressed reinforcement confidence/count updates before extending checks.

## Autonomous maintenance — reconciliation status persistence, 2026-09-27

Started clean at `546e490426933a25c943897282fd6b2574fa5323` on
`automation/hh-maintenance`; fetched origin/main remains an ancestor. No existing
fix found in other refs' reconciliation history. Baseline targeted suite 25/25.
The new regression reproduced false applied/success when a duplicate candidate's
archival UPDATE was silently ignored (25/26 before fix).

The reconciliation-only status helper now checks UPDATE rowcount and reads back
status inside the existing writer transaction. Failed archival/supersession rolls
back the entire job rather than committing an applied decision with active rows.
Regression covers duplicate, reinforcement and supersession with ABORT, IGNORE
and AFTER-trigger status reversal; compares whole-job effect snapshots, refuses
through a fresh CLI process, then retries successfully and idempotently.

Targeted suite 26/26 PASS; read-only QA independently passed it twice before the
additional reversal cases, with no blocker. Final full 31-step gate PASS using the
existing external temporary-XDG chat-offline wrapper. Two optional live-chat checks
SKIP/ENVIRONMENTAL; both synthetic live-embedding checks PASS. Configured live chat
not retested. Gate includes import/extract/CLI/fresh-process recall and evidence,
MCP/trust/security, package installation, migrations, quarantine and backup.

Python 3.14.7; Linux 7.2.5-3-omarchy x86_64; AMD Ryzen 9 9950X3D, 32 logical CPUs.
Tested this shift's diff over starting SHA with invented temporary stores only.
No schema, trust rule, classifier, main, live-store, plugin or server changes.
No performance comparison or deployment claim. Other helper-write suppression,
historical contamination and failed-job durability remain outside this narrow fix.
Next: reproduce evidence-link suppression in reconciliation before extending checks.

## Autonomous maintenance — demo portability integration, 2026-09-27

Started clean at `414d4b77a2fa8a9174fe1264664b9d4dfbfef7d4` on
`automation/hh-maintenance`; origin/main remains an ancestor. Reproduced the demo
gate failure: only its database path differed under the Hermes scratch TMPDIR.
The fix already existed on `feat/dolphinbench-campaign`: reused `75b4e85` plus only
the test-resolver correction from `953d6e8`, rather than duplicating development
or importing that branch's unrelated runtime/version/encryption changes.

Demo path normalization now handles the observed non-/tmp scratch root. Added the
existing CLI normalizer self-check and its suite to the shared runner; preserved
the golden transcript unchanged. Targeted normalizer 1/1, import hygiene 9/9 and
full demo transcript PASS. The existing external temporary-XDG chat-offline wrapper
ran `.venv/bin/python scripts/check_all.py`: all 31 steps succeeded. Two optional
live-chat checks SKIPPED/ENVIRONMENTAL; both synthetic live-embedding checks PASS.
Configured live chat was not retested. Includes 25/25 reconciliation checks,
import/extract -> fresh-process recall/evidence, MCP/security/limits, migrations,
quarantine, vectors, Hippo-Pot, backup/integrity and clean wheel installation.

Python 3.14.7; Linux 7.2.5-3-omarchy x86_64; AMD Ryzen 9 9950X3D, 32 logical CPUs.
Measured this shift's diff over starting SHA using invented temporary stores.
No performance comparison, release/deployment, main, live-store, plugin or server
changes. Simple deterministic integration; no specialist spawned. The previously
withheld reconciliation job-persistence commit is now covered by the green gate.
Next: audit remaining reconciliation helper no-op suppression, reproducing any
false applied/success report before changing runtime behavior.

## Autonomous maintenance — reconciliation job persistence, 2026-09-25

Started clean at `96ab1e99e4272a65d9a7a2db95f36d1ac25199eb` on
`automation/hh-maintenance`; fetched main remains an ancestor. Reproduced P1 false
success when job INSERT or completion UPDATE is silently suppressed. Creation now
requires a persisted job row; completion must match status, finished timestamp and
all candidate/classification counts inside the existing writer transaction. No
schema, classifier, trust boundary or standalone write-helper behavior changes.

Both IGNORE regressions failed before their respective fixes. Targeted suite now
25/25 PASS, including ABORT/IGNORE for each write, prior-job status rollback, full
checked effect/decision snapshots, CLI refusal, fresh-process retry and idempotency.
Existing import/extract -> CLI -> second-process recall/evidence checks still pass.
Read-only QA independently ran 25/25 twice and found no blocker; its extra custom
corruption probe was blocked by cron policy, not a passing check.

Full unchanged `scripts/check_all.py` via external temporary-XDG chat-offline wrapper
exited 1: only demo transcript failed. The unchanged demo normalizer hardcodes
`/tmp/hh_demo...` and does not normalize this runtime's scratch TMPDIR path. All
other steps succeeded, including wheel installation, MCP/security, ingestion/E2E,
vectors, Hippo-Pot and backup/integrity. Two optional live-chat checks SKIPPED;
both synthetic live-embedding checks passed. Configured chat was not retested.
Do not change TMPDIR to the system temp directory or regenerate expected output
to hide this mismatch. Keep this unrelated demo portability defect for the next
bounded shift. Maintenance push withheld until the broad gate is green.

Python 3.14.7; Linux 7.2.5-3-omarchy x86_64; AMD Ryzen 9 9950X3D, 32 logical CPUs.
Measured this shift's diff over the starting SHA with invented temporary stores.
No performance comparison, live-store/plugin/config/server/main changes. Other
helper write suppression and broader reconciliation-trust issues remain open.

## Autonomous maintenance — reconciliation writer transaction, 2026-09-25

Started clean at `935ab8e05609b54dc84b74b35983e9acc3566bd5` on
`automation/hh-maintenance`; fetched main remained an ancestor. Reproduced the
remaining approval race: a newly approved target was still superseded, and the new
reinforcement interleaving regression failed with added evidence/counts. Reconciliation
now acquires BEGIN IMMEDIATE before pending/comparison reads through effects and
decisions. Direct application likewise locks fresh trust checks and requires one
shared Database instance. Whole-job locking is deliberate; see ADR-009 for contention
and failure-status tradeoffs. No model/network calls occur within the transaction.

QA and Security independently found silent decision INSERT suppression committing
effects without decisions. Lead reproduced RAISE(IGNORE), added an in-transaction
persistence check, and verified ABORT/IGNORE rollback including earlier candidates.
Tests include separate-process approval attempts, precommitted CLI approval against
stale decisions, helper binding, fresh CLI retry, and existing import/extract -> CLI
-> second-process recall/provenance. No live store, plugin, main, schema or MCP changes.

A separate synthetic job INSERT IGNORE probe still returns success with one decision
but zero job rows. That pre-existing reporting/integrity gap is not the approval race;
next action is checked reconciliation job creation/update with fault regressions.
Other helper no-op suppression, historical contamination, contradiction/update
metadata and forged trusted-Python classifications remain outside this shift.
Python 3.14.7, Linux 7.2.5-3-omarchy x86_64, AMD Ryzen 9 9950X3D, 32 logical CPUs.
Measured this shift's diff over starting SHA using invented temporary stores only;
no comparative performance claim. Targeted reconciliation: 23/23 PASS. Final
unchanged `scripts/check_all.py` through the external temporary-XDG chat-offline
wrapper: all 30 steps succeeded, including clean wheel install, MCP/trust/security,
ingestion/E2E/provenance, vectors, Hippo-Pot and backup/integrity. Two live-chat
checks SKIP/ENVIRONMENTAL; both synthetic live-embedding checks PASS. Configured
live chat was not retested. No assertions weakened or suites omitted.

## Autonomous maintenance — reconciliation review boundary, 2026-09-25

Started clean at `54bf517a4f43aa5a474bc73bb149cc6182f8ddde` on
`automation/hh-maintenance`; fetched main was already an ancestor. Reproduced two
P1 trust failures encoded in old test expectations: quarantined reinforcement
attached evidence/raised counts on an operator-attested belief, and quarantined
supersession retired a nonquarantined lower-confidence belief. Both corrected
regressions failed before the minimal guards and passed afterward.

Serial reconciliation now refuses those effects, leaves candidates active and
quarantined, audits denial and records `applied=false`. It does not replay denied
decisions after later approval. Classifier counts and candidate-to-candidate
quarantined behavior stay compatible; see ADR-008 and docs/INGESTION.md.

Targeted reconciliation: 20/20 PASS, including import/extract -> CLI reconciliation
-> second-process recall with visible original evidence and a quarantine-only chain.
Read-only QA found no blocker; Security found a residual approval-interleaving race,
which the lead independently reproduced: a target approved after the snapshot read
was still superseded using stale quarantine state. This is not concurrent-approval
safety. Avoid concurrent review/reconciliation. Next: atomic fresh checks, effects
and decision persistence with interleaving regression coverage. No historical
contamination repair or change to contradiction/update metadata behavior.

First full gate failed import hygiene because the new subprocess test inserted a
test-helper path. Replaced that with normal runtime imports; targeted hygiene 9/9
PASS. Final unchanged `scripts/check_all.py`, through the external temporary-XDG
chat-offline wrapper: all 30 steps succeeded, two live-chat SKIP/ENVIRONMENTAL,
both synthetic live-embedding checks PASS. Includes MCP/auth/security/limits,
quarantine/provenance, migrations, ingestion/E2E, vectors, Hippo-Pot, backup and
clean wheel install. Configured live chat service was not retested.
Python 3.14.7, Linux 7.2.5-3-omarchy x86_64, AMD Ryzen 9 9950X3D, 32 logical CPUs;
measured this shift's diff over starting SHA using invented temporary stores.
No performance comparison, schema, main, live-store, plugin or server changes.

## Autonomous maintenance — concurrent extraction, 2026-09-25

Started clean at `a4783b1b554475109bcc4894ed6386c16bb3d99b` on
`automation/hh-maintenance`; fetched main remained an ancestor, no merge needed.
Reproduced P1 duplicate candidate persistence: two processes read the same pending
turns before their model calls and both committed successfully. Per-batch atomicity
alone did not detect stale work. Extraction now rechecks source/session progress
under its existing SQLite writer lock and explicitly refuses overlapping stale
batches before writing candidates/evidence or replacing newer checkpoints.
Retry reloads pending work. Earlier commits survive; model calls remain outside
the transaction. See ADR-007 for scope and limitations.

The regression failed before the fix (two beliefs from the same pending batch)
and passed afterward. Six deterministic cross-process cases cover belief/episode
and equal/shorter/longer batches, fresh CLI pending counts and retry. Read-only QA
also checked earlier-success/later-overlap, disjoint sessions and sources, unchanged
non-job tables after refusal, and SQLite integrity; no blocking finding.

Targeted extraction: 20 actual checks PASS, one intentionally offline live-chat
SKIP. Full unchanged `scripts/check_all.py`: all 30 steps succeeded through an
external wrapper using a temporary XDG sidecar with chat intentionally offline;
two live-chat checks SKIP/ENVIRONMENTAL, both synthetic live-embedding checks PASS.
Includes second-process recall/provenance, MCP/auth/security, ingestion/reconcile/
E2E, backup and clean wheel install. The configured live chat service was not
retested this shift. Python 3.14.7, Linux 7.2.5-3-omarchy x86_64, AMD Ryzen 9 9950X3D,
32 logical CPUs; tested shift diff over the starting SHA with invented temporary
stores. No performance comparison or deployment claim.

No schema, dependency, trust promotion, main, production store, installed plugin,
server or live configuration changes. Historical duplicate repair, lossless
oversized-turn chunking and cross-conversation claim deduplication remain outside
this fix. Next: audit integrated reconciliation for unapproved candidates
strengthening or superseding approved memories, reproducing before changing it.

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
