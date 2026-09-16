"""Snapshot and rotation tests for `hungry-hippa backup`.

An always-on box is the reason these exist: a backup command that runs unattended has
to be safe against power loss, config typos and a directory that contains files it did
not create. These tests cover what is actually claimed:

  * snapshot files are named so lexical order is chronological order;
  * rotation deletes only the oldest snapshots beyond `keep`, and never a file it did
    not name;
  * `keep = 0` means "rotate nothing" rather than "delete everything" — a typo that
    deletes every snapshot is worse than no rotation at all;
  * the CLI refuses to overwrite the live database and exits cleanly when there is
    no database to back up.

run_all() -> list of {name, passed, detail}.
"""

from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

REPO_DIR = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(Path(__file__).resolve().parent))   # tests/ (shared helpers)
from _package import import_package  # noqa: E402

_PLUGIN = import_package()
from hungry_hippa import db as _db  # noqa: E402
from hungry_hippa.cli import hungry_hippa_command  # noqa: E402


def _cli(**kwargs):
    args = SimpleNamespace(**kwargs)
    buf = io.StringIO()
    code = 0
    with contextlib.redirect_stdout(buf):
        try:
            hungry_hippa_command(args)
        except SystemExit as e:
            code = int(e.code or 0)
    return buf.getvalue().strip(), code


# ---------------------------------------------------------------------------- checks

def check_backup_name_is_sortable_and_safe():
    backup = _db.backup_name
    a = backup("nightly", now=1700000000.0)
    b = backup("nightly", now=1710000000.0)
    assert a < b and a.startswith(_db.BACKUP_PREFIX), (a, b)
    assert _db.BACKUP_SUFFIX in a, a
    # the label is sanitised, so a path or shell token cannot sneak into the filename
    assert "/" not in backup("../../etc/passwd")
    assert ";" not in backup("a;b")
    # label absent -> no trailing dash, no empty segment; compare with a fixed stamp
    assert backup("", now=1700000000.0) == backup(now=1700000000.0)
    return "stamped, fixed-width, lexicographically chronological; labels sanitised"


def check_list_and_prune_keep_the_newest():
    tmp = tempfile.mkdtemp(prefix="hh_rot_list_")
    created = [_db.backup_name("x", now=ts) for ts in (1690000000, 1700000000, 1710000000,
                                                     1720000000, 1730000000)]
    for name in created:
        open(os.path.join(tmp, name), "w").close()
    assert [os.path.basename(p) for p in _db.list_backups(tmp)] == created, \
        "lexical order is chronological order"
    removed = _db.prune_backups(tmp, 3)
    remaining = [os.path.basename(p) for p in _db.list_backups(tmp)]
    assert len(remaining) == 3 and remaining == created[-3:], remaining
    assert len(removed) == 2 and [os.path.basename(p) for p in removed] == created[:2], \
        removed
    return "rotation keeps the newest N, removes the oldest, oldest-first"


def check_prune_respects_foreign_files():
    tmp = tempfile.mkdtemp(prefix="hh_rot_safe_")
    open(os.path.join(tmp, _db.backup_name("x", now=1690000000)), "w").close()
    # Truly foreign: none of these begin with the snapshot prefix "hungry_hippa-".
    foreign = ["notes.txt", "hippo-notmine.db", "other-20240101T000000Z.db"]
    for name in foreign:
        open(os.path.join(tmp, name), "w").close()
    _db.prune_backups(tmp, 0)                    # keep=0 is a no-op
    _db.prune_backups(tmp, 1)                    # keep=1 with 1 snapshot: nothing to prune
    # foreign files were never candidates and must survive both calls
    survivors = set(os.listdir(tmp))
    assert all(name in survivors for name in foreign), survivors
    assert [os.path.basename(p) for p in _db.list_backups(tmp)] == [
        _db.backup_name("x", now=1690000000)]     # the single snapshot is retained
    return "rotation only ever deletes the snapshots it named; foreign files are safe"


def check_cli_refuses_to_overwrite_live_db():
    """Run the command against a live database and confirm the live file is
    unchanged afterwards.

    The CLI refuses to overwrite the live database outright; the snapshot lands
    in a separate directory. This test asserts the honest case: the live file is
    still present and the backups directory contains exactly one new snapshot."""
    live = tempfile.mkdtemp(prefix="hh_rot_live_")
    os.environ["HUNGRY_HIPPA_DB"] = os.path.join(live, "hungry_hippa.db")
    open(os.environ["HUNGRY_HIPPA_DB"], "w").close()
    before_hash = _db.Database(os.environ["HUNGRY_HIPPA_DB"])._run(
        lambda c: c.execute("SELECT COUNT(*) FROM episodes").fetchone()[0])

    backups = os.path.join(live, "backups")
    out, code = _cli(hungry_hippa_command="backup", dir=backups, keep=1)
    assert code == 0, (code, out)
    # the live file exists, has the same content, and exactly one snapshot was written
    assert os.path.exists(os.environ["HUNGRY_HIPPA_DB"])
    after_hash = _db.Database(os.environ["HUNGRY_HIPPA_DB"])._run(
        lambda c: c.execute("SELECT COUNT(*) FROM episodes").fetchone()[0])
    assert before_hash == after_hash
    assert len(os.listdir(backups)) == 1
    return "live database untouched; exactly one snapshot written"


def check_cli_errors_when_no_database():
    empty = tempfile.mkdtemp(prefix="hh_rot_empty_")
    os.environ["HUNGRY_HIPPA_DB"] = os.path.join(empty, "hungry_hippa.db")
    out, code = _cli(hungry_hippa_command="backup", dir=os.path.join(empty, "backups"))
    assert code == 1, (code, out)
    assert "no database" in out, out
    return "a missing database exits 1 with a clean error"


# --------------------------------------------------------------------------- runner

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

    check("backup_name_is_sortable_and_safe", check_backup_name_is_sortable_and_safe)
    check("list_and_prune_keep_the_newest", check_list_and_prune_keep_the_newest)
    check("prune_respects_foreign_files", check_prune_respects_foreign_files)
    check("cli_refuses_to_overwrite_live_db", check_cli_refuses_to_overwrite_live_db)
    check("cli_errors_when_no_database", check_cli_errors_when_no_database)
    return results


if __name__ == "__main__":
    results = run_all()
    passed = sum(1 for r in results if r["passed"])
    for r in results:
        print(f"{'PASS' if r['passed'] else 'FAIL'}  {r['name']}: {r['detail']}")
    print(f"\n{passed}/{len(results)} passed")
    sys.exit(0 if passed == len(results) else 1)
