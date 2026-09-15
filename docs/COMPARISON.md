# Comparison: Hungry Hippa against other ways of giving an agent memory

Hungry Hippa is a local-first memory runtime for AI agents. It stores and retrieves
experience and compiles context. **It does not train a model**, and nothing here is a
model-weight update.

This document compares the runtime **as it exists in this tree** (schema v5, after the
official-MCP-SDK refactor and the identity-binding hardening)
against three deliberately narrow architectural patterns:

- **basic vector-store memory** — similarity search over text chunks plus metadata;
- **file-based agent notes** — agent-maintained local text files (markdown, notes);
- **local event-log systems** — ordered, durable local events with query/replay.

These are patterns, not surveyed products, and no speed, cost, quality or "better agent
outcomes" claim is made. The right-hand columns describe what the pattern gives you *by
itself*; "application work" means the pattern does not supply that behaviour and someone
has to build it. Every pattern here can be extended into the others' territory.

A pre-migration comparison of the `6574bc6` baseline exists on the unmerged
`feat/hungry-hippa-eval` branch. It is accurate for that commit; several of its
Hungry Hippa rows (actor policy, quarantine, MCP, context compiler) describe behaviour
that did not exist yet. **This document supersedes it for the current tree.**

## Feature matrix

Legend: **yes** = implemented and covered by a test in this repository; **partial** = the
mechanism exists but with a documented limitation; **no** = not implemented here;
**application work** = the pattern does not provide it by itself.

| Capability | Hungry Hippa (this tree) | Basic vector-store memory | File-based agent notes | Local event-log systems |
|---|---|---|---|---|
| Local persistence | **yes** — SQLite WAL, four reversible migrations [1] | depends on deployment | local filesystem | local durable log |
| Offline operation | **yes** — keyword + graph recall with vectors disabled; demo and eval run in this mode [2, 9] | needs local inference for semantic search | **yes** — files are local | **yes** — local replay |
| Retrieval | **yes** — FTS5 + graph traversal + optional local vectors, ranked by salience, recency, relevance, confidence [2] | vector similarity + metadata filters | text search, or the agent reads them | query/replay over events |
| Explainable ranking | **yes** — `recall(explain=True)` returns per-item score parts and budget drops, without memory contents [2, 7] | similarity scores, usually a single number | application work | application work |
| User-directional context budget | **yes** — `build_context()` returns `{items, rendering, token_estimate, excluded}` inside a strict character budget, with dedupe [2] | top-k controls item count; token budgeting is application work | the reader must select and budget | application work |
| Memory structure | **partial** — episodes, beliefs (fact/belief/hypothesis), procedures, entities and temporal relationships; no working-memory or preference type beyond beliefs [3, 4] | chunks + metadata | arbitrary prose | typed events |
| Cross-session recall | **yes** — a new session on the same store recalls prior work (scenario 1 answers correctly with the runtime and not without it) [9] | needs a shared store | shared files | shared log |
| Cross-agent portability | **partial** — a second client process reaches the same store over MCP; only owner-actor clients see the full store, and no external client has been verified [4, 7, 9] | shared store integration | shared files | shared log format |
| Authorized sharing / access control | **partial** — actor + policy checks: untrusted actors read only their own unclassified, non-quarantined rows, cannot purge, and write quarantined [4, 8] | application policy | OS file permissions | log access policy |
| Capability-based security | **no** — explicitly not claimed; `actor_id` is caller-supplied [4, 8] | no | no | no |
| Poisoning resistance | **partial** — untrusted writes are quarantined and excluded from recall, belief listing and consolidation input; **not** a truth detector, and a caller claiming the owner actor bypasses it [3, 5, 8] | not implied by similarity | not implied | not implied |
| Prior failure context | **partial** — actions, outcomes and results are stored and recalled; the eval measures that the failure is *in context*, not that an agent independently avoids it [3, 9] | store outcome text, behaviour is application work | can document attempts | can record failure events |
| Temporal state / supersession | **yes** — relationship validity + status, belief supersession keeps the old row, recall prefers current [3, 6] | version metadata is application work | manual history or VCS | natural event ordering |
| Contradiction handling | **yes** — contradicting claims are preserved and cross-linked, resolved by confidence + source priority (explicit user correction wins) [3, 6] | application work | manual reconciliation | application work |
| Provenance | **yes** — source class, confidence, immutable sha256-hashed evidence rows, derivation links; `why()` traces a belief to its evidence [1, 6] | source metadata if supplied | citations if supplied | event origin if recorded |
| Forgetting / retention | **partial** — reversible archival, decay, compression; purge is owner-only and confirm-gated over MCP. Archival is **not** secure erasure [5, 6, 8] | delete/filter | edit or delete files | tombstones/compaction |
| Audit trail | **partial** — append-only by convention, with credential redaction; **not** tamper-evident (no hash chain) [1, 7, 8] | application work | file history | native to the log |
| Limits and abuse guards | **partial** — argument/result/frame caps, per-process call budget, no-export rule; no per-caller quotas or timeouts [7, 8] | application work | application work | application work |
| Client integrations | **partial** — Hermes provider + `cortex` tool (tested), local stdio MCP server (tested in-process and as a real process); no external MCP client verified [4, 7, 9] | client adapters needed | filesystem/tool access | log client needed |
| Encryption at rest | **no** — plaintext SQLite; OS disk encryption is the documented expectation. Sensitivity labels are read-policy labels, not encryption [8] | implementation-dependent | OS/filesystem choices | implementation-dependent |
| Hardware-backed deployment | **not demonstrated** — stdlib + SQLite would run on a small local device, but nothing has been run on one | — | — | — |
| Semantic search | **optional** — local Ollama embeddings, off by default in eval/demo; established technology, not proprietary [2] | **yes** — this is the core of the pattern | no | application work |

## Evidence in this repository

1. `schema.py` (migrations 1–5, each with a `down` script), `db.py` (`Database`, evidence
   hashing, `mutation_log`, FTS rebuild, health). `python tests/test_migration.py` → **7/7**,
   including a populated pre-v4 database migrated in place
   (`python tests/test_memory_architecture.py` → **8/8**).
2. `retrieval.py`: the `_recall` pipeline, the ranking weights at the top of the module,
   `_explain`, and `compile_context`. The strict budget, dedupe and quarantine exclusion are
   asserted in `tests/test_memory_architecture.py`.
3. `episodic.py`, `semantic.py`, `graph.py`, `procedural.py`: stored fields and public
   operations. `python tests/test_acceptance.py` → **10/10** (T1–T10, including temporal graph
   history T4, contradiction T5, provenance T7, forgetting T8, provider prefetch T10).
4. `controller.py`, `policy.py`, `trust.py`, `__init__.py`, `tools.py`, `mcp_server.py`.
   Actor policy and quarantine behaviour: `python tests/test_memory_architecture.py` → 8/8,
   `python tests/test_security.py` → **14/14**, and the MCP surface driven by a real client
   session: `python tests/test_mcp_integration.py` → **14/14**. Channel-bound identity:
   `python tests/test_trust_boundary.py` → 6/6, `python tests/test_trust_token.py` → 9/9.
5. `forgetting.py` and `Controller.forget`. Neither archival nor row deletion is physical
   erasure from SQLite pages or backups; that is stated in `docs/SECURITY.md`.
6. `observability.py` (`why`, `recent_changes`, `forgotten`) plus the acceptance tests above.
7. `limits.py` (caps, call budget, redaction) and `docs/THREAT_MODEL.md`; limits and
   injection resistance are asserted in `tests/test_security.py`.
8. `docs/SECURITY.md` and `docs/THREAT_MODEL.md` document the boundaries, the non-claims and
   the residual risks; `SECURITY.md` lists documented limitations that are not
   vulnerabilities.
9. `eval/results.json` and `eval/REPORT.md` (deterministic, offline, no LLM judge):
   recall rate **1.0 vs 0.143** on the seven scenarios where both arms are comparable,
   incorrect-memory rate **0.0 vs 0.143**, repeated-failed-attempt rate **0.0 vs 1.0**,
   permission-denial accuracy **1.0** (baseline: unsupported), median context supplied
   **109 vs 0 chars**, retrieval latency **3.2 / 3.4 / 3.8 ms** at 100 / 500 / 2 000
   episodes with a flat 747-char context versus a transcript growing 4 153 → 85 274 chars.
   `python demo/demo.py --check` → transcript matches the captured run.
10. `docs/TECHNICAL_REPORT.md` collects the measurements and, in section 8.4, the metrics
    that were deliberately **not** measured.

## What the combination actually offers

The difference is not any single novelty. It is that one local process holds episodic
experience, beliefs with provenance, temporal relationships, procedural outcomes, a
retrieval path that explains itself, a budgeted context compiler, an actor policy and a
reversible forgetting path — behind one controller, with a Hermes tool and a local MCP
surface on top. A caller does not have to assemble that logic itself, and the store never
leaves the machine.

The measurements above establish small, synthetic retrieval and policy behaviours on
throwaway databases. They do **not** establish that an agent completes more tasks, and no
comparison against another implementation was run.

## What is not claimed

- SQLite, FTS5, semantic search, vector indexes, MCP, encryption, RBAC or SQL are
  established technologies. None of them is proprietary or novel to this project.
- No superiority over a vector store, a notes file or an event log is claimed. Notes are
  often enough when inspectable prose is the need; a vector index fits similarity lookup; an
  event log fits ordered history and replay.
- No encryption at rest, no tamper-evident audit, no multi-tenant isolation, no
  capability-based security, no authenticated MCP transport, no hardware-backed
  deployment, no adversarial robustness evaluation, no cross-model interoperability test.
- No model training, fine-tuning or weight update of any kind. `neural.py` is an interface
  stub.
- This repository is public and its branches (`main`, `feat/hungry-hippa`) are pushed to
  GitHub; CI runs on every push. See [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md) and the
  repository URL in the README.
