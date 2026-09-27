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


def run_all():
    results = []
    try:
        detail = check_normaliser_follows_tempdir()
        results.append({"name": "normaliser_follows_tempdir", "passed": True, "detail": detail})
    except Exception as exc:
        results.append({"name": "normaliser_follows_tempdir", "passed": False,
                        "detail": f"{type(exc).__name__}: {exc}"})
    return results


if __name__ == "__main__":
    rows = run_all()
    passed = sum(1 for row in rows if row["passed"])
    for row in rows:
        print(f"{'PASS' if row['passed'] else 'FAIL'}  {row['name']}: {row['detail']}")
    print(f"\n{passed}/{len(rows)} passed")
    sys.exit(0 if passed == len(rows) else 1)
