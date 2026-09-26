# DolphinBench retrieval probe — not a score

Measured 2026-09-25 on unmodified ranking, then the BM25 sign fix was applied
separately for the growth fixture. This file does not claim an official
DolphinBench result. Official scoring needs a paid agent run and was not started.

Probe: `eval/dolphin_retrieval.py`
Dataset: mem0ai/dolphinbench `81cb6f8405b40a9e76089cef650806a80af06ea2`
Hungry Hippa commit at measurement: `3cddd2adcd85362fba6627dedb87ac431aa7e518`
Embeddings off. Requested k=10. Compiled lists were length 0–3, never 10.

| Persona | Hit | Facts hit | False-positive sessions | Recall p50 |
|---|---:|---:|---:|---:|
| Morgan | 12/200 | 20/354 | 70 | 16.6 ms |
| Alex | 21/200 | 40/393 | 200 | 18.6 ms |
| Riley | 23/200 | 54/500 | 173 | 25.3 ms |

56/600 requests retrieved a cited source session. 0/14 no-overlap requests hit.
Raw traces stayed local and are not published as a leaderboard result.
Codex review: not a publishable baseline until role filtering, config pinning,
and Hungry Hippa SHA/dirty status are recorded in the JSON.
