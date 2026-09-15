# Two-session cross-agent demo (Grok CLI and any other MCP client)

Proves the operator-brief requirement "an agent uses Hungry Hippa across separate
sessions". Two clients are registered against the **same local stdio server** and the
same demo database, so a memory written by one agent is readable by the other.

Server: `mcp_server.py` from this repository (stdio, no network), normally launched
as the console script `hungry-hippa-mcp`. Demo database: a throwaway path passed as
`HUNGRY_HIPPA_DB` — never the operator's own database.

Owner identity is a property of the **server launch context**: the host passes
`HUNGRY_HIPPA_OWNER_TOKEN` to the server it starts, and the server verifies it
against `$XDG_STATE_HOME/hungry-hippa/owner.token` (`0600`). A client that has no
token in its server environment is an untrusted instance, whatever it puts in
`actor_id`.

## Registration (already done on 2026-09-15)

```bash
DEMO_DB=/tmp/hungry-hippa-demo/hungry_hippa.db
TOKEN=$(hungry-hippa owner-token --print | python -c "import json,sys;print(json.load(sys.stdin)['token'])")

# owner-authorized instance: the token travels in the *server's* environment
grok mcp add hungry-hippa -s user \
  -e HUNGRY_HIPPA_DB="$DEMO_DB" -e HUNGRY_HIPPA_OWNER_TOKEN="$TOKEN" \
  -- hungry-hippa-mcp

# untrusted instance: the same command with no token
grok mcp add hungry-hippa-untrusted -s user \
  -e HUNGRY_HIPPA_DB="$DEMO_DB" -- hungry-hippa-mcp

grok mcp doctor   # expect: server started, handshake OK, 6 tools discovered
```

## Session 1 — store (fresh process, no history)

```bash
REPO=/home/djr/Work/living-cortex
grok -p "$(cat $REPO/demo/session1_store.txt)" --permission-mode auto --no-plan
# or, with Codex CLI:
codex exec --skip-git-repo-check --sandbox danger-full-access "$(cat $REPO/demo/session1_store.txt)"
```

Expected: `STORED E-0001`.

## Session 2 — recall in a separate process

```bash
REPO=/home/djr/Work/living-cortex
grok -p "$(cat $REPO/demo/session2_recall.txt)" --permission-mode auto --no-plan
# or, with Codex CLI:
codex exec --skip-git-repo-check --sandbox danger-full-access "$(cat $REPO/demo/session2_recall.txt)"
```

Expected: the stored episode is quoted back verbatim
(`tried to free the seized housing on Project A with solvent X — outcome: failure |
result: the housing cracked`) and the agent reports that the approach failed.

## Status

- **Codex CLI**: run on 2026-09-15 — both sessions behaved as above. This is real
  cross-process, cross-session recall by an LLM agent over the MCP server.
- **Grok CLI**: registration and handshake verified (`grok mcp doctor`). The two
  `grok -p` runs are blocked by `402 Payment Required — Grok Build usage balance
  exhausted`, an account/billing state on the client. Top up the Grok Build balance and
  the two commands above complete the demonstration; the server side is already proven.

`actor_id: primary` is used so the write is stored as owner memory rather than
quarantined. An untrusted client (`mcp-untrusted`, the server default) writes
quarantined and reads nothing of the owner's — see `docs/SECURITY.md`.
