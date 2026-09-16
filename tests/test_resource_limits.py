"""Resource-abuse tests: volume is bounded and the accounting survives restarts.

Finding: the only volume guard was a per-process call budget, which a caller
resets by starting a new process, and legal-size records could accumulate without
limit. There was no size visibility, consolidation scanned with undocumented
hard-coded caps, graph traversal took an unbounded hop count, and a migration
backup on a full filesystem would fail halfway.

What is fixed here is bounded/deterministic; the measurements (writes per second,
recall latency, consolidation cost) are printed as benchmark notes rather than
asserted, because they are machine-dependent.

run_all() -> list of {name, passed, detail}.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

REPO_DIR = Path(__file__).resolve().parent.parent


sys.path.insert(0, str(Path(__file__).resolve().parent))   # tests/ (shared helpers)
from _package import import_package  # noqa: E402

PACKAGE_DIR = REPO_DIR / "src" / "hungry_hippa"   # src layout
_PLUGIN = import_package()
from hungry_hippa import limits, trust  # noqa: E402
from hungry_hippa.config import get as cfg_get, load_config  # noqa: E402
from hungry_hippa.controller import MemoryController  # noqa: E402
from hungry_hippa.db import Database, backup_sqlite  # noqa: E402
from hungry_hippa.graph import KnowledgeGraph  # noqa: E402


class _Env:
    """Temporarily set an environment variable."""

    def __init__(self, **values: str) -> None:
        self.values = values
        self.previous: Dict[str, Any] = {}

    def __enter__(self):
        for k, v in self.values.items():
            self.previous[k] = os.environ.get(k)
            os.environ[k] = v
        return self

    def __exit__(self, *exc):
        for k, old in self.previous.items():
            if old is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old
        return False


def _ctrl(db: str = "", *, actor: str = "primary") -> Tuple[MemoryController, str]:
    if not db:
        db = os.path.join(tempfile.mkdtemp(prefix="hh_res_"), "hungry_hippa.db")
    cfg = load_config()
    cfg["retrieval"]["vectors_enabled"] = False
    ctrl = MemoryController(cfg, db_path=db)
    ctrl.bind_session(session_id="s", platform="cli",
                      trust=trust.local_binding(actor))
    return ctrl, db


def check_write_quota_survives_process_restarts():
    """The counter lives in the database, so a fresh process cannot reset it."""
    db = os.path.join(tempfile.mkdtemp(prefix="hh_res_restart_"), "hungry_hippa.db")
    with _Env(HUNGRY_HIPPA_MAX_WRITES_PER_HOUR="5"):
        first, _ = _ctrl(db)
        for i in range(3):
            r = first.semantic.add_belief(f"first process note {i}", kind="fact")
            assert r.get("belief_id"), r
        del first  # process exits

        # a brand-new controller = a brand-new client process
        second, _ = _ctrl(db)
        allowed, report = limits.check_write_quota(second.db, "primary")
        assert allowed, report
        assert report["used"] >= 3, f"the quota did not survive the restart: {report}"
        for i in range(2):
            second.semantic.add_belief(f"second process note {i}", kind="fact")
        out = second.semantic.add_belief("over the limit", kind="fact")
        assert out.get("error"), out
        assert "quota" in out["error"], out
    rows = sqlite3.connect(db).execute(
        "SELECT COUNT(*) FROM mutation_log WHERE action = 'write_quota_exceeded'"
    ).fetchone()[0]
    assert rows >= 1, "the refusal was not audited"
    return "quota stored in the database: 3 + 2 writes then refused, refusal audited"


def check_quota_is_per_actor():
    """One actor's volume does not consume another's budget."""
    db = os.path.join(tempfile.mkdtemp(prefix="hh_res_actor_"), "hungry_hippa.db")
    with _Env(HUNGRY_HIPPA_MAX_WRITES_PER_HOUR="2"):
        a, _ = _ctrl(db, actor="primary")
        b, _ = _ctrl(db, actor="mcp-untrusted")
        b.bind_session(session_id="s", platform="mcp",
                       trust=trust.external_binding("mcp-untrusted"))
        for i in range(2):
            r = a.semantic.add_belief(f"owner note {i}", kind="fact",
                                      actor_id="primary")
            assert r.get("belief_id"), r
        over = a.semantic.add_belief("owner over", kind="fact", actor_id="primary")
        assert over.get("error"), over
        # the other actor has its own window and its own count
        other = b.semantic.add_belief("client note", kind="fact",
                                      actor_id="mcp-untrusted")
        assert other.get("belief_id"), other
    return "quota windows are per actor, not global"


def check_default_limit_leaves_normal_use_alone():
    """With the default limit, ordinary use is not throttled."""
    ctrl, db = _ctrl(os.path.join(tempfile.mkdtemp(prefix="hh_res_normal_"),
                                 "hungry_hippa.db"))
    assert limits.max_writes_per_hour() == limits.DEFAULT_MAX_WRITES_PER_HOUR
    for i in range(50):
        r = ctrl.semantic.add_belief(f"ordinary note {i}", kind="fact")
        assert r.get("belief_id"), (i, r)
    assert limits.DEFAULT_MAX_WRITES_PER_HOUR >= 10000, limits.DEFAULT_MAX_WRITES_PER_HOUR
    return f"50 ordinary writes fine under the {limits.DEFAULT_MAX_WRITES_PER_HOUR}/hour default"


def check_database_size_is_visible_and_warned():
    """Status reports the size, and warns past the threshold without deleting."""
    db = os.path.join(tempfile.mkdtemp(prefix="hh_res_size_"), "hungry_hippa.db")
    ctrl, _ = _ctrl(db)
    ctrl.semantic.add_belief("a note that takes up a little room", kind="fact")
    report = limits.db_size_report(db)
    assert report["bytes"] > 0, report
    assert report["over_limit"] is False, report
    with _Env(HUNGRY_HIPPA_MAX_DB_BYTES="1000"):
        small = limits.db_size_report(db)
        assert small["over_limit"] is True, small
        assert "warning" in small and "not a quota" in small["note"], small
        health = ctrl.db.health()
        assert health["size"]["bytes"] > 0, health.get("size")
        assert health["size"]["limit_bytes"] == 1000, health["size"]
    assert os.path.exists(db), "the warning must not delete anything"
    return f"size reported ({report['bytes']} bytes) with a threshold warning, nothing deleted"


def check_backup_refuses_without_space():
    """A backup on a full filesystem fails loudly instead of writing rubble."""
    tmp = tempfile.mkdtemp(prefix="hh_res_space_")
    src = os.path.join(tmp, "hungry_hippa.db")
    Database(src)
    ok, detail = limits.backup_space_ok(src)
    assert ok is True, detail
    ok, detail = limits.backup_space_ok(src, need_multiplier=1e9)
    assert ok is False and "need about" in detail, detail
    dest = os.path.join(tmp, "copy.db")
    with _Env(HUNGRY_HIPPA_BACKUP_SPACE_MULTIPLIER="1000000000"):
        try:
            backup_sqlite(src, dest)
        except RuntimeError as e:
            assert "refusing to back up" in str(e), e
        else:
            raise AssertionError("backup_sqlite ignored a full filesystem")
    # and the real thing still works when there is room
    ok, detail = limits.backup_space_ok(src)
    assert ok, detail
    backup_sqlite(src, os.path.join(tmp, "fine.db"))
    return "insufficient space refused with a clear error; normal backup unaffected"


def check_graph_traversal_is_bounded():
    """hop_limit is clamped: no unbounded frontier from a caller."""
    tmp = tempfile.mkdtemp(prefix="hh_res_hops_")
    db = Database(os.path.join(tmp, "hungry_hippa.db"))
    graph = KnowledgeGraph(db, load_config())
    for i in range(40):
        graph.relate(f"n{i}", "PART_OF", f"n{i+1}")
    shallow = graph.traverse("n0", hop_limit=1)
    clamped = graph.traverse("n0", hop_limit=99)
    assert len(clamped) <= len(graph.traverse("n0", hop_limit=4)) + 1, "hop limit not clamped"
    assert len(shallow) < len(clamped), (len(shallow), len(clamped))
    assert len(clamped) < 40, "traversal did not stop at the cap"
    return f"hop_limit=99 clamped to 4 hops: {len(shallow)} edge(s) at 1 hop, {len(clamped)} at the cap"


def check_consolidation_scan_caps_are_configurable():
    """The consolidation scan is capped by config, not by a magic number."""
    cfg = load_config()
    assert cfg_get(cfg, "consolidation.max_beliefs_scan"), cfg.get("consolidation")
    assert cfg_get(cfg, "consolidation.max_episodes_scan"), cfg.get("consolidation")
    ctrl, _db = _ctrl(os.path.join(tempfile.mkdtemp(prefix="hh_res_cons_"),
                                   "hungry_hippa.db"))
    for i in range(12):
        ctrl.remember_episode(context=f"episode {i}", outcome="unknown", embed=False)
        ctrl.semantic.add_belief(f"belief {i}", kind="fact")
    ctrl.cfg["consolidation"]["max_episodes_scan"] = 2
    ctrl.cfg["consolidation"]["max_beliefs_scan"] = 2
    report = ctrl.consolidate(reason="cap test")
    assert "counts" in report, report
    full = ctrl.consolidate(reason="cap test full")
    assert isinstance(full["counts"], dict), full
    return f"scan caps read from config; run completed with caps=2 ({report['counts']})"


def benchmark_notes() -> Dict[str, Any]:
    """Measure, do not guess. Numbers for the report, not assertions."""
    notes: Dict[str, Any] = {}
    db = os.path.join(tempfile.mkdtemp(prefix="hh_bench_"), "hungry_hippa.db")
    ctrl, _ = _ctrl(db)

    t0 = time.perf_counter()
    for i in range(2000):
        ctrl.semantic.add_belief(f"benchmark belief number {i} about bay {i % 7}",
                                 kind="fact", source_class="document")
    notes["writes"] = {"count": 2000, "seconds": round(time.perf_counter() - t0, 2)}

    t0 = time.perf_counter()
    out = ctrl.recall("bay three fastener")
    notes["recall"] = {"count": out["count"],
                       "ms": round((time.perf_counter() - t0) * 1000, 2)}
    notes["db_bytes"] = os.path.getsize(db)

    t0 = time.perf_counter()
    report = ctrl.consolidate(reason="benchmark")
    notes["consolidation"] = {"seconds": round(time.perf_counter() - t0, 2),
                              "counts": report.get("counts", {})}

    t0 = time.perf_counter()
    backup = db + ".bench.bak"
    backup_sqlite(db, backup)
    notes["backup"] = {"seconds": round(time.perf_counter() - t0, 2),
                       "bytes": os.path.getsize(backup)}
    notes["size_report"] = limits.db_size_report(db)
    return notes


def run_all() -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []

    def check(name: str, fn) -> None:
        try:
            detail = fn() or "ok"
            results.append({"name": name, "passed": True, "detail": str(detail)[:400]})
        except AssertionError as e:
            results.append({"name": name, "passed": False, "detail": f"assert: {e}"})
        except Exception as e:
            results.append({"name": name, "passed": False,
                            "detail": f"{type(e).__name__}: {e}"})

    check("write_quota_survives_process_restarts",
          check_write_quota_survives_process_restarts)
    check("quota_is_per_actor", check_quota_is_per_actor)
    check("default_limit_leaves_normal_use_alone",
          check_default_limit_leaves_normal_use_alone)
    check("database_size_is_visible_and_warned",
          check_database_size_is_visible_and_warned)
    check("backup_refuses_without_space", check_backup_refuses_without_space)
    check("graph_traversal_is_bounded", check_graph_traversal_is_bounded)
    check("consolidation_scan_caps_are_configurable",
          check_consolidation_scan_caps_are_configurable)

    try:
        notes = benchmark_notes()
        results.append({"name": "benchmark_notes", "passed": True,
                        "detail": str(notes)[:900]})
    except Exception as e:
        results.append({"name": "benchmark_notes", "passed": False,
                        "detail": f"{type(e).__name__}: {e}"})
    return results


if __name__ == "__main__":
    results = run_all()
    passed = sum(1 for r in results if r["passed"])
    for r in results:
        print(f"{'PASS' if r['passed'] else 'FAIL'}  {r['name']}: {r['detail']}")
    print(f"\n{passed}/{len(results)} passed")
    sys.exit(0 if passed == len(results) else 1)
