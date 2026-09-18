"""Run all benchmark suites."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

REPO = Path(__file__).resolve().parent.parent.parent


def run_hh_specific() -> Dict[str, Any]:
    proc = subprocess.run([sys.executable, "benchmarks/runners/hh_specific.py"],
                          cwd=str(REPO), capture_output=True, text=True, timeout=600)
    return {"stdout": proc.stdout, "stderr": proc.stderr, "returncode": proc.returncode}


def main() -> int:
    result = run_hh_specific()
    print(result["stdout"])
    if result["stderr"]:
        print(result["stderr"], file=sys.stderr)
    return result["returncode"]


if __name__ == "__main__":
    sys.exit(main())
