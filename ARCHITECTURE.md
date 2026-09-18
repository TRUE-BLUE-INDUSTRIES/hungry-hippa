# Architecture

Hungry Hippa is a local Python runtime over SQLite, exposed through a maintenance
CLI, an in-process adapter and six stdio MCP tools. Preserve these boundaries;
changes must earn their complexity with evidence. The [technical report](docs/TECHNICAL_REPORT.md)
and [MCP reference](docs/MCP.md) provide deeper runtime detail.

## Data flow

```text
untrusted export bytes -> bounded parser -> canonical conversations/turns
           |                                  |
           +-> exact raw archive + hash <-----+ per-export provenance
                                              |
                           future reviewed extraction (not integrated)
                                              |
                         evidence -> derived beliefs / episodes
                                              |
                          policy -> retrieval -> framed context -> AI client
```

Original bytes, canonical history and derived memory are distinct objects.
Schema v7 preserves raw bytes inside SQLite, immutable export snapshots and
many-to-many turn/archive membership. Existing memory uses separate evidence and
belief/episode evidence links. See [ingestion](docs/INGESTION.md) for transaction,
identity, migration and input-limit behavior. Importing alone never changes recall.

`MemoryController` coordinates episodic/semantic/procedural memory, temporal
graphs, attention, consolidation and forgetting. Retrieval combines FTS5/BM25,
optional local Ollama vectors and bounded graph traversal, then policy filtering,
heuristic ranking, deduplication and a context budget. It exposes scoring parts.
A known BM25/ranking and growth-recall weakness is tracked in [ROADMAP.md](ROADMAP.md);
no retrieval-quality improvement is claimed by the ingestion changes.

SQLite uses WAL and foreign keys, a connection per operation and numbered up/down
migrations. Writes carry audit records; the audit is not tamper-evident. Import
transactions serialize deduplication and quotas with `BEGIN IMMEDIATE`.
SQLite backup includes raw source bytes; operator restore UX remains incomplete.

## Trust and interfaces

MCP identity comes from launch-time owner-token verification; actor labels cannot
grant ownership. Local operator commands use the operator channel. Model writes
are capability-limited and may be quarantined; imported roles are unverified
provider metadata. Memory context is framed as data, never as authority to run tools.

There is no network API in this release, tenant boundary, encrypted store, or
revocable device credential model. Same-user processes can read the database and
token. A connected AI host can transmit recalled context according to its own
configuration. [Security policy](SECURITY.md) and [threat model](docs/THREAT_MODEL.md)
state these limits. No personal database is used in tests or benchmarks.

The package lives in `src/hungry_hippa`; parser modules use only the standard
library. CLI and MCP console scripts are built by setuptools. CI and developers
share `scripts/check_all.py`, including orphan-test detection and a fresh-wheel
installation checked outside the source tree.
