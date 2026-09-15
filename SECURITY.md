# Security policy — Hungry Hippa

Hungry Hippa (formerly Living Cortex) is a local-first memory runtime for AI
agents, maintained by True Blue Industries. This file covers how to report a
security issue.

## Reporting a vulnerability

Open a private report through GitHub:

- **Security advisories:** https://github.com/TRUE-BLUE-INDUSTRIES/living-cortex/security/advisories/new
- **Issues (for non-sensitive reports):** https://github.com/TRUE-BLUE-INDUSTRIES/living-cortex/issues

There is no dedicated security email address, and none should be assumed.

Please include:

- the affected version or commit,
- what you ran (exact commands, MCP tool calls, or CLI invocations),
- what you expected and what happened,
- whether the database, the MCP surface, or the Hermes plugin is involved,
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

- `actor_id` is caller-supplied. A process that can start the MCP server can claim
  to be the owner actor. The MCP transport is stdio-only for this reason.
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

The `feat/hungry-hippa` line (Hungry Hippa, schema v4) is the only supported line.
The pre-rename Living Cortex code is supported only through the migration path
described in `docs/MIGRATION.md`.
