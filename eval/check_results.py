#!/usr/bin/env python3
"""Re-run the memory-challenge harness and compare the stable metrics.

``eval/results.json`` is a recording of one run: it carries a timestamp, a commit
and machine-specific latencies, so byte-comparing it against a fresh run would
always fail. This check re-runs the harness into temporary files and compares
only the metrics that must be identical on any machine (recall and
incorrect-memory rates, context sizes, denial accuracy, repeated-failure rate).

Usage:

    python eval/check_results.py           # exit 0 when stable metrics match
    python eval/check_results.py --verbose

It never writes to the tracked files, so it is safe to run in CI.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List

EVAL_DIR = Path(__file__).resolve().parent
RESULTS_PATH = EVAL_DIR / "results.json"

# Metrics that must reproduce exactly. Deliberately excludes latencies, store
# sizes and timestamps: those legitimately vary between machines and runs.
STABLE_KEYS = (
    "recall_rate",
    "incorrect_memory_rate",
    "context_chars_median",
    "permission_denial_accuracy",
    "repeat_failed_attempt_rate",
)


def _load_harness():
    spec = importlib.util.spec_from_file_location(
        "hh_eval_harness_check", str(EVAL_DIR / "harness.py"))
    if spec is None or spec.loader is None:  # pragma: no cover
        raise ImportError("cannot load eval/harness.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["hh_eval_harness_check"] = mod
    spec.loader.exec_module(mod)
    return mod


def compare(committed: Dict[str, Any], fresh: Dict[str, Any]) -> List[str]:
    """Return a list of disagreements, empty when the stable metrics match."""
    problems: List[str] = []
    for key in STABLE_KEYS:
        want = committed.get("aggregate", {}).get(key)
        got = fresh.get("aggregate", {}).get(key)
        if want != got:
            problems.append(f"aggregate.{key}: committed={want!r} fresh={got!r}")
    for arm_key in ("scored_scenarios", "comparable_scenarios",
                    "with_arm_only_scenarios", "unsupported_baseline_scenarios",
                    "not_scored_scenarios"):
        want = committed.get("aggregate", {}).get(arm_key)
        got = fresh.get("aggregate", {}).get(arm_key)
        if want != got:
            problems.append(f"aggregate.{arm_key}: committed={want!r} fresh={got!r}")
    want_ids = [s["id"] for s in committed.get("scenarios", [])]
    got_ids = [s["id"] for s in fresh.get("scenarios", [])]
    if want_ids != got_ids:
        problems.append(f"scenario ids: committed={want_ids} fresh={got_ids}")
    if committed.get("harness_version") != fresh.get("harness_version"):
        problems.append("harness_version changed; refresh eval/results.json")
    return problems


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    if not RESULTS_PATH.exists():
        print(f"missing {RESULTS_PATH}; run python eval/harness.py first",
              file=sys.stderr)
        return 2
    committed = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))

    harness = _load_harness()
    tmp = tempfile.mkdtemp(prefix="hh_eval_check_")
    out = os.path.join(tmp, "results.json")
    report = os.path.join(tmp, "REPORT.md")
    rc = harness.main(["--out", out, "--report", report])
    if rc != 0:
        print(f"harness exited {rc}", file=sys.stderr)
        return rc
    fresh = json.loads(Path(out).read_text(encoding="utf-8"))

    problems = compare(committed, fresh)
    if problems:
        print("stable metrics drifted from eval/results.json:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        print("If the change was intended, re-run python eval/harness.py and commit "
              "the regenerated results.json + REPORT.md.", file=sys.stderr)
        return 1

    if args.verbose:
        agg = fresh["aggregate"]
        print(f"committed run: {committed.get('generated_at')} "
              f"@ {str(committed.get('git_rev'))[:8]}")
        print(f"fresh run:     {fresh.get('generated_at')} "
              f"@ {str(fresh.get('git_rev'))[:8]}")
        print(f"recall rate:   {agg['recall_rate']}")
        print(f"scenarios:     {agg['scored_scenarios']} graded, "
              f"comparable {agg['comparable_scenarios']}")
    print(f"stable metrics match ({len(STABLE_KEYS)} aggregate groups, "
          f"{len(fresh.get('scenarios', []))} scenarios)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
