"""Ingestion: turn provider exports into normalized turns, then persist them.

Slice 1 is the ChatGPT parser: lossless, stdlib-only, no database. Slice 2
persists those turns as raw history (archive pointer + canonical conversation
and turn tables). Slice 3 is the CLI write path (`hungry-hippa ingest chatgpt
FILE --apply`). Nothing here extracts memories, writes episodes, opens a
network connection, or calls a model; the MCP surface is untouched and still
exactly six tools.

Parse public API::

    from hungry_hippa.ingest import parse_chatgpt_export

    conversations = parse_chatgpt_export("conversations.json")
    for convo in conversations:
        convo.turns                 # every supported textual turn, all branches
        convo.current_path_turn_ids  # the branch the export considered active

Persist::

    from hungry_hippa.ingest.store import persist_parsed_export

The parsers stay independent of the runtime's *behaviour*: ``chatgpt.py`` and
``models.py`` import only the standard library, parsing never opens or writes a
database (a parse succeeds with no store present, and creates none), and nothing
in the parse path imports the MCP SDK. ``store.py`` is the only module here that
talks to SQLite, and it is not imported by this package init, so
``from hungry_hippa.ingest import parse_chatgpt_export`` still does not open a
store. Importing the parent package still loads the ordinary runtime modules,
which is why the parse guarantee is stated as "no database is opened" rather
than "the runtime is never imported".
"""

from __future__ import annotations

from .models import KNOWN_ROLES, NormalizedTurn, ParsedConversation, summarize
from .chatgpt import (
    SOURCE as CHATGPT_SOURCE,
    load_export,
    parse_chatgpt_conversation,
    parse_chatgpt_export,
    parse_chatgpt_payload,
    resolve_export_path,
)

__all__ = [
    "NormalizedTurn",
    "ParsedConversation",
    "KNOWN_ROLES",
    "summarize",
    "CHATGPT_SOURCE",
    "load_export",
    "parse_chatgpt_export",
    "parse_chatgpt_payload",
    "parse_chatgpt_conversation",
    "resolve_export_path",
]
