# Benchmarks

Hungry Hippa's performance and memory quality must be demonstrated with reproducible
measurements. No public-benchmark result or comparative ranking is claimed here.
Research references were checked on 2026-09-18.

## Existing evidence

The [offline memory challenge](eval/README.md) exercises the runtime with invented
fixtures, throwaway databases, and a deterministic token-matching reader. It covers
cross-session recall, decisions, supersession, context budgets, portability,
forgetting, policy enforcement, and storage growth. Embeddings are disabled.

Run from an installed checkout:

```bash
python eval/harness.py --stdout
python eval/check_results.py
```

The first command regenerates [results.json](eval/results.json) and
[REPORT.md](eval/REPORT.md); the second checks reproducible machine-independent
metrics. Do not hand-edit generated measurements. The report's latency is specific
to its recorded environment. Passing these fixtures does not establish semantic
answer quality, vector recall, general poisoning resistance, or superiority to
another memory system. [Security tests](SECURITY.md) provide separate regression
evidence for specific controls.

## Public evaluation targets — not yet measured

| Target | Why it matters | Planned use |
|---|---|---|
| [LongMemEval](https://github.com/xiaowu0162/LongMemEval) and its [cleaned data](https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned) | 500 questions cover information extraction, multi-session reasoning, temporal reasoning, knowledge updates, and abstention. Evidence session IDs and answer-bearing turn labels support retrieval evaluation. | First external target: pin the cleaned dataset revision and score retrieval before adding a model reader. |
| [LoCoMo](https://github.com/snap-research/locomo) | Ten long conversations provide complementary question-answering and event-summary tasks. | Later conversation evaluation; disclose all categories and exclusions. Keep downloaded assets outside the distribution and review the upstream [CC BY-NC 4.0 license](https://github.com/snap-research/locomo/blob/main/LICENSE.txt) before reuse. |
| [LongMemEval-V2](https://github.com/xiaowu0162/LongMemEval-V2) | The 2026 benchmark evaluates agent trajectory memory with 451 questions across web and enterprise environments, including workflow knowledge and changing state. It measures accuracy and latency. | Later procedural/development-memory target, after conversation ingestion is reliable. Keep evaluator labels inaccessible to the memory backend. |

## Measurement protocol

1. Import only history, timestamps, and stable source identifiers into a fresh
   database for each evaluation case. Keep gold answers and evidence labels in the
   evaluator. Never select memories using those labels.
2. Measure evidence Recall@k, Precision@k, reciprocal rank, and complete evidence
   coverage for multi-hop questions. Report both message and session granularity;
   finding the right session alone does not prove the answer was retrieved.
   LongMemEval's upstream retrieval evaluation excludes its 30 abstention cases;
   retain them for answer/abstention evaluation and report the denominators.
3. Compare lexical, vector, and hybrid retrieval with identical data and context
   budgets. Hold the embedding and reader models fixed where applicable. Include
   no-memory and full-history answer baselines when feasible. Change one component
   at a time before adopting additional retrieval complexity.
4. Report answer accuracy, abstention, stale-fact leakage after corrections,
   contradictory-fact handling, and unsupported-answer rate separately from
   retrieval. Check provenance links and source hashes mechanically; whether the
   evidence actually supports a claim requires an additional evidence review.
5. Measure ingestion messages/second, duplicate-import behavior, storage bytes per
   message, and cold/warm retrieval p50/p95 at increasing corpus sizes. Run targeted
   poison/import adversarial cases separately and state their coverage.

All metrics in this protocol remain **unmeasured** until a linked run artifact
records them. A smoke subset must publish its selection method and case IDs; it
cannot stand in for full-split results. Report failures and exclusions, not only
successful cases. Model reader/judge evaluations are separate from offline tests;
paid calls require explicit authorization.

Each run must record HH version, commit SHA and dirty status, harness version,
dataset revision and hashes, CPU/GPU/RAM, OS/Python, model identifiers and available
digests, configuration, seed, corpus size, context budget, timing method, predictions,
per-case scores, and aggregate denominators. Retain the exact prompts and judge
configuration when a model is involved. Publish only approved, non-private fixtures
and outputs.

## Implementation references

These are candidates for controlled comparison, not a ranking or replacement plan:

- [Mem0](https://github.com/mem0ai/mem0): a memory library and self-hosted server;
  its optional NLP support adds BM25 and entity extraction. Pin a configuration
  before comparison, including its model and infrastructure costs.
- [Graphiti](https://github.com/getzep/graphiti): temporal facts, episode provenance,
  and semantic/keyword/graph retrieval. Its explicit fact validity is a useful
  reference for correction and historical-query tests.
- [Letta memory blocks](https://docs.letta.com/v1-sdk/memory/memory-blocks): shared
  and read-only blocks provide an interoperability reference. Its documented
  last-write-wins replacement behavior motivates concurrent correction tests.

Vendor-reported scores use different models, budgets, datasets, and evaluators.
They are not Hungry Hippa measurements or evidence of comparable performance.

## Synthetic import measurements

`python eval/ingest_benchmark.py --output /tmp/hh-ingest-results.json` runs all
100/1,000/5,000-message cases three times. Each run includes a fresh store, bounded
read/parse/persist, duplicate import, every-turn provenance verification and
SQLite backup recovery. No model or network is used. `--smoke` is a 100-message
correctness gate in CI; it is not a throughput acceptance threshold. Raw runs,
code hash, commit, dirty status, hardware and configuration are recorded.

The first recorded full run will be linked here after measurement from a clean
committed tree. Public benchmark/answer-quality metrics above remain unmeasured.
