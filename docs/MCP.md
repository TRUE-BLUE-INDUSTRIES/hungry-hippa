# Hungry Hippa over MCP (local stdio)

Hungry Hippa ships a **local stdio** MCP server: `mcp_server.py`. It exposes the
same `MemoryController` that the Hermes `cortex` tool uses, so several local
MCP-capable clients can share one memory runtime instead of each keeping its own
notes.

Honest status of this document:

- The server itself is implemented and covered by `tests/test_mcp_schema.py`
  (in-process tool calls + a full JSON-RPC stdio exchange) and was also exercised
  as a real subprocess (`python mcp_server.py`, `python -m mcp_server`) while
  writing this file.
- **No external client has been run against it.** Nobody has pointed Grok CLI (or
  Claude Code, Cursor, etc.) at this server yet, so every client-side snippet below
  is *illustrative and untested*. The Grok `[mcp_servers.*]` schema is copied from
  the Grok user guide installed on this machine
  (`~/.grok/docs/user-guide/07-mcp-servers.md`) — check your own client's docs,
  since config formats change between releases.

## Transport and scope

| Property | Value |
|---|---|
| Transport | stdio, newline-delimited JSON-RPC 2.0 |
| Protocol revision advertised | `2024-11-05` |
| Network listener | none |
| Unix socket / HTTP | not implemented |
| Database access | through the controller only; no SQL, no path arguments, no export tool |

Run it:

```bash
python mcp_server.py                  # serve on stdio
python -m mcp_server                  # same, from the plugin directory
python mcp_server.py --print-schemas  # dump the tool schemas as JSON
```

The database is resolved exactly like the Hermes plugin
(`HUNGRY_HIPPA_DB`, then the deprecated `LIVING_CORTEX_DB`, then
`$HERMES_HOME/hungry_hippa.db`, then a discovered `living_cortex.db`). Nothing in
the MCP surface lets a client choose a file, so a misconfigured or hostile client
cannot point the server at an arbitrary path.

## Tools

| Tool | Required arguments | Notes |
|---|---|---|
| `hippa_remember` | `memory_type`, `content` | `episodic` → episode (context/user_request/actions_taken/decisions/result/outcome); `semantic` → belief (claim/kind/confidence/source_class) |
| `hippa_recall` | `query` | keyword + graph (+ optional local vectors); `explain: true` returns score parts without contents |
| `hippa_build_context` | `query` | returns `{rendering, item_ids, token_estimate, chars_used, budget_chars, excluded}` inside an explicit character budget |
| `hippa_record_outcome` | `procedure_id`, `success` | updates procedure counters and re-evaluates confidence |
| `hippa_forget` | `target_kind`, `target_id` | `mode: archival` (default, reversible); `mode: purge` needs `confirmation: true` **and** an owner actor. Archival is authorized per record: a caller may archive only a row it is allowed to read, so an untrusted client cannot remove another actor's memory. Denials return `policy_reason` and are logged as `forget_denied`. |
| `hippa_status` | – | table counts, quarantine counts, vector availability, active policy. Counts only, never row contents |

There is deliberately **no** `export` tool: raw database extraction stays on the
local CLI (`hermes living-cortex export`), which a human runs on their own machine, and
on the legacy `cortex` agent tool's `export` action — both are owner-only and audited
(see `docs/SECURITY.md`).

## Output schemas

Every tool also advertises an `outputSchema` describing the JSON object it returns:
the shared envelope is `{ok, error}` plus tool-specific fields (ids, counts, the
compiled context, exclusion reasons and so on). `additionalProperties` is true there,
because a result that hits the frame cap gains a `truncated`/`original_chars` notice;
the schemas describe what the server returns rather than promising a closed shape.
Arguments are checked against `inputSchema` before dispatch, including `null`
rejection (`actor_id: null` is refused rather than silently becoming the owner) and
per-item `maxLength` bounds on string arrays.

`token_estimate` is `ceil(characters / 4)`. It is a cheap estimate so the runtime
needs no tokenizer dependency, not a tokenizer measurement.

## Caller identity

Every tool accepts `actor_id`, which **defaults to `mcp-untrusted`**. Policy
(`policy.py`):

| Caller | Writes | Reads | Purge |
|---|---|---|---|
| owner (`primary`, `owner`) | normal | everything, plus quarantined rows when `include_quarantined: true` | allowed with `confirmation: true` |
| anything else | stored **quarantined** | only its own `unclassified`, non-quarantined rows | always denied |

Quarantined memories never appear in default recall for anyone, are excluded from
consolidation input (so an injected memory cannot be laundered into a derived
belief), and are labelled `[QUARANTINED]` when an owner reviews them.

This is an actor/policy check. It is **not** capability-based security, and there
are no unforgeable, revocable capability tokens in this design.

## Grok CLI example (untested)

Grok configures MCP servers in `~/.grok/config.toml` under
`[mcp_servers.<name>]`, or per-project in `.grok/config.toml`:

```toml
# ~/.grok/config.toml  (illustrative — not verified against a live Grok session)
[mcp_servers.hungry-hippa]
command = "python"
args = ["/home/YOU/Work/living-cortex/mcp_server.py"]
enabled = true
startup_timeout_sec = 30
tool_timeout_sec = 120

# Optional: point the server at a specific database file.
# env = { HUNGRY_HIPPA_DB = "/home/YOU/.hermes/hungry_hippa.db" }
```

Or via the CLI:

```bash
grok mcp add hungry-hippa -- python /path/to/living-cortex/mcp_server.py
grok mcp list
grok mcp doctor hungry-hippa      # starts the server and checks the handshake
```

Grok namespaces MCP tools with the server name, so `hippa_recall` appears as
`hungry-hippa__hippa_recall`. If the server starts but never handshakes, Grok
writes its stderr to `~/.grok/logs/mcp/<server>.stderr.log` — this server writes
nothing to stdout except protocol frames, so anything on stderr is a real error.

## Generic stdio client

Any client that speaks MCP stdio needs only the command and no arguments:

```
command: python
args:    ["/path/to/living-cortex/mcp_server.py"]
```

The server answers `initialize`, `tools/list`, `tools/call`, `ping`, and
`notifications/initialized`, and returns a JSON-RPC `-32601` for unknown methods.
Unknown tool names return a normal `isError` tool result rather than an exception,
so a client never loses its session over a bad tool name.

## Security notes for MCP clients

- The client is only as trustworthy as the process that starts it: stdio means
  "whoever can run this command can talk to the server". Do not expose it through a
  wrapper that forwards a network socket; that would put an untested transport in
  front of an actor-policy-only surface.
- Untrusted clients get an untrusted actor by default. Do not pass
  `actor_id: "primary"` on behalf of an untrusted caller — that is the whole
  boundary.
- Request limits and the threat model are added in the security phase and
  documented in `docs/SECURITY.md` and `docs/THREAT_MODEL.md`.
