# Changelog

All notable changes to this project are recorded here. The project was formerly named
**Living Cortex**; entries below the rename line describe the pre-rename state.

Format: loosely [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions are
the `version:` field in `plugin.yaml`.

## [Unreleased]

Hungry Hippa migration, phased. All entries below exist on `feat/hungry-hippa`;
the repository is public and both `feat/hungry-hippa` and `main` are pushed, with CI
run on every push.

### Security (post-audit hardening)

- **Per-record authorization on archival.** `forget` in archival mode now applies the
  read policy to the target row, so a caller can only archive a memory it is allowed
  to read. Previously an untrusted MCP client could remove another actor's private row
  from normal recall without being able to read it. Denials are audited as
  `forget_denied`. **Behaviour change:** the old behaviour was asserted by
  `test_security.py` and `test_mcp_schema.py`; both tests were corrected.
- **Whitespace `actor_id` no longer elevates.** `policy.normalize_actor("  ")` returned
  the owner actor `primary` (and `hippa_status` then exposed the database path). A
  whitespace-only identity is now treated as untrusted; only `None`/`""` mean "no actor
  supplied".
- **Implicit migration backs up first.** An ordinary open of an older database
  (`Database()`, i.e. status, plugin start, MCP startup) applied pending migrations with
  no backup; only the explicit `migrate` command backed up. Any pending migration on a
  pre-existing database now writes `*.pre-migration-<UTC>.bak` before it runs.
- **Legacy export is owner-only and audited.** The `cortex` tool's `export` action could
  write a full `SELECT *` dump to any path for any actor. It now requires an owner actor
  and records both the denial (`export_denied`) and each successful export. The
  `hermes living-cortex export` CLI command applies the same rule and is audited the same
  way.
- **MCP schemas: outputs described, inputs actually enforced.** All six tools now
  advertise an `outputSchema`; `null` values (`actor_id: null` used to fall through to
  the owner default) are rejected; string-array items are checked against their
  advertised `maxLength`.
- **Test fixtures genericised.** `tests/test_acceptance.py` used the operator's real
  first name and real device/project names in its graph fixtures
  (`Dennis`/`Voxvil`/`Prusa_XL` → `Operator`/`Project_V`/`Printer_A`). This was
  pre-existing content that survived the rename; the repository is public.

### Added

- **Memory architecture (schema v4)**: `sensitivity`, `quarantined` and `actor_id`
  columns on `episodes` and `beliefs` with constant defaults and a `down` script.
- **Quarantine and actor policy** (`policy.py`): writes from a non-owner actor are
  stored quarantined; quarantined rows are excluded from recall, belief listing/search
  and consolidation input; untrusted readers see only their own unclassified,
  non-quarantined rows; purge is owner-only.
- **Explainable recall**: `recall(..., explain=True)` returns per-item score parts
  (relevance, recency, salience, confidence, provenance class, reinforcement factor,
  total, `dropped_for_budget`) and never echoes memory contents.
- **Context compiler**: `{items, rendering, token_estimate, excluded}` with an explicit
  character budget, content dedupe, active-over-superseded preference, a `HYPOTHESIS`
  marker for inferences and a `[QUARANTINED]` marker on the owner-review path.
  `recall()["context"]` remains the rendered string.
- **`record_outcome` on the `cortex` tool**, plus an optional `explain` flag on `recall`.
- **Local MCP server** (`mcp_server.py`): six `hippa_*` tools over stdio JSON-RPC 2.0
  with strict schemas (`hippa_remember`, `hippa_recall`, `hippa_build_context`,
  `hippa_record_outcome`, `hippa_forget`, `hippa_status`). No network listener, no SQL,
  no filesystem path arguments, and no export tool.
- **Request limits** (`limits.py`): argument caps (query 8k, content 32k, arrays 256),
  result caps (text 20k, JSON-RPC frame 40k), a per-process call budget
  (`HUNGRY_HIPPA_MAX_MCP_CALLS`) and credential redaction for audit logs.
- **Security documentation**: `SECURITY.md` (responsible disclosure),
  `docs/SECURITY.md` (controls, encryption-at-rest expectations, non-claims) and
  `docs/THREAT_MODEL.md` (twelve threats, controls and residual risk).
- **Memory Challenge harness** (`eval/`): ten scenarios comparing a
  session-transcript-only agent against the runtime, deterministic and offline, with
  `eval/results.json` and a generated `eval/REPORT.md`.
- **Reproducible demo** (`demo/`): eight scripted steps on a throwaway database,
  including a real second MCP client process, with `--check` against
  `demo/expected_output.txt`.
- **Migration tooling**: `hermes living-cortex migrate` backs up with the SQLite backup
  API before applying migrations; `docs/MIGRATION.md` documents the rollback path.
- **`recall --quarantined`** on the CLI so the owner can review quarantined rows.
- Test suites: `tests/test_memory_architecture.py` (8),
  `tests/test_mcp_schema.py` (11), `tests/test_security.py` (10),
  `tests/test_migration.py` (6).
- `docs/TECHNICAL_REPORT.md`, `docs/PHASE_STATUS.md` (per-phase record including what is
  not done), `docs/RELEASE_CHECKLIST.md`, `docs/LICENSE_NOTES.md`.

### Changed

- **Product rename to Hungry Hippa.** Default database filename `hungry_hippa.db`;
  environment prefix `HUNGRY_HIPPA_`; `LIVING_CORTEX_DB` still honoured with a
  `DeprecationWarning`; an existing `living_cortex.db` is discovered and used.
- **Retrieval ranking is now explicit and decomposed**: 0.30 salience + 0.22 recency +
  0.22 relevance + 0.13 term-hit bonus + 0.13 confidence, times a reinforcement factor.
  The previous formula omitted confidence and the term-hit bonus from its weights.
- Context rendering is strict about its budget (previously it could exceed a very small
  budget by one block).
- `MemoryController.build_context()` accepts `max_chars` as an alias for
  `max_context_chars`.
- Audit summaries in `mutation_log` and `retrieval_log` are redacted and length-capped;
  stored memory and immutable evidence rows are unchanged.

### Fixed

- **Untrusted semantic writes were not quarantined.** The quarantine decision lived only
  in `MemoryController.remember_episode`, so an MCP client calling the semantic path
  directly could store an unquarantined belief. The decision now lives in the write layer
  (`episodic.remember_episode`, `semantic.add_belief`).
- `procedural.record_outcome()` returned the stale pre-reevaluation row, so callers never
  saw the promotion or confidence change it had just written.
- `mcp_server.set_call_budget()` reset the counter but kept a shrunken limit, leaking a
  test's budget setting into later calls in the same process.
- Retrieval item keys were inconsistent between the retrieval pipeline (which knows
  `_kind`) and the context compiler (handed bare rows), so the same memory could appear
  as `belief:B-0001` in one place and `fact:B-0001` in another.

### Compatibility

- Hermes plugin `name` is still `living-cortex`; `hermes config set memory.provider
  living-cortex` keeps working.
- The agent tool is still `cortex`; `record_outcome` and `explain` are additive.
- Table names, existing rows and ids are unchanged by the rename and by schema v4.
- The acceptance tests T1–T10 still pass (10/10).

### Known limitations

- No encryption at rest (use OS disk encryption), no tamper-evident audit chain, no
  multi-tenant isolation, no authenticated MCP transport.
- Sensitivity is a read-policy label stored in plain text, not encryption.
- Log redaction is pattern-based and covers audit logs only.
- No external MCP client (including Grok CLI) has been run against `mcp_server.py`; the
  config snippets in `docs/MCP.md` are illustrative.

## [0.2.0] — Living Cortex

Baseline state before the rename: acceptance suite T1–T10, episodic + semantic + graph +
procedural memory, hybrid retrieval, consolidation, forgetting, observability CLI,
`cortex` tool, Hermes `MemoryProvider` integration. See
`docs/LIVING_CORTEX_BASELINE.md` for the recorded audit of that state.
