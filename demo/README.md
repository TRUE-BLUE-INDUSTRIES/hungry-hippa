# Hungry Hippa: two-session demo

Hungry Hippa is a local-first memory runtime for AI agents. This scripted Python demo shows persisted context, not model training or an autonomous agent benchmark.

## Run and reset

From the repository root, with Python 3 and SQLite FTS5:

```sh
python demo/run.py
python demo/reset.py
```

Both commands allocate a fresh temporary DB and remove it on exit. Reset starts the demonstration again; it never accepts or deletes an existing DB path. The script also works by absolute path from an empty working directory. It shares the standalone loader in `eval/runtime.py`, uses copied built-in configuration and its own generic `seed.json`, and disables vectors and automatic consolidation. No model, network, private data, or Hermes configuration is needed.

The first session records a decision/rationale and a failed repair episode, creates a procedure and records its failed outcome. A newly constructed controller in a second session retrieves the failed action and outcome without conversation history. A fixed script chooses the next step from that context; no LLM choice is measured. The Operator then archives that episode and inspects counts. Archival preserves the row, so status totals do not decrease.

The baseline has no actor ACL, quarantine, or MCP. Authorized sharing and Grok CLI integration are unsupported; two session IDs do not demonstrate an authorization boundary. The current renderer also omits some structured fields, so this demo prints selected fields from the public recall response.

See [EXPECTED.md](EXPECTED.md) for the actual clean-directory run. This was run locally by Codex; independent Hermes verification remains for the coordinator.

## Two-minute recording

- **0:00–0:20:** Show this README and identify the synthetic Operator / Project A seed and temporary DB. State that this is a deterministic controller demo.
- **0:20–0:45:** Run `python demo/reset.py`. Explain the recorded queue decision, failed retry increase, and procedure failure outcome.
- **0:45–1:10:** Highlight the fresh controller/session and recalled failed action/result. Explain that the next step is scripted, not an LLM judgment.
- **1:10–1:35:** Highlight archival forgetting, exclusion from recall, and status counts including archived rows.
- **1:35–2:00:** Show the unsupported capabilities and `PASS` line. Re-run to show fresh state and describe the character-budget defect recorded in the eval report.

Record only this synthetic terminal session. No production memory screen is part of the demonstration.
