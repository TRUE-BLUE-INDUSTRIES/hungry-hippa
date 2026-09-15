# Hungry Hippa — technical report

A description of what this repository actually implements, how each part works, and the
measurements that exist. Everything asserted here is either visible in the source, or
produced by a command named in the text. Where something is unverified, it says so.

> **Status note (post-MCP-SDK refactor).** This report was written for the phase-4 build
> and keeps its measurements as recorded then. Two things have changed since: the MCP
> protocol layer is now the **official MCP Python SDK** (`mcp_server.py` no longer
> contains hand-written JSON-RPC or a protocol constant), and the suite it refers to as
> `tests/test_mcp_schema.py` was replaced by `tests/test_mcp_integration.py`, which drives
> the same surface through a real SDK client session. Owner authorization is now a
> property of the server's launch environment (`HUNGRY_HIPPA_OWNER_TOKEN`), not a tool
> argument. See `CHANGELOG.md` for the full list; the current suite inventory is in
> `CONTRIBUTING.md` and `scripts/check_all.py`.

Formerly Living Cortex. The rename is described in `docs/MIGRATION.md`; the pre-rename
audit is in `docs/LIVING_CORTEX_BASELINE.md`.

## 1. What problem this solves

An LLM agent session ends, and everything it learned goes with it. The usual answers are:
a bigger prompt, a vector store of chat fragments, or a pile of markdown notes. Each has
a specific failure mode:

- **Bigger prompt** — the context window is a fixed budget, and the transcript competes
  with the work.
- **Vector store of chat chunks** — similarity is not truth. It cannot say "this
  supersedes that", "this failed last time", or "this caller may not see it", and it
  usually requires moving the data to a service.
- **Markdown notes** — durable, greppable, but with no structure: no provenance, no
  confidence, no current-vs-superseded state, no access policy, no budget.

Hungry Hippa is a local SQLite-backed memory runtime with those missing pieces built in:
typed memory, provenance, confidence, supersession and contradiction, a context compiler
with a hard budget, reversible forgetting, and an actor policy that lets another local
agent use the same store without handing it the keys.

## 2. Layering

```
callers            Hermes agent (`cortex` tool)  |  MCP client (stdio)  |  CLI
                   ----------------------------- | -------------------- | -----------
boundary           tools.py (arg caps)           |  mcp_server.py (schemas, caps,
                                                    call budget, policy dispatch)
core               controller.py  ->  policy.py, retrieval.py, limits.py
memory subsystems  episodic / semantic / graph / procedural / consolidation /
                   forgetting / attention / vectors / observability
storage            db.py + schema.py  ->  SQLite (WAL, FTS5, reversible migrations)
```

Core module sizes (lines, `wc -l`, this tree):

| Module | Lines | Role |
|---|---|---|
| `controller.py` | 387 | The single façade every caller goes through |
| `retrieval.py` | 509 | Hybrid recall + context compiler + explanation |
| `mcp_server.py` | 682 | stdio JSON-RPC 2.0, six tools, validation, policy dispatch |
| `db.py` | 387 | Connections, mutation log, FTS, health, backup/migrate |
| `schema.py` | 314 | Four reversible migrations |
| `semantic.py` / `episodic.py` / `graph.py` | 300 / 228 / 257 | Typed memory |
| `limits.py` / `policy.py` | 202 / 118 | Caps + redaction; actor policy |
| `tools.py` / `cli.py` / `observability.py` | 269 / 177 / 158 | Agent tool, CLI, audit views |

The repository is about 5 600 lines of Python in the plugins plus about 1 200 lines of
tests, harness and demo. No third-party runtime packages are used.

## 3. Data model

SQLite, WAL mode, one connection per operation. Four migrations, each with `up` and
`down` scripts (`schema.py`):

| Version | Change |
|---|---|
| 1 | episodes, evidence, entities, relationships, beliefs, procedures, vectors, consolidation/forget/retrieval logs, turn staging, FTS5 index |
| 2 | FTS5 rebuilt as a readable (non-contentless) table; self-healing reindex from source |
| 3 | `product_meta` (Hungry Hippa / formerly Living Cortex); no table or id renames |
| 4 | `sensitivity`, `quarantined`, `actor_id` on `episodes` and `beliefs` + four indexes |

Design rules enforced in code, not just documented:

- **Evidence is insert-only.** `db.add_evidence` writes a sha256 of the content; nothing
  updates an evidence row. `why()` traces a belief back to it.
- **History is not rewritten.** Changing a belief adds a row and marks the old one
  `superseded`/`contradicted`. Changing a graph edge sets `valid_until` and marks it
  `superseded`, so "what do we use now" and "what did we use before" are both answerable.
- **Every mutation is audited** in `mutation_log`; every recall in `retrieval_log`. Audit
  detail is redacted (`limits.redact`) and capped at 2 000 characters. The redaction
  applies to the audit copy only — the memory keeps what it was given, so a redacted log
  can never contradict the record it describes.
- **New columns carry constant defaults**, so migration v4 does not rewrite existing rows.
  Verified: `tests/test_memory_architecture.py::v4_migrates_populated_v3_database`
  builds a populated pre-v4 database, migrates it in place, and checks the rows with
  their new defaults.

## 4. Retrieval and the context compiler

Pipeline (`retrieval.py`):

1. Entity lookup (graph entry points) and optional vector search run in parallel with an
   FTS5 keyword search.
2. Graph traversal around matched entities, bounded by `graph_hop_limit`.
3. Candidates are partitioned by status and by actor policy. Non-active rows
   (superseded/archived) and disallowed rows are recorded as content-free
   `{item, reason}` exclusions rather than silently dropped.
4. Ranking, with the parts kept for inspection:

   ```
   score = (0.30 * salience + 0.22 * recency + 0.22 * relevance
            + 0.13 * term_hit_bonus + 0.13 * confidence) * reinforcement_factor
   ```

   `recency` is exponential decay with a 45-day half-life; `relevance` is the best of
   the vector score, the (legacy) scaled FTS score and term overlap; `reinforcement_factor`
   is `1 + 0.05 × min(10, reinforcement_count)`. Weights are constants at the top of the
   module and every part is reported per item by `explain=True`.
5. The context compiler builds the package: dedupe by normalized text, active beats
   superseded, quarantined rows excluded (unless an owner is explicitly reviewing), then
   a strict character budget.

```python
{
  "items": [...],          # the authorized items that fit
  "rendering": "...",      # what recall() returns as "context"
  "token_estimate": 172,   # ceil(chars / 4) — an estimate, not a tokenizer count
  "excluded": [{"item": "belief:B-0002", "reason": "superseded"}, ...],
  "budget_chars": 1500, "chars_used": 688
}
```

Notes on honesty in this layer:

- `token_estimate` is a character/4 estimate. It is deliberately not a tokenizer: that
  would be a dependency, and a wrong tokenizer would be worse than an honest estimate.
- The legacy FTS term (`fts_score / 10.0`) is kept for backward compatibility even though
  SQLite's `bm25()` is negative-is-better, which makes it contribute little. In practice
  relevance comes from term overlap and vectors. This is a known wart, documented here
  rather than hidden behind a "relevance" label.
- `explain=True` never includes memory content. The tests assert that quarantined text is
  absent from the whole debug payload
  (`tests/test_memory_architecture.py::explain_returns_score_parts`).

## 5. Actor policy and quarantine

`policy.py` implements identity + policy checks. It is **not** capability-based security:
there are no unforgeable, revocable, time-limited capability tokens, and the docs say so
in three places.

| Caller | Writes | Reads | Purge |
|---|---|---|---|
| owner (`primary`, `owner`) | normal | everything; quarantined only when explicitly reviewing | allowed with confirmation |
| anything else | stored **quarantined** | only its own `unclassified`, non-quarantined rows | denied |

Enforcement points:

- Quarantine is decided in the write layer (`episodic.remember_episode`,
  `semantic.add_belief`), not in the controller, so no call path can bypass it. This was a
  real bug found by `tests/test_security.py` and fixed in the same migration.
- Quarantined rows are excluded from default recall, from `list_beliefs` /
  `search_beliefs`, and from the consolidation input (`list_episodes_full`), so an
  injected episode cannot be laundered into a derived belief.
- The owner's review path labels every quarantined item `[QUARANTINED]` in the rendering.
- Purge is owner-only in the controller and additionally requires `confirmation: true`
  over MCP.

## 6. Request limits and log redaction

`limits.py`:

| Control | Value |
|---|---|
| Query / content / array caps | 8 000 / 32 000 chars / 256 items |
| Result text cap | 20 000 chars |
| Single JSON-RPC frame cap | 40 000 chars, then a truncation notice |
| MCP calls per process | 1 000 (`HUNGRY_HIPPA_MAX_MCP_CALLS`) |
| Redaction patterns | private-key blocks, OpenAI/GitHub/AWS/Google/Slack key shapes, JWTs, bearer tokens, `key = value` assignments |

Rejections are errors, not silent truncation. `tests/test_security.py` drives the caps,
the budget, six SQL-injection payloads, and the redaction (including that ordinary prose
is not mangled and that stored memory is not rewritten).

## 7. MCP surface

`mcp_server.py` speaks newline-delimited JSON-RPC 2.0 on stdin/stdout. It answers
`initialize`, `notifications/initialized`, `ping`, `tools/list`, `tools/call` and the
protocol's session-teardown method; unknown methods get `-32601`, unparseable frames get
`-32700`, and an unknown tool name returns a normal `isError` tool result so a client
never loses its session over a typo.

Six tools, strict schemas (`additionalProperties: false`, explicit `required`, enums,
bounds, length caps), no SQL, no path arguments, no export. `tests/test_mcp_integration.py`
runs a complete stdio conversation in-process and asserts each of those properties,
including an AST check that the module imports no network library.

**Not verified:** no external client (Grok CLI, Claude Code, Cursor) has been pointed at
this server. The snippets in `docs/MCP.md` come from client documentation on this machine
and are labelled illustrative.

## 8. Measurements

### 8.1 Acceptance and regression suites

| Command | Result |
|---|---|
| `python tests/test_acceptance.py` | 10/10 |
| `python tests/test_migration.py` | 6/6 |
| `python tests/test_memory_architecture.py` | 8/8 |
| `python tests/test_mcp_integration.py` (that build; now `tests/test_mcp_integration.py`) | 11/11 → 14/14 |
| `python tests/test_security.py` | 10/10 |

These are self-reported by the suite runner. Re-run them yourself; they use temp
databases and take a few seconds.

### 8.2 Memory challenge (`eval/REPORT.md`, `eval/results.json`)

Deterministic, offline, no LLM. Two arms read by the same token-matching reader.
From the recorded run (7 comparable scenarios):

| Metric | With Hungry Hippa | Session transcript only |
|---|---|---|
| Recall rate | 1.0 | 0.143 |
| Incorrect-memory rate | 0.0 | 0.143 |
| Repeated-failed-attempt rate | 0.0 | 1.0 |
| Median context supplied | 109 chars | 0 chars |
| Permission-denial accuracy | 1.0 | unsupported (no access control) |

The baseline's single success was scenario 5, where its whole transcript (9 518 chars) was
still inside the context window versus 386 chars for the capped with-arm. Its single
incorrect answer was scenario 4, where it held both the old and the new claim with no
supersession state, so the stale token stayed in its context.

### 8.3 Growth

From the same run, on the machine that produced it:

| Episodes | DB bytes | Ingest ms/episode | Retrieval ms (median of 5) | Context chars (with) | Context chars (transcript-only) |
|---|---|---|---|---|---|
| 100 | 290 816 | 0.62 | 3.25 | 747 | 4 153 |
| 500 | 573 440 | 0.63 | 3.37 | 747 | 21 024 |
| 2 000 | 1 544 192 | 0.64 | 3.76 | 747 | 85 274 |

Read this as shape, not as a benchmark: absolute milliseconds depend on the machine, and
the same command on your hardware will produce different numbers. The useful signals are
that ingest and retrieval grow slowly, and that the compiled context stays flat while the
transcript-only context grows linearly with the session.

### 8.4 Not measured

- No LLM-judged answer quality, semantic equivalence, or paraphrase recall.
- No vector/embedding recall quality (Ollama deliberately disabled for repeatability).
- No concurrency or multi-process write contention measurements.
- No security testing by a third party. The security tests are guards written by the same
  author as the code.

## 9. Limitations

Structural, and stated rather than implied:

- **Single operator, single database.** No accounts, no tenant isolation, no per-caller
  quotas. `actor_id` is caller-supplied, so a process that can start the MCP server can
  claim any identity. The boundary is "whoever can run this command".
- **No encryption at rest.** SQLite files are plaintext; OS disk encryption is the
  expectation. Sensitivity labels are read-policy labels stored in plaintext.
- **No tamper-evident audit.** `mutation_log` is append-only by convention, not by hash
  chain; anyone with file access can edit it.
- **Redaction is pattern-based**, and covers audit logs, not stored memory.
- **Degradation, not failure, on bad input:** database helpers return empty results rather
  than raising into the agent loop, and `db.failures` counts them. Fail-safe is good for
  an agent loop and bad for surfacing problems — check the counter.
- **Heuristic ranking.** Deterministic and inspectable, not learned. It does not try to be
  optimal; it tries to be explainable and debuggable.
- **`neural.py` is an interface stub.** No model weights are trained, updated or loaded.
  Any description of this project as "machine learning" would be wrong.

## 10. Reproducing this report

```bash
python tests/test_acceptance.py
python tests/test_migration.py
python tests/test_memory_architecture.py
python tests/test_mcp_integration.py
python tests/test_security.py
python eval/harness.py            # rewrites eval/results.json and eval/REPORT.md
python demo/demo.py --check       # 8-step demo, verified against captured output
python mcp_server.py --print-schemas
```

Timestamps, latency figures and store sizes in section 8 come from the recorded run and
are stamped in `eval/results.json` (`generated_at`, `git_rev`, `git_dirty`).
