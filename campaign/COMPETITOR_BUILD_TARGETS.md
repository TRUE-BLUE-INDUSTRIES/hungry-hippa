# Build targets from competitor weaknesses

Written 2026-09-25 after the competitor-research subagent died on HTTP 429 before it could save this file. Claims below were checked against the cited pages or against Hungry Hippa's own probe. They are not a leaderboard.

## Ranked builds

1. **Short source-cited excerpts, not whole episodes.** Our probe compiled 0–3 items because `max_context_chars` is 1500 and full messages fill it. Hindsight issue #1707 (closed by PR #1947, June 2026) showed the same class of failure: the right fact was in the candidate set, but extra high-ranked junk broadened the answer. https://github.com/vectorize-io/hindsight/issues/1707 — confirmed-by-source as a fixed Hindsight defect, not reproduced on their service. Hungry Hippa change: if a ranked episode does not fit, render a short neutralized excerpt plus the episode id, instead of dropping the rest of the ranked list. Do not raise the budget and dump more text.

2. **Supersede at write time; do not return inactive facts.** Mem0 issue #4956 (open, labeled bug, April 2026) reports v3 ADD-only extraction keeps contradictory mutable facts, and a later comment says `score_and_rank` has no temporal term. https://github.com/mem0ai/mem0/issues/4956 — user-reported, not independently reproduced here. Hungry Hippa already supersedes beliefs. The build is a regression that a newer explicit correction is what recall returns, and the old row stays as history. Do not delete history.

3. **Do not OR every boilerplate token.** Our Morgan 001 trace retrieved later "please place a pickup order" sessions instead of the cited source. That is the same irrelevant-retrieval class as #1707, measured on our store. Change FTS query construction to drop instruction boilerplate and keep identifiers. Do not add a vector database to paper over it.

4. **Last-writer-wins is a competitor bug, not a feature to copy.** Letta's legacy shared-memory docs say full-block `memory_rethink` is last-writer-wins. https://docs.letta.com/v1-sdk/memory/shared-memory — confirmed-by-source for that operation, not for every Letta write. Hungry Hippa should keep revision-checked supersession. No new code unless a test shows a stale writer can still replace a newer owner correction.

5. **Keep model calls out of the write transaction.** Graphiti collaborators described multi-second per-message LLM ingest as expected (issue #186). https://github.com/getzep/graphiti/issues/186 — confirmed-by-source for that historical path. Hungry Hippa already separates canonical import from optional extraction. Do not add a per-message cloud extract step to chase DolphinBench.

## Not a build

Published DolphinBench scores are not Hungry Hippa measurements. Do not add Mem0/Hindsight/Honcho clients, a vector database, or new MCP tools to imitate them.

The retrieval-drop diagnosis was still running when this note was written. Implement item 1 only if that diagnosis shows the gold session was in the candidate list and then dropped by the character budget.
