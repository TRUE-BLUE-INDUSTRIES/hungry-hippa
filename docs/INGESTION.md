# Historical ingestion

Hungry Hippa ingests provider exports in slices. Slice 1 parses. Slice 2
persists the parse as **raw history**. Later slices extract memories. Raw
history is not memory: canonical conversations and turns live in their own
tables, not in `episodes`.

| Slice | What it does | What it does not do |
|---|---|---|
| 1 — parse | ChatGPT `conversations.json` → `ParsedConversation` | write a database, call a model, filter, classify |
| 2 — persist | store a Layer 1 archive pointer + Layer 2 conversation/turn rows | copy the file into SQLite, write episodes, extract memories, change MCP |
| 3 — CLI write | `ingest chatgpt FILE --apply` persists via the Slice 2 library | extract memories, write episodes/beliefs, mint `user_explicit`, change MCP |
| Hermes | same parse shape + same persist, from a sessions export dir | open `state.db`, extract memories, change MCP, follow symlinks |
| 4 — extract | local LM Studio reads stored turns in small batches and writes quarantined hypotheses | mint `user_explicit`, overwrite existing beliefs, call Grok/Nous, change MCP |
| 5 — reconcile | compare those hypotheses to existing memories; classify; keep contradictions open | mint `user_explicit`, delete Layer 1/2, pick a contradiction winner, change MCP |

The MCP surface is unchanged: still exactly six tools.

---

## Slice 1 — parse

This is the ChatGPT export parser: a provider-neutral sequence of turns. The
sorter, reconciler, quarantine handoff and model extraction are not here.

```python
from hungry_hippa.ingest import parse_chatgpt_export

conversations = parse_chatgpt_export("conversations.json")
for convo in conversations:
    convo.session_id              # the export's conversation id, never regenerated
    convo.title
    convo.turns                   # every supported textual turn, all branches
    convo.current_path_turn_ids   # the branch the export considered active
    convo.warnings                # what the parser refused to guess at
```

Developer dry run (parsing only — it never touches the store):

```bash
hungry-hippa ingest chatgpt ~/Downloads/conversations.json --dry-run
```

```
ChatGPT export parsed
Conversations: 123
Turns: 4,567
Current-path turns: 3,812
Alternate-branch turns: 755
```

Without `--dry-run` **or** `--apply` the command refuses: writes are not the
default. Slice 2 is the persist library; Slice 3 is the CLI flag that calls it.

### The normalized turn

| Field | Meaning |
|---|---|
| `source` | `"chatgpt"` |
| `session_id` | the export's conversation `id` (a positional placeholder plus a warning if the export has none) |
| `session_title` | the conversation title, verbatim |
| `turn_id` | the provider's own node id — never generated |
| `parent_turn_id` | the provider's parent id, which may name a structural node that has no turn |
| `role` | `author.role` as written: `user`, `assistant`, `system`, `tool`, or anything else the provider used |
| `content` | the textual parts, joined with a single newline; code fences, indentation, greetings and whitespace preserved |
| `occurred_at` | `message.create_time` as a float, or `None` when absent, null or non-numeric |
| `branch_path` | root-to-node node ids, including structural nodes |
| `source_metadata` | a small bounded record: `node_id`, `on_current_path`, `message_id`, `author_name`, `content_type`, `unsupported_content_types`, `recipient`, and `model_slug`/`request_id`/`is_visually_hidden_from_conversation` when present |

The raw provider message object is intentionally **not** copied. The export file stays
the source of truth; storing whole provider blobs would make an import expensive for no
parsing benefit. Everything above is either an id, a timestamp, a role or text.

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

### Malformed input

Every one of these becomes a warning on the conversation, never an exception that loses
the rest of it: a node that is not an object, a `message` that is not an object, content
that is not text, `children` that is not a list, a non-string or unknown child id, a
duplicate child id, a node whose `id` field disagrees with its mapping key (the mapping
key wins, because children reference keys), a parent chain that loops, and a conversation
entry that is not an object at all.

### Slice 1 guarantees

- No database is opened or written — a parse succeeds with no store present and creates
  no file, even when `HUNGRY_HIPPA_DB` is set. `chatgpt.py`, `hermes.py` and `models.py`
  import only the standard library. `ingest/__init__.py` does not import the persist
  module.
  (Importing `hungry_hippa.ingest` still executes the parent package's ordinary imports;
  the guarantee is about behaviour, not import isolation.)
- No model calls, no network access, no MCP tools.
- No filtering, classification, deduplication or sorting-for-ingestion.
- Not yet verified against a real ChatGPT export: the fixtures in
  `tests/test_chatgpt_ingest.py` are built from the export format, and no `conversations.json`
  from an actual account was available in the development environment. The parser records
  what it cannot represent rather than failing, which is what makes that limitation
  survivable — but it is a limitation, and it is stated here rather than implied away.

---

## Slice 2 — persist

Schema **v6** adds three tables. Existing v5 databases migrate in place; a
pre-migration `.bak` is written on first open, as with earlier upgrades.
`down_sql` drops only the ingest tables. Episodes, beliefs and evidence are not
touched.

### Layer 1 — raw archive pointer

The export file is **not** copied into SQLite. The row stores:

| Column | Meaning |
|---|---|
| `original_path` | the path that was hashed (absolute) |
| `sha256` | hex digest of the file bytes, hashed in 1 MiB chunks |
| `byte_length` | size in bytes |
| `archived_path` | empty unless the caller asked for an optional copy |

An optional copy into an app-controlled directory is named by the digest, created
`0600`, and refused if that destination is a symlink. Path + hash is enough
without a copy. Unique on `sha256`: the same file is one archive.

Treat exports as hostile: no `eval`/`exec`, no extra files followed out of the
given path, no whole-file slurp just to hash it. JSON parsing is still Slice 1's
`json.load` (the parse already holds the turns in memory).

### Layer 2 — canonical conversations and turns

`ingest_conversations` is keyed on `(source, session_id)`.
`ingest_turns` is keyed on `(source, session_id, turn_id)`.

These are **not** `episodes`. Persist does not write `episodes`, `evidence`,
`beliefs`, or `memory_fts`. A later extraction slice may *read* these rows and
write memories; this slice does not.

### Library API

```python
from hungry_hippa.db import Database
from hungry_hippa.ingest import parse_chatgpt_export
from hungry_hippa.ingest.store import persist_parsed_export

db = Database(path)
conversations = parse_chatgpt_export("conversations.json")
result = persist_parsed_export(db, conversations, source_path="conversations.json")
# result.archive_id, result.turns_inserted, ...
```

`persist_conversation` is the same transaction for one `ParsedConversation`.
`copy_to=` is the optional archive-directory copy.

A persist of one export is **one SQLite transaction**. Turns are
`INSERT OR IGNORE` on `(source, session_id, turn_id)`: first write wins,
re-running the same export is a no-op. Conversation metadata (title, current
path) upserts so a later export of the same session can refresh the active
branch; new turn ids still insert.

### Slice 2 guarantees

- Existing schema v5 databases migrate to v6 without rewriting episode or belief
  ids.
- Persist is transactional and idempotent on `(source, session_id, turn_id)`.
- The ChatGPT parser module remains stdlib-only and does not import the store.
- MCP is still exactly six tools.
- No memories are extracted from the stored turns.

---

## Slice 3 — CLI write path

`--dry-run` remains the safe default. `hungry-hippa ingest chatgpt FILE` with
neither flag **refuses** and does not open the database. `--apply` is required
to persist.

```bash
hungry-hippa ingest chatgpt ~/Downloads/conversations.json --dry-run
hungry-hippa ingest chatgpt ~/Downloads/conversations.json --apply
```

`--apply` parses, then calls `persist_parsed_export`. It writes:

- Layer 1: archive pointer (absolute path, sha256, byte length) plus an
  optional copy next to the database as `ingest_archives/<sha256>` mode `0600`
- Layer 2: `ingest_conversations` and `ingest_turns` (`source=chatgpt`,
  provider ids, timestamps, content; archive sha256 is the file content hash)

It does **not** write `episodes`, `beliefs`, `evidence` or `memory_fts`. It does
not call a model. Imported history is untrusted text: the CLI uses the persist
library directly, not `_controller()`, so it cannot mint `user_explicit`
provenance. A later extraction slice may read these rows; this one does not.

Re-running `--apply` on the same file is a no-op for turns already stored
(`INSERT OR IGNORE` on `(source, session_id, turn_id)`). Malformed
conversations become warnings and do not abort the rest of the file.

Treat the export as hostile: no `eval`/`exec`, leaf symlinks refused
(`O_NOFOLLOW`), extra paths inside the JSON never opened, turn bodies not
printed in logs or CLI output. MCP is still exactly six tools.

---

## Hermes sessions

Hermes live transcripts sit in SQLite (`~/.hermes/state.db`). This adapter does
**not** open that database. It reads an export directory the operator names —
the same shape `hermes sessions export` and `/save json` write, plus the legacy
`{session_id}.jsonl` divert path under `~/.hermes/sessions/` (empty on the
development host when inspected). Personal session files were not copied into
the repo; tests use synthetic fixtures that match the inspected JSON shape.

```python
from hungry_hippa.ingest import parse_hermes_export

conversations = parse_hermes_export("~/exports/hermes-sessions")
```

```bash
hungry-hippa ingest hermes ~/exports/hermes-sessions --dry-run
hungry-hippa ingest hermes ~/exports/hermes-sessions --apply
hungry-hippa ingest hermes ./one_session.jsonl --dry-run
```

Without `--dry-run` or `--apply` the command **refuses**. `--apply` calls
`persist_parsed_export` per session file (Layer 1 archive pointer + optional
`0600` copy; Layer 2 `source=hermes` conversation/turn rows). It does not write
`episodes`, `beliefs`, `evidence`, or `memory_fts`. Turn bodies are not printed.

### What is accepted

| Input | Meaning |
|---|---|
| A directory | regular `.json` / `.jsonl` files under it, recursive, no symlink follow |
| One `.json` or `.jsonl` file | a session snapshot, a JSONL export (one session object per line), or a legacy message-per-line transcript |

Anything else (markdown, HTML, `state.db`, a leaf symlink, a non-file/non-directory) is refused. `sessions.json` (the routing index: `session_key → SessionEntry`, no messages) is skipped. Paths found inside JSON are never opened. A walk never leaves the given root.

Session ids are the provider's (`id` / `session_id`, typically `YYYYMMDD_HHMMSS_<hex>`). Message ids are the export's integer (or string) `id`, stored as text. They are never regenerated. A legacy `{session_id}.jsonl` with no `id` on the session object uses the filename stem — that stem *is* the Hermes session id.

### Normalized turn (`source=hermes`)

Hermes transcripts are a list, not a ChatGPT-style tree. `parent_turn_id` is the previous message's id. `branch_path` is the linear prefix. When a message has `active` set to `0`/`false`, it is kept as a turn and left off `current_path_turn_ids` (the closest analog of an abandoned branch). Tool-call-only assistant messages with no text produce no turn (a warning records that they were there); tool-role messages with text are kept. Tool-call **arguments** are not copied into metadata. Reasoning fields are not ingested as conversation text.

### Known limitations

- Live Hermes history is SQLite. This importer reads files, not `state.db`. To ingest a live profile, export first (`hermes sessions export backup.jsonl` or copy `~/.hermes/sessions/` if JSONL files are present).
- No sibling-branch mapping: regenerations/rewinds appear only when the export includes inactive messages (`active=0`).
- Empty assistant `tool_calls` turns are skipped; the following tool result still points at that structural id as `parent_turn_id`.
- Multimodal parts that are not text (`image_url`, …) are skipped with `unsupported_content_types`.
- Directory `--apply` hashes each session file separately because `persist_parsed_export` takes a file, not a directory.
- Not verified against a copy of the operator's personal sessions (those files must not be committed). Fixtures match the inspected export shape.

The ChatGPT parser is unchanged. MCP is still exactly six tools.

---

## Slice 4 — extract

Layer 3 of historical ingest: stored `ingest_turns` become **candidate memories**. A local LM Studio chat model proposes them; Hungry Hippa stores them as data. Conversation content is hostile: it is never `eval`'d, `exec`'d, or turned into a tool call.

```bash
# Always point at a throwaway or dedicated store. The default path can resolve
# to the live Hermes database; this command refuses to run without HUNGRY_HIPPA_DB
# and refuses the known live stores.
export HUNGRY_HIPPA_DB=/tmp/hh-extract.db

hungry-hippa ingest extract --dry-run
hungry-hippa ingest extract --apply
hungry-hippa ingest extract --apply --source chatgpt --limit 16
```

Without `--dry-run` or `--apply` the command **refuses**. `--dry-run` counts pending turns and does not call a model or write beliefs/episodes (opening the database may apply schema v7 checkpoint tables). `--apply` probes the local chat model first; if it is down, the command exits with an error and writes no job, belief, episode, or evidence rows.

### What is written

| Field | Value |
|---|---|
| `kind` | `hypothesis` (beliefs) |
| `quarantined` | always |
| `claimed_source_class` | `document` if the user stated it, else `agent_inference` |
| `verified_source_class` | `agent_reported` (extraction is model inference, never operator attestation) |
| `ingestion_channel` | `import` |
| `user_explicit` | never minted, even if the model asks |

Every candidate links to immutable `evidence` rows whose `source_ref` names the ingest turn (`kind=ingest_turn`, plus `source` / `session_id` / `turn_id`). Existing active claims are left alone: a light normalized-text heuristic skips duplicates. Full compare-and-classify is Slice 5 (`ingest reconcile`).

### Batching and resume

The loaded chat model (`qwen/qwen3.8-27b`) has an 8192-token context. Extraction never loads the archive into one prompt. Default batches are 4 turns / ~2400 content characters. Schema **v7** adds `ingest_extract_jobs` and `ingest_extract_progress` (per `source, session_id`). Re-running `--apply` continues from the last checkpointed turn. `down_sql` drops only those two tables.

### Local model

Default: `POST http://127.0.0.1:1234/v1/chat/completions` with model `qwen/qwen3.8-27b`. Loopback only; HTTP proxies are ignored so archive text cannot leave the box. Thinking is disabled (`enable_thinking: false`). The system prompt is the constant `EXTRACT_SYSTEM_PROMPT` in `src/hungry_hippa/ingest/extract.py`. Override URL/model with `HUNGRY_HIPPA_EXTRACT_URL` / `HUNGRY_HIPPA_EXTRACT_MODEL` (still must be loopback).

Grok and Nous are not used. The MCP surface is still exactly six tools.

### Known failure modes

- LM Studio down, or `qwen/qwen3.8-27b` not loaded: `--apply` fails clearly; store unchanged (no job).
- This LM Studio build rejects `response_format: json_object` (only `json_schema` or `text`); the extractor omits `response_format` and asks for JSON in the prompt.
- Model returns non-JSON, tool-call payloads, or claims that cite unknown turn ids: the batch is skipped (turns still checkpointed so a poison response cannot loop forever).
- Qwen thinking can swallow `max_tokens` as `reasoning_content` if thinking is re-enabled; this slice sends `enable_thinking: false`.
- Duplicate heuristic is string-level only; Layer 4 (`ingest reconcile`) does the full compare-and-classify.
- `--apply` without `HUNGRY_HIPPA_DB` refuses, because the default discovery path can be the live Hermes store.
- Extracted hypotheses are quarantined, so default recall does not surface them until an operator approves.

---

## Slice 5 — reconcile (Layer 4)

Extract writes candidates. Reconcile compares each quarantined import hypothesis
to memories already in the store and classifies it. Extract stays
"write candidates"; this command is the separate compare step.

```bash
export HUNGRY_HIPPA_DB=/tmp/hh-reconcile.db

hungry-hippa ingest reconcile --dry-run
hungry-hippa ingest reconcile --apply
```

Without `--dry-run` or `--apply` the command **refuses**. `--dry-run` is the
safe default. The command requires `HUNGRY_HIPPA_DB` and refuses the known live
Hermes/Grok stores, same as extract.

### Classes

| Class | Meaning | Apply |
|---|---|---|
| duplicate | same claim, evidence already attached | archive the candidate; keep the existing row |
| reinforcement | same claim, new evidence | attach evidence, nudge confidence, archive the candidate |
| contradiction | opposite polarity or conflicting values | **keep both claims and all evidence**; cross-link; do not pick a winner |
| update | refinement (existing tokens ⊂ candidate tokens) | keep both; `derived_from` records `update_of:` |
| supersession | replacement language (`now`, `moved to`, …) | unprotected: mark old `superseded`, graph `SUPERSEDES` with `valid_from`; protected: leave the existing claim, keep the candidate quarantined |
| low-confidence | too short, or a weak overlap | leave quarantined |
| irrelevant | no meaningful overlap with existing memories | leave quarantined |

Re-running `--apply`, or re-importing / re-extracting the same export, is a
no-op at this layer (`UNIQUE` on the candidate id). Layer 1 archive pointers
and Layer 2 turns are never deleted. Schema **v8** adds
`ingest_reconcile_jobs` and `ingest_reconcile_decisions`; `down_sql` drops
only those two tables.

Library:

```python
from hungry_hippa.ingest.reconcile import classify, reconcile_store, MemoryView

decision = classify(candidate, existing_memories)
result = reconcile_store(db)            # apply
preview = reconcile_store(db, dry_run=True)
```

The classifier is deterministic (token overlap, polarity, replacement cues). It
does not call a model. It does not mint `user_explicit`. MCP is still exactly
six tools. Claim text is not printed by the CLI.
