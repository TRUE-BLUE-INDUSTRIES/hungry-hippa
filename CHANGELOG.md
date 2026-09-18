# Changelog

## Unreleased

### Safe historical-import increment
- Integrate existing canonical ChatGPT ingestion work without enabling model extraction.
- Bound hostile JSON, regular-file reads, graph depth and expanded lineage; reject
  ambiguous identities and malformed export envelopes explicitly.
- Preserve exact export bytes, per-archive branch snapshots and turn provenance in
  schema v7. Refuse conflicting turns transactionally; duplicate imports are no-ops.
- Add explicit import destinations, `ingest verify` and `ingest show`; SQLite backup
  recovery retains raw bytes. No beliefs/episodes are created by importing.
- Align CI with the shared runner and validate a fresh installed wheel over real MCP.
- Add reproducible synthetic ingestion measurements and durable project documentation.

## v1.0.0 — released 2026-09-18

The following baseline changes shipped at `9b9593f`; parser-only statements describe
that release, before the unreleased write path above.

### Added
- Extract chat `max_tokens` default 768 → 2048. This LM Studio/Qwen3.8-27b build
  still emits `reasoning_content` despite `enable_thinking: false`; 768 truncated
  the JSON mid-claim (`finish_reason=length`) and extract wrote nothing.
- HH-08 ChatGPT ingest e2e: `eval/ingest_e2e.py` plus `tests/test_ingest_e2e.py`.
  Synthetic `eval/fixtures/chatgpt_e2e_conversations.json` (invented mill-setup
  notes, planted 52Nm / 12 March 2026 fact; never a real export) is ingested with
  `ingest chatgpt --apply` into a throwaway `HUNGRY_HIPPA_DB`. Raw archive pointer
  + normalized turns are asserted. Live `ingest extract --apply` against local
  LM Studio is optional (SKIP when chat is down); CI still proves ingest persist
  plus recall/why of a directly stored owner memory whose evidence points at the
  planted turn. Extracted hypotheses stay quarantined; the live demo uses owner
  CLI `recall --quarantined`. MCP still exactly six tools. Live Hermes/Grok
  stores are refused.
- `hungry-hippa ingest reconcile [--dry-run|--apply]`: Layer 4 historical ingest.
  Compares extract candidates to existing memories and classifies each as
  duplicate, reinforcement, contradiction, update, supersession, low-confidence,
  or irrelevant. Contradictions stay open (both claims + evidence). Re-import /
  re-extract of the same export is a no-op. Schema v8 adds reversible decision
  tables. Requires `HUNGRY_HIPPA_DB` (refuses live Hermes/Grok stores). MCP still
  exactly six tools.
- `hungry-hippa ingest extract [--dry-run|--apply]`: Slice 4 historical ingest.
  A local LM Studio chat model (`qwen/qwen3.8-27b` at `127.0.0.1:1234`) reads
  stored `ingest_turns` in small batches and writes **quarantined hypotheses**
  with evidence rows pointing at turn ids. Never mints verified `user_explicit`;
  `ingestion_channel=import`. Schema v7 adds reversible extract-job checkpoints.
  Requires `HUNGRY_HIPPA_DB` (refuses live Hermes/Grok stores). Offline/no-model
  `--apply` fails clearly without writing memories. MCP still exactly six tools.
- `hungry_hippa.ingest`: historical-ingestion Slice 1 — a lossless parser for ChatGPT
  `conversations.json` exports (`parse_chatgpt_export(path) -> list[ParsedConversation]`).
  Every supported textual turn is kept, including regenerated answers and edited prompts,
  with the provider's own node ids, parent ids and a root-to-node `branch_path`;
  `current_path_turn_ids` is reconstructed by walking back from `current_node`, so the
  active branch is reported separately from historical branches. Structural nodes keep
  lineage. Malformed input degrades to per-conversation warnings. Parsing only: no
  database writes, no model calls, no network, no new MCP tools.
- `hungry-hippa ingest chatgpt <conversations.json> --dry-run`: reports conversations,
  turns, current-path turns and alternate-branch turns. Without `--dry-run` it refuses.
- `tests/test_chatgpt_ingest.py` (14 checks) in `scripts/check_all.py` and CI.
- `hungry-hippa quarantine list|show|approve|reject`: operator review of memories held
  from untrusted writers. Approval reuses the existing verification semantics
  (`trust.verified_source_class` plus the single promotion write
  `SemanticMemory.set_verified_class`); rejection reuses the archival path and never
  purges. Audited as `quarantine_approved` / `quarantine_rejected`. MCP is untouched:
  still exactly six tools, and no tool can approve or reject anything.
- `tests/test_quarantine_cli.py` (8 checks) in `scripts/check_all.py` and CI.

### Changed
- Removed the hand-rolled package bootstrapping inherited from the Living Cortex era
  (`types.ModuleType` + `importlib.util.spec_from_file_location` + `sys.modules`
  injection). It existed because the runtime used to be a flat directory of modules hosted
  inside another application; Hungry Hippa is a real package under `src/` now, so the
  suites, the demo, the eval harness and the seed/build scripts import it normally.
  `tests/_package.py` is the single place that resolves it (installed package first, this
  checkout's `src/` as a fallback), and `tests/test_import_hygiene.py` (9 checks) fails the
  build if synthetic-module construction, `sys.modules` injection or a per-suite `src/`
  path insert returns.
- Renamed the last Living Cortex identifiers in current code: the `PLUGIN_DIR` constant is
  now `PACKAGE_DIR`, the selftest loader's module and scratch database are `hh_selftest`,
  and `observability` reads the legacy source-class alias from `semantic` instead of
  repeating it. Module docstrings and the seed script no longer describe the project as
  "the Living Cortex".
- Two by-path file loads remain, and are documented as such: `hungry-hippa selftest` runs
  `tests/test_acceptance.py` (a loose suite file, not a module of the package) and
  `eval/check_results.py` runs `eval/harness.py` (`eval/` is not an importable package).
- Behaviour unchanged; the migration-era compatibility surface is untouched and now
  covered by tests: the `LivingCortexProvider` alias, `hermes_inference` accepted as a
  legacy source class, the deprecated `LIVING_CORTEX_DB` environment variable, and
  discovery of a former `living_cortex.db`.

### Changed
- Runtime package moved to `src/hungry_hippa/` with package discovery from `src/` in
  `pyproject.toml`. `pip install -e .`, both console scripts, `hungry_hippa.register`,
  `HungryHippaProvider`, the compatibility aliases and legacy database discovery are
  unchanged; test/demo/eval/script path anchors were updated for the layout.
- `owner-token` help no longer suggests passing the token as a tool argument: it explains
  that `HUNGRY_HIPPA_OWNER_TOKEN` is set in the hungry-hippa-mcp **launch environment**.
- Documentation states plainly that the store is plaintext SQLite and that `0600`
  permissions are not encryption (use OS/disk encryption for sensitive memories).

All notable changes to this project are recorded here. The project was formerly named
**Living Cortex**; entries below the rename line describe the pre-rename state.

Format: loosely [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions are
the `version:` field in `plugin.yaml`.

## [Unreleased]

## [1.0.0] — official MCP SDK

Hungry Hippa is now a standalone local-first package built on the **official MCP
Python SDK**, rather than a hand-written protocol with a host-plugin wrapper.

### Changed

- **MCP transport and protocol are the SDK's.** `mcp_server.py` no longer parses
  JSON-RPC, tracks request ids, or hand-builds `initialize` / `tools/list` /
  `tools/call` responses; it registers six typed tools on the SDK's server object
  (`@app.tool()`), and the SDK negotiates the protocol revision and owns stdio
  framing. The server advertises `hungry-hippa` and the package version.
- **Owner identity is bound to the MCP launch context.** `HUNGRY_HIPPA_OWNER_TOKEN`
  is read from the server process environment once at start-up and verified against
  the operator's `0600` token file. There is no token parameter on any tool, so a
  model is never asked to handle the secret; an instance launched without a valid
  token simply is not the owner.
- **Package identity, paths and names.** The synthetic package is `hungry_hippa`
  (was `livingcortex`); `plugin.yaml` is gone and the version comes from
  `hungry_hippa.version`; the CLI is `hungry-hippa` (`owner-token`,
  `fix-permissions`, `verify`, …) with `hungry-hippa-mcp` as the server entry point;
  configuration, data and state live under XDG
  (`~/.config/hungry-hippa`, `~/.local/share/hungry-hippa`,
  `~/.local/state/hungry-hippa`) instead of another application's home directory.
- **`mcp` is a declared dependency** in `pyproject.toml`, installed by CI before the
  suites run; there is no reliance on a developer's environment.
- **Source-class vocabulary**: `agent_inference` is the canonical name for "the
  agent inferred this" (the former `hermes_inference` is still accepted on input and
  still readable from older rows).
- **System writes carry system provenance.** Consolidation's automatic merges and
  contradiction passes are stamped `identity=system`,
  `provenance=agent_consolidation`, so a background merge can never inherit a
  CLI/user trust default or mint `user_explicit`.
- **Rendered provenance is the verified class**, falling back to `source_class` only
  for rows written before schema v5.

### Added

- `tests/test_mcp_integration.py`: a real MCP session through the official SDK
  client covering initialization, tool listing, schema surface, the full
  remember/recall/context/outcome/forget flow, unauthorized purge, owner-only
  behaviour, actor-label spoofing, SDK-side validation, and stdout hygiene.
- `tests/test_trust_token.py`: token creation, mode, existing/empty/corrupt files,
  failed writes, `XDG_STATE_HOME`, the fallback state directory, the explicit
  override, strict comparison, and launch-environment binding.
- `tests/mcp_harness.py`: the shared SDK-client harness the MCP suites use.

### Removed

- The custom MCP implementation (stdin/stdout loop, JSON-RPC parsing, dispatch
  table, response builders, protocol constants) and its test suite
  (`tests/test_mcp_schema.py`); every assertion it still made moved to the
  integration suite, which proves the same properties through a real session.



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
  first name and real device/project names in its graph fixtures. Those identifiers are
  replaced with `Operator`/`Project_V`/`Printer_A`; this was pre-existing content that
  survived the rename, in a public repository. (The identifiers are deliberately not
  repeated here.)

### Security (red-team hardening pass)

Eight findings from an operator-requested red-team review, each reproduced before
being fixed and each with a named regression test. Full detail, including what is
still weak: `docs/SECURITY_AUDIT.md` and `RED_TEAM_REPORT.md`.

- **Identity is bound to the channel.** An MCP caller is the owner only with the
  owner token (`0600` file, `hermes living-cortex owner-token`); `actor_id` is a
  label, never privilege. Previously `actor_id: "primary"` read private memory,
  returned the database path and purged owner beliefs.
- **Recalled memory is framed as data** with a no-authority trust block, and every
  rendered field is neutralized so it cannot forge markup, a metadata header or a
  role turn. Not a claim that prompt injection is solved.
- **Non-enumerating exclusions**: an unauthorized caller no longer learns whether a
  protected memory exists, or its id, or graph entity names.
- **Owner-only file permissions** for new databases, backups and exports (never
  wider than the source), with `fix-permissions` as the explicit remedy for an
  existing lax file.
- **Provenance split** (schema v5): `claimed_source_class` vs
  `verified_source_class`, plus `source_actor` and `ingestion_channel`. The model's
  text is `agent_reported`; confidence is capped by the verified class.
- **Protected facts cannot be rewritten by a non-operator channel**: supersede is
  refused, a contradiction becomes a quarantined candidate, and ordinary rows are
  unaffected.
- **Capability ladder** per channel: the model may read and write candidates, not
  approve, correct or forget protected facts, or purge. Purge additionally needs an
  operator channel and is audited when refused.
- **Volume controls**: database-backed write quota that survives process restarts,
  database-size warning, configurable consolidation scan caps, clamped graph hops,
  and backups that refuse to run without space.

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
