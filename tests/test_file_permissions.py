"""File-permission tests for the database, backups and exports.

Finding: a fresh database was created mode 0644, and (after the first fix)
backups inherited the source mode — so a world-readable database produced a
world-readable copy of every memory, including the backup written before a
migration.

Permissions are not encryption: the files stay plaintext, and a process running
as the operator can read them. These tests cover what is actually claimed: other
local users cannot read the database, its sidecars, its backups or its exports.

run_all() -> list of {name, passed, detail}.
"""

from __future__ import annotations

import importlib.util
import json
import os
import stat
import sys
import tempfile
import types
from pathlib import Path
from typing import Any, Dict, List

PLUGIN_DIR = Path(__file__).resolve().parent.parent


def _import_plugin():
    if sys.modules.get("hungry_hippa") is not None and getattr(
        sys.modules["hungry_hippa"], "__file__", None
    ):
        return sys.modules["hungry_hippa"]
    pkg = types.ModuleType("hungry_hippa")
    pkg.__path__ = [str(PLUGIN_DIR)]
    pkg.__file__ = str(PLUGIN_DIR / "__init__.py")
    sys.modules["hungry_hippa"] = pkg
    spec = importlib.util.spec_from_file_location(
        "hungry_hippa", str(PLUGIN_DIR / "__init__.py"),
        submodule_search_locations=[str(PLUGIN_DIR)])
    mod = importlib.util.module_from_spec(spec)
    sys.modules["hungry_hippa"] = mod
    spec.loader.exec_module(mod)
    return mod


_PLUGIN = _import_plugin()
from hungry_hippa import schema as _schema  # noqa: E402
from hungry_hippa import trust  # noqa: E402
from hungry_hippa.config import load_config  # noqa: E402
from hungry_hippa.controller import MemoryController  # noqa: E402
from hungry_hippa.db import Database, backup_sqlite  # noqa: E402
from hungry_hippa.observability import Observability  # noqa: E402

POSIX = os.name == "posix"


def _mode(path: str) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


def check_new_database_is_owner_only():
    """A new database must not be created readable by other local users."""
    if not POSIX:
        return "skipped: POSIX permission bits not available"
    tmp = tempfile.mkdtemp(prefix="hh_perm_db_")
    db = os.path.join(tmp, "hungry_hippa.db")
    ctrl = MemoryController(load_config(), db_path=db)
    ctrl.semantic.add_belief("a memory that should not be world readable", kind="fact")
    mode = _mode(db)
    assert mode & 0o077 == 0, f"database mode {oct(mode)} is group/other readable"
    assert mode == 0o600, oct(mode)
    return f"new database mode {oct(mode)}"


def check_backup_is_never_wider_than_owner_only():
    """A world-readable source must not produce a world-readable backup."""
    if not POSIX:
        return "skipped: POSIX permission bits not available"
    tmp = tempfile.mkdtemp(prefix="hh_perm_bak_")
    src = os.path.join(tmp, "old.db")
    Database(src)
    # simulate the operator's existing lax database
    os.chmod(src, 0o644)
    dest = os.path.join(tmp, "copy.db")
    backup_sqlite(src, dest)
    mode = _mode(dest)
    assert mode & 0o077 == 0, f"backup mode {oct(mode)} inherited a world-readable source"
    assert mode == 0o600, oct(mode)
    # and a restrictive source stays restrictive
    os.chmod(src, 0o600)
    dest2 = os.path.join(tmp, "copy2.db")
    backup_sqlite(src, dest2)
    assert _mode(dest2) == 0o600, oct(_mode(dest2))
    return f"0644 source -> backup {oct(mode)}; 0600 source -> backup 0600"


def check_implicit_migration_backup_is_private():
    """The pre-migration copy is owner-only even from a lax database."""
    if not POSIX:
        return "skipped: POSIX permission bits not available"
    tmp = tempfile.mkdtemp(prefix="hh_perm_mig_")
    path = os.path.join(tmp, "old.db")
    import sqlite3
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY,"
        " applied_at TEXT NOT NULL, description TEXT NOT NULL,"
        " down_sql TEXT NOT NULL DEFAULT '')")
    for version in (1, 2, 3):
        mig = _schema.MIGRATIONS[version]
        conn.executescript(mig["up"])
        conn.execute("INSERT INTO schema_migrations VALUES (?,?,?,?)",
                     (version, "2020-01-01T00:00:00Z", mig["description"], mig["down"]))
    conn.commit()
    conn.close()
    os.chmod(path, 0o644)
    db = Database(path)
    assert db.last_backup, "no backup written"
    mode = _mode(db.last_backup)
    assert mode & 0o077 == 0, f"migration backup mode {oct(mode)}"
    return f"pre-migration backup mode {oct(mode)} from a 0644 source"


def check_lax_database_is_reported_not_silently_changed():
    """An existing lax file is warned about, not chmod-ed behind the operator."""
    if not POSIX:
        return "skipped: POSIX permission bits not available"
    tmp = tempfile.mkdtemp(prefix="hh_perm_warn_")
    path = os.path.join(tmp, "hungry_hippa.db")
    Database(path)
    os.chmod(path, 0o644)
    db = Database(path)
    perms = db.file_permissions()
    assert db.permissions_lax is True, perms
    assert perms["lax"] is True, perms
    assert "fix-permissions" in db.permissions_warning, db.permissions_warning
    assert _mode(path) == 0o644, "the runtime changed the mode without being asked"
    # and the health/status surface reports it
    health = db.health()
    assert health["permissions"]["lax"] is True, health.get("permissions")
    assert "not encryption" in json.dumps(health["permissions"]).lower(), health
    return f"lax mode {oct(_mode(path))} reported with a remediation hint, unchanged"


def check_export_file_is_owner_only():
    """A full export must not be world-readable."""
    if not POSIX:
        return "skipped: POSIX permission bits not available"
    tmp = tempfile.mkdtemp(prefix="hh_perm_exp_")
    db = os.path.join(tmp, "hungry_hippa.db")
    ctrl = MemoryController(load_config(), db_path=db)
    ctrl.bind_session(session_id="s", platform="cli", trust=trust.local_binding())
    obs = Observability(ctrl.db, ctrl.cfg, controller=ctrl)
    out_path = os.path.join(tempfile.mkdtemp(prefix="hh_perm_expout_"), "dump.json")
    result = obs.export(out_path, "all")
    assert "exported" in result, result
    mode = _mode(out_path)
    assert mode & 0o077 == 0, f"export mode {oct(mode)} is readable by others"
    return f"export mode {oct(mode)}"


def check_fix_permissions_remediates():
    """The documented remediation tightens the db, sidecars and backups."""
    if not POSIX:
        return "skipped: POSIX permission bits not available"
    import types as _types

    tmp = tempfile.mkdtemp(prefix="hh_perm_fix_")
    path = os.path.join(tmp, "hungry_hippa.db")
    Database(path)
    backup = path + ".pre-migration-20200101T000000Z.bak"
    backup_sqlite(path, backup)
    for target in (path, backup):
        os.chmod(target, 0o644)

    from hungry_hippa.cli import _cmd_fix_permissions

    _cmd_fix_permissions(_types.SimpleNamespace(db=path))
    assert _mode(path) == 0o600, oct(_mode(path))
    assert _mode(backup) == 0o600, oct(_mode(backup))
    return "db and backup tightened to 0600 by the documented command"


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

    check("new_database_is_owner_only", check_new_database_is_owner_only)
    check("backup_is_never_wider_than_owner_only",
          check_backup_is_never_wider_than_owner_only)
    check("implicit_migration_backup_is_private",
          check_implicit_migration_backup_is_private)
    check("lax_database_is_reported_not_silently_changed",
          check_lax_database_is_reported_not_silently_changed)
    check("export_file_is_owner_only", check_export_file_is_owner_only)
    check("fix_permissions_remediates", check_fix_permissions_remediates)
    return results


if __name__ == "__main__":
    results = run_all()
    passed = sum(1 for r in results if r["passed"])
    for r in results:
        print(f"{'PASS' if r['passed'] else 'FAIL'}  {r['name']}: {r['detail']}")
    print(f"\n{passed}/{len(results)} passed")
    sys.exit(0 if passed == len(results) else 1)
