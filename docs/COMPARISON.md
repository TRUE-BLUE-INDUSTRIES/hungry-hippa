# Hungry Hippa comparison: Phase 2 baseline

Hungry Hippa is a local-first memory runtime for AI agents, formerly Living Cortex. It stores and retrieves experience; it does not train a model. This comparison describes the runtime at `6574bc6`, the baseline used by the [actual challenge run](../eval/REPORT.md). Later work on other branches is outside its scope.

The other columns are deliberately narrow architectural patterns, not surveyed products or measured competitors. A **basic vector store** means similarity search over text chunks and metadata. **File notes** means agent-maintained local text files. A **local event log** means ordered, durable events with replay/query. Each can be extended with the features below; “application work” means the pattern alone does not supply them. No speed, cost, or quality superiority is claimed.

## Feature matrix

| Feature | Hungry Hippa in this worktree | Basic vector-store memory | File-based agent notes | Local event-log systems |
|---|---|---|---|---|
| Local persistence | SQLite with WAL and schema migrations [1] | Depends on storage deployment | Local filesystem | Local durable log |
| Retrieval | FTS5 keywords, optional local Ollama vectors, graph traversal, heuristic ranking [2] | Vector similarity and metadata filters | Text search or agent reads | Event queries/replay; semantic indexing is application work |
| Offline operation | Keyword/graph paths work with vectors disabled; eval uses this mode [2, 7] | Local embedding inference/index needed for offline semantic search | Files can be read offline | Local query/replay can operate offline |
| Memory structure | Episodes, semantic beliefs, procedures, entities and temporal relationships [3] | Chunks/metadata; richer semantics need application work | Arbitrary prose and file conventions | Typed events; current-state memory projections need application work |
| Sessions and portability | New Python controller/session can read same DB; Hermes provider integration exists. No tested cross-model client interoperability [4, 7] | Shared store integration needed | Shared files can be read by compatible tools | Shared log format/client needed |
| Authorized sharing | No actor ACL or permission-scoped recall; session IDs are not read isolation [4] | Depends on implementation and application policy | OS file permissions; finer scopes need application work | Depends on log access policy and projections |
| Prior failure context | Stores action/result/outcome; challenge verifies later structured recall. Autonomous avoidance unmeasured [3, 7] | Can store outcome text; behavior is application work | Can document failed attempts | Can record failure events; relevant context assembly is application work |
| Temporal state | Relationship validity/status/history; belief supersession preserves old rows [3, 6] | Version metadata and resolution need application work | Manual history or version control | Event ordering/history natural; supersession projection is application work |
| Contradictions | Explicit contradiction links and source/confidence resolution; not a general truth detector [3, 6] | Application work | Manual or agent-authored reconciliation | Application projection/resolution logic |
| Provenance | Source refs, evidence IDs/hashes and derivation links; acceptance test traces belief to evidence [1, 6] | Source metadata if supplied | Citations or file history if supplied | Event origin/correlation if recorded |
| Context budget | Item limit and character-oriented renderer. Oversized first item violates cap; structured items have no character cap. No tokenizer-based compiler [2, 7] | Top-k commonly controls item count; token budgeting is application work | Reader/agent must select and budget text | Query limit and context compilation need application work |
| Forgetting | Explicit archival excludes episodes/beliefs from normal recall; decay/compression and purge paths exist. Archival is not erasure [5, 7] | Delete/filter/retention depends on implementation | Edit/delete files; history may retain content | Tombstones/retention/compaction depend on design |
| Poison resistance | No quarantine enforcement or measured prompt-injection defense [4, 7] | Not implied by similarity search | Not implied by storing notes | Not implied by event durability |
| Integrations | Hermes provider and `cortex` tool; no MCP server or verified Grok CLI path [4, 6] | Client adapters needed | Filesystem/tool access needed | Log client/adapters needed |
| Encryption / audit | No built-in DB encryption. Evidence hashing and mutation logging are not protection against a malicious DB-file writer [1] | Implementation-dependent | OS/filesystem choices | Implementation-dependent |

## Evidence in this repository

1. [db.py](../db.py): `Database`, evidence hashing, mutation log, FTS and health counts; [schema.py](../schema.py): migrations. [Migration tests](../tests/test_migration.py) passed **6/6** during this delivery.
2. [retrieval.py](../retrieval.py): `RetrievalRouter._recall` and `render`; [vectors.py](../vectors.py): optional embedding path. Optional vector behavior was code-reviewed, not exercised in this delivery. The `project` argument prioritizes matching items and retains other projects; it is not an access filter.
3. [episodic.py](../episodic.py), [semantic.py](../semantic.py), [procedural.py](../procedural.py), and [graph.py](../graph.py): stored fields and public operations. A procedure outcome can be recorded, but ordinary recall searches episode/belief FTS and graph paths, not procedure FTS.
4. [controller.py](../controller.py): session binding, public recall and mutation methods; [provider](../__init__.py) and [tools.py](../tools.py): Hermes integration. Subagent episode-write suppression is not general authorization: recall has no actor permission check.
5. [forgetting.py](../forgetting.py): archival, decay, compression; controller `forget` also exposes explicit purge. Neither archival nor row deletion demonstrates secure physical erasure from SQLite pages/backups.
6. [Acceptance tests](../tests/test_acceptance.py) passed **10/10** during this delivery: temporal graph history (T4), explicit contradiction (T5), provenance (T7), forgetting (T8), and simulated provider prefetch (T10). These are local tests, not an installed-Hermes or Grok end-to-end validation.
7. [Challenge results](../eval/results.json): **6 pass, 1 fail, 3 unsupported**. Factual recall, rationale, failed-fix context, supersession, archival, and growth measurements ran on throwaway DBs. The strict character-budget check failed. Authorized portability, poisoning resistance, and unauthorized retrieval are unsupported. [Demo evidence](../demo/EXPECTED.md) records clean-directory script/reset runs; independent Hermes verification remains pending.

## What the combination offers

The implemented distinction is a common controller that connects episodic experience, beliefs with provenance, temporal relationships, procedural outcomes, retrieval, and conservative archival in a local database, with a Hermes provider. That reduces the amount of memory-specific application logic a caller must assemble. The current challenge establishes small synthetic retrieval behaviors, not superiority over another architecture or improved agent task success.

SQLite, FTS, semantic search, encryption, RBAC, and MCP are established technologies, not proprietary inventions claimed here. RBAC, quarantine and MCP are absent from this baseline. No hardware-backed deployment, adversarial robustness, cross-model interoperability, or strict context compiler is demonstrated. File notes may be sufficient when inspectable prose is the main need; a basic vector index fits similarity lookup; an event log fits ordered history and replay. The matrix is a scope comparison, not a purchasing recommendation.
