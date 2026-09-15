"""SQLite access layer for the Living Cortex.

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
import sqlite3
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from . import schema as _schema

logger = logging.getLogger("living_cortex.db")

_ID_PREFIX = {
    "episode": "E", "entity": "EN", "relationship": "R", "belief": "B",
    "procedure": "P", "evidence": "EV", "vector": "V", "consolidation": "CR",
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
        self._lock = threading.Lock()
        self._ensure_schema()

    # ------------------------------------------------------------- infra

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
            conn = self._connect()
            try:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS schema_migrations ("
                    "version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL,"
                    "description TEXT NOT NULL, down_sql TEXT NOT NULL DEFAULT '')"
                )
                applied = {r["version"] for r in conn.execute("SELECT version FROM schema_migrations")}
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
        def _log(conn: sqlite3.Connection) -> None:
            conn.execute(
                "INSERT INTO mutation_log(ts, action, target_kind, target_id, detail, session_id)"
                " VALUES (?,?,?,?,?,?)",
                (now_iso(), action, target_kind, target_id, detail[:2000], session_id),
            )

        self._run(_log, write=True)

    def add_evidence(self, content: str, kind: str = "hermes_inference",
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
            }

        return self._run(_h) or {"path": self.path, "counts": {}, "failures": self.failures}


def backup_sqlite(src: str, dest: str) -> None:
    """Consistent SQLite backup (API, not file copy) so WAL is included."""
    parent = os.path.dirname(os.path.abspath(dest))
    if parent:
        os.makedirs(parent, exist_ok=True)
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
