"""Canonical ingest store (Slice 2): archive pointers + conversation/turn tables.

Raw history is not memory. These tests fail if persist writes ``episodes``,
reuses evidence, or extracts beliefs. Throwaway directories only.

run_all() -> list of {name, passed, detail}.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List

REPO_DIR = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _package import import_package  # noqa: E402

PACKAGE_DIR = REPO_DIR / "src" / "hungry_hippa"
_PLUGIN = import_package()

from hungry_hippa.ingest import parse_chatgpt_export  # noqa: E402
from hungry_hippa.ingest.store import (  # noqa: E402
    ArchivePointer,
    inspect_archive,
    persist_conversation,
    persist_parsed_export,
)


def _fresh_db() -> str:
    from hungry_hippa.db import Database

    path = os.path.join(tempfile.mkdtemp(prefix="hh_ingest_store_"), "hungry_hippa.db")
    Database(path)
    return path


def _db(path: str):
    from hungry_hippa.db import Database

    return Database(path)


def _message(role: str, text: Any, *, create_time: Any = 1_700_000_000.0) -> Dict[str, Any]:
    return {"author": {"role": role},
            "content": {"content_type": "text", "parts": [text]},
            "create_time": create_time, "id": ""}


def _node(node_id: str, parent: Any = None, children: Any = None,
          message: Any = None) -> Dict[str, Any]:
    return {"id": node_id, "parent": parent, "children": children or [],
            "message": message}


def _write(payload: Any, name: str = "conversations.json") -> str:
    where = tempfile.mkdtemp(prefix="hh_ingest_store_export_")
    path = os.path.join(where, name)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    return path


def _linear_export() -> List[Dict[str, Any]]:
    mapping = {
        "root": _node("root", None, ["n-a"]),
        "n-a": _node("n-a", "root", ["n-b"],
                     _message("user", "how do I hang a 4x12 on a metal stud wall?")),
        "n-b": _node("n-b", "n-a", [],
                     _message("assistant", "Frame, insulate, then hang from the top down.")),
    }
    return [{"id": "conv-linear", "title": "Hanging board",
             "create_time": 1_699_000_000.0, "update_time": 1_699_000_060.0,
             "current_node": "n-b", "mapping": mapping}]


def _regen_export() -> List[Dict[str, Any]]:
    mapping = {
        "root": _node("root", None, ["n-a"]),
        "n-a": _node("n-a", "root", ["n-b1", "n-b2"],
                     _message("user", "what solvent frees a seized housing?",
                              create_time=1_700_000_100.0)),
        "n-b1": _node("n-b1", "n-a", [],
                      _message("assistant", "Try heat first.",
                               create_time=1_700_000_200.0)),
        "n-b2": _node("n-b2", "n-a", ["n-c"],
                      _message("assistant", "Soak it in solvent X for twenty minutes.",
                               create_time=1_700_000_300.0)),
        "n-c": _node("n-c", "n-b2", [],
                     _message("user", "it cracked", create_time=1_700_000_400.0)),
    }
    return [{"id": "conv-regen", "title": "Seized housing",
             "create_time": 1_699_000_000.0, "update_time": 1_699_000_060.0,
             "current_node": "n-c", "mapping": mapping}]


def _episode_count(path: str) -> int:
    conn = sqlite3.connect(path)
    try:
        return conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
    finally:
        conn.close()


def _table_names(path: str) -> set:
    conn = sqlite3.connect(path)
    try:
        return {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()


def check_v6_tables_exist_on_fresh_db():
    from hungry_hippa.schema import CURRENT_VERSION

    path = _fresh_db()
    assert CURRENT_VERSION >= 6, CURRENT_VERSION
    tables = _table_names(path)
    for name in ("ingest_archives", "ingest_conversations", "ingest_turns"):
        assert name in tables, (name, tables)
    assert "episodes" in tables
    conn = sqlite3.connect(path)
    try:
        versions = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
    finally:
        conn.close()
    assert versions >= {1, 2, 3, 4, 5, 6}, versions
    return "fresh database is schema v6+ with ingest tables plus episodes"


def check_v5_database_migrates_and_keeps_episodes():
    from hungry_hippa import schema as _schema
    from hungry_hippa.db import Database

    tmp = tempfile.mkdtemp(prefix="hh_ingest_v5_")
    path = os.path.join(tmp, "old.db")
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY,"
        " applied_at TEXT NOT NULL, description TEXT NOT NULL,"
        " down_sql TEXT NOT NULL DEFAULT '')"
    )
    for version in (1, 2, 3, 4, 5):
        mig = _schema.MIGRATIONS[version]
        conn.executescript(mig["up"])
        conn.execute("INSERT INTO schema_migrations VALUES (?,?,?,?)",
                     (version, "2020-01-01T00:00:00Z", mig["description"], mig["down"]))
    conn.execute(
        "INSERT INTO episodes(episode_id, ts_start, ts_end, context, outcome,"
        " importance, confidence, status, created_at, updated_at)"
        " VALUES ('E-v5','2020-01-01T00:00:00Z','2020-01-01T00:00:00Z',"
        " 'pre-v6 episode must survive','success',0.5,0.5,'active',"
        " '2020-01-01T00:00:00Z','2020-01-01T00:00:00Z')"
    )
    conn.commit()
    conn.close()

    db = Database(path)
    assert db.last_backup and db.last_backup.endswith(".bak"), db.last_backup
    conn = sqlite3.connect(path)
    try:
        versions = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
        assert 6 in versions, versions
        row = conn.execute(
            "SELECT context FROM episodes WHERE episode_id = 'E-v5'"
        ).fetchone()
        assert row and "pre-v6 episode must survive" in row[0], row
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert "ingest_turns" in tables and "ingest_conversations" in tables
        assert conn.execute("SELECT COUNT(*) FROM ingest_turns").fetchone()[0] == 0
    finally:
        conn.close()
    return "v5 database upgrades to v6; existing episode kept; ingest tables empty"


def check_persist_uses_ingest_tables_not_episodes():
    path = _fresh_db()
    db = _db(path)
    export = _write(_regen_export())
    conversations = parse_chatgpt_export(export)
    before = _episode_count(path)
    result = persist_parsed_export(db, conversations, source_path=export)
    assert result.ok, result.error
    assert result.turns_inserted == 4, result
    assert result.conversations_inserted == 1, result
    assert _episode_count(path) == before
    conn = sqlite3.connect(path)
    try:
        turns = conn.execute(
            "SELECT turn_id, role, content FROM ingest_turns ORDER BY rowid"
        ).fetchall()
        assert [t[0] for t in turns] == ["n-a", "n-b1", "n-b2", "n-c"], turns
        assert turns[1][2] == "Try heat first."
        episodes = conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
        evidence = conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]
        fts = conn.execute("SELECT COUNT(*) FROM memory_fts").fetchone()[0]
        assert episodes == 0 and evidence == 0 and fts == 0
        archived = conn.execute(
            "SELECT original_path, sha256, byte_length, archived_path FROM ingest_archives"
        ).fetchone()
        assert archived is not None
        assert archived[0] == os.path.abspath(export)
        raw = open(export, "rb").read()
        assert archived[1] == hashlib.sha256(raw).hexdigest()
        assert archived[2] == len(raw)
        assert archived[3] == ""
        # the file bytes themselves are not in sqlite
        blobs = " ".join(
            str(r[0]) for r in conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name LIKE 'ingest_%'"
            )
        )
        assert "content TEXT" in blobs  # turn text, not the archive
    finally:
        conn.close()
    stored = db.get_ingest_conversation("chatgpt", "conv-regen")
    assert stored is not None
    assert stored["title"] == "Seized housing"
    assert stored["current_path_turn_ids"] == ["n-a", "n-b2", "n-c"]
    turns = db.get_ingest_turns("chatgpt", "conv-regen")
    b1 = next(t for t in turns if t["turn_id"] == "n-b1")
    assert b1["on_current_path"] == 0
    assert b1["parent_turn_id"] == "n-a"
    assert b1["branch_path"] == ("root", "n-a", "n-b1")
    return "persist wrote ingest_* only; episodes/evidence/fts untouched"


def check_idempotent_on_source_session_turn():
    path = _fresh_db()
    db = _db(path)
    export = _write(_linear_export())
    conversations = parse_chatgpt_export(export)
    first = persist_parsed_export(db, conversations, source_path=export)
    second = persist_parsed_export(db, conversations, source_path=export)
    assert first.ok and second.ok, (first.error, second.error)
    assert first.turns_inserted == 2 and first.conversations_inserted == 1
    assert second.turns_inserted == 0 and second.conversations_inserted == 0
    assert second.archive_inserted is False
    assert db.ingest_counts() == {
        "ingest_archives": 1,
        "ingest_conversations": 1,
        "ingest_turns": 2,
    }
    # same conversation, extra turn id: only the new row is inserted
    from hungry_hippa.ingest.models import ParsedConversation, NormalizedTurn

    grafted = ParsedConversation(
        source="chatgpt",
        session_id="conv-linear",
        title="Hanging board",
        turns=conversations[0].turns + (
            NormalizedTurn(
                source="chatgpt", session_id="conv-linear",
                session_title="Hanging board", turn_id="n-extra",
                parent_turn_id="n-b", role="user", content="and then tape it",
                occurred_at=1_700_000_500.0, branch_path=("root", "n-a", "n-b", "n-extra"),
                source_metadata={"on_current_path": True},
            ),
        ),
        current_path_turn_ids=conversations[0].current_path_turn_ids + ("n-extra",),
        current_path_node_ids=conversations[0].current_path_node_ids + ("n-extra",),
        current_node="n-extra",
        created_at=conversations[0].created_at,
        updated_at=conversations[0].updated_at,
    )
    third = persist_conversation(
        db, grafted, archive=ArchivePointer(
            original_path=first.original_path, sha256=first.sha256,
            byte_length=first.byte_length, source="chatgpt",
        ),
    )
    assert third.ok, third.error
    assert third.turns_inserted == 1, third
    assert third.conversations_inserted == 0
    assert db.ingest_counts()["ingest_turns"] == 3
    stored = db.get_ingest_conversation("chatgpt", "conv-linear")
    assert stored["current_path_turn_ids"][-1] == "n-extra"
    return "re-persist is a no-op; a new turn_id inserts one row"


def check_transaction_rolls_back():
    path = _fresh_db()
    db = _db(path)
    export = _write(_linear_export())
    pointer = inspect_archive(export)

    def boom(conn):
        conn.execute(
            "INSERT INTO ingest_archives("
            "archive_id, source, original_path, sha256, byte_length, archived_path, captured_at)"
            " VALUES ('IA-boom','chatgpt',?,?,0,'','2020-01-01T00:00:00Z')",
            (pointer.original_path, pointer.sha256),
        )
        raise RuntimeError("forced failure")

    assert db._run(boom, write=True) is None
    assert db.ingest_counts()["ingest_archives"] == 0
    result = persist_parsed_export(db, parse_chatgpt_export(export), source_path=export)
    assert result.ok, result.error
    assert db.ingest_counts()["ingest_turns"] == 2
    return "failed persist transaction leaves no ingest rows; a later persist works"


def check_archive_hash_is_chunked_and_matches():
    payload = _linear_export()
    export = _write(payload)
    raw = open(export, "rb").read()
    pointer = inspect_archive(export)
    assert pointer.sha256 == hashlib.sha256(raw).hexdigest()
    assert pointer.byte_length == len(raw)
    assert pointer.original_path == os.path.abspath(export)
    try:
        inspect_archive(os.path.dirname(export))
        raise AssertionError("directory was accepted")
    except IsADirectoryError:
        pass
    return "sha256/length match file bytes; directories refused"


def check_optional_copy_is_0600():
    path = _fresh_db()
    db = _db(path)
    export = _write(_linear_export())
    archive_dir = os.path.join(tempfile.mkdtemp(prefix="hh_ingest_arc_"), "copies")
    result = persist_parsed_export(
        db, parse_chatgpt_export(export), source_path=export, copy_to=archive_dir,
    )
    assert result.ok, result.error
    assert result.archived_path
    assert os.path.isfile(result.archived_path)
    mode = os.stat(result.archived_path).st_mode & 0o777
    assert mode == 0o600, oct(mode)
    copied = open(result.archived_path, "rb").read()
    assert hashlib.sha256(copied).hexdigest() == result.sha256
    row = db.get_ingest_archive(result.sha256)
    assert row["archived_path"] == result.archived_path
    # a symlink at the destination is refused, not followed
    other = os.path.join(archive_dir, "elsewhere")
    with open(other, "wb") as fh:
        fh.write(b"not-the-archive")
    decoy_dir = tempfile.mkdtemp(prefix="hh_ingest_link_")
    os.symlink(other, os.path.join(decoy_dir, result.sha256))
    failed = persist_parsed_export(
        db, parse_chatgpt_export(export), source_path=export, copy_to=decoy_dir,
    )
    assert failed.ok is False, failed
    assert "symlink" in failed.error.lower() or "OSError" in failed.error, failed.error
    return "optional archive copy is 0600; symlink destinations refused"


def check_parser_modules_do_not_import_store():
    chatgpt = (PACKAGE_DIR / "ingest" / "chatgpt.py").read_text(encoding="utf-8")
    models = (PACKAGE_DIR / "ingest" / "models.py").read_text(encoding="utf-8")
    for src in (chatgpt, models):
        assert "sqlite3" not in src
        assert "from .store" not in src
        assert "ingest.store" not in src
        assert "eval(" not in src and "exec(" not in src
    store = (PACKAGE_DIR / "ingest" / "store.py").read_text(encoding="utf-8")
    assert "eval(" not in store and "exec(" not in store
    assert "episodes" in store  # the module documents that it does not write them
    return "parser remains stdlib-only; store does not eval/exec"


def check_down_sql_drops_ingest_keeps_episodes():
    from hungry_hippa.schema import MIGRATIONS

    path = _fresh_db()
    db = _db(path)
    export = _write(_linear_export())
    persist_parsed_export(db, parse_chatgpt_export(export), source_path=export)
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "INSERT INTO episodes(episode_id, ts_start, ts_end, context, outcome,"
            " importance, confidence, status, created_at, updated_at)"
            " VALUES ('E-keep','2020-01-01T00:00:00Z','2020-01-01T00:00:00Z',"
            " 'must survive down_sql','success',0.5,0.5,'active',"
            " '2020-01-01T00:00:00Z','2020-01-01T00:00:00Z')"
        )
        conn.executescript(MIGRATIONS[6]["down"])
        conn.execute("DELETE FROM schema_migrations WHERE version = 6")
        conn.commit()
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert "ingest_turns" not in tables
        assert "ingest_conversations" not in tables
        assert "ingest_archives" not in tables
        assert "episodes" in tables
        row = conn.execute(
            "SELECT context FROM episodes WHERE episode_id = 'E-keep'"
        ).fetchone()
        assert row and "must survive down_sql" in row[0]
    finally:
        conn.close()
    # re-open reapplies v6
    db2 = _db(path)
    assert "ingest_turns" in _table_names(path)
    assert db2.ingest_counts()["ingest_turns"] == 0
    return "v6 down_sql drops ingest tables only; episodes remain; reopen reapplies v6"


def run_all() -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []

    def check(name: str, fn) -> None:
        try:
            detail = fn() or "ok"
            results.append({"name": name, "passed": True, "detail": str(detail)[:300]})
        except AssertionError as e:
            results.append({"name": name, "passed": False, "detail": f"assert: {e}"})
        except Exception as e:
            results.append({"name": name, "passed": False,
                            "detail": f"{type(e).__name__}: {e}"})

    check("v6_tables_exist_on_fresh_db", check_v6_tables_exist_on_fresh_db)
    check("v5_database_migrates_and_keeps_episodes",
          check_v5_database_migrates_and_keeps_episodes)
    check("persist_uses_ingest_tables_not_episodes",
          check_persist_uses_ingest_tables_not_episodes)
    check("idempotent_on_source_session_turn", check_idempotent_on_source_session_turn)
    check("transaction_rolls_back", check_transaction_rolls_back)
    check("archive_hash_is_chunked_and_matches", check_archive_hash_is_chunked_and_matches)
    check("optional_copy_is_0600", check_optional_copy_is_0600)
    check("parser_modules_do_not_import_store", check_parser_modules_do_not_import_store)
    check("down_sql_drops_ingest_keeps_episodes", check_down_sql_drops_ingest_keeps_episodes)
    return results


if __name__ == "__main__":
    results = run_all()
    passed = sum(1 for r in results if r["passed"])
    for r in results:
        print(f"{'PASS' if r['passed'] else 'FAIL'}  {r['name']}: {r['detail']}")
    print(f"\n{passed}/{len(results)} passed")
    sys.exit(0 if passed == len(results) else 1)
