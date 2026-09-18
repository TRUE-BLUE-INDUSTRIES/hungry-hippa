"""Slice 2: persist parsed conversations as raw history, not memory.

Layer 1 is a pointer at the export file (path + sha256 + byte length). The file
bytes are not stored in SQLite. Layer 2 is canonical conversation and turn
rows. Neither layer writes ``episodes``: raw history is not a memory.

The ChatGPT parser stays independent of this module. Callers parse first
(``parse_chatgpt_export``) and then persist. The CLI write path is a later
slice; this is the library API it will call.
"""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from typing import Any, Optional, Sequence, Union

from .models import NormalizedTurn, ParsedConversation

_HASH_CHUNK = 1024 * 1024  # 1 MiB; never slurp a multi-GB export to hash it


@dataclass(frozen=True)
class ArchivePointer:
    """Layer 1: where the export lives and how to recognise it again."""

    original_path: str
    sha256: str
    byte_length: int
    archived_path: str = ""
    source: str = ""


@dataclass(frozen=True)
class PersistResult:
    """Outcome of one persist transaction (one export, any number of conversations)."""

    ok: bool
    archive_id: str = ""
    sha256: str = ""
    byte_length: int = 0
    original_path: str = ""
    archived_path: str = ""
    archive_inserted: bool = False
    conversations_inserted: int = 0
    conversations_seen: int = 0
    turns_inserted: int = 0
    turns_seen: int = 0
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "archive_id": self.archive_id,
            "sha256": self.sha256,
            "byte_length": self.byte_length,
            "original_path": self.original_path,
            "archived_path": self.archived_path,
            "archive_inserted": self.archive_inserted,
            "conversations_inserted": self.conversations_inserted,
            "conversations_seen": self.conversations_seen,
            "turns_inserted": self.turns_inserted,
            "turns_seen": self.turns_seen,
            "error": self.error,
        }


def inspect_archive(path: Union[os.PathLike[str], str]) -> ArchivePointer:
    """Hash ``path`` in chunks. Follows only the given path, not extra files.

    Raises ``FileNotFoundError`` / ``IsADirectoryError`` / ``OSError`` rather
    than guessing. The digest is of the bytes ``open(path, 'rb')`` yields, so a
    symlink the operator named is hashed as that file's content; we do not walk
    a directory or chase additional paths found inside the export.
    """
    given = os.fspath(path)
    if os.path.isdir(given):
        raise IsADirectoryError(given)
    if not os.path.isfile(given):
        raise FileNotFoundError(given)
    sha256, size = _hash_file(given)
    return ArchivePointer(
        original_path=os.path.abspath(given),
        sha256=sha256,
        byte_length=size,
    )


def persist_conversation(db: Any, conversation: ParsedConversation, *,
                         source_path: Optional[str] = None,
                         archive: Optional[ArchivePointer] = None,
                         copy_to: Optional[str] = None) -> PersistResult:
    """Persist one ``ParsedConversation`` transactionally."""
    return persist_parsed_export(
        db, [conversation], source_path=source_path, archive=archive, copy_to=copy_to,
    )


def persist_parsed_export(
    db: Any,
    conversations: Sequence[ParsedConversation],
    *,
    source_path: Optional[str] = None,
    archive: Optional[ArchivePointer] = None,
    copy_to: Optional[str] = None,
) -> PersistResult:
    """Persist parsed conversations against a Layer 1 archive pointer.

    ``source_path`` is hashed in chunks when given. ``copy_to`` optionally
    copies those bytes into an app-controlled directory as a ``0600`` file
    named by the digest; path + hash is enough without a copy.

    Re-running on the same export is a no-op for turns already stored
    (``INSERT OR IGNORE`` on ``(source, session_id, turn_id)``).
    """
    try:
        pointer = _resolve_archive(source_path, archive, conversations)
        archived_path = ""
        if copy_to:
            archived_path = _copy_archive(
                pointer.original_path, copy_to, pointer.sha256,
            )
            pointer = ArchivePointer(
                original_path=pointer.original_path,
                sha256=pointer.sha256,
                byte_length=pointer.byte_length,
                archived_path=archived_path,
                source=pointer.source,
            )
        rows = [_conversation_row(c) for c in conversations]
        turns = [_turn_row(t) for c in conversations for t in c.turns]
        written = db.persist_ingest(
            archive={
                "source": pointer.source,
                "original_path": pointer.original_path,
                "sha256": pointer.sha256,
                "byte_length": pointer.byte_length,
                "archived_path": pointer.archived_path,
            },
            conversations=rows,
            turns=turns,
        )
    except (OSError, ValueError, TypeError) as e:
        return PersistResult(ok=False, error=f"{type(e).__name__}: {e}")
    if not written:
        return PersistResult(
            ok=False,
            sha256=pointer.sha256,
            byte_length=pointer.byte_length,
            original_path=pointer.original_path,
            archived_path=pointer.archived_path,
            error="database write failed",
        )
    return PersistResult(
        ok=True,
        archive_id=str(written.get("archive_id") or ""),
        sha256=pointer.sha256,
        byte_length=pointer.byte_length,
        original_path=pointer.original_path,
        archived_path=pointer.archived_path,
        archive_inserted=bool(written.get("archive_inserted")),
        conversations_inserted=int(written.get("conversations_inserted") or 0),
        conversations_seen=int(written.get("conversations_seen") or 0),
        turns_inserted=int(written.get("turns_inserted") or 0),
        turns_seen=int(written.get("turns_seen") or 0),
    )


def _resolve_archive(
    source_path: Optional[str],
    archive: Optional[ArchivePointer],
    conversations: Sequence[ParsedConversation],
) -> ArchivePointer:
    source = ""
    if conversations:
        source = conversations[0].source or ""
    if archive is None and not source_path:
        raise ValueError("source_path or archive is required")
    if source_path:
        pointer = inspect_archive(source_path)
        if archive is not None and archive.sha256 and archive.sha256 != pointer.sha256:
            raise ValueError("archive sha256 does not match source_path")
        return ArchivePointer(
            original_path=pointer.original_path,
            sha256=pointer.sha256,
            byte_length=pointer.byte_length,
            archived_path=archive.archived_path if archive else "",
            source=source or (archive.source if archive else ""),
        )
    assert archive is not None
    return ArchivePointer(
        original_path=archive.original_path,
        sha256=archive.sha256,
        byte_length=archive.byte_length,
        archived_path=archive.archived_path,
        source=source or archive.source,
    )


def _hash_file(path: str) -> tuple:
    digest = hashlib.sha256()
    size = 0
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(_HASH_CHUNK)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _copy_archive(src: str, dest_dir: str, sha256: str) -> str:
    """Copy ``src`` to ``dest_dir/<sha256>`` at 0600. Never write through a symlink."""
    dest_dir = os.path.abspath(dest_dir)
    os.makedirs(dest_dir, mode=0o700, exist_ok=True)
    dest = os.path.join(dest_dir, sha256)
    if os.path.lexists(dest):
        if os.path.islink(dest) or stat.S_ISLNK(os.lstat(dest).st_mode):
            raise OSError("refusing to write archive copy through a symlink")
        existing, _ = _hash_file(dest)
        if existing != sha256:
            raise ValueError("existing archive copy does not match sha256")
        return dest
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(dest, flags, 0o600)
    try:
        with open(src, "rb") as fh:
            while True:
                chunk = fh.read(_HASH_CHUNK)
                if not chunk:
                    break
                os.write(fd, chunk)
        os.fchmod(fd, 0o600)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(dest)
        except OSError:
            pass
        raise
    os.close(fd)
    return dest


def _conversation_row(convo: ParsedConversation) -> dict:
    return {
        "source": convo.source,
        "session_id": convo.session_id,
        "title": convo.title or "",
        "current_node": convo.current_node,
        "created_at": convo.created_at,
        "updated_at": convo.updated_at,
        "current_path_turn_ids": list(convo.current_path_turn_ids),
        "current_path_node_ids": list(convo.current_path_node_ids),
        "warnings": list(convo.warnings),
        "source_metadata": dict(convo.source_metadata),
    }


def _turn_row(turn: NormalizedTurn) -> dict:
    meta = dict(turn.source_metadata)
    return {
        "source": turn.source,
        "session_id": turn.session_id,
        "turn_id": turn.turn_id,
        "parent_turn_id": turn.parent_turn_id,
        "role": turn.role,
        "content": turn.content,
        "occurred_at": turn.occurred_at,
        "branch_path": list(turn.branch_path),
        "source_metadata": meta,
        "on_current_path": bool(meta.get("on_current_path")),
    }


def fetch_conversation(db: Any, source: str, session_id: str) -> Optional[dict]:
    """Return a stored conversation plus its turns, or None."""
    convo = db.get_ingest_conversation(source, session_id)
    if not convo:
        return None
    convo["turns"] = db.get_ingest_turns(source, session_id)
    return convo


__all__ = [
    "ArchivePointer",
    "PersistResult",
    "inspect_archive",
    "persist_conversation",
    "persist_parsed_export",
    "fetch_conversation",
]
