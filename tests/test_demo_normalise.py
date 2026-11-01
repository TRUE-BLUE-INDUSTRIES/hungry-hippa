"""Demo transcript normalisation must follow the live temp directory.

The golden-transcript gate failed when TMPDIR was not /tmp: mkdtemp wrote
hh_demo_* under the scratch directory and the normaliser only rewrote /tmp.
"""

from __future__ import annotations

import subprocess
import sys

import _package

REPO = _package.REPO_DIR


def check_normaliser_follows_tempdir():
    result = subprocess.run(
        [sys.executable, "demo/demo.py", "--check-normaliser"],
        cwd=REPO, capture_output=True, text=True, timeout=60, check=False)
    assert result.returncode == 0, result.stderr or result.stdout
    assert "PASS demo path normaliser" in result.stdout
    return "temp-dir demo paths rewrite to <demo-db>"


def check_seed_clock_boundary():
    # Run from demo/ so its loose script is importable normally, without adding
    # another package-resolution path to this suite.
    script = (
        "import sys; sys.path.insert(0, %r); "
        "from test_demo_normalise import _check_seed_clock_boundary; "
        "print(_check_seed_clock_boundary())"
    ) % str(REPO / "tests")
    result = subprocess.run([sys.executable, "-c", script], cwd=REPO / "demo",
                            capture_output=True, text=True, timeout=60, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout.strip()


def _check_seed_clock_boundary():
    """Crossing a wall-clock second during seeding must not reorder the demo."""
    import contextlib
    import difflib
    import io
    import tempfile
    from datetime import datetime, timedelta, timezone
    from pathlib import Path
    from unittest.mock import patch

    _package.import_package()
    import importlib
    demo = importlib.import_module("demo")
    from hungry_hippa import db, episodic

    original = episodic.EpisodicMemory.remember_episode
    start = datetime.now(timezone.utc) - timedelta(seconds=10)
    calls = []

    def advancing_clock(memory, **fields):
        stamp = (start + timedelta(seconds=len(calls))).strftime("%Y-%m-%dT%H:%M:%SZ")
        calls.append(stamp)
        with patch.object(db, "now_iso", return_value=stamp):
            return original(memory, **fields)

    with tempfile.TemporaryDirectory(prefix="hh_demo_clock_") as tmp:
        path = str(Path(tmp) / "hungry_hippa.db")
        with patch.object(episodic.EpisodicMemory, "remember_episode", advancing_clock):
            demo.reset_database(path)
        assert len(calls) == 2 and calls[0] != calls[1], calls
        import sqlite3
        with sqlite3.connect(path) as conn:
            rows = conn.execute(
                "SELECT ts_start, ts_end, created_at FROM episodes ORDER BY episode_id"
            ).fetchall()
        assert len(rows) == 2 and rows[0][:2] == rows[1][:2], rows
        assert rows[0][0] == rows[0][1], rows
        assert [row[2] for row in rows] == calls, rows
        with contextlib.redirect_stdout(io.StringIO()):
            transcript = demo.run_demo(path, True)
        actual = demo.normalise("\n".join(transcript.lines))
        expected = demo.normalise(demo.EXPECTED_PATH.read_text(encoding="utf-8"))
        assert actual == expected, "\n".join(difflib.unified_diff(
            expected.splitlines(), actual.splitlines(), "expected", "clock-boundary"))
    return "advancing seed clock preserves full transcript, including fresh MCP recall"


def run_all():
    results = []
    for fn in (check_normaliser_follows_tempdir, check_seed_clock_boundary):
        try:
            detail = fn()
            results.append({"name": fn.__name__, "passed": True, "detail": detail})
        except Exception as exc:
            results.append({"name": fn.__name__, "passed": False,
                            "detail": f"{type(exc).__name__}: {exc}"})
    return results


if __name__ == "__main__":
    rows = run_all()
    passed = sum(1 for row in rows if row["passed"])
    for row in rows:
        print(f"{'PASS' if row['passed'] else 'FAIL'}  {row['name']}: {row['detail']}")
    print(f"\n{passed}/{len(rows)} passed")
    sys.exit(0 if passed == len(rows) else 1)
