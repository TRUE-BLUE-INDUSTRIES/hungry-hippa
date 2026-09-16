"""Ingestion: turn provider exports into normalized turns.

Slice 1 is the ChatGPT parser only — no sorter, no reconciler, no evidence
tables, no quarantine handoff, no model extraction. Nothing in this package writes
to the Hungry Hippa database, opens a network connection, or calls a model; the
MCP surface is untouched and still exactly six tools.

Public API::

    from hungry_hippa.ingest import parse_chatgpt_export

    conversations = parse_chatgpt_export("conversations.json")
    for convo in conversations:
        convo.turns                 # every supported textual turn, all branches
        convo.current_path_turn_ids  # the branch the export considered active

The parsers are deliberately independent of the runtime's *behaviour*: the modules
in this package import only the standard library, parsing never opens or writes a
database (a parse succeeds with no store present, and creates none), and nothing
here imports the MCP SDK. Importing the parent package still loads the ordinary
runtime modules, which is why the guarantee is stated as "no database is opened"
rather than "the runtime is never imported".
"""

from __future__ import annotations

from .models import KNOWN_ROLES, NormalizedTurn, ParsedConversation, summarize
from .chatgpt import (
    SOURCE as CHATGPT_SOURCE,
    load_export,
    parse_chatgpt_conversation,
    parse_chatgpt_export,
    parse_chatgpt_payload,
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
]
