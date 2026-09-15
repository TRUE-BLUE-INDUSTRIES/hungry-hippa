# Two-session cross-agent demo (Grok CLI and any other MCP client)

Proves the operator-brief requirement "an agent uses Hungry Hippa across separate
sessions". Two clients are registered against the **same local stdio server** and the
same demo database, so a memory written by one agent is readable by the other.

Server: `/home/djr/.hermes/plugins/living-cortex/mcp_server.py` (stdio, no network).
Demo database: `~/.grok/hungry-hippa-demo/hungry_hippa.db` — never the live database.

## Registration (already done on 2026-09-15)

```bash
grok mcp add hungry-hippa -s user \
  -e HUNGRY_HIPPA_DB=/home/djr/.grok/hungry-hippa-demo/hungry_hippa.db \
  -- python /home/djr/.hermes/plugins/living-cortex/mcp_server.py

codex mcp add hungry-hippa \
  --env HUNGRY_HIPPA_DB=/home/djr/.grok/hungry-hippa-demo/hungry_hippa.db \
  -- python /home/djr/.hermes/plugins/living-cortex/mcp_server.py

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
