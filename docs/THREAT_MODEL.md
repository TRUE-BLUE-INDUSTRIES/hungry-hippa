# Hungry Hippa threat model

Scope: the Hungry Hippa memory runtime in this repository — the Hermes
`MemoryProvider` plugin (`living-cortex`, tool name `cortex`), the local stdio MCP
server (`mcp_server.py`), the SQLite store and the retrieval/context pipeline.

This document describes what is actually implemented. Anything listed under
"not covered" is not a claim that it is impossible — it is work that has not been
done, and it should be treated as an open risk.

## Assets

| Asset | Where it lives | Why it matters |
|---|---|---|
| Memory contents (episodes, beliefs, procedures) | SQLite DB (`hungry_hippa.db`, legacy `living_cortex.db`) | Operator's accumulated work history, preferences, project state |
| Immutable evidence rows | `evidence` table | The provenance record a belief is traced back to (`why()`) |
| Knowledge graph | `entities`, `relationships` | Current-state facts and history |
| Audit trail | `mutation_log`, `retrieval_log`, `forget_log` | Explains what changed, when and why |
| Vector index | `vectors` + local Ollama embeddings | Optional; disabled degrades to keyword/graph recall |
| Caller identity policy | `policy.py` | Decides who can read or purge what |

## Trust boundaries

1. **Operator ↔ Hermes agent process.** The operator runs the agent. Anything the
   agent can read, the operator can read. Not a boundary we defend.
2. **Hermes agent ↔ memory runtime.** In-process Python calls. Not a security
   boundary; the `cortex` tool is a request-shape and policy boundary only.
3. **MCP client ↔ MCP server.** A separate process speaking JSON-RPC over stdio.
   This *is* a boundary: the client is untrusted by default (`mcp-untrusted`).
4. **Runtime ↔ local disk.** SQLite files sit on the operator's filesystem with
   ordinary file permissions. Anyone with filesystem access to the DB has the
   memory contents; see `docs/SECURITY.md` on disk encryption.
5. **Runtime ↔ network.** There is no network listener. Remote access is out of
   scope by design and not implemented.

## Threats, controls, and residual risk

### 1. Prompt injection into stored memories

*Threat:* a web page or tool result instructs the agent to store "ignore the
lockout procedure" as a durable fact; a later session reads it back as truth.

*Implemented:* every belief records `source_class`; `hermes_inference` and
`external_source` start at lower confidence (`source_confidence` in `config.py`),
retrieval reports provenance per item, and rendering labels hypotheses
`HYPOTHESIS` so an inference is never presented as fact. `explain=True` shows the
provenance class of each retrieved item.

*Residual:* the runtime cannot detect a well-formed lie from a trusted-sounding
source. Provenance and confidence are signals for the reader, not filters.

### 2. Memory poisoning via an untrusted writer

*Threat:* a malicious MCP client writes a false memory that then influences later
sessions.

*Implemented:* any non-owner actor's write is stored **quarantined**
(`policy.write_quarantine`, enforced in `episodic.remember_episode` and
`semantic.add_belief`, so no call path can bypass it). Quarantined rows are
excluded from default recall, from `search_beliefs`/`list_beliefs`, and from the
consolidation input (`list_episodes_full`) — so an injected episode cannot be
laundered into a derived belief. An owner reviewing them sees a `[QUARANTINED]`
marker. Tested by `tests/test_memory_architecture.py` and
`tests/test_security.py`.

*Residual:* the owner can still accept a quarantined memory manually, and nothing
detects poisoning performed by a client that claims `actor_id: "primary"` — see
threat 5.

### 3. Unauthorized bulk extraction

*Threat:* a client tries to drain the store (all episodes, all beliefs, raw DB).

*Implemented:* there is **no** MCP tool that dumps rows, exports the database, or
takes a path/DB/SQL argument (`tests/test_mcp_schema.py`,
`tests/test_security.py`). `hippa_status` returns counts only. `hippa_recall`
returns at most `limit` items (cap 50) and the context compiler caps the rendered
text. `export` remains a local CLI command (`hermes living-cortex export`) that a
human runs on their own machine.

*Residual:* an allowed caller can still page through recall results repeatedly.
The per-process call budget bounds that; it does not stop a patient attacker.

### 4. Malicious or buggy MCP clients

*Threat:* a client sends malformed frames, unknown methods, oversized payloads,
or endless calls.

*Implemented:* strict tool schemas (`additionalProperties: false`, required
fields, enums, bounds, length caps) plus a second length check in `limits.py`;
`-32700` for unparseable frames, `-32601` for unknown methods, `isError` tool
results instead of exceptions, a per-process call budget, and a hard cap on a
single result frame. Tested in `tests/test_mcp_schema.py` /
`tests/test_security.py`.

*Residual:* one process-wide budget, not per-client quotas. A client that can
start the process can also read its stdout.

### 5. Impersonation of the owner actor

*Threat:* an MCP client passes `actor_id: "primary"` and becomes the owner.

*Implemented:* nothing prevents this. `actor_id` is caller-supplied by design;
the boundary is "whoever can start this process". This is documented in
`docs/MCP.md` and is the main reason the MCP surface is stdio-only and must not be
put behind a network wrapper.

*Residual:* accept and document, or add an authenticated transport later. Do not
describe it as solved.

### 6. SQL injection

*Threat:* SQL smuggled through a query, claim, id or filter.

*Implemented:* all statements are parameterized. The only string-interpolated
identifiers are fixed internal names (table/column choices from literal tuples).
`tests/test_security.py` drives six injection payloads through recall, remember and
forget and asserts the schema is intact, no side effects occur, and the payloads
are stored as inert text.

*Residual:* none known; the test set is a guard, not a proof.

### 7. Path traversal / arbitrary file access

*Threat:* a caller makes the runtime read or write an arbitrary path.

*Implemented:* no MCP tool accepts a path, file or database argument. The DB path
comes from config/env, not from a tool call. `hippa_status` only reveals the path
to owner actors.

*Residual:* whoever controls the environment controls the DB path — that is the
operator's own configuration.

### 8. Oversized payloads / denial of service

*Threat:* a huge string, huge array, or a call loop exhausts memory or CPU.

*Implemented:* query 8k, content 32k, array 256 items, result text 20k, result
frame 40k, per-process call budget (`limits.py`). Rejected on both surfaces.
Retrieval is bounded: item limit, graph hop limit, FTS row limit, character
budget.

*Residual:* several large-but-legal calls can still consume CPU; there is no
timeout or per-caller quota.

### 9. Secrets stored as memories

*Threat:* an agent stores an API key as a memory, and it ends up in an audit log.

*Implemented:* likely credentials (private-key blocks, OpenAI/GitHub/AWS/Google/
Slack shapes, JWTs, bearer tokens, `key = value` assignments) are replaced with
`[REDACTED:<kind>]` before anything is written to `mutation_log` or
`retrieval_log`. Memory content and immutable evidence rows are deliberately
**not** rewritten — silently altering a memory would corrupt the record.
`tests/test_security.py` checks both the redaction and the preservation, and scans
all tracked files for credential-shaped strings.

*Residual:* pattern-based, so an unusual key format can slip through; and the
secret is still in the memory content itself (that is what the operator asked to
store). Sensitivity labels are not encryption.

### 10. Cross-agent / cross-user data leakage

*Threat:* one client reads another's memories.

*Implemented:* untrusted actors read only rows they wrote, only when
`unclassified` and not quarantined (`policy.may_read`); untrusted callers cannot
raise the sensitivity label of their own writes; recall exclusions are reported
as content-free `{item, reason}` records.

*Residual:* a single shared SQLite database with one process and one owner actor
is not multi-tenant isolation. There is no per-user account model.

### 11. Tampering with provenance or audit records

*Threat:* rewrite `evidence`, delete audit rows, or forge `derived_from`.

*Implemented:* evidence rows are insert-only in `db.py` (update attempts are
refused by design and evidence content is hashed at write time), memory revisions
create new rows and mark the old ones `superseded`/`contradicted` instead of
overwriting claims, and forgetting defaults to reversible archival.

*Residual:* `mutation_log` is an append-only *convention*, not a tamper-evident
hash chain. Anyone with write access to the DB file (or to the machine) can edit
the logs with a SQLite client. Detecting that requires OS-level controls or a
future hash chain — not implemented.

### 12. Quarantine as a laundering path

*Threat:* untrusted content enters normal memory indirectly (via consolidation,
dedupe, summaries or graph edges).

*Implemented:* quarantined rows are excluded from `list_episodes_full` (the
consolidation input), from `list_beliefs`/`search_beliefs`, and from the context
compiler unless an owner explicitly reviews them.

*Residual:* relationships created by untrusted code would not be quarantined —
`relate()` is not exposed over MCP, and graph writes still come from the primary
process only.

### 13. Denial of recall by archival (memory integrity)

*Threat:* a caller that cannot read a private memory still removes it from normal
recall by archiving it, silently degrading the operator's history.

*Implemented:* `Controller.forget` applies the read policy to the target row before
archiving (`Controller._may_forget`, via `policy.may_read`), so an actor may archive
only a record it is allowed to read; the denial is returned as
`{"error": "forget denied for this actor", "policy_reason": ...}` and written to
`mutation_log` as `forget_denied`. `test_security.py`
(`untrusted_archival_denied_per_record`) and `test_mcp_schema.py`
(`purge_denied_over_mcp`) cover the untrusted and owner paths.

*Residual:* this is a policy check on a caller-supplied `actor_id`, so the
impersonation limitation of threat 5 applies unchanged; archival remains reversible
and audited.

### 14. Silent schema upgrade of an existing database

*Threat:* a routine open of an older database (status, plugin start, MCP startup)
applies migrations in place, leaving no pre-upgrade copy to roll back to.

*Implemented:* any pending migration against a pre-existing, non-empty database
writes `*.pre-migration-<UTC>.bak` through the SQLite backup API before the first
migration script runs (`db.Database._ensure_schema`, exposed as `db.last_backup`).
Brand-new and already-current databases are not backed up.
`test_migration.py::implicit_open_backs_up_before_upgrading` asserts the backup
contents equal the pre-migration state.

*Residual:* the backup is a plaintext copy next to the database — it inherits the
same file permissions and is not encrypted at rest. Automated retention/pruning of
old backups is not implemented.

## Explicitly not covered

- Encryption at rest, key management, per-field encryption. See
  `docs/SECURITY.md` for the OS-level expectations instead.
- Tamper-evident audit trail (no hash chain).
- Multi-user accounts, per-user quotas, tenant isolation.
- Network transports, remote access, OAuth (there is no network listener at all).
- Malware or a hostile user with filesystem access to the database.
- Adversarial-review-level assurance. The tests here are guards written by the
  same author as the code; treat them as regression protection, not proof.
