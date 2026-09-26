# Retrieval drop diagnosis

Measured 2026-09-25 on a throwaway database. Persona Morgan only (3,400 sessions, 200 tests). Embeddings off. Hungry Hippa worktree `feat/dolphinbench-campaign`. Not an official DolphinBench score.

## Before cited excerpts

BM25 sign inversion was already in this worktree. Ranking was not otherwise changed.

| Check | Count |
|---|---:|
| Tests | 200 |
| Gold session in FTS top 20 | 147 |
| Gold session in compiled recall | 47 |
| Gold absent from FTS top 20 | 53 |
| In FTS, then dropped before the compiled list | 100 |
| Median compiled items | 1 |

The character budget was dropping ranked hits. Median FTS list length was 20, the search cap. Median compiled length was 1.

## After cited excerpts

Same ingest and the same queries. A ranked episode that does not fit whole is now rendered as a neutralized 240-character window with its source id. Stored rows are not rewritten.

| Check | Count |
|---|---:|
| Gold session in FTS top 20 | 147 |
| Gold session in compiled recall | 87 |
| Gold absent from FTS top 20 | 53 |
| In FTS, then dropped before the compiled list | 60 |
| Median compiled items | 3 |
| Compiled hits whose rendering used an excerpt | 73 |

Compiled hits moved 47 → 87 on this persona. 60 gold sessions are still in the FTS top 20 and absent from the compiled list. Those are outside the items that fit in the 1,500-character budget even as excerpts, or outside `recall(limit=10)`. 53 gold sessions never enter FTS top 20. Excerpts do not fix either of those. Extracted facts with source ids are still the next retrieval change. Do not add a vector database for this gap.
