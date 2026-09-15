# Hungry Hippa migration plan (formerly Living Cortex)

Hungry Hippa is a local-first memory runtime for AI agents. Spelling is exactly **Hungry Hippa**. Do not confuse the name with HIPAA and do not make healthcare-compliance claims.

This plan is incremental. Working Living Cortex behavior stays until compatibility wrappers and migration tests exist. Do not rewrite the runtime to look cleaner.

**Goal:** Convert the existing plugin into a polished, testable, demonstrable product that Hermes still loads, Grok CLI can use over local MCP, and existing SQLite memories survive.

**Architecture:** Keep the Python `MemoryController` + SQLite core. Add a product façade (`hungry_hippa`), compatibility shims for `living-cortex` / `LIVING_CORTEX_*` / `cortex`, deterministic DB migrations, a stdio MCP server wrapping the same controller, then layer missing memory, security, eval, demo, and packaging work on top.

**Tech stack:** Python 3 stdlib + SQLite (WAL, FTS5) + optional local Ollama embeddings. No new runtime dependency without a documented benefit. MCP stdio using the Python standard library or a single small SDK only if tests require it.

**Spec:** `/home/djr/Documents/masterP.txt` (operator brief). Baseline: `docs/LIVING_CORTEX_BASELINE.md`.

## Global constraints

- Product name: `Hungry Hippa`
- Technical description: `Local-First Memory Runtime for AI Agents`
- Python package where applicable: `hungry_hippa`
- CLI command: `hippa` (keep `hermes living-cortex` as a compatibility alias)
- Environment prefix: `HUNGRY_HIPPA_` (keep `LIVING_CORTEX_DB` with a deprecation warning)
- Database default: `hungry_hippa.db` (migrate from `living_cortex.db`)
- Branch: `feat/hungry-hippa`
- Never erase Git history; never push/publish without explicit approval
- Never dump private production memories
- Do not rename every internal symbol mechanically
- Do not claim training, consciousness, unhackability, or enterprise-readiness
- One descriptive Git commit per completed phase
- Hermes sub-agent: bounded audits/tests/docs only; primary agent owns architecture and commits
- Do not edit the live `$HERMES_HOME/living_cortex.db` during development; tests use throwaway copies

## Compatibility policy

Until Hungry Hippa is the documented default:

1. Hermes still discovers a provider named `living-cortex` **or** a wrapper that registers under that name and `hungry-hippa`.
2. The `cortex` tool remains; new `hippa_*` MCP tools are additive.
3. Old env keys and DB filenames are accepted, warned, and migrated.
4. Existing T1–T10 keep passing on every phase commit.
5. Living Cortex interfaces are not deleted until wrappers + migration tests exist.

## File ownership (avoid concurrent edits)

| Area | Owner |
|---|---|
| schema / db / controller / retrieval | primary |
| Hermes provider (`__init__.py`, `tools.py`, `cli.py`) | primary |
| MCP server (new files) | primary, Hermes may draft tests |
| Docs | primary after Hermes review |
| Eval / demo scripts (new files) | Hermes may implement after primary sketches the API |

---

## Phase 1 — Audit and baseline (this commit)

**Objective:** Record architecture, tests, risks, and this plan. No runtime change.

**Files:** `docs/LIVING_CORTEX_BASELINE.md`, `docs/MIGRATION_PLAN.md`

**Hermes task:** Independent inventory (read-only). Completed; conflicts recorded in the baseline and in the Phase 1 report.

**Validation:** `python tests/test_acceptance.py` → 10/10 (already recorded).

**Rollback:** delete the two docs; branch can be abandoned.

**Status:** in progress at plan-write time; commit closes the phase.

---

## Phase 2 — Safe rebrand and database migration

**Objective:** Product-facing Hungry Hippa names without breaking Hermes or existing DBs.

**In scope:**

- `plugin.yaml` description + dual names
- `config.py`: `HUNGRY_HIPPA_DB` / `HUNGRY_HIPPA_` overlay; warn on `LIVING_CORTEX_DB`
- Default DB filename `hungry_hippa.db` with discovery of `living_cortex.db`
- `schema.py` migration v3: metadata table recording product name / former name; no destructive column rewrites
- Backup-before-migrate helper (SQLite backup API) used by CLI `hippa migrate`
- Compatibility: provider `name` stays loadable as `living-cortex`; add `hungry-hippa` alias if the host allows one provider
- CLI: `hermes living-cortex` remains; add `hippa` module entry if we add packaging later — for this phase, add `hermes living-cortex` help text “formerly Living Cortex / Hungry Hippa”
- Docs note in README header only if tests still pass; full README polish is Phase 8
- Tests: copy a fixture DB named `living_cortex.db` with known episode/belief ids, run migrate, assert ids and claims survive, assert backup file exists, assert rollback instructions in docs

**Out of scope:** renaming every class (`MemoryController` may stay). Do not rename tables.

**Hermes task:** Write `tests/test_migration.py` against a throwaway copy; do not touch the live home DB.

**Validation:**

```
python tests/test_acceptance.py
python tests/test_migration.py
```

**Evidence of success:** existing memories survive; deprecation warning on old env; backup created; T1–T10 still pass.

**Rollback:** restore from the `.bak` copy; set `LIVING_CORTEX_DB` / old filename; checkout previous commit.

---

## Phase 3 — Memory architecture (additive, conservative)

**Objective:** Make the operations the product needs explicit, without forcing unused columns.

Already present (keep): unique ids, timestamps, session, episode/belief/procedure kinds, content, entities, relationships, confidence, importance/salience, provenance, supersession, contradiction, retention-ish status, evidence hash.

Add only what is missing and testable:

1. **Sensitivity + quarantine** — optional columns via migration v4 with defaults (`sensitivity=unclassified`, `status` already has active/archived; add `quarantined` as a status or a boolean). Untrusted MCP/tool inserts default to quarantine if caller is not the owner.
2. **Caller identity on writes/reads** — `actor_id` / `agent_id` on new rows (nullable default `primary`). Retrieval filters by policy.
3. **Explainable ranking** — `recall(..., explain=True)` returns per-item score parts (relevance, recency, salience, confidence, provenance, contradiction/supersession, budget drop). Debug must not leak unauthorized contents.
4. **Context compiler** — structured package `{items, rendering, token_estimate, excluded[]}` with character/token budget, dedupe, prefer current over superseded, provenance, verified-vs-hypothesis distinction. Keep current string rendering as `rendering`.
5. **Outcome recording** — already `record_outcome`; expose it on the tool/MCP surface as `hippa_record_outcome`.
6. **Supersession/contradiction** already exist; add tests that retrieval prefers current.
7. **Do not implement silent deletion.** Archival/tombstone remains default.

Do not add unused metadata fields “for completeness.”

**Hermes task:** unit tests for ranking explanation, budget, supersession preference, quarantine exclusion. Primary implements controller/retrieval changes.

**Validation:** new tests + T1–T10.

**Rollback:** migration v4 down_sql; feature flags defaulting to old renderer.

---

## Phase 4 — Local MCP (cross-agent)

**Objective:** Expose the same controller over MCP so Grok CLI and other local clients can use Hungry Hippa. Local default. Remote disabled.

Transport order:

1. MCP stdio (required)
2. Unix-domain socket (optional, later)
3. Loopback HTTP (optional, later, off by default)
4. Remote network: do not implement

Tools (strict schemas, no SQL, no filesystem, no raw DB download):

| Tool | Maps to |
|---|---|
| `hippa_remember` | `remember_episode` / `add_belief` with explicit type |
| `hippa_recall` | `recall` |
| `hippa_build_context` | context compiler |
| `hippa_record_outcome` | `record_outcome` |
| `hippa_forget` | archival default; purge requires a distinct confirmation flag and is denied to non-owner |
| `hippa_status` | counts + health, no row dump |

Remove or gate `export` on the MCP surface. Hermes `cortex` tool may keep `export` behind a local-CLI-only path, not MCP.

Preserve Hermes integration tests (T10). Add `tests/test_mcp_schema.py` that instantiates the server in-process and calls tools. Add a **sample** Grok `config.toml` snippet in docs; do not claim Grok was tested until a real Grok session calls the server.

**Hermes task:** schema/error/authorization review of the MCP module; integration tests in a separate file.

**Validation:** in-process MCP tests; T1–T10; `hermes memory status` still living-cortex/hungry-hippa.

**Rollback:** leave MCP module unused; Hermes path unchanged.

---

## Phase 5 — Security and integrity

**Objective:** Practical controls matching the threat model. Security is a foundation, not the novelty claim.

Threats: prompt injection into stored memories, memory poisoning, unauthorized bulk extraction, malicious MCP clients, SQL injection, path traversal, oversized payloads, DoS, secrets stored as memories, cross-agent leakage, audit tampering.

Controls to implement (incremental):

- Keep parameterized SQL
- JSON schema validation on MCP/tool args with max lengths
- Result size caps
- Simple per-process rate / item limits
- Actor + policy checks on recall/forget
- Sensitivity + quarantine (from Phase 3)
- Mutation log remains append-only; document that it is tamper-evident only with OS file integrity, not a hash chain unless a small hash-chain is cheap and tested
- Encryption-at-rest: document OS disk encryption; optional SQLCipher is **out of scope** unless a dependency is approved
- Redact secrets in logs (scan tool args before logging)
- No raw schema dump over MCP

Authorization: this is **policy/identity checks**, not capability-based security, unless we add narrowly scoped, revocable, time-limited grants. Do not call it RBAC-as-capability.

Docs: `docs/THREAT_MODEL.md`, `docs/SECURITY.md`, root `SECURITY.md` (responsible disclosure).

**Hermes task:** adversarial test plan + tests for unauthorized recall, oversized payload, export-denied-on-MCP. Hermes must not print secrets or live DB rows.

**Validation:** new security tests + T1–T10.

**Rollback:** feature-flag strict MCP auth off only in tests; never ship MCP without auth checks.

---

## Phase 6 — Hungry Hippa Memory Challenge

**Objective:** Reproducible harness: same agent without vs with Hungry Hippa. Real numbers only.

Scenarios: cross-session recall, decision rationale, avoid failed solution, superseded info, token budget, cross-agent portability, user forget, poison resistance, unauthorized retrieval, growth/performance.

Store JSON results + Markdown report. Unsupported metrics marked unsupported.

Use throwaway DBs and seed data with **no personal information**.

**Hermes task:** review harness for reproducibility; do not invent results.

**Validation:** run harness once; commit only if JSON is produced by the run.

**Rollback:** delete `eval/` if it misleads.

---

## Phase 7 — Demonstration

**Objective:** Repeatable local demo, no production DB.

Script:

1. Agent starts a small project
2. Records a decision, failed fix, outcome
3. Session ends
4. New session without conversation history
5. Hippa restores context
6. Agent avoids the failed fix
7. Second agent sees only authorized memories
8. User inspects, corrects, forgets

Deliver: `demo/README.md`, seed data, reset command, scripted demo, expected output, two-minute video instructions.

**Hermes task:** run demo from a clean temp dir; report reproducibility issues. Do not claim the demo works until independently run.

**Rollback:** demo is additive.

---

## Phase 8 — Packaging

**Objective:** A stranger can install and test without contacting the operator.

- Root README with the required opening sentence
- Architecture diagram (text/mermaid from real modules)
- Quick start, sample config, MCP client examples (mark untested)
- Troubleshooting, migration guide, changelog, contributing, license notes
- `docs/TECHNICAL_REPORT.md`
- Automated tests (keep custom runner; add pytest only if it simplifies CI)
- CI config (GitHub Actions running T1–T10 + migration + MCP schema tests)
- Release checklist
- One-command dev setup where practical (`python tests/test_acceptance.py`)

**Hermes task:** doc consistency, broken-link check, examples vs actual commands.

**Rollback:** docs-only revert.

---

## Phase 9 — Differentiation

**Objective:** Honest comparison vs vector-store memory, file-based notes, local event logs.

`docs/COMPARISON.md` feature matrix **only** for implemented, tested, or documented-as-absent behavior. Do not claim SQLite, encryption, semantic search, RBAC, or MCP as proprietary.

**Hermes task:** independent evidence review; strip unsupported claims.

---

## Per-phase execution checklist

Before each phase:

- State objective, files, Hermes task, validation commands, success evidence, rollback
- Pause if a decision could expose patentable detail beyond what this public repo already contains

After each phase:

- Run relevant tests
- Review the complete diff
- Confirm no secrets or private memory data
- Record actual results in the commit message body
- Commit separately
- Do not push

## Hermes coordination

For every Hermes task: define file scope, require files-changed report, require actual test output, inspect the diff, re-run tests independently, reject unrelated changes, commit only after validation. Do not let Hermes and the primary agent edit the same files concurrently.

## Definition of done (from the operator brief)

- Living Cortex still works or has a documented migration
- Grok CLI can use Hungry Hippa across sessions **once MCP is verified**, not before
- DB migrates without losing existing memories
- MCP is local
- Unauthorized callers cannot retrieve protected memories
- No interface exposes arbitrary SQL or raw DB extraction
- Demo reproducible from a clean environment
- Evaluation suite produces real results
- Docs match behavior
- All tests pass
- Repo contains no secrets or personal memory data
- A competent stranger can install and test
- Hermes work reviewed and independently validated
- One commit per phase
- Nothing pushed without approval
