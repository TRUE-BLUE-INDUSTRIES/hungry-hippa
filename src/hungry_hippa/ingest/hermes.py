"""Hermes session transcripts → normalized turns.

Parsing only. This module reads a directory of Hermes session files (or one
allowed ``.json`` / ``.jsonl`` file) and returns
:class:`~hungry_hippa.ingest.models.ParsedConversation` values. It does not
write to the memory database, does not call a model, does not filter or
classify anything, and does not touch the network.

Inspected layout (this host, 2026-09-18)
----------------------------------------
Live Hermes transcripts are in SQLite (``~/.hermes/state.db``: ``sessions`` +
``messages``). ``~/.hermes/sessions/`` exists but held no files: the JSONL
transcript dir is legacy / divert-path (``{session_id}.jsonl``, one message
object per line). ``hermes sessions export`` writes JSONL with one full
session object per line (``id``, ``title``, ``started_at``, ``messages``).
``/save json`` writes a pretty-printed snapshot
(``hermes_session_{id}.json``). Session ids look like ``YYYYMMDD_HHMMSS_<hex>``.
Messages have integer ``id``, ``role``, ``content`` (string or list of parts),
``timestamp``, and optionally ``tool_name`` / ``tool_calls`` / ``active``.

This adapter reads an **export directory** (or one session file). It does not
open ``state.db``, does not scan ``~/.hermes`` unless that path was given, and
never follows extra paths found inside JSON.

Supported inputs
----------------
* A directory: regular ``.json`` / ``.jsonl`` files under it (recursive, no
  symlink follow). ``sessions.json`` (routing index) is skipped.
* One allowed session file: ``.json`` or ``.jsonl`` only.

A session object is a dict with a ``messages`` list (or ``segments`` of those).
A JSONL file is either session-per-line or message-per-line (legacy
``{session_id}.jsonl``; session id is the filename stem — the provider's id,
not a generated one).

Hermes transcripts are linear. There is no ChatGPT-style sibling mapping.
When a message carries ``active is 0/false``, it is kept as a turn and left
off ``current_path_turn_ids`` (the closest analog of an abandoned branch).
Tool-call-only assistant messages with no text produce no turn; tool-role
messages with text are kept. Reasoning fields are not copied into content.

Malformed files in a directory become warnings, not a failed walk. Provider
session ids and message ids are preserved; missing session ids fall back to
the filename stem, then a positional placeholder plus a warning.
"""

from __future__ import annotations

import json
import logging
import os
import stat
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .models import NormalizedTurn, ParsedConversation

logger = logging.getLogger(__name__)

SOURCE = "hermes"

#: Part types that are not conversation text (pointers, reasoning blobs).
SKIPPED_PART_TYPES = frozenset({
    "image_url",
    "image",
    "input_image",
    "image_asset_pointer",
    "reasoning",
    "reasoning_content",
    "input_audio",
    "audio",
    "video",
})

PART_SEPARATOR = "\n"

_ALLOWED_SUFFIXES = (".json", ".jsonl")
_SKIP_FILENAMES = frozenset({"sessions.json"})
_CONTENT_JSON_PREFIX = "\x00json:"  # Hermes SQLite encoding for structured content


# --------------------------------------------------------------------- paths

def resolve_hermes_path(path: "os.PathLike[str] | str") -> str:
    """Return a directory or allowed session-file path; refuse a leaf symlink.

    The operator names one root. We do not follow a symlink leaf (escape to
    another path) and we do not open devices or FIFOs. ``..`` is resolved by
    ``abspath``. Extra paths inside JSON are never opened.

    Allowed: a real directory, or a regular file whose name ends in ``.json``
    or ``.jsonl``. Anything else is refused.
    """
    given = os.fspath(path)
    if not given or "\x00" in given:
        raise ValueError("invalid Hermes export path")
    absolute = os.path.abspath(os.path.expanduser(given))
    try:
        st = os.lstat(absolute)
    except OSError:
        raise FileNotFoundError(absolute) from None
    if stat.S_ISLNK(st.st_mode):
        raise OSError("refusing to follow a symlink export path")
    if stat.S_ISDIR(st.st_mode):
        return absolute
    if not stat.S_ISREG(st.st_mode):
        raise OSError("export path is not a directory or a regular file")
    if not _has_allowed_suffix(os.path.basename(absolute)):
        raise OSError("session file must be .json or .jsonl")
    return absolute


def list_hermes_session_files(root: "os.PathLike[str] | str") -> List[str]:
    """Regular session files under ``root``, no symlink follow, no escape.

    Order is sorted relative path, so repeated walks of the same tree produce
    the same file list. Files that are not ``.json``/``.jsonl``, whose name is
    ``sessions.json``, or that are not regular files are skipped.
    """
    resolved = resolve_hermes_path(root)
    st = os.lstat(resolved)
    if stat.S_ISREG(st.st_mode):
        return [resolved]
    out: List[str] = []
    for dirpath, dirnames, filenames in os.walk(resolved, followlinks=False):
        dirnames[:] = sorted(
            name for name in dirnames
            if _is_walkable_dir(os.path.join(dirpath, name), resolved)
        )
        for name in sorted(filenames):
            path = os.path.join(dirpath, name)
            if not _is_session_filename(name):
                continue
            if not _is_regular_inside(path, resolved):
                continue
            out.append(path)
    return out


def _has_allowed_suffix(name: str) -> bool:
    lower = name.lower()
    return any(lower.endswith(suffix) for suffix in _ALLOWED_SUFFIXES)


def _is_session_filename(name: str) -> bool:
    if not name or name.startswith("."):
        return False
    if name.lower() in _SKIP_FILENAMES:
        return False
    if name.lower().startswith("request_dump_"):
        return False
    return _has_allowed_suffix(name)


def _inside_root(path: str, root: str) -> bool:
    try:
        return os.path.commonpath([os.path.abspath(path), os.path.abspath(root)]) == os.path.abspath(root)
    except ValueError:
        return False


def _is_walkable_dir(path: str, root: str) -> bool:
    try:
        st = os.lstat(path)
    except OSError:
        return False
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        return False
    return _inside_root(path, root)


def _is_regular_inside(path: str, root: str) -> bool:
    try:
        st = os.lstat(path)
    except OSError:
        return False
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        return False
    return _inside_root(path, root)


def _open_read(path: str):
    """Open ``path`` for reading; ``O_NOFOLLOW`` so a swapped-in symlink is refused."""
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags)
    try:
        return os.fdopen(fd, "r", encoding="utf-8")
    except Exception:
        os.close(fd)
        raise


# --------------------------------------------------------------------- loading

def load_export(path: "os.PathLike[str] | str") -> Any:
    """Load one session file as JSON or JSONL. Raises on unreadable input.

    JSONL becomes a list of decoded objects (invalid lines are dropped from
    the value and must be recorded by the caller via :func:`parse_hermes_payload`
    when ``origin_path`` is set — this loader itself raises only on a total
    failure to read). Extra paths inside the payload are never opened.
    """
    resolved = resolve_hermes_path(path)
    st = os.lstat(resolved)
    if stat.S_ISDIR(st.st_mode):
        raise IsADirectoryError(resolved)
    return _load_file_payload(resolved)


def _load_file_payload(path: str) -> Any:
    lower = path.lower()
    with _open_read(path) as fh:
        if lower.endswith(".jsonl"):
            return _load_jsonl(fh)
        return json.load(fh)


def _load_jsonl(fh) -> List[Any]:
    rows: List[Any] = []
    for line_no, raw in enumerate(fh, start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            # Isolate one line: a marker the payload parser turns into a warning.
            rows.append({"__hermes_bad_line__": line_no})
    return rows


def parse_hermes_export(path: "os.PathLike[str] | str") -> List[ParsedConversation]:
    """Parse a Hermes export directory (or one session file) into conversations.

    Directory walks are confined to the given root: no symlink follow, no
    files whose path is outside the root, no extra paths from JSON. Order is
    sorted file path, then in-file order. One malformed file in a directory
    becomes warnings; a malformed *given* file still raises so the CLI can
    say the path is not valid JSON.
    """
    resolved = resolve_hermes_path(path)
    st = os.lstat(resolved)
    if stat.S_ISDIR(st.st_mode):
        conversations: List[ParsedConversation] = []
        for i, file_path in enumerate(list_hermes_session_files(resolved)):
            conversations.extend(_parse_one_file(file_path, index=i, isolate=True))
        return conversations
    return _parse_one_file(resolved, index=0, isolate=False)


def _parse_one_file(path: str, *, index: int, isolate: bool) -> List[ParsedConversation]:
    try:
        payload = _load_file_payload(path)
    except json.JSONDecodeError as e:
        if isolate:
            logger.warning("file %s skipped (%s)", os.path.basename(path),
                           type(e).__name__)
            return [_failed_file(path, index, type(e).__name__)]
        raise
    except (OSError, UnicodeDecodeError) as e:
        if isolate:
            logger.warning("file %s skipped (%s)", os.path.basename(path),
                           type(e).__name__)
            return [_failed_file(path, index, type(e).__name__)]
        raise
    try:
        return parse_hermes_payload(payload, origin_path=path, index=index)
    except Exception as e:  # noqa: BLE001 — hostile export; isolate one file
        if isolate:
            logger.warning("file %s skipped (%s)", os.path.basename(path),
                           type(e).__name__)
            return [_failed_file(path, index, type(e).__name__)]
        raise


def _failed_file(path: str, index: int, kind: str) -> ParsedConversation:
    session_id = _session_id_from_filename(os.path.basename(path)) or f"{SOURCE}-session-{index}"
    return ParsedConversation(
        source=SOURCE,
        session_id=session_id,
        title=None,
        warnings=(f"file {os.path.basename(path)!r} failed to parse ({kind}); skipped",),
        source_metadata=_file_meta(path),
    )


def parse_hermes_payload(payload: Any, *, origin_path: Optional[str] = None,
                         index: int = 0) -> List[ParsedConversation]:
    """Parse an already-decoded export payload.

    A session that raises is recorded as a warning and skipped; the rest of
    the payload still parses. Logs carry the session index and exception
    type, never turn text.
    """
    entries, file_warnings = _session_entries(payload, origin_path=origin_path)
    conversations: List[ParsedConversation] = []
    for i, entry in enumerate(entries):
        try:
            conversations.append(
                parse_hermes_session(entry, index=index + i, origin_path=origin_path,
                                     extra_warnings=file_warnings if i == 0 else ()),
            )
        except Exception as e:  # noqa: BLE001 — hostile export; isolate one entry
            logger.warning("session %s skipped (%s)", index + i, type(e).__name__)
            conversations.append(ParsedConversation(
                source=SOURCE,
                session_id=_placeholder_session_id(origin_path, index + i),
                title=None,
                warnings=(f"session {index + i} failed to parse "
                          f"({type(e).__name__}); skipped",),
                source_metadata=_file_meta(origin_path),
            ))
    if not entries and file_warnings:
        conversations.append(ParsedConversation(
            source=SOURCE,
            session_id=_placeholder_session_id(origin_path, index),
            title=None,
            warnings=tuple(file_warnings),
            source_metadata=_file_meta(origin_path),
        ))
    return conversations


def _session_entries(payload: Any, *, origin_path: Optional[str]
                     ) -> Tuple[List[Any], Tuple[str, ...]]:
    warnings: List[str] = []
    if payload is None:
        return [], ("payload is empty; no sessions parsed",)
    if isinstance(payload, list):
        if not payload:
            return [], ()
        # Drop JSONL bad-line markers into warnings; they are not sessions.
        cleaned: List[Any] = []
        for item in payload:
            if isinstance(item, dict) and "__hermes_bad_line__" in item:
                warnings.append(
                    f"jsonl line {item['__hermes_bad_line__']} is not valid JSON; skipped"
                )
                continue
            cleaned.append(item)
        if cleaned and all(_is_message_object(item) for item in cleaned):
            # Legacy {session_id}.jsonl: one message object per line. The
            # filename stem is the provider session id; parse_hermes_session
            # reads it as a fallback so we do not mint a new id field.
            return [{"messages": cleaned}], tuple(warnings)
        sessions = [item for item in cleaned if _is_session_object(item)]
        skipped = len(cleaned) - len(sessions)
        if skipped:
            warnings.append(f"{skipped} jsonl record(s) had no messages list; skipped")
        return sessions, tuple(warnings)
    if isinstance(payload, dict):
        if _is_session_object(payload):
            return [payload], tuple(warnings)
        inner = payload.get("sessions") or payload.get("conversations")
        if isinstance(inner, list):
            return [item for item in inner if _is_session_object(item) or _is_message_object(item)], tuple(warnings)
        warnings.append("json object has no messages list; skipped (not a session transcript)")
        return [], tuple(warnings)
    warnings.append(f"payload is {type(payload).__name__}, not a session object; skipped")
    return [], tuple(warnings)


def _is_session_object(obj: Any) -> bool:
    if not isinstance(obj, dict):
        return False
    if isinstance(obj.get("messages"), list):
        return True
    if isinstance(obj.get("segments"), list):
        return True
    return False


def _is_message_object(obj: Any) -> bool:
    if not isinstance(obj, dict):
        return False
    role = obj.get("role")
    return isinstance(role, str) and bool(role.strip())


# ---------------------------------------------------------------- one session

def parse_hermes_session(entry: Any, *, index: int = 0,
                         origin_path: Optional[str] = None,
                         extra_warnings: Sequence[str] = ()) -> ParsedConversation:
    """Parse one Hermes session object (export snapshot or assembled JSONL)."""
    warnings: List[str] = list(extra_warnings)

    if not isinstance(entry, dict):
        return ParsedConversation(
            source=SOURCE,
            session_id=_placeholder_session_id(origin_path, index),
            title=None,
            warnings=(f"session {index} is not an object "
                      f"({type(entry).__name__}); nothing could be parsed",),
            source_metadata=_file_meta(origin_path),
        )

    session_id, id_warning = _session_id_of(entry, origin_path, index)
    if id_warning:
        warnings.append(id_warning)

    title = entry.get("title")
    if title is None:
        display = entry.get("display_name")
        title = display if isinstance(display, str) else None
    if title is not None and not isinstance(title, str):
        warnings.append(f"session title is {type(title).__name__}; kept as text")
        title = str(title)

    messages = _messages_of(entry, warnings)
    turns, node_ids, current_node_ids = _turns_from_messages(
        messages, session_id=session_id, title=title, warnings=warnings,
    )
    turn_ids = {t.turn_id for t in turns}
    current_turn_ids = tuple(n for n in current_node_ids if n in turn_ids)
    current_node = current_node_ids[-1] if current_node_ids else None

    return ParsedConversation(
        source=SOURCE,
        session_id=session_id,
        title=title,
        turns=tuple(turns),
        current_path_turn_ids=current_turn_ids,
        current_path_node_ids=current_node_ids,
        current_node=current_node,
        created_at=_as_time(entry.get("started_at") or entry.get("created_at")),
        updated_at=_as_time(entry.get("last_activity_at") or entry.get("ended_at")
                            or entry.get("updated_at")),
        warnings=tuple(warnings),
        source_metadata=_session_metadata(entry, origin_path, len(messages)),
    )


def _messages_of(entry: Dict[str, Any], warnings: List[str]) -> List[Dict[str, Any]]:
    raw = entry.get("messages")
    if isinstance(raw, list):
        messages = raw
    elif isinstance(entry.get("segments"), list):
        messages = []
        for seg in entry["segments"]:
            if isinstance(seg, dict) and isinstance(seg.get("messages"), list):
                messages.extend(seg["messages"])
            else:
                warnings.append("segment is not a session object; skipped")
    else:
        warnings.append("session messages is missing; no turns produced")
        return []
    out: List[Dict[str, Any]] = []
    for i, item in enumerate(messages):
        if not isinstance(item, dict):
            warnings.append(f"message {i} is {type(item).__name__}, not an object; skipped")
            continue
        out.append(item)
    return out


def _session_id_of(entry: Dict[str, Any], origin_path: Optional[str],
                   index: int) -> Tuple[str, Optional[str]]:
    raw = entry.get("id")
    if raw is None:
        raw = entry.get("session_id")
    if isinstance(raw, str) and raw.strip():
        return raw.strip(), None
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        # Provider integer ids are preserved as decimal text, not regenerated.
        if isinstance(raw, float) and not raw.is_integer():
            return str(raw), None
        return str(int(raw)), None
    from_name = _session_id_from_filename(
        os.path.basename(origin_path) if origin_path else ""
    )
    if from_name:
        return from_name, "session has no id; using the filename stem (Hermes session id)"
    return _placeholder_session_id(origin_path, index), (
        "session has no id; using its position in the export"
    )


def _session_id_from_filename(name: str) -> Optional[str]:
    if not name:
        return None
    stem = name
    lower = stem.lower()
    for suffix in (".jsonl", ".json"):
        if lower.endswith(suffix):
            stem = stem[: -len(suffix)]
            lower = stem.lower()
            break
    if lower.endswith(".trace"):
        stem = stem[: -len(".trace")]
        lower = stem.lower()
    prefix = "hermes_session_"
    if lower.startswith(prefix):
        stem = stem[len(prefix):]
    stem = stem.strip()
    return stem or None


def _placeholder_session_id(origin_path: Optional[str], index: int) -> str:
    stem = _session_id_from_filename(os.path.basename(origin_path) if origin_path else "")
    if stem:
        return stem
    return f"{SOURCE}-session-{index}"


def _turns_from_messages(
    messages: List[Dict[str, Any]],
    *,
    session_id: str,
    title: Optional[str],
    warnings: List[str],
) -> Tuple[List[NormalizedTurn], Tuple[str, ...], Tuple[str, ...]]:
    """Linear walk: every textual message is a turn; empty ones stay structural."""
    turns: List[NormalizedTurn] = []
    node_ids: List[str] = []
    current_node_ids: List[str] = []
    last_id: Optional[str] = None
    path_so_far: List[str] = []

    for i, message in enumerate(messages):
        nid = _message_id(message)
        if nid is None:
            warnings.append(f"message {i}: no id; no turn produced")
            continue
        node_ids.append(nid)
        path_so_far.append(nid)
        parent_id = last_id
        last_id = nid
        on_current = _is_active(message)
        if on_current:
            current_node_ids.append(nid)

        text, unsupported = _extract_text(message.get("content"))
        role = _role_of(message)
        if not text.strip():
            if message.get("tool_calls"):
                warnings.append(
                    f"message {nid}: tool_calls have no textual form; no turn produced"
                )
            elif unsupported:
                warnings.append(
                    f"message {nid}: content type {unsupported[0]!r} has no textual "
                    "form; no turn produced"
                )
            continue

        turns.append(NormalizedTurn(
            source=SOURCE,
            session_id=session_id,
            session_title=title,
            turn_id=nid,
            parent_turn_id=parent_id,
            role=role,
            content=text,
            occurred_at=_timestamp_of(nid, message, warnings),
            branch_path=tuple(path_so_far),
            source_metadata=_turn_metadata(nid, message, unsupported, on_current),
        ))

    return turns, tuple(node_ids), tuple(current_node_ids)


def _message_id(message: Dict[str, Any]) -> Optional[str]:
    raw = message.get("id")
    if raw is None:
        raw = message.get("message_id")
    if raw is None:
        raw = message.get("platform_message_id")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        if isinstance(raw, float) and not raw.is_integer():
            return str(raw)
        return str(int(raw))
    return None


def _is_active(message: Dict[str, Any]) -> bool:
    if "active" not in message:
        return True
    value = message.get("active")
    if value in (0, False, "0", "false", "False"):
        return False
    return True


def _role_of(message: Dict[str, Any]) -> str:
    role = message.get("role")
    if isinstance(role, str) and role.strip():
        return role.strip()
    return "unknown"


def _extract_text(content: Any) -> Tuple[str, List[str]]:
    """Return ``(text, unsupported_type_names)``. Never raises."""
    if content is None:
        return "", []
    if isinstance(content, str):
        if content.startswith(_CONTENT_JSON_PREFIX):
            try:
                return _extract_text(json.loads(content[len(_CONTENT_JSON_PREFIX):]))
            except (json.JSONDecodeError, TypeError, ValueError):
                return "", ["<json-prefix>"]
        return content, []
    if isinstance(content, (int, float)) and not isinstance(content, bool):
        return str(content), []
    if not isinstance(content, (list, dict)):
        return "", [f"<{type(content).__name__}>"]

    if isinstance(content, dict):
        content_type = str(content.get("type") or content.get("content_type") or "").strip()
        if content_type in SKIPPED_PART_TYPES:
            return "", [content_type]
        if isinstance(content.get("text"), str):
            return content["text"], []
        if isinstance(content.get("content"), str):
            return content["content"], []
        if isinstance(content.get("parts"), list):
            return _extract_text(content["parts"])
        return "", [content_type or "<dict-content>"]

    fragments: List[str] = []
    unsupported: List[str] = []
    for part in content:
        if part is None:
            continue
        if isinstance(part, str):
            fragments.append(part)
            continue
        if isinstance(part, dict):
            marker = str(part.get("type") or part.get("content_type") or "").strip()
            if marker in SKIPPED_PART_TYPES:
                unsupported.append(marker)
                continue
            text = part.get("text")
            if isinstance(text, str):
                fragments.append(text)
                continue
            inner = part.get("content")
            if isinstance(inner, str):
                fragments.append(inner)
                continue
            unsupported.append(marker or "<dict-part>")
            continue
        unsupported.append(f"<{type(part).__name__}>")
    return PART_SEPARATOR.join(fragments), unsupported


def _timestamp_of(nid: str, message: Dict[str, Any],
                  warnings: List[str]) -> Optional[float]:
    raw = message.get("timestamp")
    if raw is None:
        raw = message.get("created_at")
    value = _as_time(raw)
    if value is None and raw is not None:
        warnings.append(f"message {nid}: timestamp {raw!r} is not a number; "
                        "occurred_at left empty")
    return value


def _as_time(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return float(text)
        except (TypeError, ValueError):
            pass
        try:
            iso = text[:-1] + "+00:00" if text.endswith("Z") else text
            return datetime.fromisoformat(iso).timestamp()
        except (TypeError, ValueError):
            return None
    return None


def _turn_metadata(nid: str, message: Dict[str, Any], unsupported: Sequence[str],
                   on_current: bool) -> Dict[str, Any]:
    """A small bounded record. Tool-call *arguments* are not copied."""
    meta: Dict[str, Any] = {"message_id": nid, "on_current_path": on_current}
    tool_name = message.get("tool_name") or message.get("name")
    if isinstance(tool_name, str) and tool_name:
        meta["tool_name"] = tool_name
    tool_call_id = message.get("tool_call_id")
    if isinstance(tool_call_id, str) and tool_call_id:
        meta["tool_call_id"] = tool_call_id
    names = _tool_call_names(message.get("tool_calls"))
    if names:
        meta["tool_names"] = names
    if unsupported:
        meta["unsupported_content_types"] = sorted(set(unsupported))
    if "active" in message:
        meta["active"] = bool(_is_active(message))
    if message.get("reasoning") or message.get("reasoning_content"):
        meta["had_reasoning"] = True
    return meta


def _tool_call_names(tool_calls: Any) -> List[str]:
    if isinstance(tool_calls, str):
        try:
            tool_calls = json.loads(tool_calls)
        except (json.JSONDecodeError, TypeError):
            return []
    if not isinstance(tool_calls, list):
        return []
    names: List[str] = []
    for call in tool_calls:
        if not isinstance(call, dict):
            continue
        fn = call.get("function")
        name = None
        if isinstance(fn, dict):
            name = fn.get("name")
        if not name:
            name = call.get("name")
        if isinstance(name, str) and name:
            names.append(name)
    return names


def _file_meta(origin_path: Optional[str]) -> Dict[str, Any]:
    if not origin_path:
        return {}
    return {
        "export_path": os.path.abspath(origin_path),
        "export_file": os.path.basename(origin_path),
    }


def _session_metadata(entry: Dict[str, Any], origin_path: Optional[str],
                      message_count: int) -> Dict[str, Any]:
    meta: Dict[str, Any] = {"message_count": message_count}
    meta.update(_file_meta(origin_path))
    source = entry.get("source")
    if isinstance(source, str) and source:
        meta["hermes_source"] = source
    model = entry.get("model")
    if isinstance(model, str) and model:
        meta["model"] = model
    parent = entry.get("parent_session_id")
    if isinstance(parent, str) and parent:
        meta["parent_session_id"] = parent
    if entry.get("system_prompt"):
        meta["had_system_prompt"] = True
    return meta
