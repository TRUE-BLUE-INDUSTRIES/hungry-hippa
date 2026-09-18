"""Slice 2: persist parsed conversations as raw history, not memory.

Layer 1 retains exact export bytes in SQLite, plus path, sha256 and byte length. Layer 2 is canonical conversation and turn
rows. Neither layer writes ``episodes``: raw history is not a memory.

The ChatGPT parser stays independent of this module. Callers parse first
(``parse_chatgpt_export``) and then persist. The CLI ``--apply`` path calls
this API; it does not extract memories.
"""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from typing import Any, Optional, Sequence, Union

from .models import NormalizedTurn, ParsedConversation


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
    """Inspect one bounded regular-file snapshot; refuse leaf symlinks."""
    from .chatgpt import read_export_bytes
    raw = read_export_bytes(path)
    return ArchivePointer(original_path=os.path.abspath(os.path.expanduser(os.fspath(path))),
                          sha256=hashlib.sha256(raw).hexdigest(), byte_length=len(raw))


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
    source_bytes: Optional[bytes] = None,
) -> PersistResult:
    """Validate normalized rows against the exact bytes stored with them.

    File input is read once here; CLI callers supply their already-read snapshot.
    Existing pointer-only imports must be reimported to acquire verified bytes.
    Raw history never creates episodes or beliefs. Optional file copies are
    redundant conveniences; the database backup contains the original bytes.
    """
    try:
        from .chatgpt import read_export_bytes, parse_chatgpt_bytes
        if source_bytes is not None:
            raw = source_bytes
        elif source_path:
            raw = read_export_bytes(source_path)
        elif archive:
            raw = db.get_ingest_archive_bytes(archive.sha256)
            if raw is None:
                raise ValueError("source bytes are required to verify an archive pointer")
        else:
            raise ValueError("source_path or source_bytes is required")
        if list(conversations) != parse_chatgpt_bytes(raw):
            raise ValueError("parsed conversations do not match the source snapshot")
        digest = hashlib.sha256(raw).hexdigest()
        if archive and (archive.sha256 != digest or archive.byte_length != len(raw)):
            raise ValueError("archive metadata does not match source bytes")
        original = (os.path.abspath(os.path.expanduser(source_path)) if source_path
                    else archive.original_path if archive else "")
        pointer = ArchivePointer(original, digest, len(raw),
                                 source=conversations[0].source if conversations else "chatgpt")
        if copy_to:
            pointer = ArchivePointer(original, digest, len(raw),
                                     _copy_archive(raw, copy_to, digest), pointer.source)
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
            raw_bytes=raw,
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
            error="database write refused: conflicting turn, integrity failure, size budget or storage error",
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


def _copy_archive(raw: bytes, dest_dir: str, sha256: str) -> str:
    """Publish a complete optional copy using directory-relative operations.

    The destination directory must be private and not a symlink. Existing files
    are checked through one descriptor; no path from imported data is opened.
    """
    dest_dir = os.path.abspath(dest_dir)
    os.makedirs(dest_dir, mode=0o700, exist_ok=True)
    flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
    directory = os.open(dest_dir, flags)
    temporary = ""
    try:
        info = os.fstat(directory)
        if stat.S_IMODE(info.st_mode) & 0o077 or info.st_uid != os.getuid():
            raise OSError("archive directory must be owner-only (0700)")
        try:
            existing = os.open(sha256, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                               dir_fd=directory)
        except FileNotFoundError:
            existing = None
        if existing is not None:
            with os.fdopen(existing, "rb") as handle:
                info = os.fstat(handle.fileno())
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                        or stat.S_IMODE(info.st_mode) & 0o077):
                    raise OSError("existing archive must be a private regular file")
                if info.st_size != len(raw) or handle.read(len(raw) + 1) != raw:
                    raise ValueError("existing archive copy does not match source bytes")
            return os.path.join(dest_dir, sha256)
        import secrets
        temporary = ".pending-" + secrets.token_hex(16)
        fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                     0o600, dir_fd=directory)
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, sha256, src_dir_fd=directory, dst_dir_fd=directory,
                follow_symlinks=False)
        os.fsync(directory)
        return os.path.join(dest_dir, sha256)
    finally:
        if temporary:
            os.unlink(temporary, dir_fd=directory)
        os.close(directory)


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


def verify_archive(db: Any, sha256: str) -> dict:
    """Verify stored source bytes and each canonical turn without printing text.

    This detects accidental corruption; a process that can rewrite the database
    can also rewrite hashes. It does not attest provider identity or truth.
    """
    from .chatgpt import parse_chatgpt_bytes
    from ..db import jload
    def read_snapshot(conn):
        conn.execute("BEGIN")
        pointer = conn.execute(
            "SELECT a.*, b.raw_bytes FROM ingest_archives a LEFT JOIN ingest_archive_bytes b "
            "USING (archive_id) WHERE a.sha256 = ?", (sha256,),
        ).fetchone()
        if not pointer or pointer["raw_bytes"] is None:
            return None
        snapshots = conn.execute(
            "SELECT * FROM ingest_snapshots WHERE archive_id = ?", (pointer["archive_id"],)
        ).fetchall()
        rows = conn.execute(
            "SELECT t.*, s.on_current_path AS snapshot_current, "
            "s.source_metadata AS snapshot_metadata FROM ingest_turn_sources s "
            "JOIN ingest_turns t USING (source, session_id, turn_id) WHERE s.archive_id = ?",
            (pointer["archive_id"],),
        ).fetchall()
        return dict(pointer), [dict(row) for row in snapshots], [dict(row) for row in rows]

    snapshot = db._run(read_snapshot)
    if snapshot is None:
        return {"ok": False, "sha256": sha256,
                "error": "verified source bytes unavailable; reimport the original export"}
    pointer, snapshots, rows = snapshot
    raw = bytes(pointer["raw_bytes"])
    if hashlib.sha256(raw).hexdigest() != sha256 or len(raw) != pointer["byte_length"]:
        return {"ok": False, "sha256": sha256, "error": "archive integrity mismatch"}
    try:
        conversations = parse_chatgpt_bytes(raw)
        manifest = {(r["source"], r["session_id"]): jload(r["conversation_json"]) for r in snapshots}
        stored = {(r["source"], r["session_id"], r["turn_id"]): r for r in rows}
        for convo in conversations:
            if manifest.get((convo.source, convo.session_id)) != _conversation_row(convo):
                raise ValueError("conversation snapshot mismatch")
            for turn in convo.turns:
                row = stored.get((convo.source, convo.session_id, turn.turn_id))
                if not row or any(row[field] != getattr(turn, field) for field in
                                  ("role", "content", "parent_turn_id", "occurred_at")):
                    raise ValueError("canonical turn mismatch")
                if tuple(jload(row["branch_path"], [])) != turn.branch_path:
                    raise ValueError("canonical lineage mismatch")
                if (bool(row["snapshot_current"]) != bool(turn.source_metadata.get("on_current_path"))
                        or jload(row["snapshot_metadata"]) != turn.source_metadata):
                    raise ValueError("turn provenance mismatch")
        turns = sum(c.turn_count for c in conversations)
        if (len(snapshots), len(rows)) != (len(conversations), turns):
            raise ValueError("archive membership count mismatch")
    except (ValueError, TypeError, KeyError) as error:
        return {"ok": False, "sha256": sha256, "error": str(error)}
    return {"ok": True, "sha256": sha256, "byte_length": len(raw),
            "conversations": len(conversations), "turns": turns,
            "note": "hash and provenance consistency; not authenticity or encryption"}


__all__ = [
    "ArchivePointer",
    "PersistResult",
    "inspect_archive",
    "persist_conversation",
    "persist_parsed_export",
    "fetch_conversation",
    "verify_archive",
]
