# Hungry Hippa security notes

What the runtime actually enforces, what it does not, and how to run it safely.
The threat-by-threat analysis is in `docs/THREAT_MODEL.md`; disclosure is in
`/SECURITY.md`.

This is a local-first tool for one operator. It is not hardened, it is not
"unhackable", and it is not an access-control product. Read the "not provided"
section below before putting anything sensitive in it.

## Authorization model

Hungry Hippa uses **actor + policy checks**. It is deliberately *not* described as
capability-based security: there are no unforgeable, revocable, time-limited
capability tokens, and no delegation model. A caller states an `actor_id`; the
runtime applies fixed rules from `policy.py`:

| Caller | Writes | Reads | Forget (archival) | Purge |
|---|---|---|---|---|
| owner (`primary`, `owner`) | normal | everything; quarantined rows only when `include_quarantined` is set | anything | allowed with an explicit confirmation flag |
| any other actor | stored quarantined | only its own `unclassified`, non-quarantined rows | only rows it may read | always denied |

The default actor for the MCP surface is `mcp-untrusted`. `actor_id` is
caller-supplied: it is a **policy selector, not authentication**. Whoever can start
this process can claim to be the owner — a known, documented limitation, and the
reason the MCP transport is stdio-only. Two hardening details follow from it:

- Archival is authorized **per record**, using the same read policy: an actor may
  archive only a record it is allowed to read, so an untrusted caller cannot take
  another actor's memory out of normal recall. Denials are written to the audit log
  as `forget_denied`.
- A **whitespace-only** `actor_id` is treated as untrusted. It never falls back to
  the owner actor (`policy.normalize_actor`); only `None` or the empty string means
  "no actor supplied" and resolves to the local owner default.

Sensitivity (`unclassified`/`internal`/`private`/`restricted`) is a **read-policy
label stored in plain text**. It is not encryption and not a data-classification
system. Untrusted actors cannot raise the label of their own writes.

## Controls implemented

### Request shape and size

| Control | Limit | Where |
|---|---|---|
| Query length | 8 000 chars | `limits.py`, MCP schema, `cortex` tool |
| Content length (claim, context, result, …) | 32 000 chars | same |
| Array length | 256 items | same |
| Result text (context/rendering) | 20 000 chars | `tools.py`, `mcp_server.py` |
| Single MCP result frame | 40 000 chars, then a truncation notice | `mcp_server._result` |
| MCP calls per process | 1 000 by default (`HUNGRY_HIPPA_MAX_MCP_CALLS`) | `limits.CallBudget` |
| Retrieval items | `retrieval.max_items` (6), hard cap 50 | `retrieval.py`, MCP schema |
| Context budget | `retrieval.max_context_chars` (1500) | `retrieval.compile_context` |

Rejections are explicit: the caller gets `{"ok": false, "error": "... exceeds N
characters"}` rather than a silent truncation. Truncation only happens where a
partial answer is still useful, and it leaves a visible `…[truncated]` marker.

The call budget is a blunt resource guard against a runaway loop. It does not
identify or authorize callers.

### Database access

- Every SQL statement is parameterized. String interpolation is only used with
  fixed internal table/column names chosen from literal tuples.
- No MCP tool accepts SQL, a file path or a database path.
- There is no MCP export, dump or schema tool. The legacy surfaces that do export
  (`cortex` action `export` and `hermes living-cortex export`) are **owner-only and
  audited**: a non-owner actor gets `{"error": "export is operator-only; ..."}`, the
  denial is recorded in `mutation_log` as `export_denied`, and every successful
  export is recorded as `export`. Export writes `SELECT *` output to a
  caller-specified path, so it stays an operator-side maintenance action and is not
  part of the agent-facing contract.
- Evidence rows are insert-only; `add_evidence` never updates in place.
- Forgetting defaults to reversible archival; archival is authorized per record
  (see above) and purge is owner-only and, over MCP, requires `confirmation: true`
  as well.
- **Migration safety:** applying pending schema migrations to an existing database
  always writes a `*.pre-migration-<UTC>.bak` copy first — including the implicit
  upgrade performed by an ordinary open (status, plugin start, MCP server startup),
  not just `hermes living-cortex migrate`. Brand-new databases and already-current
  databases are not backed up. The copy is created with the source database's own
  permission bits (a `0600` database yields a `0600` backup), so the backup is never
  readable by other local users when the database is not. Rotating or pruning old
  backups is not implemented.

### Quarantine

Untrusted writes are stored quarantined at the write layer
(`episodic.remember_episode`, `semantic.add_belief`), so no code path can skip it.
Quarantined rows are excluded from default recall, from belief listing/search,
from the context compiler, and from consolidation input, so injected content
cannot be laundered into a derived belief or a summary. An owner reviewing them
sees a `[QUARANTINED]` marker in the rendered context.

### Log redaction

Likely credentials (private-key blocks, OpenAI/GitHub/AWS/Google/Slack key shapes,
JWTs, bearer tokens, `key = value` assignments) are replaced with
`[REDACTED:<kind>]` before they are written to `mutation_log` or `retrieval_log`.
Memory content and immutable `evidence` rows keep exactly what they were given —
redacting a memory would corrupt the record it exists to preserve. Redaction is
pattern-based and therefore best-effort.

### Failure behavior

Database helpers return empty results instead of raising into the agent loop, and
`db.failures` counts them. The MCP server converts handler exceptions into
`isError` tool results so one bad call cannot take down a session.

## Encryption at rest

Not implemented. Hungry Hippa writes a plain SQLite database (WAL mode). If the
contents matter, the expectation is that you encrypt the disk:

- Linux: LUKS (or an encrypted home / filesystem holding `$HERMES_HOME`);
- macOS: FileVault;
- Windows: BitLocker.

Additional requirements if you enable them:

- File permissions: the DB and its `-wal`/`-shm` siblings should be readable only
  by your user (default `umask` behaviour on a single-user home directory).
- Backups created by `hermes living-cortex migrate` (`*.pre-hippa-<UTC>.bak`) are
  plain copies of the database. They inherit its exposure: keep them on encrypted
  storage and delete them when no longer needed.
- SQLCipher (an encrypted SQLite variant) is **not** supported and is not a
  dependency. Adding it would mean a new runtime dependency, which this project
  avoids without a documented benefit.

## Not provided

- No encryption at rest, no per-field encryption, no key management.
- No tamper-evident audit trail. `mutation_log` is append-only by convention; it
  is not a hash chain, and someone with write access to the file can alter it.
- No multi-user accounts, quotas, or tenant isolation. One database, one owner.
- No network transport, remote access or OAuth. There is no listener to secure.
- No automatic detection of poisoned content from a caller claiming to be the
  owner. Quarantine protects against untrusted *actors*, not against a
  compromised process that can start the server.
- No secrets scanner over already-stored memories. Redaction covers log writes
  only.

## Running it safely (checklist)

1. Keep the MCP transport stdio-only. Do not wrap it in a socket forwarder or
   expose it through a network service.
2. Never pass `actor_id: "primary"` on behalf of a caller you do not control.
3. Encrypt the disk holding `$HERMES_HOME` if the memories matter.
4. Set `HUNGRY_HIPPA_MAX_MCP_CALLS` when a session is long-lived.
5. Review quarantined rows periodically:
   `hermes living-cortex recall "<topic>" --quarantined`, then decide to keep or
   forget them. Without the flag, quarantined content never appears.
6. Prefer `mode: archival` over `purge`. Archival is reversible; purge is not.
7. Treat the database as the sensitive artefact it is: it accumulates whatever
   the agent has seen.

## Verifying the controls yourself

```bash
python tests/test_security.py          # limits, redaction, policy, injection, no-export
python tests/test_mcp_schema.py        # schemas, policy, stdio round trip
python tests/test_memory_architecture.py  # quarantine, explain, context budget
python tests/test_acceptance.py        # T1-T10 still pass
```

Each test uses a throwaway temporary database. None of them touch
`$HERMES_HOME/living_cortex.db`.
