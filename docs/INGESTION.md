# Historical conversation ingestion

This branch adds safe ChatGPT JSON import to the released parser. It preserves
original bytes and canonical conversations separately from derived memory.
Importing does **not** create beliefs, episodes, embeddings or recall results.
Model extraction and additional provider adapters remain follow-up work.

### Maintenance-branch extraction safety

The integrated `automation/hh-maintenance` extractor refuses any batch containing
an LM Studio prompt body over 800 characters (after existing NUL removal), rather
than sending only a prefix and marking the whole turn processed. Exactly 800
characters are accepted. Failure occurs before the completion POST; the job is
failed and the entire refused batch remains pending. Earlier successful batches
stay checkpointed. Canonical source text is not modified. Dry-run remains a
pending-count preview, not a prompt-size validation.

Lossless chunking is not implemented: retrying the same oversized turn still
fails. Do not shorten canonical history or clear checkpoints as a workaround.
Previously checkpointed truncated turns are not automatically repaired. Malformed
response envelopes also fail without advancing progress. Non-object candidate
members (including null, strings, numbers and arrays) now reject the entire batch,
even when mixed with valid candidates, leaving its turns pending for retry.
Supplied `turn_ids` must be a list of strings: null, scalar/object containers and
non-string members reject the entire batch before content filtering. Missing/empty
citations still yield no candidate; unknown IDs are filtered and duplicates removed.
Supplied `type`, `claim`, `context`, `user_request`, `result` and `source_class`
fields must be strings, including on candidates that content filters would discard.
Nulls, booleans, numbers, arrays and objects reject the batch instead of becoming
coerced text or a successful empty extraction. Missing fields and empty strings
retain their existing defaults/fallbacks; source-class remapping and control-text
filtering are unchanged.

### Atomic extraction persistence (2026-09-21)

Each completed model batch persists its evidence, quarantined candidates, evidence
links, FTS/audit writes, checkpoint and job counts in one SQLite transaction. SQL
failures or candidate write/quota refusals roll back that batch, leaving its turns
pending. Earlier committed batches survive and can be resumed without repeating
them. Job creation must succeed before batch persistence; missing candidate/evidence
rows or links and zero-row checkpoint/job updates are refused rather than counted.
Model calls run outside the SQLite writer transaction. Standalone database callers
retain their existing error-handling behavior; no schema or trust promotion changed.

Fault-injection coverage uses invented stores and checks both SQL aborts and silent
insert suppression. This does not repair historical partial writes or provide
lossless oversized-turn chunking. Failed-job status reporting remains best-effort
if the database itself cannot accept writes.

### Overlapping extraction jobs (2026-09-25)

Before writing a batch, extraction rechecks that source/session's progress under
SQLite's writer lock. If another job already processed any turn in the batch, the
stale batch is refused and its job fails with `extraction progress changed`.
No stale candidates/evidence are written and newer progress cannot be overwritten.
Earlier successful batches from either job remain committed. Retry the extraction
command to reload the remaining pending turns; do not clear checkpoints.

Model requests still run outside the writer lock and may run redundantly. This is
not a job scheduler, a global cross-conversation claim-deduplication guarantee, or
a repair for duplicates created by older versions. Independent sessions can still
progress. Six controlled cross-process cases cover beliefs/episodes and equal,
shorter and longer overlapping batches, with fresh CLI pending counts and retries.


## Operator workflow

Install from this branch in a virtual environment. Choose a new database for the
first import; an existing database is backed up before schema migration.

```bash
hungry-hippa ingest chatgpt /path/to/conversations.json --dry-run
hungry-hippa ingest chatgpt /path/to/conversations.json --apply --db /path/to/import.db
hungry-hippa ingest verify DIGEST_PRINTED_BY_IMPORT --db /path/to/import.db
hungry-hippa ingest show CONVERSATION_ID --db /path/to/import.db
HUNGRY_HIPPA_DB=/path/to/import.db hungry-hippa backup --dir /path/to/backups --keep 0
```

`--dry-run` does not open a database. Applying requires `--apply` and an explicit
`--db` or `HUNGRY_HIPPA_DB`; it never discovers a legacy store implicitly. The
import summary prints counts, destination and digest, not conversation bodies.
`show` deliberately displays the conversation as JSON with archive references;
its contents are untrusted historical data, including claimed roles/identities.
`verify` checks source hashes, conversation snapshots, turn content/lineage and
archive membership without printing message content. It detects accidental
corruption, not a malicious same-user process that can rewrite data and hashes.

Only unpacked ChatGPT JSON is accepted. ZIP/HTML/text files are not executed,
rendered or extracted. Manually export and decompress through the provider's
normal tools; there is no archive unpacker in this path.

## Evidence and storage

Schema v6 introduces `ingest_archives`, `ingest_conversations`, and
`ingest_turns`. Schema v7 adds `ingest_archive_bytes`, `ingest_snapshots`, and
`ingest_turn_sources`. It preserves exact source bytes as a BLOB keyed through
the archive digest and immutable per-export conversation/turn membership.
These tables are separate from `evidence`, `beliefs`, `episodes`, and memory FTS.
Provider metadata cannot mint operator-verified provenance.

The file is opened as a bounded regular-file snapshot. The same immutable bytes
are parsed, hashed, validated against normalized rows and transactionally stored.
The source can be moved or removed after a successful verified import without
losing the original evidence. SQLite backups contain the bytes and provenance.
The optional library `copy_to` makes a redundant 0600 file in a private directory;
it is not needed by the CLI or for backup recovery.

Identical archives are no-ops, including the audit log and current-branch view.
A different export of a session may add turns and update its latest-imported
branch view; every export retains its own snapshot. Reusing a turn identity with
changed text, role, timestamp, parent or lineage rejects the entire transaction.
There is no silent first-write-wins loss or automatic contradiction averaging.
Reimporting an already-seen older archive does not roll back the current view.
Conversation IDs missing from the provider receive a content-derived digest ID;
changing that idless conversation creates a separate identity, not an inferred
continuation. Duplicate session IDs or duplicate JSON keys are ambiguous and
refused. Provider identifiers and dates are claims, not authenticated metadata.

Existing v6 rows acquire no invented provenance on upgrade. They remain visible,
but `verify` refuses pointer-only archives until the original bytes are reimported
and match their canonical rows. No live store is modified by development tests.
Migration down scripts exist; execute them only on disposable copies or after a
verified backup because dropping import tables removes imported history.

## Supported normalization

The provider-neutral frozen dataclasses in `ingest/models.py` preserve roles,
source/session/turn IDs, parents, timestamps, branch paths and source metadata.
Unsupported content remains recoverable in the exact raw export even when it
cannot become a text turn. Conversation text never becomes an instruction.

### Branches

A ChatGPT export is a tree. Regenerating an answer or editing a prompt adds a *sibling*
node and leaves the abandoned one in `mapping`. Sorting nodes by `create_time` would
interleave those siblings into a conversation that never happened, so the parser does
not sort them:

- **`turns`** — depth-first over the export's own `children` arrays (which exist for
  every node, unlike `create_time`), so a fork's branches stay together and a branch's
  turns stay contiguous. Timestamps are used only to order multiple roots and nodes
  whose parent is missing from the export, with the node id as the final tie-break.
- **`current_path_node_ids`** — produced by walking *backwards* from
  `conversation.current_node` to the root, then reversing. Structural nodes are
  included: they are part of the visible path.
- **`current_path_turn_ids`** — the subset of that path that has textual turns, in
  root-to-current order. `current_path_turns` gives those as objects,
  `alternate_branch_turns` gives everything else.

Given

```
root -> user A -> assistant B1        (regenerated away)
                -> assistant B2 -> user C     (kept)
current_node = C
```

the parser returns four turns including `B1`, and `current_path_turn_ids` is
`(A, B2, C)`. `B1` is retained as branch evidence rather than silently discarded, and
`B1.source_metadata["on_current_path"]` is `False`.

### Content handling

Taken as text: `parts` entries that are strings or objects with a `text` field, plus the
single `text` field used by `code` and `execution_output`. Multiple parts join with one
newline; nothing is summarized, classified, stripped or reflowed.

Skipped, with the type recorded in `source_metadata["unsupported_content_types"]` and (for
whole messages) a note in `conversation.warnings`: `thoughts`, `reasoning_recap`,
`model_editable_context`, `user_editable_context`, `system_error`, `tether_quote`,
`tether_browsing_display`, image/asset pointers and any unknown payload. Reasoning traces
and injected context are provider-internal; representing them as conversation would
misrepresent what was exchanged. A multimodal message keeps its text parts and reports the
pointer it could not represent.

## Input limits and failures

Admission limits are explicit constants in `ingest/chatgpt.py`:

| Resource | Limit |
|---|---:|
| File bytes / decoded text budget | 64 MiB |
| JSON nesting | 64 |
| JSON values/keys / admission item budget | 1,000,000 |
| Conversations | 10,000 |
| Mapping nodes | 100,000 total; 20,000 per conversation |
| Branch depth | 2,048 |
| Expanded lineage | 1,000,000 entries and 64 MiB of ID text |
| Identifier length | 512 characters |

Deep linear conversations expand quadratically in this canonical representation;
the lineage budget can reject one before the depth limit. Rejection is explicit,
never a successful empty import. Split oversized exports by whole conversation;
a future streaming representation may lift these limits after benchmarking.
JSON nesting is checked before decoding. Non-finite numbers, unpaired Unicode,
unsupported top-level shapes and malformed conversation envelopes are rejected.
Individual malformed nodes/content can still produce warnings while the source
bytes retain the complete input. Iterative traversal avoids Python recursion loss.

Imports also enforce the existing `HUNGRY_HIPPA_MAX_DB_BYTES` value as a size
budget (default 512 MiB), using a conservative preflight and actual SQLite page
count inside a serialized transaction. Failed imports roll back all import rows.
The runtime's separate general size warning is unchanged. These are bounded
resource controls, not a sandbox or per-client quota. Stores and backups are
plaintext; see [SECURITY.md](../SECURITY.md).

## Library use

```python
from hungry_hippa.db import Database
from hungry_hippa.ingest.chatgpt import read_export_bytes, parse_chatgpt_bytes
from hungry_hippa.ingest.store import persist_parsed_export, verify_archive

raw = read_export_bytes("conversations.json")
conversations = parse_chatgpt_bytes(raw)
db = Database("import.db")
result = persist_parsed_export(db, conversations, source_bytes=raw)
assert result.ok, result.error
assert verify_archive(db, result.sha256)["ok"]
```

The compatibility `parse_chatgpt_export` and `persist_parsed_export(source_path=)`
APIs remain. Persistence reparses the source to ensure caller-supplied canonical
rows match it; a fabricated archive pointer cannot support invented turns.

## Validation and next work

`test_chatgpt_ingest.py`, `test_ingest_store.py`, `test_ingest_integrity.py`, and
`test_migration.py` cover parsing, repeat imports, hostile files, atomic refusal,
multiple archive provenance, tamper detection and backup recovery. The
[ingestion benchmark](../BENCHMARKS.md) uses synthetic data, not private exports.
Real-account export diversity and extraction quality remain unmeasured.

The unmerged extraction/reconciliation prototypes must address response failure
checkpointing, truncated prompts and unapproved confidence/supersession changes
before integration. Their schema versions must be rebased onto this branch's v7;
do not mix incompatible experimental migration histories in one database.
