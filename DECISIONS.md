# Engineering decisions

## ADR-001 — Reuse reviewed ingestion slices; defer model extraction (2026-09-18)

Evidence: main v1.0.0 only parses exports. Existing commits `1221b16` and `b25d715`
add canonical tables and explicit CLI writes. Later extraction checkpoints even
when malformed model output parses as an empty result and truncates each turn to
800 characters; reconciliation can strengthen or supersede memory before approval.

Decision: reuse the two foundational commits and harden their boundaries. Keep
later branches intact for repair; do not release their end-to-end claims. No model
provider replacement or broad architecture rewrite. Success means repeatable,
verified import and recovery on synthetic evidence, measured independently of recall.

## ADR-002 — Retain exact bytes and archive membership in SQLite (2026-09-18)

Evidence: the prototype parsed, hashed and copied through separate file opens;
conversation upsert changed the archive pointer while first-write-wins turns kept
old contents. A path/hash pointer alone cannot recover a removed export or ensure
that normalized rows came from the hashed bytes.

Decision: read one bounded immutable byte snapshot; parse, hash and validate that
snapshot; transactionally store it in a separate raw table. Preserve per-export
conversation snapshots and many-to-many turn/archive membership. Reject conflicting
canonical identities instead of silently discarding either claim. Existing archive
reimports are no-ops; the latest distinct import controls the current branch view.

Migration: additive schema v7; v6 rows are not silently trusted/backfilled. Reimport
original bytes to verify them. Later experimental branches already use their own
v7/v8; rebase those migrations before integration. Never mix those branch databases.
Costs: source bytes increase database/backup size. Enforce input/lineage/storage
budgets, benchmark bytes per message and throughput. Tests cover file replacement,
transaction rollback, multiple sources, tampering, migration and SQLite recovery.
Hashes prove consistency, not provider authenticity or same-user tamper resistance.

## ADR-003 — One verification runner and measured claims (2026-09-18)

Evidence: CI's duplicated list omitted the Hippo-Pot suite and orphan-test guard.
The published synthetic eval does not represent imported-history QA; growth recall
has failures and its historical clean-tree note disagrees with its dirty flag.

Decision: CI invokes the shared runner; validate an installed wheel outside the
checkout. Add a separate deterministic ingestion benchmark with all runs, commit,
code digest, dirty status, hardware and limits. Keep dataset-backed recall evaluation
as explicit future work. Do not present smoke tests as proof of general security or
state-of-the-art memory quality.

## ADR-004 — AML Cycle 2 adapter: isolated owner-bound HTTP surface (2026-10-04)

Evidence: the Agent Memory Leaderboard Cycle 2 requires open-source entrants
to self-deploy a public Add/Search HTTP API (repo-only no longer accepted);
Search must return evidence, never a generated answer; each Key allows max 2
Full runs with the 2nd gated 30 days after the 1st, so the cycle admits
effectively one scored run. Hungry Hippa's MCP surface is stdio-only and its
trust model quarantines non-owner writes out of recall.

Decision: scaffold `src/hungry_hippa/aml_adapter.py` on an isolated feature
branch (`feature/aml-add-search-adapter`), stdlib `http.server` only (zero new
dependencies), Bearer auth, requests serialized behind one lock. The adapter
binds as owner on a DEDICATED database (`aml_eval.db` default) and
hard-refuses the live default store; quarantine is deliberately not applied
to the benchmark corpus on that isolated DB. Recall is global to the DB, so
each eval run (smoke vs Full) gets a fresh database file. Wire field names
are scaffold-grade and must be verified against the official API Guide after
Key issuance. Tests use invented data and throwaway DBs only
(`tests/test_aml_adapter.py`, wired into `scripts/check_all.py`).

## ADR-005 — AML adapter contract v2: official wire shapes, per-user isolation, idempotent Add (2026-10-04)

Evidence: the official API Guide (agentmemoryleaderboard.ai/api-guide, read
2026-10-04) fixes the Add/Search schemas the scaffold had guessed. Two
independent contract-exact community adapters corroborate every field.
The scaffold's shapes (`items[]`, `{results, errors}`, `{results, count}`,
global recall) would have failed the smoke test: the platform sends
`messages[]` and reads `data[]`.

Decision: rewrite the adapter on `feature/aml-adapter-contract-v2`
(stdlib only, unpushed, owner reviews): official request/response schemas
with byte-for-byte id echoes and `success: true` only after durable +
searchable writes; per-`user_id` isolated stores (`users/<sha256[:32]>/`)
since `user_id` is the only isolation field and the platform uses
per-conversation user ids; idempotent Add on `(user_id, request_id)` (same
payload replays the echo, conflicting payload -> 409) because the platform
retries Add with a stable `request_id`; `data[]` evidence records capped at
`top_k`; Bearer/Token/X-Api-Key auth; 429 + Retry-After backpressure;
contract errors fail fast with 400/401/404 (not retried). Division guidance:
Academic is prize-eligible but mandates text-embedding-v4 (+~$22.50/run)
and gpt-4o-mini, which breaks the local-first thesis — Industrial
(recommended) has no model constraints, no prize, $0 spend. Deployment:
prefer Tailscale Funnel for the Full run; community operators report
Cloudflare-proxied hostnames 524 after ~125 s and the platform does not
retry Search on 524. Tests: 11/11 contract checks on throwaway DBs.
