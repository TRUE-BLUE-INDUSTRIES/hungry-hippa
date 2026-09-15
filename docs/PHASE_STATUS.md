# Follow-up status

The phase entries below are historical. Installation and subsequent CI verification
are recorded in [FOLLOWUP.md](FOLLOWUP.md); its results supersede the earlier
statements that nothing was pushed and CI had never run.

# Hungry Hippa phase status

Operator brief: `/home/djr/Documents/masterP.txt`. Branch: `feat/hungry-hippa`.
Nothing is pushed. Tests use throwaway temp DBs; the live
`$HERMES_HOME/living_cortex.db` is never opened by tests or demos.

---

## Phase 1 — audit and baseline — COMMIT `dbb5a88`

Objective: record architecture, tests, risks, migration plan. No runtime change.
Files: `docs/LIVING_CORTEX_BASELINE.md`, `docs/MIGRATION_PLAN.md`.
Validation: `python tests/test_acceptance.py` → 10/10.
Status: done.

---

## Phase 2 — safe rebrand and DB migration — COMMIT `6574bc6`

Objective: product-facing Hungry Hippa naming with Living Cortex compatibility.
Files: `plugin.yaml`, `config.py`, `schema.py`, `db.py`, `cli.py`, `docs/MIGRATION.md`,
`tests/test_migration.py`.
Validation: `python tests/test_acceptance.py` → 10/10;
`python tests/test_migration.py` → 6/6.
Status: done.

---

## Phase 3 — memory architecture (additive)

Objective: add only the memory-layer behavior the product needs and can test —
sensitivity/quarantine, actor identity on rows, explainable recall scoring,
and a structured context compiler — without renaming tables or dropping columns.

Files in scope: `schema.py` (migration v4), `policy.py` (new), `episodic.py`,
`semantic.py`, `retrieval.py`, `controller.py`, `tools.py`, `db.py` (health counts),
`tests/test_memory_architecture.py` (new).

Validation commands:

```
python tests/test_acceptance.py
python tests/test_migration.py
python tests/test_memory_architecture.py
```

Expected evidence: all three suites pass; existing episodes/beliefs gain
`sensitivity='unclassified'`, `quarantined=0`, `actor_id='primary'` by default;
quarantined rows are absent from default recall; `explain=True` yields score
parts; the compiled context obeys `retrieval.max_context_chars`.

Rollback: `schema.py` migration v4 carries a `down` script that drops the three
columns and the two indexes; the live DB is restored from the
`.pre-hippa-<UTC>.bak` file written by `migrate`; or `git checkout HEAD~1` for
the pure-code path. New columns all have constant defaults, so leaving them in
place is also backward compatible with the previous code.

Status: see the "Phase 3 results" section at the bottom.

---

## Phase 3 results — COMMIT (see git log, `feat: add quarantine, explainable recall, and context compiler`)

Files changed: `schema.py` (+27), `policy.py` (new, 145), `episodic.py` (+37/-?),
`semantic.py` (+49), `retrieval.py` (rewritten sections, +431/-?), `controller.py` (+63),
`db.py` (+9), `procedural.py` (+2), `tools.py` (+44),
`tests/test_memory_architecture.py` (new), `docs/PHASE_STATUS.md`.

What was implemented:

1. Schema migration **v4** (constant defaults only, no table renames):
   `sensitivity TEXT NOT NULL DEFAULT 'unclassified'`, `quarantined INTEGER NOT NULL DEFAULT 0`,
   `actor_id TEXT NOT NULL DEFAULT 'primary'` on `episodes` and `beliefs`, plus four indexes.
   `down_sql` drops them again.
2. `policy.py` — actor/policy checks (explicitly **not** capability-based security):
   owner actors read everything; untrusted actors read only their own unclassified,
   non-quarantined rows; untrusted writes are stored quarantined; purge is owner-only.
3. Retrieval excludes quarantined rows by default for every actor, and partitions
   candidates into `items` (allowed) and `excluded` (content-free `{item, reason}`).
   Consolidation input (`list_episodes_full`) also excludes quarantined rows so an
   untrusted write cannot be laundered into a derived belief.
4. `recall(..., explain=True)` returns per-item score parts
   (relevance, recency, salience, confidence, provenance class, reinforcement factor,
   total, `dropped_for_budget`) and never echoes memory contents — verified by a test
   that asserts quarantined text is absent from the debug payload.
5. Context compiler `RetrievalRouter.compile_context()` returns
   `{items, rendering, token_estimate, excluded}` (+ `budget_chars`, `chars_used`, `query`).
   `recall()["context"]` remains the rendered string, so the existing provider and
   `cortex` tool behaviour is unchanged. Dedupe by normalized text; active beats
   superseded; hypotheses render with a `HYPOTHESIS` marker; quarantined items are
   labelled `[QUARANTINED]` on the owner-review path.
6. Ranking is now explicit and decomposed: 0.30 salience + 0.22 recency +
   0.22 relevance + 0.13 term-hit bonus + 0.13 confidence, times a reinforcement factor.
   Differences from the previous formula are recorded here because the previous
   version silently omitted confidence and the term-hit bonus from the weights.
7. The `cortex` tool gained the additive action `record_outcome` (plus optional
   `explain` on `recall`). No existing action was removed or renamed.

Bugs found and fixed while testing this phase:

- `procedural.record_outcome()` returned the stale pre-reevaluation row, so callers never
  saw the promotion/confidence change it had just written. It now re-reads after
  re-evaluation.
- The context renderer honoured the budget only after placing at least one block, so a
  tiny budget could overflow. The budget is now strict.

Actual test results (run 2026-09-15, this working tree):

```
python tests/test_acceptance.py            -> 10/10 passed
python tests/test_migration.py             ->  6/6 passed
python tests/test_memory_architecture.py   ->  8/8 passed
```

Not done in this phase (recorded so nobody assumes it): no encryption at rest beyond
documented OS disk encryption, no tamper-evident hash chain on `mutation_log`, no
sensitivity-based encryption, and sensitivity is a read-policy label only.


---

## Phase 4 — local MCP stdio server

Objective: expose the same controller over local MCP stdio so other local clients can
use Hungry Hippa, without adding a network listener, arbitrary SQL, filesystem access
or raw database export.

Files in scope: `mcp_server.py` (new), `tests/test_mcp_schema.py` (new), `docs/MCP.md`
(new). Read-only touch: none — the Hermes `cortex` tool and provider are unchanged.

Validation commands:

```
python tests/test_acceptance.py
python tests/test_migration.py
python tests/test_memory_architecture.py
python tests/test_mcp_schema.py
python mcp_server.py --print-schemas      # human/tooling inspection
```

Expected evidence: the six `hippa_*` tools exist with strict JSON schemas; `export` is
absent; a remember→recall roundtrip works in-process on a throwaway DB; an untrusted
actor cannot recall another actor's quarantined row; purge over MCP is denied without an
explicit confirmation flag and an owner actor; no tool takes a path/db argument.

Rollback: delete `mcp_server.py`, `tests/test_mcp_schema.py`, `docs/MCP.md`. Nothing
else imports them, so the Hermes path is unaffected.

Status: see the "Phase 4 results" section at the bottom.

---

## Phase 4 results — COMMIT `feat: add local stdio MCP server for Hungry Hippa`

Files: `mcp_server.py` (new, ~600 lines), `tests/test_mcp_schema.py` (new, 11 checks),
`docs/MCP.md` (new). No existing file was modified, so the Hermes provider, the
`cortex` tool and T10 are untouched by this phase.

What was implemented:

- `mcp_server.py`: newline-delimited JSON-RPC 2.0 over **stdio only**. Answers
  `initialize`, `notifications/initialized`, `ping`, `tools/list`, `tools/call`, the
  protocol's `shutdown` method; unknown methods get `-32601`, malformed JSON gets
  `-32700`, unknown tools get a normal `isError` tool result. Logging goes to stderr
  because stdout is the protocol channel. No socket, HTTP, asyncio or third-party
  import (asserted by an AST import check in the test file).
- Six tools with strict schemas (`additionalProperties: false`, explicit `required`,
  enums, numeric bounds, string/array length caps): `hippa_remember`, `hippa_recall`,
  `hippa_build_context`, `hippa_record_outcome`, `hippa_forget`, `hippa_status`.
  No `export`, no SQL, no path/database argument on any tool.
- Caller identity: `actor_id` on every tool, defaulting to `mcp-untrusted`. Untrusted
  writes are stored quarantined; untrusted reads see only their own unclassified,
  non-quarantined rows; purge requires `confirmation: true` **and** an owner actor and
  is otherwise denied. `hippa_status` hides the database path from untrusted callers.
- Handlers and the validator are importable in-process, so the tests drive real tool
  calls, real validation and a real stdio round trip without spawning a subprocess.

Verification beyond the test file (manual, this working tree):

- `python mcp_server.py --print-schemas` → prints the six tools as JSON.
- `python mcp_server.py` was piped an `initialize` / `tools/list` / three `tools/call`
  sequence against `HUNGRY_HIPPA_DB=/tmp/...` and returned correct results, including
  an untrusted caller being excluded with reason `other-actor`.
- `python -m mcp_server` works from the plugin directory.

Actual test results (run 2026-09-15, this working tree):

```
python tests/test_acceptance.py            -> 10/10 passed
python tests/test_migration.py             ->  6/6 passed
python tests/test_memory_architecture.py   ->  8/8 passed
python tests/test_mcp_schema.py            -> 11/11 passed
```

Not done in this phase: no external MCP client has been run against this server. The
Grok CLI `[mcp_servers.*]` snippet in `docs/MCP.md` is illustrative and marked
untested; its schema was copied from the Grok user guide installed on this machine.
No Unix socket, no loopback HTTP, no OAuth, no remote transport.

---

## Phase 5 — security

Objective: practical controls matching the threat model — request/result limits, a
per-process call budget, audit-log redaction, and documented boundaries. Security is a
foundation here, not the product's novelty.

Files in scope: `limits.py` (new), `mcp_server.py`, `tools.py`, `db.py`,
`controller.py`, `episodic.py`, `semantic.py`, `cli.py`, `tests/test_security.py` (new),
`docs/THREAT_MODEL.md` (new), `docs/SECURITY.md` (new), `SECURITY.md` (new).

Validation commands:

```
python tests/test_acceptance.py
python tests/test_migration.py
python tests/test_memory_architecture.py
python tests/test_mcp_schema.py
python tests/test_security.py
```

Expected evidence: oversized payloads rejected on both surfaces; result and frame caps
enforced; the call budget stops an abusive loop; no export/SQL/path tool over MCP;
untrusted recall of quarantined rows denied; purge denied without confirmation plus an
owner actor; SQL-injection payloads inert; credential-shaped strings redacted in audit
logs while stored memory is preserved; every tracked file free of credential shapes.

Rollback: the limits live in one new module and are applied at three call sites
(`tool` dispatch, MCP dispatch, `db.log_mutation`); reverting `limits.py` plus those
call sites restores the previous behaviour. Docs are additive. Never ship the MCP
surface without the actor checks.

Status: see the "Phase 5 results" section at the bottom.

---

## Phase 5 results — COMMIT `security: add request limits, threat model, and MCP auth tests`

Files: `limits.py` (new), `tests/test_security.py` (new, 10 checks),
`docs/THREAT_MODEL.md` (new), `docs/SECURITY.md` (new), `SECURITY.md` (new);
`mcp_server.py`, `tools.py`, `db.py`, `controller.py`, `episodic.py`, `semantic.py`,
`cli.py` updated.

Implemented:

- `limits.py`: argument caps (query 8000 / content 32000 / arrays 256 / ids 64),
  result caps (text 20000, JSON-RPC frame 40000), a thread-safe per-process
  `CallBudget` (`HUNGRY_HIPPA_MAX_MCP_CALLS`), and credential redaction for audit
  logs. Limits are enforced on the MCP surface (schema + a second length check),
  on the Hermes `cortex` tool, and on the returned context text.
- Redaction is applied where audit copies are written (`db.log_mutation`,
  `controller.recall`'s `retrieval_log` insert). Stored memory and immutable
  evidence rows keep exactly what they were given, so a redacted log never
  contradicts the record it describes.
- `docs/THREAT_MODEL.md`: twelve threats with the control that addresses each and
  the residual risk, plus an explicit "not covered" list.
- `docs/SECURITY.md`: the actor/policy model (stated as policy checks, **not**
  capability-based security), the control table, encryption-at-rest expectations
  (OS disk encryption; no SQLCipher dependency), what is not provided, and a
  safe-running checklist.
- root `SECURITY.md`: responsible disclosure through GitHub issues/advisories on
  `TRUE-BLUE-INDUSTRIES/living-cortex` (no invented email address), plus the list
  of documented limitations that are not vulnerabilities.
- `cli.py`: `hermes living-cortex recall --quarantined` so an owner can actually
  review quarantined rows; without the flag they never appear.

Security bug found and fixed by the new tests: an untrusted actor's **semantic**
write was not quarantined, because the quarantine decision lived only in
`MemoryController.remember_episode` and the MCP handler calls
`semantic.add_belief` directly. The decision moved into the write layer
(`episodic.remember_episode`, `semantic.add_belief`), which every path goes
through. Also fixed: `set_call_budget()` reset the counter but kept a shrunken
limit, leaking a test's budget setting into later calls in the same process.

Actual test results (run 2026-09-15, this working tree):

```
python tests/test_acceptance.py            -> 10/10 passed
python tests/test_migration.py             ->  6/6 passed
python tests/test_memory_architecture.py   ->  8/8 passed
python tests/test_mcp_schema.py            -> 11/11 passed
python tests/test_security.py              -> 10/10 passed
```

Not done in this phase: no encryption at rest, no tamper-evident hash chain, no
per-caller quotas or timeouts, no secret scanning of already-stored memories, no
authenticated MCP transport (a caller that can start the process can claim any
`actor_id`). All of these are stated in the docs rather than implied away.

---

## Phase 6 — Hungry Hippa Memory Challenge (eval harness)

Objective: a reproducible harness comparing the same agent with and without Hungry
Hippa, on ten scenarios, producing machine-readable results from a real run. No
invented numbers; unmeasurable metrics marked unsupported.

Files in scope: `eval/harness.py` (new), `eval/fixtures.json` (new),
`eval/README.md` (new), `eval/results.json` (new, generated), `eval/REPORT.md` (new,
generated). Read-only touch: `controller.py` gains a `max_chars` alias on
`build_context`.

Validation commands:

```
python eval/harness.py --stdout     # regenerates results.json + REPORT.md, prints summary
python tests/test_acceptance.py
python tests/test_migration.py
python tests/test_memory_architecture.py
python tests/test_mcp_schema.py
python tests/test_security.py
```

Expected evidence: `results.json` contains real measurements (recall rates, context
sizes, latencies, DB growth) from a completed run; `REPORT.md` is generated from it;
`fixtures.json` contains no personal information.

Rollback: delete `eval/`; nothing imports it.

Status: see the "Phase 6 results" section at the bottom.

---

## Phase 6 results — COMMIT `test: add Hungry Hippa memory challenge harness and results`

Files: `eval/harness.py` (new), `eval/fixtures.json` (new), `eval/README.md` (new),
`eval/results.json` + `eval/REPORT.md` (generated by an actual run);
`controller.py` (one-line `max_chars` alias on `build_context`, needed by the harness
and by MCP's `hippa_build_context`).

Design: two arms read by the **same deterministic reader** (exact token match on the
assembled context) so the only variable is the context source:
`without` = session-transcript-only agent (no store, no budget, no policy, no
supersession state); `with` = the real runtime on a throwaway DB with embeddings off.
No LLM, no network. Grading, the baseline definition and the unsupported metrics are
documented in `eval/README.md`.

Actual run (2026-09-15, this working tree, 1.8 s wall):

```
recall rate (7 comparable scenarios)   with 1.0   without 0.143
incorrect-memory rate                  with 0.0   without 0.143
repeated-failed-attempt (scenario 3)   with 0.0   without 1.0
median context supplied                with 109   without 0 chars
permission-denial accuracy             with 1.0   without unsupported
retrieval latency vs growth 100/500/2000 episodes: 3.2 / 3.4 / 3.8 ms
DB bytes at 100/500/2000 episodes: 290816 / 573440 / 1544192
context chars at those points: with 747 / 747 / 747, without 4153 / 21024 / 85274
```

Scenario notes worth keeping: the baseline answered correctly exactly once
(scenario 5, because the whole transcript was still in its context window at 9 518
chars versus 386 for the capped with-arm), and it produced an *incorrect* memory in
scenario 4 — it holds both the old and the new claim with no supersession state, so
the stale token stays in its context.

Unsupported metrics (recorded in `results.json` and `REPORT.md`, never estimated):
natural-language answer quality and semantic-equivalence grading (need an LLM judge),
embedding/vector recall quality (needs Ollama, deliberately disabled), the baseline
arm of scenarios 8 and 9 (no store to poison; no access control to test), and
multi-user isolation (not implemented).

Actual test results after this phase:

```
python tests/test_acceptance.py            -> 10/10 passed
python tests/test_migration.py             ->  6/6 passed
python tests/test_memory_architecture.py   ->  8/8 passed
python tests/test_mcp_schema.py            -> 11/11 passed
python tests/test_security.py              -> 10/10 passed
python eval/harness.py                     -> completed, wrote results.json + REPORT.md
```

Not done: no LLM-judge metrics, no concurrency measurements, no cross-machine
benchmarking. `results.json` records `git_dirty: true` because the harness and its
outputs were uncommitted at run time; that is provenance, not a failure.

---

## Phase 7 — reproducible demonstration

Objective: an eight-step local demo proving the cross-session story (record a decision,
a failed attempt and an outcome, end the session, restore context in a cold session,
avoid the failed fix, keep a second agent inside its permissions, then inspect/correct/
forget) that runs against a throwaway database and can be re-run by anyone.

Files in scope: `demo/demo.py` (new), `demo/seed.json` (new), `demo/README.md` (new),
`demo/expected_output.txt` (new, captured from a real run), `.gitignore` (ignore
`demo/.demo_db/`). No runtime files changed.

Validation commands:

```
python demo/demo.py --reset            # recreate the demo database from the seed
python demo/demo.py                    # play the demo
python demo/demo.py --check            # play and diff against expected_output.txt
python demo/demo.py --tmp --check      # same, on a throwaway temp database
```

Expected evidence: `--check` exits 0 with "transcript matches expected_output.txt";
the demo database lives under `demo/.demo_db` (gitignored) or a temp dir, never
`$HERMES_HOME`.

Rollback: delete `demo/`. Nothing imports it.

Status: see the "Phase 7 results" section at the bottom.

---

## Phase 7 results — COMMIT `docs: add reproducible Hungry Hippa demo`

Files: `demo/demo.py`, `demo/seed.json`, `demo/README.md`, `demo/expected_output.txt`,
`.gitignore` (one line). No runtime module changed.

What the demo does: eight steps, each printed as it runs — agent starts work; records a
decision, a failed attempt (`solvent X` → `the housing cracked`) and a working outcome;
session A ends; session B starts with no conversation history; Hungry Hippa restores the
decision plus the failure inside a character budget; the agent does not repeat the failed
fix; a **separate local MCP client process** (spawned by the demo over stdio) is denied
everything as `mcp-untrusted` (count=0, 6 denials, all `other-actor`) while the owner
actor receives the history; and finally the operator inspects a belief, corrects it
(supersession), archives it (reversible), and reads the audit trail.

Reproducibility work: `--check` resets first (so a comparison always starts from the
seed), and the comparison normalises the database path, dates/timestamps and the closing
cleanup note. The seed holds only background history; the demo records its own decision
and failure at run time, so no ids are duplicated.

Actual verification run (2026-09-15, this working tree), starting from a deleted
`demo/.demo_db` (clean state):

```
python demo/demo.py --check        -> exit 0, "transcript matches expected_output.txt"
python demo/demo.py --tmp --check  -> exit 0, matched the same expected output
python demo/demo.py --check        -> exit 0 again against an existing database
```

Nothing was sent anywhere: no network, no LLM (the "agent" is a deterministic script),
embeddings disabled. The only cross-process element is the local stdio MCP client in
step 7.

Actual test results after this phase:

```
python tests/test_acceptance.py            -> 10/10 passed
python tests/test_migration.py             ->  6/6 passed
python tests/test_memory_architecture.py   ->  8/8 passed
python tests/test_mcp_schema.py            -> 11/11 passed
python tests/test_security.py              -> 10/10 passed
```

Not done: no video was recorded (the two-minute script is in `demo/README.md`), and the
demo does not drive a real Grok CLI session — step 7 uses our own MCP client process, so
"a second compatible agent" is demonstrated with a generic MCP client, not with Grok.

---

## Phase 8 — product-quality packaging

Objective: a technically competent stranger can install, test and understand the project
without contacting the operator.

Files in scope: `README.md` (rewritten), `CHANGELOG.md` (new), `CONTRIBUTING.md` (new),
`docs/TECHNICAL_REPORT.md` (new), `docs/RELEASE_CHECKLIST.md` (new),
`docs/LICENSE_NOTES.md` (new), `eval/check_results.py` (new),
`scripts/check_all.py` (new), `.github/workflows/test.yml` (new). No runtime module
changed.

Validation commands:

```
python scripts/check_all.py         # every suite + demo check + eval drift check
python -c "import yaml; yaml.safe_load(open('.github/workflows/test.yml'))"
```

Expected evidence: the README opens with the required sentence; the mermaid diagram names
only modules that exist; every local link resolves; the CI steps are the same commands a
contributor runs locally and all of them pass locally.

Rollback: docs-only revert, plus deleting the two new scripts and the workflow file.

Status: see the "Phase 8 results" section at the bottom.

---

## Phase 8 results — COMMIT `docs: package Hungry Hippa for a first-time installer`

Files: `README.md` (rewritten), `CHANGELOG.md`, `CONTRIBUTING.md`,
`docs/TECHNICAL_REPORT.md`, `docs/RELEASE_CHECKLIST.md`, `docs/LICENSE_NOTES.md`,
`eval/check_results.py`, `scripts/check_all.py`, `.github/workflows/test.yml`,
`eval/README.md` (one table row). No runtime module changed.

What was produced:

- `README.md` opens with the exact required sentence, then: a capability table where every
  row names the test that covers it, quick start (`cp -r` into `$HERMES_HOME/plugins` plus
  `hermes config set memory.provider living-cortex`), a sample config, an MCP section
  marked untested for clients, a troubleshooting table drawn from real failure modes, a
  mermaid architecture diagram built from the actual modules, layout, evidence table and
  links to the licensing/security/changelog documents.
- `CHANGELOG.md`: the unreleased migration work (added/changed/fixed/compatibility/known
  limitations), including the two real bugs fixed during the migration, plus the 0.2.0
  Living Cortex baseline entry.
- `CONTRIBUTING.md`: the test gate, the eight hard rules (stdlib only, never silently
  delete, no unsupported claims, throwaway DBs, no secrets/personal data, no overclaiming,
  additive compatibility, reversible migrations), test/commit conventions.
- `docs/TECHNICAL_REPORT.md`: data model, retrieval formula, context-compiler contract,
  actor policy, limits, MCP surface, the measured numbers, and a limitations section
  (including the negative-is-better bm25 wart and the `neural.py` stub).
- `docs/RELEASE_CHECKLIST.md`: eight sections incl. an explicit "CI has not run yet" item
  and a rollback path.
- `docs/LICENSE_NOTES.md`: MIT, standard-library-only dependency review, host-provided
  optional imports, optional Ollama, naming/trademark notes.
- `.github/workflows/test.yml`: compileall gate, the five suites, the demo check, a schema
  assertion that `export` is absent, the eval drift check, and a tracked-database check.
- `scripts/check_all.py`: one command that runs the same seven steps CI runs.
- `eval/check_results.py`: re-runs the harness into a temp dir and compares the
  machine-independent aggregate metrics against the committed `results.json`, so CI can
  detect drift without failing on timestamps or latencies.

Verification actually performed at the time (before the branch was pushed; CI has since
run green on every pushed commit):

```
python scripts/check_all.py --quiet                       -> all 7 steps passed
python eval/check_results.py --verbose                    -> stable metrics match (5 groups, 10 scenarios)
python -c "import yaml; yaml.safe_load(...)"               -> workflow YAML parses
python -m compileall -q . -x '__pycache__'                 -> ok
python mcp_server.py --print-schemas                       -> 6 tools, no export
git ls-files | grep -Ei '\.(db|sqlite|bak|key|pem)$'       -> no matches
local markdown link check over 17 files                    -> 16 links, 0 broken
mermaid module check                                       -> 16 modules referenced, 0 missing
```

Not done: the GitHub Actions matrix (Python 3.12/3.13) has never executed — the workflow
is unverified configuration, and the release checklist says so. Development and every
measurement in this repository were produced on Python 3.14.7; no other version has been
run.

---

## Phase 9 — honest differentiation

Objective: a feature matrix against the three narrow architectural alternatives, claiming
only implemented and tested behaviour.

Files in scope: `docs/COMPARISON.md` (new), `README.md` (one link). No runtime change.

Validation: every row cross-checked against this tree; the local link check re-run; the
test suites re-run at the end of the phase.

Rollback: delete `docs/COMPARISON.md` and the README link.

Status: see the "Phase 9 results" section at the bottom.

---

## Phase 9 results — COMMIT `docs: add honest comparison matrix`

Files: `docs/COMPARISON.md` (new), `README.md` (link added).

Approach: a fourth peer agent (Codex) had already written a comparison on the unmerged
`feat/hungry-hippa-eval` branch, describing the `6574bc6` baseline. Its framing was kept
(narrow architectural patterns rather than strawman products; "application work" rather
than implied absence; no superiority claim; technology-not-proprietary). Its Hungry Hippa
rows were re-derived from this tree, because after Phases 3–8 four of them are simply no
longer true of this code: actor policy, quarantine, the MCP server and the strict context
compiler all now exist and are tested. Its harness numbers (from its own separate eval)
were not copied; this document cites the numbers produced in this tree by
`eval/results.json`.

The matrix compares against basic vector-store memory, file-based agent notes and local
event-log systems, with a legend that separates implemented-and-tested (`yes`), implemented
with a stated limitation (`partial`), not implemented (`no`) and "the pattern does not
supply it" (`application work`).

Rows marked `no` on purpose: capability-based security (the project uses actor/policy
checks and says so), encryption at rest, and hardware-backed deployment ("not
demonstrated" — it may well run on a small local device, but nothing was run on one).
Rows marked `partial` include cross-agent portability (owner actors only, no external
client verified), poisoning resistance (quarantine is real and tested, but it is not a
truth detector and a caller claiming the owner actor bypasses it), audit trail
(append-only convention, not tamper-evident), forgetting (archival is not secure erasure)
and limits (no per-caller quotas or timeouts).

Explicit non-claims restated at the end: SQLite/FTS5/vector search/MCP/encryption/RBAC are
established technologies, nothing is proprietary, no superiority is claimed, no model
training happens anywhere in this repository.

---

## Definition of done — final summary

| Phase | Commit | Tests at that commit | Notes |
|---|---|---|---|
| 1 audit + baseline | `dbb5a88` | acceptance 10/10 | pre-existing |
| 2 rebrand + migration | `6574bc6` | acceptance 10/10, migration 6/6 | pre-existing |
| 3 memory architecture | `5939fac` | 10/10, 6/6, memory 8/8 | migration v4, policy, explain, compiler |
| 4 local MCP server | `112a6a2` | + MCP 11/11 | stdio only, six tools, no export |
| 5 security | `1920c3e` | + security 10/10 | caps, budget, redaction, threat model |
| 6 memory challenge | `52a8597` | all five suites green | real run, results.json + REPORT.md |
| 7 demo | `b702972` | all five suites green | `--check` matches captured output |
| 8 packaging | `2b8c7bc` | `scripts/check_all.py` 7/7 steps | README, CI, reports, checklist |
| 9 comparison | this commit | re-run below | matrix + non-claims |

Final test state (run in this tree after the last commit):

```
python scripts/check_all.py --quiet   -> all 7 steps passed
  acceptance 10/10 | migration 6/6 | memory architecture 8/8
  MCP schema 11/11 | security 10/10 | demo transcript match | eval metrics stable
```

Bugs found and fixed during the migration (all of them real, all found by tests written in
the phases above): untrusted *semantic* writes bypassed quarantine; `record_outcome`
returned a stale pre-reevaluation row; the context renderer could exceed a tiny budget;
retrieval item keys were inconsistent between the pipeline and the compiler; and the test
call-budget reset leaked a shrunken limit into later calls.

Outstanding, deliberately not done (each is stated in the relevant document rather than
implied away): no encryption at rest; no tamper-evident audit chain; no per-caller quotas
or timeouts; no authenticated MCP transport; no external MCP client (including Grok CLI)
has been run against the server; no LLM-judged eval metrics; no video recorded for the
demo. (Superseded since this entry was written: the repository is now public and pushed,
and the GitHub Actions matrix has run green on every pushed commit — see
[FOLLOWUP.md](FOLLOWUP.md).)

Concurrent-work note: `docs/AGENT_COORDINATION.md` appeared in this working tree during
Phase 8 (written by a peer coordinator agent, not by this session) and was included in the
Phase 8 commit before it was noticed. It is a benign coordination document and is retained
as-is. Its claim that `eval/`, `demo/` and `docs/COMPARISON.md` should come from the other
branch was followed only as input: the eval and demo in this tree were built and verified
here, and the comparison was rewritten against this tree's code and measurements instead of
copying the baseline version.

---

## Phase 10 — post-audit hardening (operator-requested)

Objective: fix every finding raised by the 2026-09-15 compliance audit
(Hermes, three passes on fresh clones) and its independent Codex verification.

Files: `controller.py`, `policy.py`, `db.py`, `mcp_server.py`, `tools.py`,
`tests/test_security.py`, `tests/test_mcp_schema.py`, `tests/test_migration.py`,
`tests/test_acceptance.py`, docs and eval outputs.

Committed as `3e3a2b0`, `19eae23`, `72749e3`, `093ed5a`, `898a07a`, `a604ad3`.

| Finding | Fix | Regression test |
|---|---|---|
| Untrusted caller could archive another actor's private memory | `Controller._may_forget` applies the read policy per record; denials audited as `forget_denied` | `test_security.py::untrusted_archival_denied_per_record` |
| Whitespace `actor_id` resolved to the owner actor | `policy.normalize_actor` returns the untrusted actor for whitespace-only input | `test_security.py::whitespace_actor_does_not_elevate` |
| Ordinary open migrated an old database without a backup | `Database._ensure_schema` writes `*.pre-migration-<UTC>.bak` before pending migrations | `test_migration.py::implicit_open_backs_up_before_upgrading` |
| Legacy `cortex` export wrote a raw dump for any actor | owner-only + audited (`export` / `export_denied`) | `test_security.py::export_is_operator_only` |
| No MCP `outputSchema`; `null` accepted; array item bounds unenforced | all six tools advertise `outputSchema`; nulls rejected; per-item `maxLength` enforced | `test_security.py::schema_enforcement` |
| Real personal identifiers in `tests/test_acceptance.py` | genericised to `Operator`/`Project_V`/`Printer_A` | acceptance suite unchanged and green |
| Docs claimed the repository was unpushed/unpublished | corrected in COMPARISON, PHASE_STATUS, CHANGELOG, baseline; threats 13/14 added | doc review |
| Eval results recorded `git_dirty=true` | regenerated at `093ed5a` with a clean tree | `eval/check_results.py` stable |

Validation actually run after the fixes (this checkout, Python 3.14.7):
`python scripts/check_all.py` → all 7 steps passed (acceptance 10/10, migration 7/7,
memory architecture 8/8, MCP 11/11, security 14/14, demo transcript match, eval stable).
The installed plugin copy was re-synced and passes `test_acceptance.py` 10/10,
`test_migration.py` 7/7, `test_security.py` 14/14 from
`/home/djr/.hermes/plugins/living-cortex`.

MCP client status after this phase:
- Grok CLI: registered (`grok mcp add hungry-hippa -s user -e HUNGRY_HIPPA_DB=… -- python
  mcp_server.py`); `grok mcp doctor` → server started, handshake OK (protocol 2024-11-05),
  6 tools discovered. A two-session Grok conversation is still NOT run: `grok -p` returns
  `402 Payment Required — Grok Build usage balance exhausted`, a client-side billing block.
- Codex CLI: registered the same way and used for the two-session check. Session 1 (fresh
  process) stored `E-0001` over MCP; session 2 (separate process, no history) recalled it
  verbatim and reported the failed approach. Both point at
  `~/.grok/hungry-hippa-demo/hungry_hippa.db`, not the live database.

Rollback: `git revert` the six commits above; each is independent. The behaviour changes
are documented in `CHANGELOG.md` under "Security (post-audit hardening)".

Still open, and stated rather than implied: the Grok two-session demonstration (blocked on
Grok billing, not on the runtime), encryption at rest, tamper-evident audit chain,
per-caller quotas, authenticated MCP transport, multi-tenant isolation, LLM-judged eval
metrics, and a recorded demo video.






---

