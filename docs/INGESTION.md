# Historical ingestion — Slice 1 (ChatGPT export parser)

This document covers **Slice 1 only**: parsing a ChatGPT `conversations.json` export
into a provider-neutral sequence of turns. The sorter, reconciler, evidence tables,
quarantine handoff and model extraction are deliberately not here yet, and this slice
writes nothing to the memory database.

## What it does

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

Without `--dry-run` the command refuses, because there is no ingestion step yet to run.

## The normalized turn

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

## Branches

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

## Content handling

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

## Malformed input

Every one of these becomes a warning on the conversation, never an exception that loses
the rest of it: a node that is not an object, a `message` that is not an object, content
that is not text, `children` that is not a list, a non-string or unknown child id, a
duplicate child id, a node whose `id` field disagrees with its mapping key (the mapping
key wins, because children reference keys), a parent chain that loops, and a conversation
entry that is not an object at all.

## Guarantees and non-guarantees

- No database is opened or written — a parse succeeds with no store present and creates
  no file, even when `HUNGRY_HIPPA_DB` is set. The `ingest` package imports only the
  standard library. (Importing `hungry_hippa.ingest` still executes the parent package's
  ordinary imports; the guarantee is about behaviour, not import isolation.)
- No model calls, no network access, no MCP tools. The MCP surface is unchanged at exactly
  six tools.
- No filtering, classification, deduplication or sorting-for-ingestion: that is the next
  slice's job, and doing it here would make it invisible.
- Not yet verified against a real ChatGPT export: the fixtures in
  `tests/test_chatgpt_ingest.py` are built from the export format, and no `conversations.json`
  from an actual account was available in the development environment. The parser records
  what it cannot represent rather than failing, which is what makes that limitation
  survivable — but it is a limitation, and it is stated here rather than implied away.
