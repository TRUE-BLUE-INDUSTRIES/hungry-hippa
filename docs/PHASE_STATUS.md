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

