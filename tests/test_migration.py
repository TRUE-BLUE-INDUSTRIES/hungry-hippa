"""Hungry Hippa migration and compatibility tests (Phase 2).

Throwaway directories only. Never opens the operator's own database.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import warnings
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent


sys.path.insert(0, str(Path(__file__).resolve().parent))   # tests/ (shared helpers)
from _package import import_package  # noqa: E402

PACKAGE_DIR = REPO_DIR / "src" / "hungry_hippa"   # src layout
_PLUGIN = import_package()


def _clear_db_env():
    os.environ.pop("HUNGRY_HIPPA_DB", None)
    os.environ.pop("LIVING_CORTEX_DB", None)


def test_hungry_hippa_db_env_wins():
    _clear_db_env()
    path = os.path.join(tempfile.gettempdir(), "hh_env_wins.db")
    os.environ["HUNGRY_HIPPA_DB"] = path
    os.environ["LIVING_CORTEX_DB"] = os.path.join(tempfile.gettempdir(), "old.db")
    try:
        from hungry_hippa.config import load_config, resolve_db_path

        cfg = load_config()
        assert resolve_db_path(cfg) == path
    finally:
        _clear_db_env()


def test_living_cortex_db_env_still_works_with_warning():
    _clear_db_env()
    path = os.path.join(tempfile.gettempdir(), "lc_compat.db")
    os.environ["LIVING_CORTEX_DB"] = path
    try:
        from hungry_hippa.config import load_config, resolve_db_path

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            cfg = load_config()
            assert resolve_db_path(cfg) == path
        assert any("LIVING_CORTEX_DB" in str(w.message) for w in caught), caught
    finally:
        _clear_db_env()


def test_existing_living_cortex_file_is_discovered():
    from hungry_hippa.config import discover_default_db_path

    home = Path(tempfile.mkdtemp(prefix="hh_disc_"))
    old = home / "living_cortex.db"
    old.write_bytes(b"sqlite-placeholder")
    assert discover_default_db_path(home) == str(old)
    assert Path(discover_default_db_path(home)).name == "living_cortex.db"


def test_new_install_defaults_to_hungry_hippa_db():
    from hungry_hippa.config import discover_default_db_path

    home = Path(tempfile.mkdtemp(prefix="hh_new_"))
    path = discover_default_db_path(home)
    assert path.endswith("hungry_hippa.db")
    assert not Path(path).exists()


def test_migrate_backs_up_and_preserves_memories():
    from hungry_hippa.config import load_config
    from hungry_hippa.controller import MemoryController
    from hungry_hippa.db import migrate_database

    tmp = tempfile.mkdtemp(prefix="hh_mig_")
    src = os.path.join(tmp, "living_cortex.db")
    for f in (src, src + "-wal", src + "-shm"):
        if os.path.exists(f):
            os.remove(f)

    cfg = load_config()
    cfg["retrieval"]["vectors_enabled"] = False
    c = MemoryController(cfg, db_path=src)
    c.bind_session(session_id="mig-test", platform="cli")
    remembered = c.remember_episode(
        context="migration probe: cracked bracket decision",
        user_request="fix the bracket",
        actions_taken="larger fillet",
        outcome="failure",
        project="mig_probe",
        embed=False,
    )
    belief = c.semantic.add_belief(
        "4mm fillet failed on this bracket",
        kind="fact",
        confidence=0.9,
        source_class="user_explicit",
        session_id="mig-test",
    )
    episode_id = remembered["episode_id"]
    belief_id = belief["belief_id"]

    report = migrate_database(src)
    assert report.get("backup"), report
    assert os.path.isfile(report["backup"]), report
    assert os.path.getsize(report["backup"]) > 0
    assert report.get("product_name") == "Hungry Hippa"
    assert "Living Cortex" in (report.get("formerly") or "")

    conn = sqlite3.connect(src)
    try:
        versions = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
        assert 3 in versions, versions
        ep = conn.execute(
            "SELECT context, outcome FROM episodes WHERE episode_id = ?",
            (episode_id,),
        ).fetchone()
        assert ep is not None
        assert "cracked bracket" in ep[0]
        assert ep[1] == "failure"
        bel = conn.execute(
            "SELECT claim FROM beliefs WHERE belief_id = ?",
            (belief_id,),
        ).fetchone()
        assert bel is not None
        assert "4mm fillet failed" in bel[0]
        meta = conn.execute(
            "SELECT product_name, formerly FROM product_meta WHERE id = 1"
        ).fetchone()
        assert meta[0] == "Hungry Hippa"
        assert "Living Cortex" in meta[1]
    finally:
        conn.close()


def test_v6_ingest_tables_and_down_sql():
    """Schema v6 adds ingest tables; down_sql removes them and leaves episodes."""
    from hungry_hippa.schema import CURRENT_VERSION, MIGRATIONS
    from hungry_hippa.db import Database

    assert CURRENT_VERSION == 7, CURRENT_VERSION
    assert 6 in MIGRATIONS and MIGRATIONS[6]["down"].strip(), MIGRATIONS.keys()
    assert "ingest_turns" in MIGRATIONS[6]["up"]
    assert "episodes" not in MIGRATIONS[6]["up"] or "CREATE TABLE episodes" not in MIGRATIONS[6]["up"]

    path = os.path.join(tempfile.mkdtemp(prefix="hh_mig_v6_"), "hungry_hippa.db")
    Database(path)
    conn = sqlite3.connect(path)
    try:
        versions = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
        assert 6 in versions, versions
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert "ingest_archives" in tables and "ingest_conversations" in tables
        assert "ingest_turns" in tables and "episodes" in tables
        conn.execute(
            "INSERT INTO episodes(episode_id, ts_start, ts_end, context, outcome,"
            " importance, confidence, status, created_at, updated_at)"
            " VALUES ('E-mig6','2020-01-01T00:00:00Z','2020-01-01T00:00:00Z',"
            " 'v6 down must not drop me','success',0.5,0.5,'active',"
            " '2020-01-01T00:00:00Z','2020-01-01T00:00:00Z')"
        )
        conn.executescript(MIGRATIONS[7]["down"])
        conn.executescript(MIGRATIONS[6]["down"])
        tables_after = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert "ingest_turns" not in tables_after
        assert "episodes" in tables_after
        kept = conn.execute(
            "SELECT context FROM episodes WHERE episode_id = 'E-mig6'"
        ).fetchone()
        assert kept and "v6 down must not drop me" in kept[0]
    finally:
        conn.close()
    return "v6 up creates ingest tables; down_sql drops them; episodes remain"


def test_rollback_instructions_exist():
    doc = (REPO_DIR / "docs" / "MIGRATION.md").read_text(encoding="utf-8")
    assert "Rollback" in doc
    assert "living_cortex.db" in doc
    assert "Hungry Hippa" in doc
    assert "formerly living cortex" in doc.lower()


def test_implicit_open_backs_up_before_upgrading():
    """Opening an old database must not upgrade it without a backup first.

    Regression: `migrate_database()` backed up, but an ordinary `Database()`
    open (status, plugin start, MCP server startup) ran the pending migration
    scripts directly, so a discovered old database could be upgraded before the
    operator ever ran the documented backup command.
    """
    from hungry_hippa import schema as _schema
    from hungry_hippa.db import Database

    with tempfile.TemporaryDirectory(prefix="hh_mig_implicit_") as tmp:
        path = os.path.join(tmp, "old.db")
        conn = sqlite3.connect(path)
        conn.execute(
            "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY,"
            " applied_at TEXT NOT NULL, description TEXT NOT NULL,"
            " down_sql TEXT NOT NULL DEFAULT '')"
        )
        for version in (1, 2, 3):
            mig = _schema.MIGRATIONS[version]
            conn.executescript(mig["up"])
            conn.execute("INSERT INTO schema_migrations VALUES (?,?,?,?)",
                         (version, "2020-01-01T00:00:00Z", mig["description"], mig["down"]))
        conn.commit()
        conn.close()

        db = Database(path)  # ordinary open, exactly what status/startup does
        backups = [f for f in os.listdir(tmp) if f.endswith(".bak")]
        assert backups, "implicit migration created no backup"
        assert db.last_backup and db.last_backup.endswith(".bak"), db.last_backup

        # the backup must not be more permissive than the database it copies
        with tempfile.TemporaryDirectory(prefix="hh_mig_perm_") as pdir:
            p2 = os.path.join(pdir, "old.db")
            conn = sqlite3.connect(p2)
            conn.execute(
                "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY,"
                " applied_at TEXT NOT NULL, description TEXT NOT NULL,"
                " down_sql TEXT NOT NULL DEFAULT '')"
            )
            for version in (1, 2, 3):
                mig = _schema.MIGRATIONS[version]
                conn.executescript(mig["up"])
                conn.execute("INSERT INTO schema_migrations VALUES (?,?,?,?)",
                             (version, "2020-01-01T00:00:00Z", mig["description"],
                              mig["down"]))
            conn.commit()
            conn.close()
            os.chmod(p2, 0o600)
            db2 = Database(p2)
            assert db2.last_backup, "no backup on the permission check"
            mode = os.stat(db2.last_backup).st_mode & 0o777
            assert mode & 0o077 == 0, f"backup is readable by others: {oct(mode)}"
            assert mode == 0o600, oct(mode)

        conn = sqlite3.connect(db.last_backup)
        try:
            versions = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
        finally:
            conn.close()
        assert versions == {1, 2, 3}, f"backup is not the pre-migration state: {versions}"

        conn = sqlite3.connect(path)
        try:
            after = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
        finally:
            conn.close()
        assert after >= {1, 2, 3, 4}, after

        # a second open has nothing pending: no new backup files pile up
        before = len([f for f in os.listdir(tmp) if f.endswith(".bak")])
        Database(path)
        after_count = len([f for f in os.listdir(tmp) if f.endswith(".bak")])
        assert before == after_count, "a fully-migrated database produced another backup"

        # a brand-new database is not backed up (nothing to lose)
        fresh_dir = tempfile.mkdtemp(prefix="hh_mig_fresh_")
        Database(os.path.join(fresh_dir, "new.db"))
        assert not [f for f in os.listdir(fresh_dir) if f.endswith(".bak")], \
            "new database was backed up"

    return "implicit migration backs up first; no backup on new or current databases"


def run_all() -> list:
    results = []

    def check(name, fn):
        try:
            detail = fn() or "ok"
            results.append({"name": name, "passed": True, "detail": str(detail)[:300]})
        except AssertionError as e:
            results.append({"name": name, "passed": False, "detail": f"assert: {e}"})
        except Exception as e:
            results.append(
                {"name": name, "passed": False, "detail": f"{type(e).__name__}: {e}"}
            )

    check("hungry_hippa_db_env_wins", test_hungry_hippa_db_env_wins)
    check(
        "living_cortex_db_env_still_works_with_warning",
        test_living_cortex_db_env_still_works_with_warning,
    )
    check("existing_living_cortex_file_is_discovered", test_existing_living_cortex_file_is_discovered)
    check("new_install_defaults_to_hungry_hippa_db", test_new_install_defaults_to_hungry_hippa_db)
    check("migrate_backs_up_and_preserves_memories", test_migrate_backs_up_and_preserves_memories)
    check("implicit_open_backs_up_before_upgrading",
          test_implicit_open_backs_up_before_upgrading)
    check("rollback_instructions_exist", test_rollback_instructions_exist)
    check("v6_ingest_tables_and_down_sql", test_v6_ingest_tables_and_down_sql)
    return results


if __name__ == "__main__":
    results = run_all()
    passed = sum(1 for r in results if r["passed"])
    for r in results:
        print(f"{'PASS' if r['passed'] else 'FAIL'}  {r['name']}: {r['detail']}")
    print(f"\n{passed}/{len(results)} passed")
    sys.exit(0 if passed == len(results) else 1)
