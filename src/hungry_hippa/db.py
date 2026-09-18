"""SQLite access layer for Hungry Hippa.

Design rules:
  - WAL mode; a fresh connection per operation (thread-safe, no shared cursors).
  - Every mutation is recorded in ``mutation_log`` (§19.11–19.12).
  - Raw evidence rows are append-only; update attempts are refused.
  - All failures return empty results rather than raising into the agent loop
    (fail safely, §19.15). ``Database.failures`` counts them for diagnostics.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
import stat
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from . import schema as _schema
from . import limits as _limits

logger = logging.getLogger("hungry_hippa.db")

_ID_PREFIX = {
    "episode": "E", "entity": "EN", "relationship": "R", "belief": "B",
    "procedure": "P", "evidence": "EV", "vector": "V", "consolidation": "CR",
    "ingest_archive": "IA",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _utc_now_float() -> float:
    return time.time()


def jdump(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def jload(text: Any, default: Any = None) -> Any:
    if text in (None, ""):
        return default
    if isinstance(text, (list, dict)):
        return text
    try:
        return json.loads(text)
    except Exception:
        return default


class Database:
    """Owns the Cortex SQLite store."""

    def __init__(self, path: str):
        self.path = path
        self.failures = 0
        self.last_backup: Optional[str] = None
        self.permissions_lax = False
        self.permissions_warning = ""
        self._lock = threading.Lock()
        self._secure_new_file()
        self._ensure_schema()

    # ------------------------------------------------------------- infra

    def _secure_new_file(self) -> None:
        """Create a new database 0600, and warn about an existing lax one.

        This is a permission, not encryption: the file is still plaintext, and a
        process running as this user can read it. It only stops *other* local
        users from reading the operator's memory. No-op on platforms without
        POSIX permission bits.
        """
        try:
            if not os.path.exists(self.path):
                parent = os.path.dirname(os.path.abspath(self.path))
                if parent:
                    os.makedirs(parent, exist_ok=True)
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.close(fd)
                return
            mode = stat.S_IMODE(os.stat(self.path).st_mode)
            if mode & 0o077:
                self.permissions_lax = True
                self.permissions_warning = (
                    f"{self.path} is mode {oct(mode)}: other local users can read the "
                    "plaintext memory database. Run `hungry-hippa fix-permissions` to set 0600.")
                logger.warning(self.permissions_warning)
        except (OSError, AttributeError, NotImplementedError):
            # Windows and other platforms without POSIX bits: nothing to do.
            return

    def file_permissions(self) -> Dict[str, Any]:
        """Permission state of the database and its sidecars (not encryption).

        ``lax`` means at least one file is readable by other local users. The
        runtime never silently changes an existing file's mode; it reports, and
        ``hungry-hippa fix-permissions`` is the explicit remediation.
        """
        files: Dict[str, Optional[str]] = {}
        lax = False
        for suffix in ("", "-wal", "-shm"):
            target = self.path + suffix
            try:
                mode = stat.S_IMODE(os.stat(target).st_mode)
            except OSError:
                continue
            files[suffix or "db"] = oct(mode)
            if mode & 0o077:
                lax = True
        return {"mode": files.get("db"), "files": files, "lax": lax,
                "warning": self.permissions_warning,
                "note": "permissions are not encryption; the file is plaintext"}

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _ensure_schema(self) -> None:
        try:
            parent = os.path.dirname(os.path.abspath(self.path))
            if parent:
                os.makedirs(parent, exist_ok=True)
            # A pre-existing, non-empty file is somebody's database: if this open
            # is going to apply migrations to it, back it up first. Brand-new
            # (or empty) paths are skipped, and a fully-migrated database never
            # produces a backup on ordinary opens.
            pre_existing = (os.path.exists(self.path)
                            and os.path.getsize(self.path) > 0)
            conn = self._connect()
            try:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS schema_migrations ("
                    "version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL,"
                    "description TEXT NOT NULL, down_sql TEXT NOT NULL DEFAULT '')"
                )
                applied = {r["version"] for r in conn.execute("SELECT version FROM schema_migrations")}
                pending = [v for v in sorted(_schema.MIGRATIONS) if v not in applied]
                if pending and pre_existing and applied:
                    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                    backup = f"{self.path}.pre-migration-{ts}.bak"
                    backup_sqlite(self.path, backup)
                    self.last_backup = backup
                    logger.warning(
                        "schema upgrade on an existing database: backed up %s -> %s "
                        "(pending migrations %s)", self.path, backup, pending)
                for version in sorted(_schema.MIGRATIONS):
                    if version in applied:
                        continue
                    mig = _schema.MIGRATIONS[version]
                    conn.executescript(mig["up"])
                    conn.execute(
                        "INSERT INTO schema_migrations(version, applied_at, description, down_sql)"
                        " VALUES (?,?,?,?)",
                        (version, now_iso(), mig["description"], mig["down"]),
                    )
                conn.commit()
                self._rebuild_fts_if_empty(conn)
            finally:
                conn.close()
        except Exception as e:
            self.failures += 1
            logger.error("schema init failed for %s: %s", self.path, e)
            raise

    def _rebuild_fts_if_empty(self, conn: sqlite3.Connection) -> None:
        """Self-heal: if the FTS index is empty but source tables have rows
        (e.g. after a schema fix), reindex everything from source."""
        try:
            n_fts = conn.execute("SELECT COUNT(*) FROM memory_fts").fetchone()[0]
            if n_fts > 0:
                return
            sources = sum(
                conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                for t in ("episodes", "beliefs", "entities", "procedures")
            )
            if sources == 0:
                return
            for r in conn.execute(
                "SELECT episode_id, context, user_request, actions_taken, decisions,"
                " result, project, visual_entities, audio_transcript, participants"
                " FROM episodes"
            ):
                body = " ".join(str(x) for x in (
                    r["context"], r["user_request"], r["actions_taken"],
                    r["decisions"], r["result"], r["project"],
                    r["visual_entities"], r["audio_transcript"], r["participants"],
                ) if x).strip()
                if body:
                    conn.execute(
                        "INSERT INTO memory_fts(body, target_kind, target_id)"
                        " VALUES (?,?,?)", (body, "episode", r["episode_id"]))
            for r in conn.execute("SELECT belief_id, claim FROM beliefs"):
                if r["claim"]:
                    conn.execute(
                        "INSERT INTO memory_fts(body, target_kind, target_id)"
                        " VALUES (?,?,?)", (r["claim"], "belief", r["belief_id"]))
            for r in conn.execute("SELECT entity_id, name FROM entities"):
                if r["name"]:
                    conn.execute(
                        "INSERT INTO memory_fts(body, target_kind, target_id)"
                        " VALUES (?,?,?)", (r["name"], "entity", r["entity_id"]))
            for r in conn.execute(
                "SELECT procedure_id, name, description, applicability FROM procedures"
            ):
                body = " ".join(str(x) for x in (
                    r["name"], r["description"], r["applicability"]) if x).strip()
                if body:
                    conn.execute(
                        "INSERT INTO memory_fts(body, target_kind, target_id)"
                        " VALUES (?,?,?)", (body, "procedure", r["procedure_id"]))
            conn.commit()
            logger.info("cortex fts reindexed from source rows")
        except Exception as e:
            logger.warning("fts reindex failed: %s", e)

    def _run(self, fn, *args, write: bool = False) -> Any:
        try:
            if write:
                with self._lock:
                    conn = self._connect()
                    try:
                        result = fn(conn, *args)
                        conn.commit()
                        # void write functions return None; callers treat None
                        # as failure, so normalize success to True.
                        return True if result is None else result
                    except Exception:
                        conn.rollback()
                        raise
                    finally:
                        conn.close()
            else:
                conn = self._connect()
                try:
                    return fn(conn, *args)
                finally:
                    conn.close()
        except Exception as e:
            self.failures += 1
            logger.debug("cortex db %s (write=%s): %s", self.path, write, e)
            return None

    # ------------------------------------------------------------ helpers

    def next_id(self, kind: str) -> str:
        """Atomic counter-backed ID, e.g. E-0001 / EN-0007 / B-0003."""
        prefix = _ID_PREFIX.get(kind, kind[0].upper())

        def _next(conn: sqlite3.Connection) -> str:
            conn.execute("INSERT OR IGNORE INTO counters(name, value) VALUES (?,0)", (kind,))
            row = conn.execute(
                "UPDATE counters SET value = value + 1 WHERE name = ? RETURNING value", (kind,)
            ).fetchone()
            return f"{prefix}-{row['value']:04d}"

        return self._run(_next, write=True)

    def log_mutation(self, action: str, target_kind: str, target_id: str = "",
                     detail: str = "", session_id: str = "") -> None:
        """Append an audit row.

        The audit *summary* is redacted and length-capped; the stored memory and
        its immutable evidence rows keep exactly what they were given, so a
        redacted audit log never contradicts the record it describes.
        """
        safe_detail = _limits.redact(detail)[:2000]

        def _log(conn: sqlite3.Connection) -> None:
            conn.execute(
                "INSERT INTO mutation_log(ts, action, target_kind, target_id, detail, session_id)"
                " VALUES (?,?,?,?,?,?)",
                (now_iso(), action, target_kind, target_id, safe_detail, session_id),
            )

        self._run(_log, write=True)

    def add_evidence(self, content: str, kind: str = "agent_inference",
                     source_ref: str = "", session_id: str = "") -> str:
        """Store immutable raw evidence; returns evidence id."""
        evidence_id = self.next_id("evidence")
        content_hash = hashlib.sha256(content.encode("utf-8", "replace")).hexdigest()

        def _add(conn: sqlite3.Connection) -> None:
            conn.execute(
                "INSERT INTO evidence(evidence_id, kind, content, content_hash, captured_at, source_ref)"
                " VALUES (?,?,?,?,?,?)",
                (evidence_id, kind, content, content_hash, now_iso(), source_ref),
            )

        if self._run(_add, write=True) is not None:
            self.log_mutation("add_evidence", "evidence", evidence_id, kind, session_id)
            return evidence_id
        return ""

    def link_evidence(self, owner_kind: str, owner_id: str, evidence_ids: List[str],
                      session_id: str = "") -> None:
        if owner_kind == "episode":
            table, col = "episode_evidence", "episode_id"
        elif owner_kind == "belief":
            table, col = "belief_evidence", "belief_id"
        else:
            return

        def _link(conn: sqlite3.Connection) -> None:
            for ev in evidence_ids or []:
                conn.execute(
                    f"INSERT OR IGNORE INTO {table}({col}, evidence_id) VALUES (?,?)",
                    (owner_id, ev),
                )

        self._run(_link, write=True)

    def get_evidence(self, evidence_ids: List[str]) -> List[Dict[str, Any]]:
        def _get(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
            rows = []
            for ev in evidence_ids or []:
                row = conn.execute(
                    "SELECT * FROM evidence WHERE evidence_id = ?", (ev,)
                ).fetchone()
                if row:
                    rows.append(dict(row))
            return rows

        return self._run(_get) or []

    # ------------------------------------------------------------ FTS5

    def fts_insert(self, target_kind: str, target_id: str, body: str) -> None:
        def _ins(conn: sqlite3.Connection) -> None:
            conn.execute(
                "INSERT INTO memory_fts(body, target_kind, target_id) VALUES (?,?,?)",
                (body, target_kind, target_id),
            )

        self._run(_ins, write=True)

    def fts_delete(self, target_kind: str, target_id: str) -> None:
        def _del(conn: sqlite3.Connection) -> None:
            conn.execute(
                "DELETE FROM memory_fts WHERE target_kind = ? AND target_id = ?",
                (target_kind, target_id),
            )

        self._run(_del, write=True)

    def fts_search(self, query: str, kinds: Optional[List[str]] = None,
                   limit: int = 10) -> List[Dict[str, Any]]:
        q = query.strip()
        if not q:
            return []
        fts_query = " OR ".join(f'"{part}"' for part in q.split() if len(part) > 1)
        if not fts_query:
            fts_query = f'"{q}"'
        sql = "SELECT target_kind, target_id, bm25(memory_fts) AS score FROM memory_fts WHERE memory_fts MATCH ?"
        params: List[Any] = [fts_query]
        if kinds:
            sql += " AND target_kind IN (%s)" % ",".join("?" for _ in kinds)
            params.extend(kinds)
        sql += " ORDER BY score LIMIT ?"
        params.append(limit)

        def _search(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
            try:
                return [dict(r) for r in conn.execute(sql, params)]
            except sqlite3.OperationalError:
                return []

        return self._run(_search) or []

    # ---------------------------------------------------------- health

    def health(self) -> Dict[str, Any]:
        def _h(conn: sqlite3.Connection) -> Dict[str, Any]:
            counts = {}
            for table in ("episodes", "entities", "relationships", "beliefs",
                          "procedures", "evidence", "vectors"):
                try:
                    counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                except Exception:
                    counts[table] = -1
            # quarantine visibility (counts only, never row contents)
            for table in ("episodes", "beliefs"):
                key = f"{table}_quarantined"
                try:
                    counts[key] = conn.execute(
                        f"SELECT COUNT(*) FROM {table} WHERE quarantined = 1"
                    ).fetchone()[0]
                except Exception:
                    counts[key] = -1
            return {
                "path": self.path,
                "counts": counts,
                "failures": self.failures,
                "permissions": self.file_permissions(),
                "size": _limits.db_size_report(self.path),
            }

        return self._run(_h) or {"path": self.path, "counts": {}, "failures": self.failures}

    # ---------------------------------------------------- ingest (raw history)

    def persist_ingest(
        self,
        *,
        archive: Dict[str, Any],
        conversations: List[Dict[str, Any]],
        turns: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """Store a Layer 1 archive pointer and Layer 2 conversations/turns.

        One transaction. Turns are idempotent on ``(source, session_id, turn_id)``
        (first write wins). Conversations upsert on ``(source, session_id)`` so a
        later export of the same session can refresh title and current path.
        This does not write episodes, beliefs, evidence, or FTS: raw history is
        not memory.
        """

        def _persist(conn: sqlite3.Connection) -> Dict[str, Any]:
            archive_id, archive_inserted = _upsert_ingest_archive(conn, archive)
            conv_before = conn.execute(
                "SELECT COUNT(*) FROM ingest_conversations"
            ).fetchone()[0]
            turn_before = conn.execute(
                "SELECT COUNT(*) FROM ingest_turns"
            ).fetchone()[0]
            stored_at = now_iso()
            for convo in conversations:
                _upsert_ingest_conversation(conn, convo, archive_id, stored_at)
            for turn in turns:
                _insert_ingest_turn(conn, turn, stored_at)
            conv_after = conn.execute(
                "SELECT COUNT(*) FROM ingest_conversations"
            ).fetchone()[0]
            turn_after = conn.execute(
                "SELECT COUNT(*) FROM ingest_turns"
            ).fetchone()[0]
            detail = (
                f"archive={archive_id} sha256={(archive.get('sha256') or '')[:16]} "
                f"conversations={len(conversations)} turns={len(turns)}"
            )[:2000]
            conn.execute(
                "INSERT INTO mutation_log(ts, action, target_kind, target_id, detail, session_id)"
                " VALUES (?,?,?,?,?,?)",
                (stored_at, "ingest_persist", "ingest_archive", archive_id, detail, ""),
            )
            return {
                "archive_id": archive_id,
                "archive_inserted": archive_inserted,
                "conversations_inserted": conv_after - conv_before,
                "conversations_seen": len(conversations),
                "turns_inserted": turn_after - turn_before,
                "turns_seen": len(turns),
            }

        return self._run(_persist, write=True)

    def ingest_counts(self) -> Dict[str, int]:
        """Row counts for the canonical ingest tables only (not memory tables)."""

        def _c(conn: sqlite3.Connection) -> Dict[str, int]:
            out: Dict[str, int] = {}
            for table in ("ingest_archives", "ingest_conversations", "ingest_turns"):
                out[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            return out

        return self._run(_c) or {
            "ingest_archives": -1,
            "ingest_conversations": -1,
            "ingest_turns": -1,
        }

    def get_ingest_archive(self, sha256: str) -> Optional[Dict[str, Any]]:
        def _g(conn: sqlite3.Connection) -> Optional[Dict[str, Any]]:
            row = conn.execute(
                "SELECT * FROM ingest_archives WHERE sha256 = ?", (sha256,)
            ).fetchone()
            return dict(row) if row else None

        return self._run(_g)

    def get_ingest_conversation(
        self, source: str, session_id: str
    ) -> Optional[Dict[str, Any]]:
        def _g(conn: sqlite3.Connection) -> Optional[Dict[str, Any]]:
            row = conn.execute(
                "SELECT * FROM ingest_conversations WHERE source = ? AND session_id = ?",
                (source, session_id),
            ).fetchone()
            if not row:
                return None
            out = dict(row)
            out["current_path_turn_ids"] = jload(out.get("current_path_turn_ids"), [])
            out["current_path_node_ids"] = jload(out.get("current_path_node_ids"), [])
            out["warnings"] = jload(out.get("warnings"), [])
            out["source_metadata"] = jload(out.get("source_metadata"), {})
            return out

        return self._run(_g)

    def get_ingest_turns(self, source: str, session_id: str) -> List[Dict[str, Any]]:
        def _g(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
            rows = conn.execute(
                "SELECT * FROM ingest_turns WHERE source = ? AND session_id = ?"
                " ORDER BY rowid",
                (source, session_id),
            ).fetchall()
            out: List[Dict[str, Any]] = []
            for row in rows:
                item = dict(row)
                item["branch_path"] = tuple(jload(item.get("branch_path"), []) or [])
                item["source_metadata"] = jload(item.get("source_metadata"), {})
                out.append(item)
            return out

        return self._run(_g) or []


def _upsert_ingest_archive(
    conn: sqlite3.Connection, archive: Dict[str, Any]
) -> tuple:
    sha256 = str(archive.get("sha256") or "")
    if not sha256:
        raise ValueError("ingest archive sha256 is required")
    row = conn.execute(
        "SELECT archive_id FROM ingest_archives WHERE sha256 = ?", (sha256,)
    ).fetchone()
    if row:
        archived_path = str(archive.get("archived_path") or "")
        if archived_path:
            conn.execute(
                "UPDATE ingest_archives SET archived_path = ? "
                "WHERE archive_id = ? AND archived_path = ''",
                (archived_path, row["archive_id"]),
            )
        return row["archive_id"], False
    conn.execute(
        "INSERT OR IGNORE INTO counters(name, value) VALUES ('ingest_archive', 0)"
    )
    n = conn.execute(
        "UPDATE counters SET value = value + 1 WHERE name = 'ingest_archive' RETURNING value"
    ).fetchone()["value"]
    archive_id = f"IA-{n:04d}"
    conn.execute(
        "INSERT INTO ingest_archives("
        "archive_id, source, original_path, sha256, byte_length, archived_path, captured_at)"
        " VALUES (?,?,?,?,?,?,?)",
        (
            archive_id,
            str(archive.get("source") or ""),
            str(archive.get("original_path") or ""),
            sha256,
            int(archive.get("byte_length") or 0),
            str(archive.get("archived_path") or ""),
            now_iso(),
        ),
    )
    return archive_id, True


def _upsert_ingest_conversation(
    conn: sqlite3.Connection,
    convo: Dict[str, Any],
    archive_id: str,
    stored_at: str,
) -> None:
    conn.execute(
        "INSERT INTO ingest_conversations("
        "source, session_id, archive_id, title, current_node, created_at, updated_at,"
        " current_path_turn_ids, current_path_node_ids, warnings, source_metadata, stored_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)"
        " ON CONFLICT(source, session_id) DO UPDATE SET"
        " archive_id=excluded.archive_id,"
        " title=excluded.title,"
        " current_node=excluded.current_node,"
        " created_at=excluded.created_at,"
        " updated_at=excluded.updated_at,"
        " current_path_turn_ids=excluded.current_path_turn_ids,"
        " current_path_node_ids=excluded.current_path_node_ids,"
        " warnings=excluded.warnings,"
        " source_metadata=excluded.source_metadata,"
        " stored_at=excluded.stored_at",
        (
            str(convo.get("source") or ""),
            str(convo.get("session_id") or ""),
            archive_id,
            str(convo.get("title") or ""),
            convo.get("current_node"),
            convo.get("created_at"),
            convo.get("updated_at"),
            jdump(convo.get("current_path_turn_ids") or []),
            jdump(convo.get("current_path_node_ids") or []),
            jdump(convo.get("warnings") or []),
            jdump(convo.get("source_metadata") or {}),
            stored_at,
        ),
    )


def _insert_ingest_turn(
    conn: sqlite3.Connection, turn: Dict[str, Any], stored_at: str
) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO ingest_turns("
        "source, session_id, turn_id, parent_turn_id, role, content, occurred_at,"
        " branch_path, source_metadata, on_current_path, stored_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            str(turn.get("source") or ""),
            str(turn.get("session_id") or ""),
            str(turn.get("turn_id") or ""),
            turn.get("parent_turn_id"),
            str(turn.get("role") or ""),
            str(turn.get("content") or ""),
            turn.get("occurred_at"),
            jdump(list(turn.get("branch_path") or [])),
            jdump(turn.get("source_metadata") or {}),
            1 if turn.get("on_current_path") else 0,
            stored_at,
        ),
    )


def backup_sqlite(src: str, dest: str) -> None:
    """Consistent SQLite backup (API, not file copy) so WAL is included.

    The copy inherits the source file's permission bits (never wider): a backup of
    a ``0600`` database must not be world-readable, which is what a plain
    ``sqlite3.connect(dest)`` would produce under the usual umask.
    """
    parent = os.path.dirname(os.path.abspath(dest))
    if parent:
        os.makedirs(parent, exist_ok=True)
    # A full filesystem turns a routine backup into a half-written copy, so refuse
    # up front rather than reporting success on a truncated file.
    ok, detail = _limits.backup_space_ok(src)
    if not ok:
        raise RuntimeError(f"refusing to back up: {detail}")
    try:
        mode = stat.S_IMODE(os.stat(src).st_mode)
    except OSError:
        mode = 0o600
    # The copy is never wider than 0600 and never wider than its source: a
    # world-readable source (or a lax umask) must not produce a world-readable
    # backup of the operator's memory. Permissions are not encryption — see
    # docs/SECURITY.md.
    mode = (mode & 0o600) or 0o600
    # create the destination ourselves so the file never exists with looser bits,
    # even briefly, and let sqlite write into it
    try:
        fd = os.open(dest, os.O_CREAT | os.O_EXCL | os.O_WRONLY, mode)
        os.close(fd)
    except FileExistsError:
        os.chmod(dest, mode)
    src_conn = sqlite3.connect(src, timeout=30.0)
    try:
        dest_conn = sqlite3.connect(dest, timeout=30.0)
        try:
            src_conn.backup(dest_conn)
            dest_conn.commit()
        finally:
            dest_conn.close()
    finally:
        src_conn.close()
    try:
        os.chmod(dest, mode)
    except OSError:
        pass


#: Operator snapshots are named by this project and by nothing else, so rotation
#: can never delete a file it did not create.
BACKUP_PREFIX = "hungry_hippa"
BACKUP_SUFFIX = ".db"
_BACKUP_STAMP_RE = re.compile(r"-(\d{8}T\d{6}Z)")


def backup_name(label: str = "", *, now: Optional[float] = None) -> str:
    """Sortable snapshot filename: ``hungry_hippa-<UTC stamp>[-label].db``.

    The stamp is UTC and fixed-width, so lexical order is chronological order and
    rotation never has to trust a filesystem timestamp.
    """
    stamp = datetime.fromtimestamp(
        time.time() if now is None else now, timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    clean = re.sub(r"[^A-Za-z0-9._-]+", "-", str(label or "").strip()).strip("-")
    return f"{BACKUP_PREFIX}-{stamp}{'-' + clean if clean else ''}{BACKUP_SUFFIX}"


def _backup_sort_key(path: str) -> tuple:
    """Order snapshots by the stamp in the name, falling back to the filename."""
    match = _BACKUP_STAMP_RE.search(os.path.basename(path))
    return (match.group(1) if match else "", os.path.basename(path))


def list_backups(directory: str) -> List[str]:
    """Snapshot files in ``directory``, oldest first. Non-matching files ignored."""
    if not directory or not os.path.isdir(directory):
        return []
    names = [n for n in os.listdir(directory)
             if n.startswith(BACKUP_PREFIX + "-") and n.endswith(BACKUP_SUFFIX)]
    return sorted((os.path.join(directory, n) for n in names), key=_backup_sort_key)


def prune_backups(directory: str, keep: int) -> List[str]:
    """Delete the oldest snapshots beyond ``keep``; return the paths removed.

    ``keep <= 0`` means "rotate nothing" rather than "delete everything": an
    always-on box that loses power mid-run must not be able to end up with no
    backups because of a config typo. Files this project did not name are never
    candidates, so a human's notes in the same directory are safe.
    """
    if keep is None or int(keep) <= 0:
        return []
    snapshots = list_backups(directory)
    removed: List[str] = []
    for path in snapshots[:max(0, len(snapshots) - int(keep))]:
        try:
            os.remove(path)
            removed.append(path)
        except OSError as e:          # a snapshot we cannot remove is reported, not hidden
            logger.warning("could not rotate backup %s: %s", path, e)
    return removed


def migrate_database(src: str) -> Dict[str, Any]:
    """Backup ``src``, apply pending schema migrations, record product meta.

    Existing episode/belief ids are not rewritten. The live production
    database must not be passed from tests; callers choose the path.
    """
    if not src or not os.path.exists(src):
        return {"error": f"missing database {src}"}
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = src + f".pre-hippa-{ts}.bak"
    backup_sqlite(src, backup)
    db = Database(src)
    health = db.health()

    def _meta(conn: sqlite3.Connection) -> Dict[str, Any]:
        row = conn.execute(
            "SELECT product_name, formerly FROM product_meta WHERE id = 1"
        ).fetchone()
        return dict(row) if row else {}

    meta = db._run(_meta) or {}
    return {
        "backup": backup,
        "path": src,
        "product_name": meta.get("product_name") or "Hungry Hippa",
        "formerly": meta.get("formerly") or "Living Cortex",
        "counts": health.get("counts", {}),
    }
