# Verified demo output

Result: **PASS**. Codex ran both `run.py` and `reset.py` by absolute path from a newly created empty temporary working directory on 2026-09-15 UTC. Both exited 0; reset produced the same output with an additional RESET line. Independent Hermes verification has not been performed.

```text
1. Recorded decision: Use a queue because bursts exceed worker capacity.
   Recorded failed fix and failure outcome: increase retries.
2. New controller, session demo-two; no conversation history supplied.
3. Recalled action: Increase retries from two to eight.
   Outcome: failure. Duplicate requests increased; use request deduplication next.
   Scripted next step: try request deduplication; do not repeat the failed retry increase.
4. Operator forgot failed-fix episode: archived and excluded from recall.
5. Status counts: {"beliefs": 0, "entities": 0, "episodes": 2, "evidence": 0, "procedures": 1, "relationships": 0, "vectors": 0}
   Episode totals include 1 active and 1 archived; forgetting is not secure deletion.
UNSUPPORTED: authorized cross-agent sharing, quarantine, MCP/Grok integration.
PASS: demo completed; temporary database removed.
```

Status counts include archived episodes. All displayed content is synthetic. A repeat run should match this output; there are no timestamps or generated paths in it.
