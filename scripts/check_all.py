#!/usr/bin/env python3
"""One command: run every test suite, the demo check and the eval drift check.

    python scripts/check_all.py

This is the same set of steps the CI workflow runs, so a green local run and a
green CI run mean the same thing. Exit code is non-zero if anything fails, and
each suite's own output is streamed through unchanged.

Nothing here touches a production database: every suite uses throwaway temp
databases, the demo uses a throwaway database, and the eval check writes only to
a temp directory.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import List, Sequence, Tuple

REPO = Path(__file__).resolve().parent.parent

STEPS: Sequence[Tuple[str, List[str]]] = (
    ("acceptance (T1-T10)", ["python", "tests/test_acceptance.py"]),
    ("migration + compatibility", ["python", "tests/test_migration.py"]),
    ("memory architecture", ["python", "tests/test_memory_architecture.py"]),
    ("MCP schema + policy", ["python", "tests/test_mcp_schema.py"]),
    ("identity binding", ["python", "tests/test_trust_boundary.py"]),
    ("existence oracle", ["python", "tests/test_existence_oracle.py"]),
    ("file permissions", ["python", "tests/test_file_permissions.py"]),
    ("provenance", ["python", "tests/test_provenance.py"]),
    ("injection framing", ["python", "tests/test_injection_framing.py"]),
    ("security", ["python", "tests/test_security.py"]),
    ("demo transcript", ["python", "demo/demo.py", "--tmp", "--check"]),
    ("eval result drift", ["python", "eval/check_results.py"]),
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--quiet", action="store_true",
                        help="print only the summary line per step")
    args = parser.parse_args(argv)

    env = dict(os.environ)
    env.setdefault("PYTHONUNBUFFERED", "1")

    failures: List[str] = []
    for label, cmd in STEPS:
        print(f"\n=== {label}: {' '.join(cmd)} ===", flush=True)
        result = subprocess.run(cmd, cwd=str(REPO), env=env,
                                capture_output=args.quiet, text=True)
        if args.quiet:
            output = (result.stdout or "") + (result.stderr or "")
        else:
            output = ""
        tail = [line for line in output.splitlines() if line.strip()][-3:]
        status = "ok" if result.returncode == 0 else f"FAILED (exit {result.returncode})"
        if args.quiet:
            for line in tail:
                print(f"    {line}")
        print(f"--- {label}: {status}", flush=True)
        if result.returncode != 0:
            failures.append(label)

    print("\n" + "=" * 60)
    if failures:
        print(f"FAILED: {', '.join(failures)}")
        return 1
    print(f"all {len(STEPS)} steps passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
