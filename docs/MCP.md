# Hungry Hippa over MCP (local stdio)

Hungry Hippa exposes its memory runtime as a Model Context Protocol server, built
on the **official MCP Python SDK**. The SDK owns the protocol: transport framing
(newline-delimited JSON-RPC over stdio), request ids, `initialize` negotiation,
`tools/list`, `tools/call`, protocol-version selection and response construction.
Hungry Hippa owns the tools, the limits and the trust boundary.

```bash
python -m pip install -e .        # installs the project and the official mcp SDK
python mcp_server.py             # serve over stdio
hungry-hippa-mcp                 # the same thing, as a console script
python mcp_server.py --print-schemas   # diagnostic: dump the tool schemas
```

| Property | Value |
|---|---|
| Transport | stdio only — newline-delimited JSON-RPC, owned by the SDK |
| Protocol revision | negotiated by the SDK (currently `2025-11-25`) |
| Network listener | none: no HTTP, no socket, nothing to bind or firewall |
| stdout | protocol traffic only; every diagnostic goes to stderr |
| Database access | through the controller only; no SQL, no path arguments, no export tool |
| Dependencies | the official `mcp` SDK (declared in `pyproject.toml`) |

## The tools

| Tool | Required arguments | Notes |
|---|---|---|
| `hippa_remember` | `memory_type`, `content` | episodic (what happened) or semantic (a claim/fact, with `kind`, `confidence`, `source_class`) |
| `hippa_recall` | `query` | keyword + graph (+ optional local vectors); `explain=true` returns score parts without memory contents |
| `hippa_build_context` | `query` | `{rendering, item_ids, token_estimate, chars_used, budget_chars, excluded, trust}` inside an explicit character budget |
| `hippa_record_outcome` | `procedure_id`, `success` | updates procedure counters and re-evaluates confidence |
| `hippa_forget` | `target_kind`, `target_id` | `mode: archival` (default, reversible); `mode: purge` needs `confirmation: true` **and** an owner-authorized instance |
| `hippa_status` | – | counts, quarantine counts, vector availability, policy, capability and binding summaries. Counts only, never memory contents |

Every tool also takes an optional `actor_id`: a **label**, never a privilege. There
is deliberately **no token parameter on any tool** — a model is never asked to
handle the owner secret.

Older releases had hand-written protocol code and a `hippa_export`-style surface
was never offered over MCP: raw database extraction stays on the operator's own
CLI (`hungry-hippa export`), which is owner-only and audited.

## Identity: the launch environment authenticates

`actor_id` in a request is a claim. The server resolves identity from its **launch
context**, once, at start-up:

1. The operator's token file lives at `$XDG_STATE_HOME/hungry-hippa/owner.token`
   (`~/.local/state/hungry-hippa/owner.token`), mode `0600`, created by
   `hungry-hippa owner-token`.
2. The host passes its contents to the server process as
   `HUNGRY_HIPPA_OWNER_TOKEN`.
3. The server compares it (constant-time) against the file. Match → the instance is
   **owner-authorized**. Missing or wrong → the instance is **untrusted**, and no
   argument any client sends changes that.

That is why the token is a *launch* detail, not a tool argument: the thing being
authenticated is the configuration the operator wrote, not a string a model chose.

### Passing the environment explicitly

MCP hosts do **not** all forward your shell environment to the server they launch.
Pass it explicitly:

```jsonc
// generic MCP host configuration
{
  "mcpServers": {
    "hungry-hippa": {
      "command": "hungry-hippa-mcp",
      "env": {
        "HUNGRY_HIPPA_OWNER_TOKEN": "<paste from: hungry-hippa owner-token --print>"
      }
    }
  }
}
```

```bash
# Grok CLI
grok mcp add hungry-hippa -s user \
  -e HUNGRY_HIPPA_OWNER_TOKEN="$TOKEN" \
  -- hungry-hippa-mcp
grok mcp doctor          # expect: handshake OK, 6 tools discovered
```

An **untrusted** configuration is the same entry with no `env` block: the server
logs that it is serving as an untrusted instance, writes from that instance are
stored quarantined, and its reads return only its own rows.

`HUNGRY_HIPPA_DB` may be set the same way to point the instance at a specific
database; without it the resolved default is
`$XDG_DATA_HOME/hungry-hippa/hungry_hippa.db`.

## Security posture

- An untrusted instance cannot read protected rows, purge anything, archive a row
  it may not read, or learn what it was not allowed to see (no ids, no counts, no
  graph entities — see `docs/SECURITY.md`).
- A model-authored write is recorded as `agent_reported`; only the operator's own
  channel can attest `user_explicit`.
- Recalled memory is framed as data with no authority and cannot forge runtime
  markup or metadata.
- Server-side limits are enforced by Hungry Hippa, not only advertised by the
  schema: a client that ignores the schema is still bounded.

## What this document does not claim

- No network transport, no authentication over a network, no multi-tenant
  isolation. The token is a local capability: a process running as the operator can
  read the file and the database.
- No encryption at rest; permissions are not encryption.
- Client snippets above are configuration examples, not a compatibility guarantee
  for every host. Verified against the official SDK client (see
  `tests/test_mcp_integration.py`) and `grok mcp doctor`.
