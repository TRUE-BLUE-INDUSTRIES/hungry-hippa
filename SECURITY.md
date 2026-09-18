# Security policy — Hungry Hippa

Hungry Hippa (formerly Living Cortex) is a local-first memory runtime for AI
agents, maintained by True Blue Industries. This file covers how to report a
security issue.

## Reporting a vulnerability

Open a private report through GitHub:

- **Security advisories:** https://github.com/TRUE-BLUE-INDUSTRIES/hungry-hippa/security/advisories/new
- **Issues (for non-sensitive reports):** https://github.com/TRUE-BLUE-INDUSTRIES/hungry-hippa/issues

There is no dedicated security email address, and none should be assumed.

Please include:

- the affected version or commit,
- what you ran (exact commands, MCP tool calls, or CLI invocations),
- what you expected and what happened,
- whether the database, the MCP surface, or the in-process adapter is involved,
- and, if relevant, a minimal reproduction using a throwaway database.

**Please do not attach a real memory database, real credentials, or private
memories to a report.** A redacted reproduction or an invented equivalent is
enough; if you think a real database is required, say so and wait for a response
before sending anything.

## What to expect

This is a small project without a formal SLA or a security team. Reports are
triaged by the maintainer:

- acknowledgement of a report when it is opened,
- an assessment, including whether the behaviour is a known documented
  limitation (see `docs/THREAT_MODEL.md` and `docs/SECURITY.md`),
- a fix or an explicit "not fixed, here is why" decision for accepted issues,
- credit in the changelog if you want it.

Please give a reasonable window for a fix before disclosing publicly.

## Known limitations are not vulnerabilities

The following are documented, intentional limitations, not unknown issues. Read
them first — reports about them will be answered by pointing at the docs:

- MCP identity is bound to the server launch channel. An actor label alone cannot
  grant owner identity; the owner token must verify. A process running as the same
  OS user can read that token and the store. MCP remains stdio-only.
- Actor + policy checks are **not** capability-based security.
- There is no encryption at rest; disk encryption is the operator's
  responsibility.
- `mutation_log` is append-only by convention, not a tamper-evident hash chain.
- Log redaction is pattern-based and best-effort; it covers audit logs, not the
  stored memory content.
- There is no multi-user account model or tenant isolation.
- Quarantine protects against untrusted *actors*, not against a compromised
  process that can act as the owner.

## Supported versions

The released baseline is v1.0.0 (schema v5). This unreleased ingestion branch
adds schema v6/v7 and is validated on isolated test stores.
The pre-rename Living Cortex code is supported only through the migration path
described in `docs/MIGRATION.md`.

## Historical imports

Imports are untrusted data. ChatGPT JSON passes bounded regular-file reading,
JSON/depth/node/lineage validation and exact-byte provenance checks before a
transaction can persist history. Symlink leaves and special files are refused;
paths embedded in content are never followed. Importing grants no model or
operator authority, does not execute HTML/code, and creates no derived memory.
See [input limits](docs/INGESTION.md) and `tests/test_ingest_integrity.py`.

Original bytes live in the same plaintext database and its backups. Hashes detect
inconsistency, not authenticated provider identity or tampering by a process that
can rewrite hashes. There is no encrypted backup implementation yet.
