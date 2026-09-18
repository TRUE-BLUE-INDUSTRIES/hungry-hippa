"""ChatGPT ``conversations.json`` → normalized turns.

Slice 1: parsing only. This module reads a file, walks the export's message tree
and returns :class:`~hungry_hippa.ingest.models.ParsedConversation` values. It
does not write to the memory database, does not call a model, does not filter or
classify anything, and does not touch the network.

Why a tree walk and not a timestamp sort
----------------------------------------
A ChatGPT export is a tree, not a transcript. Regenerating an answer or editing a
prompt creates a *sibling* node, and the abandoned answer stays in ``mapping``
forever. Sorting nodes by ``create_time`` would interleave those siblings and
present a conversation that never happened. So:

* every supported textual node becomes a turn, including abandoned branches;
* each turn keeps ``parent_turn_id`` and a root-to-node ``branch_path``;
* ``current_path_turn_ids`` is computed by walking *backwards* from
  ``conversation.current_node``, which is the branch the export considered active.

Structural nodes (no ``message``, or no textual content) produce no turn but are
still part of every ``branch_path`` that passes through them, so lineage survives.

Tolerated malformations (each becomes a warning on the conversation, never an
exception): a node that is not an object, a non-string or unknown child id, a
duplicate child id, a cycle, a message that is not an object, a content payload
that is not text, a missing or non-numeric timestamp, a conversation with no id.

Supported content
-----------------
Text is taken from ``message.content.parts`` (strings, and objects carrying a
``text`` field), joined with a single newline. Code blocks, greetings and
whitespace inside a part are preserved verbatim: parts are not summarized,
classified, stripped or reflowed. Content types that cannot be represented as
text (``thoughts``, ``reasoning_recap``, ``*_editable_context``, image/asset
pointers, unknown payloads) are skipped and their type names are recorded in the
turn's metadata so nothing silently disappears.
"""

from __future__ import annotations

import json
import logging
import os
import stat
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .models import NormalizedTurn, ParsedConversation

logger = logging.getLogger(__name__)

SOURCE = "chatgpt"

#: Content types that are deliberately not turned into text. Reasoning traces and
#: injected context are provider-internal; representing them as conversation would
#: misrepresent what the human and the assistant actually exchanged.
SKIPPED_CONTENT_TYPES = frozenset({
    "thoughts",
    "reasoning_recap",
    "model_editable_context",
    "user_editable_context",
    "system_error",
    "tether_quote",
    "tether_browsing_display",
})

#: Separator used when a message has several textual parts. A newline is the least
#: surprising join: it neither injects spaces into code nor glues lines together.
PART_SEPARATOR = "\n"


# --------------------------------------------------------------------- loading

def resolve_export_path(path: "os.PathLike[str] | str") -> str:
    """Return a regular-file path, refusing a leaf symlink or a non-file.

    Export files are hostile. The operator names one file; we do not follow a
    symlink leaf (escape to another path) and we do not open directories,
    devices or FIFOs. ``..`` is resolved by ``abspath`` so the name we open is
    the canonical file, not a traversal string. Extra paths inside the JSON are
    never opened.
    """
    given = os.fspath(path)
    if not given or "\x00" in given:
        raise ValueError("invalid export path")
    absolute = os.path.abspath(os.path.expanduser(given))
    try:
        st = os.lstat(absolute)
    except OSError:
        raise FileNotFoundError(absolute) from None
    if stat.S_ISLNK(st.st_mode):
        raise OSError("refusing to follow a symlink export path")
    if stat.S_ISDIR(st.st_mode):
        raise IsADirectoryError(absolute)
    if not stat.S_ISREG(st.st_mode):
        raise OSError("export path is not a regular file")
    return absolute


def load_export(path: "os.PathLike[str] | str") -> Any:
    """Load an export file as JSON. Raises on unreadable or invalid JSON.

    Opens with ``O_NOFOLLOW`` so a leaf symlink swapped in after the path check
    is still refused. Does not ``eval``/``exec`` the file.
    """
    resolved = resolve_export_path(path)
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(resolved, flags)
    try:
        with os.fdopen(fd, "r", encoding="utf-8") as fh:
            fd = -1
            return json.load(fh)
    finally:
        if fd >= 0:
            os.close(fd)


def parse_chatgpt_export(path: "os.PathLike[str] | str") -> List[ParsedConversation]:
    """Parse a ChatGPT ``conversations.json`` file into normalized conversations.

    The file is either a JSON array of conversations (what ChatGPT exports) or an
    object with a ``conversations`` array. Order follows the file, so repeated
    runs on the same export produce the same result. One malformed conversation
    becomes warnings, not a failed file.
    """
    return parse_chatgpt_payload(load_export(path))


def parse_chatgpt_payload(payload: Any) -> List[ParsedConversation]:
    """Parse an already-decoded export payload.

    A conversation that raises is recorded as a warning and skipped; the rest
    of the file still parses. Logs carry the conversation index and exception
    type, never turn text.
    """
    entries = _conversation_entries(payload)
    conversations: List[ParsedConversation] = []
    for i, entry in enumerate(entries):
        try:
            conversations.append(parse_chatgpt_conversation(entry, index=i))
        except Exception as e:  # noqa: BLE001 — hostile export; isolate one entry
            logger.warning("conversation %s skipped (%s)", i, type(e).__name__)
            conversations.append(ParsedConversation(
                source=SOURCE,
                session_id=f"{SOURCE}-conversation-{i}",
                title=None,
                warnings=(f"conversation {i} failed to parse "
                          f"({type(e).__name__}); skipped",),
            ))
    return conversations


def _conversation_entries(payload: Any) -> List[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        inner = payload.get("conversations")
        if isinstance(inner, list):
            return inner
        # A single conversation object is a valid convenience input.
        if "mapping" in payload:
            return [payload]
    return []


# ---------------------------------------------------------------- one conversation

def parse_chatgpt_conversation(entry: Any, *, index: int = 0) -> ParsedConversation:
    """Parse one conversation object from the export.

    ``index`` is only used to build a deterministic, clearly-synthetic session id
    when the export itself provides none.
    """
    warnings: List[str] = []

    if not isinstance(entry, dict):
        return ParsedConversation(
            source=SOURCE, session_id=f"{SOURCE}-conversation-{index}", title=None,
            warnings=(f"conversation {index} is not an object "
                      f"({type(entry).__name__}); nothing could be parsed",),
        )

    raw_id = entry.get("id")
    session_id = raw_id if isinstance(raw_id, str) and raw_id else ""
    if not session_id:
        session_id = f"{SOURCE}-conversation-{index}"
        warnings.append("conversation has no id; using its position in the export")

    title = entry.get("title")
    if title is not None and not isinstance(title, str):
        warnings.append(f"conversation title is {type(title).__name__}; kept as text")
        title = str(title)

    nodes = _collect_nodes(entry.get("mapping"), warnings)
    children = {nid: _children_of(nid, node, nodes, warnings)
                for nid, node in nodes.items()}
    order = _traversal_order(nodes, children, warnings)
    path_cache: Dict[str, Tuple[str, ...]] = {}

    current_node = entry.get("current_node")
    current_node_ids = _active_node_ids(nodes, current_node, warnings)

    # A node with no message (or no usable text) is structural: no turn, but its
    # id stays in every branch_path that runs through it.
    turns: List[NormalizedTurn] = []
    for nid in order:
        node = nodes[nid]
        message = node.get("message")
        if message is None:
            continue
        if not isinstance(message, dict):
            warnings.append(f"node {nid}: message is {type(message).__name__}, "
                            "not an object; no turn produced")
            continue
        text, content_type, unsupported = _extract_text(message.get("content"))
        if not text.strip():
            if content_type or unsupported:
                warnings.append(
                    f"node {nid}: content type "
                    f"{content_type or unsupported[0]!r} has no textual form; "
                    "no turn produced")
            continue

        turns.append(NormalizedTurn(
            source=SOURCE,
            session_id=session_id,
            session_title=title,
            turn_id=nid,
            parent_turn_id=_parent_of(nid, nodes),
            role=_role_of(message),
            content=text,
            occurred_at=_timestamp_of(nid, message, warnings),
            branch_path=_branch_path(nid, nodes, path_cache, warnings),
            source_metadata=_turn_metadata(nid, message, content_type, unsupported,
                                           current_node_ids),
        ))

    turn_ids = {t.turn_id for t in turns}
    current_turn_ids = tuple(n for n in current_node_ids if n in turn_ids)

    return ParsedConversation(
        source=SOURCE,
        session_id=session_id,
        title=title,
        turns=tuple(turns),
        current_path_turn_ids=current_turn_ids,
        current_path_node_ids=current_node_ids,
        current_node=current_node if isinstance(current_node, str) else None,
        created_at=_as_time(entry.get("create_time")),
        updated_at=_as_time(entry.get("update_time")),
        warnings=tuple(warnings),
        source_metadata={"node_count": len(nodes), "root_count":
                         sum(1 for nid in nodes if _parent_of(nid, nodes) is None)},
    )


# ------------------------------------------------------------------ tree helpers

def _collect_nodes(mapping: Any, warnings: List[str]) -> Dict[str, Dict[str, Any]]:
    """Index the mapping by node id.

    The mapping key is authoritative. Where a node repeats a *different* id in its
    own ``id`` field the discrepancy is recorded (and the key wins), which is the
    deterministic choice: children arrays reference mapping keys.
    """
    if not isinstance(mapping, dict):
        warnings.append(f"conversation mapping is {type(mapping).__name__}, not an "
                        "object; no turns produced")
        return {}
    nodes: Dict[str, Dict[str, Any]] = {}
    for key, raw in mapping.items():
        if not isinstance(raw, dict):
            warnings.append(f"node {key!r} is {type(raw).__name__}, not an object; "
                            "skipped")
            continue
        declared = raw.get("id")
        if isinstance(declared, str) and declared and declared != key:
            warnings.append(f"node {key!r} declares a different id {declared!r}; "
                            "using the mapping key")
        nodes[str(key)] = raw
    return nodes


def _parent_of(nid: str, nodes: Dict[str, Dict[str, Any]]) -> Optional[str]:
    parent = nodes.get(nid, {}).get("parent")
    if isinstance(parent, str) and parent in nodes:
        return parent
    return None


def _children_of(nid: str, node: Dict[str, Any], nodes: Dict[str, Dict[str, Any]],
                 warnings: List[str]) -> List[str]:
    raw = node.get("children")
    if raw is None:
        return []
    if not isinstance(raw, list):
        warnings.append(f"node {nid}: children is {type(raw).__name__}, not a list; "
                        "treated as no children")
        return []
    out: List[str] = []
    seen: set = set()
    for child in raw:
        if not isinstance(child, str):
            warnings.append(f"node {nid}: non-string child {child!r}; skipped")
            continue
        if child in seen:
            warnings.append(f"node {nid}: duplicate child {child!r}; kept once")
            continue
        if child not in nodes:
            warnings.append(f"node {nid}: child {child!r} is not in the mapping; "
                            "skipped")
            continue
        seen.add(child)
        out.append(child)
    return out


def _roots(nodes: Dict[str, Dict[str, Any]],
           children: Dict[str, List[str]]) -> List[str]:
    """Roots first, in the export's own child order where it is known.

    A node is a root when it has no resolvable parent, or when its declared parent
    is not in the mapping (a partial export). Sorting is by (timestamp, id) so the
    result never depends on dict iteration order.
    """
    roots = [nid for nid in nodes if _parent_of(nid, nodes) is None]
    return sorted(roots, key=lambda nid: (_node_sort_time(nodes[nid]), nid))


def _node_sort_time(node: Dict[str, Any]) -> float:
    message = node.get("message")
    raw = message.get("create_time") if isinstance(message, dict) else None
    value = _as_time(raw)
    return float("inf") if value is None else value


def _traversal_order(nodes: Dict[str, Dict[str, Any]],
                     children: Dict[str, List[str]],
                     warnings: List[str]) -> List[str]:
    """Depth-first order over the export's own sibling order.

    Depth-first (rather than breadth-first or time-sorted) keeps a branch's turns
    together: the regenerated answer appears immediately after the answer it
    replaced, so a reader can see the fork. Siblings keep the order the export's
    ``children`` array gives them — that array is the provider's own chronology
    and, unlike ``create_time``, it exists for every node. Timestamps are used only
    where no array order exists (choosing between roots, and for nodes that
    reference a parent missing from the export), with the node id as the final
    tie-break, so the result is reproducible for a given export.
    """
    order: List[str] = []
    visited: set = set()

    def walk(nid: str) -> None:
        if nid in visited:
            warnings.append(f"node {nid!r} is reachable more than once "
                            f"(cycle or shared child); walked once")
            return
        visited.add(nid)
        order.append(nid)
        for child in children.get(nid, []):
            walk(child)

    for root in _roots(nodes, children):
        walk(root)

    # Defensive: nodes unreachable from any root (cycles) still get parsed, in a
    # deterministic order, instead of vanishing from the import.
    leftovers = sorted((nid for nid in nodes if nid not in visited),
                       key=lambda nid: (_node_sort_time(nodes[nid]), nid))
    if leftovers:
        warnings.append(f"{len(leftovers)} node(s) unreachable from any root; "
                        "parsed in id order")
        for nid in leftovers:
            walk(nid)
    return order


def _branch_path(nid: str, nodes: Dict[str, Dict[str, Any]],
                 cache: Dict[str, Tuple[str, ...]],
                 warnings: List[str]) -> Tuple[str, ...]:
    """Root-to-node lineage, walking through structural nodes."""
    if nid in cache:
        return cache[nid]
    chain: List[str] = []
    seen: set = set()
    cur: Optional[str] = nid
    while cur and cur not in seen:
        seen.add(cur)
        chain.append(cur)
        cur = _parent_of(cur, nodes)
    if cur is not None and cur in seen:
        warnings.append(f"node {nid}: parent chain loops at {cur!r}; path truncated")
    path = tuple(reversed(chain))
    cache[nid] = path
    return path


def _active_node_ids(nodes: Dict[str, Dict[str, Any]], current_node: Any,
                     warnings: List[str]) -> Tuple[str, ...]:
    """The export's active branch: walk backwards from ``current_node``.

    Structural nodes are included here (they are part of the visible path); the
    turns-only subset is derived from this in ``parse_chatgpt_conversation``.
    """
    if not isinstance(current_node, str) or not current_node:
        if current_node is not None:
            warnings.append(f"current_node is {type(current_node).__name__}, "
                            "not a node id; no active branch resolved")
        return ()
    if current_node not in nodes:
        warnings.append(f"current_node {current_node!r} is not in the mapping; "
                        "no active branch resolved")
        return ()
    chain: List[str] = []
    seen: set = set()
    cur: Optional[str] = current_node
    while cur and cur not in seen:
        seen.add(cur)
        chain.append(cur)
        cur = _parent_of(cur, nodes)
    if cur is not None and cur in seen:
        warnings.append(f"active branch loops at {cur!r}; path truncated")
    return tuple(reversed(chain))


# ---------------------------------------------------------------- message details

def _extract_text(content: Any) -> Tuple[str, str, List[str]]:
    """Return ``(text, content_type, unsupported_type_names)``.

    Never raises: an unrecognised payload yields no text plus the type name that
    was encountered, so the caller can record it and move on.
    """
    if content is None:
        return "", "", []
    if isinstance(content, str):          # tolerated shorthand
        return content, "text", []
    if not isinstance(content, dict):
        return "", "", [f"<{type(content).__name__}>"]

    content_type = content.get("content_type") or content.get("type") or ""
    content_type = str(content_type).strip()

    if content_type in SKIPPED_CONTENT_TYPES:
        # Reasoning traces and injected context are not conversation; the type is
        # reported so the caller can record that something was there.
        return "", content_type, [content_type]

    fragments: List[str] = []
    unsupported: List[str] = []

    parts = content.get("parts")
    if isinstance(parts, list):
        for part in parts:
            if part is None:
                continue
            if isinstance(part, str):
                fragments.append(part)
                continue
            if isinstance(part, dict):
                text = part.get("text")
                if isinstance(text, str):
                    fragments.append(text)
                    continue
                marker = part.get("content_type") or part.get("type")
                unsupported.append(str(marker or "<dict-part>"))
                continue
            unsupported.append(f"<{type(part).__name__}>")
    elif isinstance(parts, str):          # tolerated shorthand
        fragments.append(parts)

    # Some content types carry a single ``text`` field instead of ``parts``
    # (``code``, ``execution_output``), and keeping it is what makes code blocks
    # survivable.
    if not fragments and isinstance(content.get("text"), str):
        fragments.append(content["text"])

    return PART_SEPARATOR.join(fragments), content_type, unsupported


def _role_of(message: Dict[str, Any]) -> str:
    author = message.get("author")
    if isinstance(author, dict):
        role = author.get("role")
        if isinstance(role, str) and role.strip():
            return role.strip()
    return "unknown"


def _timestamp_of(nid: str, message: Dict[str, Any],
                  warnings: List[str]) -> Optional[float]:
    value = _as_time(message.get("create_time"))
    if value is None and message.get("create_time") is not None:
        warnings.append(f"node {nid}: create_time "
                        f"{message.get('create_time')!r} is not a number; "
                        "occurred_at left empty")
    return value


def _as_time(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except (TypeError, ValueError):
            return None
    return None


def _turn_metadata(nid: str, message: Dict[str, Any], content_type: str,
                   unsupported: Sequence[str],
                   current_node_ids: Tuple[str, ...]) -> Dict[str, Any]:
    """A small, bounded provider-specific record.

    The raw message object is deliberately *not* copied: the export file stays the
    source of truth, and keeping whole provider blobs here would make an import
    expensive to store for no parsing benefit.
    """
    meta: Dict[str, Any] = {"node_id": nid, "on_current_path": nid in current_node_ids}
    message_id = message.get("id")
    if isinstance(message_id, str) and message_id:
        meta["message_id"] = message_id
    author = message.get("author")
    if isinstance(author, dict):
        name = author.get("name")
        if isinstance(name, str) and name:
            meta["author_name"] = name
        if author.get("role") == "assistant" and author.get("metadata"):
            meta["author_metadata"] = author.get("metadata")
    if content_type:
        meta["content_type"] = content_type
    if unsupported:
        meta["unsupported_content_types"] = sorted(set(unsupported))
    recipient = message.get("recipient")
    if isinstance(recipient, str) and recipient and recipient != "all":
        meta["recipient"] = recipient
    inner = message.get("metadata")
    if isinstance(inner, dict):
        for key in ("model_slug", "resolved_model_slug", "request_id",
                    "is_visually_hidden_from_conversation"):
            if inner.get(key) is not None:
                meta[key] = inner[key]
    return meta
