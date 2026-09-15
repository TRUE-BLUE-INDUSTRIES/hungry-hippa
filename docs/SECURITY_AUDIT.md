# Hungry Hippa security audit — hardening pass 2

Scope: the eight findings produced by the operator-requested red-team review of
2026-09-15, verified against `d22f556` (the then-current HEAD) and fixed in the
commits listed below. Baseline for "confirmed": a reproduction run on HEAD before
any change, using throwaway databases and the real stdio MCP server. Nothing here
is claimed fixed unless a named regression test exercises it.

Full suite at completion: `python scripts/check_all.py` → **all 15 steps passed**
(acceptance 10/10, migration 7/7, memory architecture 8/8, MCP 11/11, identity
binding 6/6, existence oracle 5/5, file permissions 6/6, provenance 6/6, injection
framing 7/7, supersession 7/7, confused deputy 6/6, resource limits 8/8, demo
transcript match, eval stable).

| Phase | Commit | Content |
|---|---|---|
| B | `cbf7d2c` | identity bound to the channel |
| C | `ff4dae5` | existence oracle closed |
| D | `b6f319b` | file permissions |
| E | `b0c8a7f` | claimed vs verified provenance |
| F | `ad7722b` | recalled-memory framing |
| G | `4396dbf` | supersession authorization |
| H | `09e891f` | capability ladder / confused deputy |
| I | `18ba2f4` | resource controls |

---

## Finding 1 — caller-controlled owner identity

**Confirmed.** Yes, with a reproduction on HEAD: an MCP client sending
`actor_id="primary"` (no token) read the owner's private belief
(`hippa_recall` → count 1), received `db_path` from `hippa_status`, and **purged an
owner belief** with `hippa_forget mode=purge confirmation=true`.

**Vulnerable path.** `mcp_server._actor_of()` → `policy.normalize_actor(payload
actor_id)` → `controller.bind_session(actor_id=…)` → `policy.is_owner(actor_id)`.
Identity was a request field, so the request decided its own privileges.

**Consequence.** Any local process able to start the server (or any client
configured for it) had full owner rights: read everything, export, purge.

**Fix.** `trust.py` resolves a `Binding(actor_id, identity, provenance, channel)`
server-side. In-process code is owner; an MCP caller is owner only with the owner
token (32 random bytes, `0600` file, `hermes living-cortex owner-token`); anything
else is untrusted and every write is quarantined regardless of the label. A claim
colliding with an owner label is remapped to `mcp-untrusted`, and `policy.may_read`
refuses the collision a second time. The token is consumed at the boundary: never
echoed, stored, logged.

**Regression test.** `tests/test_trust_boundary.py` →
`claimed_owner_is_not_owner`, `untrusted_cannot_read_private_or_self_promote`,
`trusted_owner_path_still_works`, `token_file_is_private_and_not_logged`,
`binding_is_channel_derived_in_process`, `owner_label_collision_is_remapped`.
**Result: 6/6 pass.**

**Remaining limitation.** This is a local capability, not authentication. A
process already running as the operator can read the token file and the database
directly. The transport is stdio with no network listener, so "can read the token"
means "is, or runs as, the operator" — that is the honest boundary, not a claim of
user authentication.

---

## Finding 2 — persistent prompt injection through memory

**Confirmed.** Yes: a stored belief containing an instruction was returned
verbatim in the next session's compiled context, with no statement that it was
historical data. The rendering also accepted content that imitated runtime markup
and metadata.

**Vulnerable path.** `retrieval._render_body()` → `compile_context()` →
`recall()["context"]` → the agent's context window. Only three runtime-owned
prefixes (`[EPISODE …]`, `[BELIEF …]`, `[QUARANTINED]`) distinguished memory text,
and all three were forgeable from content.

**Consequence.** Memory is a persistence layer for injection: any content that
reaches a write path is replayed into every future session, potentially as an
instruction or as metadata that looks runtime-issued.

**Fix.** Every compiled context is wrapped in a `recalled_memory` frame stating
that the content is historical data which cannot authorize tools, change policy or
override instructions, and the package carries a structured `trust` block
(`content_kind`, `authority: none`, `is_instruction: false`,
`may_authorize_tools: false`, `may_change_policy: false`). Every field taken from a
memory row is neutralized: newlines collapse, `<`/`>` are escaped, a leading
bracketed run is escaped on both brackets, a leading role label is escaped. Per
item, the verified provenance and ingestion channel are printed. The frame is
charged against the character budget.

**Regression test.** `tests/test_injection_framing.py` →
`context_is_framed_as_data`, `injection_stays_inert_text`,
`memory_cannot_forge_markup_or_roles`, `memory_cannot_forge_runtime_metadata`,
`authorization_metadata_is_not_content_driven`,
`provenance_travels_into_the_compiled_context`, `limitation_is_documented`.
**Result: 7/7 pass.** Benign payloads only.

**Remaining limitation.** Not solved and not claimed to be. Hungry Hippa preserves
the trust boundary and makes it visible; it cannot guarantee that a given
downstream model ignores hostile text it is shown. Long-form memory text can still
argue with a model in prose. The mitigation is the boundary, the framing and the
operator's ability to inspect and forget — not immunity.

---

## Finding 3 — existence oracle

**Confirmed.** Yes. Untrusted recall returned
`excluded=[{"item": "belief:B-0002", "reason": "other-actor"}]` for a topic matching
a protected memory, and `[]` for a topic matching nothing — plus matched graph
entity names, unfiltered.

**Vulnerable path.** `retrieval._recall()` built `excluded` from `may_read()`
reasons and returned `matched_entities`, both before any identity check.

**Consequence.** An unauthorized caller could ask "does the operator hold a memory
about X" and get a yes/no, learn row ids (sequential, so also how many exist), and
read entity names out of graph memory.

**Fix.** Recall takes the caller's identity. Anyone who is not the owner gets a
single uniform answer — `{"unauthorized": true, "note": …}` — whether one protected
row matched or none did, with no ids, no per-reason counts, no withheld-count and
no entities. The owner keeps the rich diagnostics.

**Regression test.** `tests/test_existence_oracle.py` →
`hit_and_miss_are_indistinguishable`, `no_protected_ids_or_counts_leak`,
`owner_keeps_rich_diagnostics`, `untrusted_own_rows_learn_nothing_else`,
`entity_names_are_not_leaked`. **Result: 5/5 pass.**

**Remaining limitation.** The owner's own view still enumerates exclusions by
design; a caller that can read the token file has the database anyway. Query
*timing* was not measured as a side channel.

---

## Finding 4 — database and backup file permissions

**Confirmed.** Yes: a fresh database was created `0644`, and the previous pass's
backup fix copied the source mode through, so a world-readable database produced a
world-readable backup of every memory.

**Vulnerable path.** `Database.__init__` → `sqlite3.connect(path)` (created with
the process umask); `backup_sqlite()` → `mode = stat.S_IMODE(os.stat(src).st_mode)`;
`observability.export()` → `open(path, "w")`.

**Consequence.** Any local user could read the operator's memory database, its
`-wal`, its migration backups and its exports.

**Fix.** New databases are created `0600` before sqlite opens them; backups are
never wider than `0600` and never wider than their source; exports are created
`0600`. An existing lax file is *reported*, never silently changed:
`Database.file_permissions()` and `hermes living-cortex status` expose `mode`/`lax`
with a remediation hint, and `hermes living-cortex fix-permissions` performs the
explicit change (database, `-wal`, `-shm`, `*.bak`).

**Regression test.** `tests/test_file_permissions.py` →
`new_database_is_owner_only`, `backup_is_never_wider_than_owner_only`,
`implicit_migration_backup_is_private`,
`lax_database_is_reported_not_silently_changed`, `export_file_is_owner_only`,
`fix_permissions_remediates`. **Result: 6/6 pass** (POSIX; skipped with a stated
reason elsewhere).

**Remaining limitation.** This is a permission, not encryption. The database is
plaintext and a process running as the operator reads it. Backups are never pruned,
so an old copy can outlive a deletion. Windows has no POSIX mode bits; the check is
skipped and the OS-level answer is account separation and file ACLs.

**Operator note.** The live database at `~/.hermes/living_cortex.db` was still
`0644` at the end of this pass. It is reported, not changed; one command fixes it.

---

## Finding 5 — self-declared source class / provenance

**Confirmed.** Yes: `source_class` came from the request payload and was stored
verbatim. A caller could write memory wearing `user_explicit` — the highest trust
weight and the winner of contradiction resolution — together with its own
confidence number. No column separated claim from verification.

**Vulnerable path.** `semantic.add_belief(source_class=…)` /
`episodic.remember_episode()` → straight into `source_class`, which
`_SOURCE_PRIORITY` and `default_confidence()` weigh.

**Consequence.** Untrusted or model-authored text could occupy the operator's voice
and outrank the operator's own statements.

**Fix.** Schema v5 adds `claimed_source_class`, `verified_source_class`,
`source_actor` and `ingestion_channel`. The effective `source_class` (what the trust
weighting uses) is channel-derived: `user` provenance may assert an origin; `agent`
provenance is recorded as `agent_reported`; `external` provenance is
`external_source` and stays quarantined. Confidence is capped by the verified class
so a claim cannot carry a user-grade number. The operator attests a memory with
`hermes living-cortex verify <id> --source-class user_explicit`; `why()` and the
audit log expose claim, verified class, actor and channel.

**Regression test.** `tests/test_provenance.py` →
`untrusted_claim_does_not_become_trusted`,
`agent_channel_cannot_promote_its_own_text`, `operator_channel_can_attest`,
`trust_weighting_uses_verified_class`, `provenance_is_inspectable_and_audited`,
`episode_provenance_is_recorded`. **Result: 6/6 pass.** The first two drive the real
MCP handler and the real `cortex` tool.

**Remaining limitation.** The operator channel can still state a false origin; that
is the operator's own terminal, and a human can always type something untrue. The
model's text keeps its claim as a label, so a determined reader can see the
provenance rather than a rewritten history.

---

## Finding 6 — history rewrite / false correction

**Confirmed.** Yes: an untrusted actor contradicted a `user_explicit` belief, the
target flipped to `contradicted`, and the replacement became the active,
recall-visible claim (`conf 0.99`). Nothing about the rewrite required the operator.

**Vulnerable path.** `semantic.contradict()` / `supersede()` — no per-record
authorization; the cluster re-resolved purely on confidence plus source priority.

**Consequence.** A single write could change what the memory runtime says is true,
and the operator's own statement was the thing retired.

**Fix.** A belief is *protected* when it is operator-attested (verified
`user_explicit`) or a high-confidence (`>= 0.90`), non-quarantined canonical fact.
For a protected target: `supersede` from a non-operator channel is refused and
audited as `supersede_denied`; `contradict` from a non-operator channel stores the
claim as a quarantined candidate (audited as `contradict_blocked`) and leaves the
protected row and the cluster untouched. Ordinary rows are unaffected — an
unprotected low-confidence belief can still be superseded by the model. Audit rows
now carry actor and provenance.

**Regression test.** `tests/test_supersession.py` →
`agent_cannot_supersede_operator_fact`,
`agent_contradiction_becomes_quarantined_candidate`,
`high_confidence_canonical_is_protected`,
`untrusted_channel_cannot_touch_trusted_memory`,
`operator_correction_still_works_and_is_attributable`,
`unprotected_memory_can_still_change`, `candidate_cannot_be_promoted_by_content`.
**Result: 7/7 pass.**

**Remaining limitation.** The protection rule is a heuristic with two named
triggers; a protected belief is still editable by the operator, and the operator
can be wrong. Blocked candidates accumulate in quarantine until reviewed —
deliberately, since deleting a claim someone made is worse than showing it — and
there is no automatic review queue beyond `recall --quarantined`.

---

## Finding 7 — resource exhaustion

**Confirmed.** Yes, in part: the per-process call budget resets by starting a new
process; legal-size records accumulate without limit; nothing reported database
size. Measured on HEAD: 300 writes accepted with no cross-process accounting,
380 KB database, no size field in `health()`.

**Vulnerable path.** `mcp_server.CALL_BUDGET` (per process, in memory);
`limits.check_args()` (per request only); no aggregate or persistent accounting.

**Consequence.** Cheap local denial of service and storage abuse: a client loop
that restarts, or simply patience, grows the store until the disk is full;
consolidation then scans more data, and each migration copies it.

**Fix.** Write accounting lives in the database (`write_quota`, one row per
hour-window per actor), so it survives restarts and is per actor. Default 20000
writes/hour, far above normal use; refusals are audited as `write_quota_exceeded`.
Database size is reported in `health()` with a warning threshold (default 512 MiB,
`HUNGRY_HIPPA_MAX_DB_BYTES`) — a warning, not a quota: nothing is deleted, nothing
is refused. Consolidation scan limits become configurable
(`consolidation.max_beliefs_scan`, `max_episodes_scan`) instead of hard-coded.
Graph traversal clamps `hop_limit` to 4. A migration backup refuses to run without
room for a full copy.

**Regression test.** `tests/test_resource_limits.py` →
`write_quota_survives_process_restarts`, `quota_is_per_actor`,
`default_limit_leaves_normal_use_alone`, `database_size_is_visible_and_warned`,
`backup_refuses_without_space`, `graph_traversal_is_bounded`,
`consolidation_scan_caps_are_configurable`. **Result: 7/7 pass** (plus benchmark
notes: 2000 writes in 1.65 s, recall 3.9 ms at 2000 beliefs, database 1.5 MB,
consolidation and backup under 10 ms each on this machine).

**Remaining limitation.** These are local-first guards, not a security boundary. An
attacker with write access to the database can clear the accounting directly. There
are no per-caller quotas on reads, no timeouts on long queries, and no automatic
compaction or backup rotation — a full disk still stops writes, it just says so.

---

## Finding 8 — owner tool / confused deputy

**Confirmed.** Yes: the `cortex` tool runs in-process with owner identity, so a
model call wrote a belief stored as `source_class=user_explicit`, `quarantined=0`,
`actor_id=primary` — identical, in the rendered context, to something the operator
said.

**Vulnerable path.** `__init__.py` plugin → `bind_session(platform, agent_context)`
→ `actor_id = agent_context = "primary"`; `tools.handle()` → `controller` →
`semantic.add_belief()` with the caller's `source_class`.

**Consequence.** A model that had read a hostile web page, issue or dependency
README could write memory that reads as the operator's own statement, or retire one
the operator relies on. Externally sourced text became owner-trusted memory without
any human confirmation.

**Fix.** Two layers, both channel-derived. (1) Provenance: the plugin binds with
owner identity but `agent` provenance, so its writes are `agent_reported` and
confidence-capped. (2) Capabilities: `policy.may_capability()` maps the channel to
`read`, `write_candidate`, `approve`, `correct`, `forget`, `purge`. A model may
read and write candidates; it may not approve (only `hermes living-cortex verify`
does that), may not correct or forget a protected target, and may not purge.
`purge` now requires owner identity *and* an operator channel and is audited as
`purge_denied` when refused.

**Regression test.** `tests/test_confused_deputy.py` →
`capability_table_is_channel_derived`,
`webpage_text_cannot_become_operator_memory`,
`model_cannot_forget_what_the_operator_relies_on`,
`model_can_still_forget_its_own_candidates`, `model_cannot_purge_or_approve`,
`recalled_content_is_not_an_instruction_to_the_tool`.
**Result: 6/6 pass**, driving the real `cortex` tool with benign "fetched page" text.

**Remaining limitation.** The boundary is between channels, not between thoughts: a
model that decides to write memory will write memory, correctly labelled as its own
report. Nothing verifies that the *content* of an operator-channel write is true.
Provenance says where a claim came from, not whether it holds.

---

## Security invariants after this pass

| Invariant | Status | Evidence |
|---|---|---|
| Caller-provided identity cannot create trust | hold | `test_trust_boundary` 6/6 |
| Memory is data, never code | hold | framed rendering; memory text is never executed (nothing `eval`s or `exec`s stored text; `test_security::sql_injection_attempts_are_inert`) |
| Memory is never higher-authority instruction text | hold (boundary only) | `test_injection_framing` 7/7, stated limitation |
| Untrusted callers cannot infer protected existence | hold | `test_existence_oracle` 5/5 |
| Sensitive files are owner-readable only by default | hold | `test_file_permissions` 6/6 |
| Callers cannot self-assign high-trust provenance | hold | `test_provenance` 6/6 |
| Quarantined material cannot supersede trusted facts | hold | `test_supersession` 7/7 |
| Model output alone cannot authorize privileged mutations | hold | `test_confused_deputy` 6/6 |
| Resource guards survive repeated sessions | hold (as far as the architecture allows) | `test_resource_limits` 8/8 |
| Every high-impact mutation is attributable | hold | audit rows carry actor, provenance, reason |
| Existing security tests still pass | hold | quarantine 8/8, MCP 11/11, security 14/14, injection inert, caps enforced |
| Every fixed finding has a regression test | hold | 12 new suites/checks, 15-step `check_all.py` |

## Not fixed, and stated

- Encryption at rest; tamper-evident audit chain; authenticated MCP transport;
  multi-tenant isolation; per-caller read quotas and query timeouts.
- Downstream model behaviour under hostile text (the framing makes the boundary
  visible; it does not compel a model to respect it).
- The live database's current `0644` mode, until the operator runs
  `hermes living-cortex fix-permissions`.
