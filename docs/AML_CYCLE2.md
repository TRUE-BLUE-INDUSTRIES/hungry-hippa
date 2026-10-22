# Agent Memory Challenge — Cycle 2: entry plan for Hungry Hippa

Second public cycle of the Agent Memory Leaderboard challenge
(https://agentmemoryleaderboard.ai/competition/), opened 2026-09-20.
Hosted by CSIG (organizers: Nanjing University, Zhejiang University,
Datawhale, CSIG enterprise liaison & standardization committee). Three tracks
(Textual / Coding / Multimodal). Entry is free.

Target: **Textual Memory track** — recall of explicit facts/relations/multi-hop,
temporal sequences, and memory governance. That maps directly onto Hungry
Hippa's temporal graph, contradiction handling, quarantine, and reversible
forgetting. Coding is a plausible second; Multimodal is a skip (vision/audio
toggles are off by default).

## Hard dates (UTC+8; PDT = UTC+8 minus 15h)

| Milestone | UTC+8 | DJ's time (PDT) |
|---|---|---|
| Materials due | Oct 31, 2026 23:59 | **Oct 31, 2026 08:59** |
| Evaluation stops | Nov 4, 2026 23:59 | Nov 4, 2026 08:59 |
| Leaderboard published | mid-November | mid-November |

## The one-shot rule (read this twice)

Each evaluation Key gets **max 2 Full runs per track**, and the 2nd cannot
start until **30 days after the first Full completes**. With evaluation
stopping Nov 4, there is effectively **ONE scored run**. Prep quality beats
iteration — do not burn the Full run on an untested deployment.

## Which division: academic vs industrial (decision needed)

The open-source methods leaderboard has two divisions, chosen at application:

| | 学术榜 Academic | 工业榜 Industrial |
|---|---|---|
| Prize eligibility | **Yes** — ¥50K/track pool (¥20K 1st, 2×¥8K 2nd, 3×¥3K 3rd, ¥5K innovation) | **No** — "商业产品榜不参与奖金评选" |
| Model constraints | Embedding MUST be `text-embedding-v4`; LLM components MUST be `gpt-4o-mini`; reranker unrestricted | None — self-trained / open-weight / local models explicitly welcome ("工业榜不要求商业化，非商业开源项目也可参赛") |
| Source disclosure | Public repo at fixed commit | Not required |

Hungry Hippa's embeddings are fully local today. Entering Academic would
require switching to `text-embedding-v4` via DashScope (~**$22.50 per
Textual Full run** at $0.07/MTok × ~300M corpus tokens, plus a DashScope
account and API spend) — and it breaks the local-first thesis that IS the
project. **Recommendation: enter Industrial.** The prize was never the point
of this campaign — a public leaderboard placement in November is the
proof-of-skill artifact the Meta goal needs, and Industrial keeps the build
honest: zero spend, local-first, no model swap. If the prize money ever
matters more than the thesis, Academic is a future cycle's fight, not this
one's.

## What the platform requires

1. A **publicly reachable Add/Search HTTP API**, deployed by us. Repo-only
   submissions are NOT accepted in Cycle 2. Endpoints must be public HTTPS;
   no credentials in URLs; private/loopback addresses rejected.
2. Open-source entrants submit: the API endpoint + GitHub repo + **fixed
   commit**. Results are bound to that commit for audit.
3. Flow: apply for an evaluation Key (form asks: division, contact email,
   system name + version, Add URL, Search URL, auth scheme
   [Token/Bearer/X-Api-Key], your Memory System Key, project/paper URL,
   deployment description; optional health-check URL) → key issued by
   **19:00 Beijing time the day after applying** → pass the **smoke test**
   (synchronous Add→Search→Answer→Evaluate; 1/hour, max 30/track) → submit
   the **Full** evaluation → platform runs Answer + Eval itself.
4. The system under test does memory only: Search must return **evidence
   records, never a generated final answer** (our adapter enforces this).

## The official wire contract (verified 2026-10-04)

Source: official API Guide (agentmemoryleaderboard.ai/api-guide) plus two
independent contract-exact community adapters. Paths are participant-defined;
schemas are fixed.

**`POST /add`** — request:
```json
{"request_id": "eval:run_abc:locomo:conv-0:chunk-0",
 "messages": [{"role": "user", "content": "I live in Seattle.",
               "timestamp": 1704067200000}],
 "user_id": "eval:run_abc:locomo:conv-0",
 "session_id": "eval:run_abc:sample:0"}
```
Response `200` ONLY after the write is persisted AND immediately searchable:
```json
{"success": true, "request_id": "...", "user_id": "...", "session_id": "..."}
```
Ids echoed byte-for-byte; omitting `success: true` or mis-echoing fails the
stage even with HTTP 200. `content` is a string on text/coding tracks
(multimodal uses ContentPart[] — rejected here). `timestamp` is optional
Unix ms.

**`POST /search`** — request:
```json
{"query": "Where does the user live?",
 "options": ["A. Seattle", "B. Boston"],
 "user_id": "eval:run_abc:locomo:conv-0",
 "top_k": 100}
```
Response: `{"data": [{"id": "mem_1", "content": "…", "score": 0.87,
"created_at": "2024-01-01T00:00:00+00:00"}]}` — stored fragments only,
relevance-ordered, **never more than `top_k`** (excess is a contract error,
not silently truncated), `data: []` when empty. Formal evals use
`top_k = 100`. `options` is a top-level string array on multiple-choice
questions (never contains the gold answer); omitted for open questions.

**Operational rules that shaped the adapter:**
- `user_id` is the ONLY isolation field — Search must retrieve solely under
  the given `user_id`; `session_id` is stored, never filtered on.
- Add is retried with the SAME `request_id` (408/409/425/429/500/502/503/
  504/524, timeouts) → the endpoint must tolerate re-delivery (idempotent).
  Search is retried on 408/425/429/500/502/503/504 — **not** on 409 or 524.
- 400/401/403/404/422 are NOT retried (fail fast on contract errors).
- One request may run up to 30 minutes. 429 with `Retry-After` is retried
  with bounds.
- Eval data must be deleted within 30 days after the job completes.

## The adapter (this repo)

`src/hungry_hippa/aml_adapter.py` — stdlib-only HTTP server, contract v2
(branch `feature/aml-adapter-contract-v2`, 11/11 contract checks green):

* `POST /add` → validates the official schema (400 on contract errors);
  one episode per message, annotated `[ISO time] role: text`; responds
  `{success: true, request_id, user_id, session_id}` echoed byte-for-byte,
  only after commit.
* Idempotent Add on `(user_id, request_id)`: same payload replays the
  original echo without rewriting; conflicting payload → `409`.
* `POST /search` → hybrid `recall` scoped to the user's isolated store;
  returns `{data: [{id, content, score, created_at}]}`, ≤ `top_k`, `[]` for
  unknown users. `options` are folded into the retrieval query
  (`HIPPA_AML_INCLUDE_OPTIONS=0` to disable).
* `GET /health` → liveness (no auth).
* Auth: `Authorization: Bearer` (declare this), also accepts `Token`
  scheme and `X-Api-Key` header; constant-time compare.
* **Per-user isolation, always.** Base dir `HIPPA_AML_DATA_DIR` (default
  `<data-dir>/aml_eval`); each `user_id` gets `users/<sha256[:32]>/store.db`.
  Hard-refuses the live store. Use a **fresh base dir per run** — the
  smoke-test corpus must never share storage with the Full-run corpus.
* Backpressure: max 8 in-flight (`HIPPA_AML_MAX_INFLIGHT`), else `429`
  with `Retry-After: 5`.
* No LLM on Add or Search; embeddings stay local (the controller's
  VectorStore). Write quota is per user-store per hour (default 20K;
  raise via `HUNGRY_HIPPA_MAX_WRITES_PER_HOUR` if a run ever approaches it).

## Zero-spend public endpoint (from the battlestation)

No VPS, no purchases. **Prefer Tailscale Funnel** for the Full run:

```bash
export HIPPA_AML_API_KEY="$(openssl rand -hex 24)"
export HIPPA_AML_DATA_DIR="$HOME/.local/share/hungry-hippa/aml_eval_full"
python -m hungry_hippa.aml_adapter --port 8000 &
tailscale funnel 8000   # serves https://<machine>.<tailnet>.ts.net
```

Hand the funnel URL (+ `/add`, `/search` paths) to the platform as the API
endpoint. Declare auth scheme `Authorization: Bearer`.

**Why not Cloudflare Tunnel for the Full run:** community operators report
Cloudflare-proxied hostnames return 524 after ~125 s, and the platform does
**not** retry Search on 524 — a slow Search through Cloudflare fails
unretried. (Add IS retried on 524 and our Add is idempotent, so it's
survivable — just not worth the risk on the one scored run.) Cloudflare
quick tunnels remain fine for smoke tests.

Keep the endpoint up for the whole evaluation. The rules do NOT require it
to stay public after results are in; delete eval data within 30 days.

## Run checklist

- [x] Adapter implements the official wire contract (11/11 checks green).
- [ ] DJ reviews `feature/aml-adapter-contract-v2`, merges, pushes.
- [ ] Decide division: **Industrial** (recommended) vs Academic.
- [ ] Fresh base dir for the smoke run; deploy via Tailscale Funnel.
- [ ] Apply for the Key (form fields listed above); key lands by next-day
      19:00 Beijing time.
- [ ] Smoke test passes (Add → Search roundtrip through the public URL).
- [ ] Fresh base dir for the Full run; tag/fix the commit; submit API +
      repo + commit before Oct 31 08:59 PDT.
- [ ] Full evaluation completes before Nov 4 08:59 PDT; delete eval data
      within 30 days; results mid-November.

## What this is NOT

* Not a second Full run to "try again" — the 30-day rule kills that.
* Not touching the live memory store — per-user isolated DBs under a base
  dir that hard-refuses the live path, and eval base dirs are throwaway.
* Not a purchase — Industrial division + local embeddings + free tunnel
  keeps the whole run at $0.
