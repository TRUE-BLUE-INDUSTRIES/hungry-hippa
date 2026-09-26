# Competitor-gap research for Hungry Hippa

## Scope and evidence rules

Research snapshot: September 25, 2026 (PDT). Public official documentation, the DolphinBench paper/repository, and GitHub issues only. No competitor services were tested or attacked; no Hungry Hippa (HH) source code was changed or benchmark executed.

HH is treated as a local-first SQLite/FTS5 memory runtime, per the task brief, not as an independently audited implementation. Every HH recommendation below is a **proposed improvement or verification target**, not a claim that HH currently lacks it or already outperforms a competitor. All recommendations fit existing SQLite/FTS5 storage and existing interfaces: no new vector database, cloud dependency, or MCP tools.

- **confirmed-by-source** means an official source documents a behavior, limitation, fixed defect, or published result; it does not mean independently reproduced here.
- **user-reported** means a public issue supplies observations/reproduction steps, but this research did not reproduce them; maintainer acknowledgement is noted separately.
- **hypothesis** means a proposed HH benefit/test, not a demonstrated competitor defect.
- “Not stated” means the source does not pin an affected release. Current unversioned docs must not be projected backward onto benchmark implementations.
- Numbered source references resolve to exact URLs in the source list. Historical defects are explicitly separated from current limitations.

## Comparison matrix / finding ledger

| ID | System | Weakness class / evidence boundary | Affected version or scope | Source type / URL reference | One-sentence source-backed claim | Reproducibility | SQLite-compatible HH improvement? |
|---|---|---|---|---|---|---|---|
| M1 | Mem0 | Hallucinated memories, irrelevant storage, memory growth | Release not stated; one Qdrant deployment, Feb–Mar 2026, gemma2:2b then Sonnet 4.6; fork changed during audit | GitHub issue [1] | One operator reports that an audit classified 97.8% of 10,134 stored entries as junk, including hallucinations, duplicates and transient operational content. | user-reported; not a general Mem0 error rate | **Yes, hypothesis:** require source-message IDs/spans for extracted facts; distinguish user assertions from assistant output/recalled material; reject low-value candidates and deduplicate before insertion. |
| M2 | Mem0 OSS | Setup and provider portability, not exclusive vendor lock-in | Current unversioned docs; library and server defaults differ | official doc [2] | Library defaults combine OpenAI generation/embeddings, local Qdrant and SQLite history, while the server defaults to Postgres/pgvector, with configurable components in both cases. | confirmed-by-source; documented architecture, not defect | **Yes:** preserve a usable SQLite/FTS5 path without model-provider credentials and expose optional provider configuration explicitly; do not advertise Mem0 as cloud-only. |
| G1 | Graphiti, not all Zep deployments | Expensive ingest | October 2024 issue; package version not stated; OpenAI-model path | GitHub issue [3] | A Graphiti collaborator described approximately 12 seconds per message as expected for that historical OpenAI ingestion path because extraction, temporal reasoning, deduplication and invalidation require substantial processing. | confirmed-by-source for historical collaborator statement; no current latency claim | **Yes:** keep durable source capture separate from optional enrichment and expose pending/completed ingestion state through existing interfaces. |
| G2 | Graphiti / Zep | Setup; temporal updates and contradictions are competitor strengths | Current unversioned docs | official doc [4] | Graphiti documents bi-temporal tracking, fact invalidation and point-in-time queries on pluggable graph backends, whereas Zep is the managed context service using Graphiti-derived artifacts. | confirmed-by-source; not a temporal defect | **Yes:** represent assertion time and validity intervals in SQLite, retain superseded facts, and test as-of queries without adding a graph database. |
| G3 | Zep | Provenance limitations, not missing provenance | Current docs; v4 field-name differences documented | official doc [5] | Zep links derived facts to source episodes and explicitly warns that provenance identifies source data but does not guarantee source or derived-fact correctness. | confirmed-by-source | **Yes:** keep source references, trust labels and assertion-versus-inference status separate; source presence must not automatically establish truth. |
| L1 | Letta / MemGPT lineage | Stale updates / lost concurrent edits | **Legacy V1 SDK** shared-memory docs; release not stated | official doc [6] | Letta documents full-block `memory_rethink` rewrites as non-concurrent-safe and last-writer-wins, while `memory_replace` is a targeted edit that fails if its target string changed and `memory_insert` is append-only. | confirmed-by-source; documented concurrency semantics | **Yes:** use revision-checked SQLite updates, append-only audit history and explicit conflict responses; reject stale full replacements rather than silently overwrite. |
| HN1 | Honcho | Missing derived recall / setup | **3.0.5**, self-hosted, async writes | GitHub issue [7] | A user reports stored messages and queued work without automatic derivation until a separate worker was started, with some profile/context/search surfaces still empty afterward. | user-reported; reporter explicitly allows configuration/documentation gap rather than confirmed product bug | **Yes:** verify a stored fact survives restart and becomes retrievable, report queue backlog separately from API health, and make worker requirements visible. |
| HN2 | Honcho | Token cost / context-budget failure | **3.1.1**, commit `5d992bc`, one deployment tested from two clients | GitHub issue [8] | A maintainer-approved issue reports that the context endpoint's `tokens` parameter did not bound peer representation and requesting that representation suppressed an otherwise available session summary. | user-reported with controlled request sweeps and maintainer-approved label; not independently reproduced | **Yes:** enforce the budget over the final serialized context, reserve space by component, and return explicit truncation metadata through existing output fields. |
| HN3 | Honcho | Setup and provider portability | Current V3 docs; not necessarily 3.0.5 behavior | official doc [9] | Honcho's current local setup requires PostgreSQL/pgvector and a configured LLM, and its CLI can start API, deriver, Postgres and Redis together while supporting OpenAI-compatible endpoints including Ollama and vLLM. | confirmed-by-source; architecture, not mandatory cloud lock-in | **Yes:** offer one-process SQLite operation where feasible and an offline end-to-end setup check; acknowledge that Honcho now documents an orchestrated local stack. |
| HN4 | Honcho | Provenance limits | Current V3 evidence API docs | official doc [10] | Honcho's deterministic evidence lists material the answering agent read rather than proven answer dependencies, and includes successful tool calls but omits failed calls and tool-result bodies. | confirmed-by-source; disclosed audit limitation | **Yes:** label retrieved evidence versus claim support distinctly and retain source IDs plus retrieval/error metadata locally without treating either as proof of correctness. |
| HS1 | Hindsight | Memory growth / DB contention | Historical behavior changed in **0.5.0**; introduction version not stated | official doc (release notes) [11] | Hindsight 0.5.0 moved read-heavy resolution outside the write transaction because the previous long transaction made concurrent ingestion queue behind bank-size-dependent ANN work. | confirmed-by-source; **fixed historical issue**, not present-version allegation | **Yes:** keep SQLite write transactions short, perform model calls outside them, revalidate before commit and test concurrent writers/readers under load. |
| HS2 | Hindsight | Memory growth / expensive retrieval | Historical behavior changed in **0.5.0** | official doc (release notes) [11] | Hindsight reports that high-fanout entity joins caused unpredictable recall latency and added per-entity caps, a composite index and a timeout fallback in 0.5.0. | confirmed-by-source; **fixed historical issue** | **Yes:** cap candidate expansion, inspect query plans, use supporting indexes and test bounded FTS5/entity joins on high-fanout synthetic corpora. |
| HS3 | Hindsight | Provider portability counterevidence | **0.5.0** feature announcement | official doc (release notes) [11] | Hindsight 0.5.0 added a built-in llama.cpp provider for local fact extraction, consolidation and reflection without external inference API calls. | confirmed-by-source; capability, not weakness | **Yes, positioning/verification only:** HH must demonstrate its own local operation rather than claim competitors inherently require cloud inference. |
| S1 | Supermemory | Failed retrieval / provider consistency | **v0.0.5**, documented fixed in **v0.0.7** | official doc [12] | Supermemory documents mixed embedding models between ingestion and query paths in v0.0.5 causing empty exact-text results in multilingual scenarios, fixed by a locked embedding plan in v0.0.7. | confirmed-by-source; **fixed historical defect** | **Yes:** record extraction/index configuration and test write/read consistency and multilingual lexical retrieval; SQLite/FTS5 is not automatically immune to tokenizer failures. |
| S2 | Supermemory | Provider portability / migration cost | Current self-hosting docs; release not stated | official doc [12] | Changing embedding models in place is unsupported, requiring fresh data or full re-ingestion, and a dimension mismatch with stored data prevents server startup. | confirmed-by-source; documented migration constraint | **Yes:** preserve canonical source text and version derived indexes so rebuilding search does not require recovering source data from a provider. |
| S3 | Supermemory | Irrelevant or missing retrieval | Current default local embedding configuration | official doc [12] | Supermemory warns its default English-only embedding model can yield weak non-English dense recall even when ingestion succeeds. | confirmed-by-source; scoped to documented default, not every configuration | **Yes:** add multilingual and exact-identifier retrieval tests, disclose tokenizer limits and preserve a deterministic lexical fallback. |
| S4 | Supermemory | Setup / lock-in counterevidence | Current self-hosted offering; release not pinned | official doc [13] | Supermemory now documents a self-contained local binary with embedded storage, local embeddings and fully offline OpenAI-compatible local-model operation, while some hosted features and proprietary extraction models differ. | confirmed-by-source; capability and product boundary | **Yes, positioning only:** differentiate HH on verified simplicity, provenance and bounded behavior, not a false claim that Supermemory is cloud-only. |
| B1 | Mem0, Honcho, Hindsight, Supermemory and built-in baseline | Cost and end-to-end task failure; no diagnosed per-task cause | Published Hermes + GPT-5.6-Luna configurations; 600 tasks | published benchmark [14]; paper [15] | DolphinBench publishes different accuracy, total-cost and median-task-latency tradeoffs for these configurations, with no HH result in the supplied comparison. | confirmed-by-source as published results; **not reproduced and non-comparable to an HH run** | **Yes:** adopt isolated source ingestion, frozen checkpoints, cross-session tasks, usage accounting and grading evidence before making comparative claims. |

### Important interpretation limits

**Letta last-write-wins:** the official wording is specifically about full rewrites via `memory_rethink`, not a blanket statement that every `memory_replace` silently overwrites concurrent changes; the same page distinguishes the three operations and recommends contention-aware block design.[6]

**Mem0 audit:** the 97.8% number is an operator's classification from a changing integration/model configuration, not an independently validated population statistic or a benchmark against HH; the report itself says hallucination behavior changed after the model switch.[1]

**Honcho deployment:** the 3.0.5 issue and the current setup guide should be read together: the former reports a worker/configuration failure mode, while the latter explicitly launches the worker and documents verification, so “Honcho cannot derive local memory” would be false.[7][9]

**No unsupported security assertion:** no competitor prompt-injection/poisoning vulnerability is asserted here. Search surfaced Mem0 issue #5151, but its snippet referred to privately sent proof-of-concept material; that was insufficient to establish a public reproducible vulnerability and was excluded from the finding ledger. Source-linked memories are still untrusted data; the suggested HH controls below are defensive hypotheses, not evidence of an exploit in any named competitor.

**No blanket temporal or forgetting claim:** Graphiti/Zep explicitly offer temporal invalidation and historical queries, and DolphinBench task failures alone do not distinguish forgotten facts from retrieval selection, reasoning or tool-execution failures.[4][15]

## Published DolphinBench results — not an HH comparison

Repository snapshot: `81cb6f8405b40a9e76089cef650806a80af06ea2`; repository license **Apache-2.0**. Paper: **arXiv:2609.24971**, retrieved v2. The paper is authored by Mem0-affiliated researchers, so these are publisher/vendor-reported results, not independent replication.[14][15]

**Hermes + GPT-5.6-Luna; 600 tasks.** The table uses the task brief's one-decimal latency presentation; the paper provides additional decimals. Cost is **total ingestion plus testing**, including memory processing, not a memory API's standalone price; latency is **median per task including tool use**, not standalone retrieval latency.[15]

| Memory system | Published accuracy | Published total cost (USD) | Published median task latency |
|---|---:|---:|---:|
| Mem0 | 70.67% | $96.21 | 37.7 s |
| Hindsight | 69.50% | $84.65 | 55.3 s |
| Honcho | 68.50% | $142.85 | 44.7 s |
| Built-in | 65.67% | $61.48 | 44.4 s |
| Supermemory | 59.17% | $345.64 | 52.7 s |

These values were checked against paper Table 2. **HH has not been measured on this harness; no HH accuracy, cost, latency, ranking, or improvement percentage can be inferred.** Zep/Graphiti and Letta are not rows in this supplied configuration. No scores are invented for them. The combined agent/model/memory configuration is the unit of comparison; results must not be generalized to every deployment or today's local editions.[15]

The repository instructs evaluators to ingest dated messages in order, isolate persona/configuration stores, wait for ingestion completion, preserve a completed checkpoint, and start each task with fresh conversation/app state without allowing test writes to affect subsequent tests.[14]

## Prioritized HH hypotheses and local acceptance tests

These are research proposals, not completed changes. First inspect HH's existing implementation and tests before deciding what is genuinely missing.

1. **Revision-safe updates and temporal history (L1, G2).** Store a revision and validity interval with each assertion; require compare-and-swap for replacements. Test two concurrent writers, out-of-order updates, explicit corrections, historical as-of recall and retractions. A stale writer must not silently destroy the newer assertion; a superseded assertion must remain explainable through history.
2. **Grounded ingestion and feedback-loop control (M1, G3, HN4).** Retain canonical source IDs, source spans, actor/trust category and extraction metadata. Separate assertions from inferences and do not count recalled text as new user confirmation. Test a fabricated extractor candidate, an assistant paraphrase, repeated recall/re-ingestion and conflicting sources. Untrusted source instructions must not gain policy authority merely by being stored; this is a safety test, not a competitor-vulnerability claim.
3. **Enforced final-context budget (HN2).** Budget the full serialized response including metadata, not only individual result strings; preserve a minimum allocation for distinct components and disclose truncation. Test small budgets, oversized single facts, Unicode, many duplicates and stable deterministic ordering. Report the tokenizer or conservative approximation actually used.
4. **Durability and ingestion readiness (HN1, G1).** Persist accepted sources before optional enrichment; expose pending/failed/indexed state through existing status surfaces. Test process restart after acceptance, worker interruption and retry idempotency. API process health is not proof that an accepted fact is retrievable.
5. **Bounded SQLite growth (HS1, HS2).** Keep LLM work outside write transactions, revalidate at commit, cap expansion and index the actual predicates. Measure lock waits, database size, candidate counts, p50/p95 latency and query plans under concurrent synthetic writes and large duplicate/high-fanout corpora; use explicit test sizes rather than assuming constant-time performance.
6. **Portable sources and multilingual retrieval (S1–S4, M2, HN3, HS3).** Preserve source text independently of providers, version derived indexes and verify export/rebuild. Test offline startup and restart, provider changes, exact identifiers, languages without whitespace and non-English paraphrases. Do not assume FTS5 alone provides multilingual semantic recall.
7. **Comparable evaluation before marketing (B1).** Only a real, separately authorized HH harness run with pinned model/provider, frozen memory, preserved traces and measured cost/latency can support a DolphinBench comparison. No benchmark execution or new MCP integration was performed for this note.

## Search coverage and limitations

- Retrieved current docs for all six systems/groupings; Letta's cited concurrency page is explicitly **legacy V1**, not an assertion about every current SDK path.
- Retrieved GitHub issue bodies for Mem0 #4573, Graphiti #186, Honcho #494 and #1176. Historical Graphiti timing and fixed Hindsight/Supermemory defects are intentionally not presented as current benchmark results.
- Letta issue search returned mostly older wrapper/retry reports rather than a clean relevant contemporary memory-loss reproduction; official concurrency documentation was stronger evidence.
- Supermemory issue search for update failures returned mostly older/unrelated feature requests; official embedding documentation supplied the versioned retrieval defect instead. No unsupported update/contradiction defect was added.
- The older `https://docs.honcho.dev/contributing/self-hosting` URL returned a 404 page despite a search snippet. Recovered the current V3 URL through the official documentation index; the stale snippet is not evidence for current requirements.
- Public issue discussions can be incomplete in extracted GitHub HTML (the Mem0 page included a “load more” boundary). Claims here are limited to the retrieved issue body and visible acknowledgements, not an assertion that all later comments or fixes were reviewed.
- No private datasets, credentials, issue reporters' environment dumps, or production identifiers are reproduced. No live attack testing or independent competitor reproduction was attempted.

## Sources

[1] **GitHub issue — Mem0 #4573**, “What we found after auditing 10,134 mem0 entries: 97.8% were junk,” opened March 27, 2026; operator report, release unspecified. https://github.com/mem0ai/mem0/issues/4573

[2] **Official doc — Mem0 Open Source overview**, current library/server defaults and configurable components. https://docs.mem0.ai/open-source/overview

[3] **GitHub issue — Graphiti #186**, “Graphiti messages are added very slowly,” October 2024; collaborator's expected-ingestion-latency explanation. https://github.com/getzep/graphiti/issues/186

[4] **Official doc — Graphiti overview**, temporal features, graph backends, current bulk-processing capability and Graphiti/Zep distinction. https://help.getzep.com/graphiti/getting-started/overview

[5] **Official doc — Zep graph overview**, source episodes, validity timestamps and provenance caveat. https://help.getzep.com/graph-overview

[6] **Official doc — Letta shared memory, legacy V1 SDK**, concurrency table and read-only/shared block guidance. https://docs.letta.com/v1-sdk/memory/shared-memory

[7] **GitHub issue — Honcho #494**, “Self-hosted/local Honcho ingests messages but derived memory does not appear automatically; peer card/context/search remain empty,” version 3.0.5. https://github.com/plastic-labs/honcho/issues/494

[8] **GitHub issue — Honcho #1176**, “tokens does not bound the representation in get_context, and the summary is starved as a result,” version 3.1.1 / `5d992bc`; maintainer-approved label visible. https://github.com/plastic-labs/honcho/issues/1176

[9] **Official doc — Honcho V3 Local Environment Setup**, current stack, LLM requirements, provider options and worker verification. https://honcho.dev/docs/v3/contributing/self-hosting.md

[10] **Official doc — Honcho V3 Evidence**, deterministic read evidence and limitations. https://honcho.dev/docs/v3/documentation/features/advanced/evidence.md

[11] **Official doc — Hindsight 0.5.0 release notes**, April 7, 2026: transaction restructuring, capped entity expansion and llama.cpp support. https://hindsight.vectorize.io/blog/2026/04/07/version-0-5-0

[12] **Official doc — Supermemory self-hosting embeddings**, English default, migration constraints and v0.0.5/v0.0.7 defect/fix. https://supermemory.ai/docs/self-hosting/embeddings

[13] **Official doc — Supermemory local overview**, offline deployment and hosted/local feature distinctions. https://supermemory.ai/docs/self-hosting/overview

[14] **Published benchmark — DolphinBench repository README pinned to requested commit**, evaluation protocol, dataset, configurations and Apache-2.0 license reference. https://raw.githubusercontent.com/mem0ai/dolphinbench/81cb6f8405b40a9e76089cef650806a80af06ea2/README.md

[15] **Paper / published benchmark — DolphinBench, arXiv:2609.24971v2**, Table 2 and metrics definitions; Mem0-affiliated authors. https://arxiv.org/html/2609.24971v2 — abstract/version record: https://arxiv.org/abs/2609.24971
