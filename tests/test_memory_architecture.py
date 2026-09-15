"""Hungry Hippa memory-architecture tests (Phase 3).

Throwaway temp databases only — never the live $HERMES_HOME database.

Covers the additive Phase 3 behaviour: schema-v4 defaults, quarantine,
actor policy, explainable ranking, the context compiler budget, and
record_outcome on the `cortex` tool surface.

run_all() -> list of {name, passed, detail}; ``python tests/test_memory_architecture.py``
prints one line per check and exits non-zero on failure.
"""

from __future__ import annotations

import importlib.util
import json
import math
import os
import sqlite3
import sys
import tempfile
import types
from pathlib import Path
from typing import Any, Dict, List, Tuple

PLUGIN_DIR = Path(__file__).resolve().parent.parent


def _import_plugin():
    """Register the plugin dir as the ``livingcortex`` package and import it."""
    if sys.modules.get("livingcortex") is not None and getattr(
        sys.modules["livingcortex"], "__file__", None
    ):
        return sys.modules["livingcortex"]

    pkg = types.ModuleType("livingcortex")
    pkg.__path__ = [str(PLUGIN_DIR)]
    pkg.__file__ = str(PLUGIN_DIR / "__init__.py")
    sys.modules["livingcortex"] = pkg
    spec = importlib.util.spec_from_file_location(
        "livingcortex",
        str(PLUGIN_DIR / "__init__.py"),
        submodule_search_locations=[str(PLUGIN_DIR)],
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["livingcortex"] = mod
    spec.loader.exec_module(mod)
    return mod


_PLUGIN = _import_plugin()


def _fresh(prefix: str = "hh_ma_", **cfg_overrides: Any) -> Tuple[Any, str]:
    """A controller on a brand-new temp database (vectors off, offline)."""
    from livingcortex.config import load_config
    from livingcortex.controller import MemoryController

    tmp = tempfile.mkdtemp(prefix=prefix)
    db_path = os.path.join(tmp, "hungry_hippa.db")
    cfg = load_config()
    cfg["retrieval"]["vectors_enabled"] = False
    cfg["consolidation"]["on_session_end"] = False
    for key, value in cfg_overrides.items():
        cfg[key] = value
    ctrl = MemoryController(cfg, db_path=db_path)
    ctrl.bind_session(session_id="ma-test", platform="cli")
    return ctrl, db_path


def _ids(out: Dict[str, Any]) -> List[str]:
    return [it.get("episode_id") or it.get("belief_id") or it.get("rel_id") or ""
            for it in out.get("items", [])]


# ---------------------------------------------------------------- checks

def check_quarantined_not_recalled():
    c, db = _fresh("hh_ma_q_")
    secret = "classified north shaft wiring incident"
    q = c.remember_episode(
        context=secret, result="crew stood down", outcome="failure",
        project="classified_job", quarantined=True, embed=False)
    assert q.get("quarantined") is True, q
    normal = c.remember_episode(
        context="north shaft ceiling grid layout approved", outcome="success",
        project="shop_job", embed=False)

    out = c.recall("classified north shaft wiring incident")
    ids = _ids(out)
    assert q["episode_id"] not in ids, ids
    # no quarantined text anywhere in the content-bearing fields (the
    # context_package echoes the caller's own query, which is not memory)
    payload = json.dumps([out.get("items", []), out.get("context", ""),
                          out.get("excluded", []), out.get("explain", [])],
                         default=str)
    assert secret not in payload, "quarantined content leaked"
    reasons = {e["reason"] for e in out.get("excluded", [])}
    assert "quarantined" in reasons, out.get("excluded")

    # the unrelated, non-quarantined memory is still recallable
    other = c.recall("north shaft ceiling grid layout")
    assert normal["episode_id"] in _ids(other), other.get("items")

    # owner review path can surface it explicitly, clearly labelled
    review = c.recall("classified north shaft wiring incident",
                      include_quarantined=True)
    assert q["episode_id"] in _ids(review), review.get("excluded")
    assert "[QUARANTINED]" in review["context"], review["context"]

    # consolidation must not launder quarantined episodes into derived memory
    assert c.episodic.list_episodes_full() == [] or all(
        e["quarantined"] == 0 for e in c.episodic.list_episodes_full())
    return f"quarantined {q['episode_id']} excluded from default recall and from consolidation input"


def check_superseded_belief_loses():
    c, _db = _fresh("hh_ma_sup_")
    b1 = c.semantic.add_belief("the fixture jig uses aluminium plate",
                               kind="fact", confidence=0.9,
                               source_class="user_explicit")
    b2 = c.semantic.supersede(b1["belief_id"], "the fixture jig uses steel plate",
                              reason="operator correction",
                              source_class="user_explicit")
    assert c.semantic.get_belief(b1["belief_id"])["status"] == "superseded"

    out = c.recall("fixture jig plate material")
    ids = _ids(out)
    assert b2["belief_id"] in ids, (ids, out.get("excluded"))
    assert b1["belief_id"] not in ids, ids
    assert {"item": f"belief:{b1['belief_id']}", "reason": "superseded"} \
        in out.get("excluded", []), out.get("excluded")

    # the compiler itself prefers current over superseded when handed both
    old = c.semantic.get_belief(b1["belief_id"])
    new = c.semantic.get_belief(b2["belief_id"])
    old["_score"] = 999.0  # even if the stale row scored higher
    new["_score"] = 1.0
    pkg = c.retrieval.compile_context([old, new], "fixture jig plate")
    kept = [it["belief_id"] for it in pkg["items"]]
    assert kept == [b2["belief_id"]], kept
    assert {"item": f"belief:{b1['belief_id']}", "reason": "superseded"} \
        in pkg["excluded"], pkg["excluded"]
    return f"{b2['belief_id']} wins; {b1['belief_id']} kept as superseded history"


def check_explain_has_score_parts():
    c, _db = _fresh("hh_ma_ex_")
    claim = "the hoist cable inspection interval is quarterly"
    c.semantic.add_belief(claim, kind="fact", confidence=0.9,
                          source_class="document")
    c.remember_episode(context="hoist cable inspection quarterly performed",
                       outcome="success", embed=False)
    c.remember_episode(context="secret quarantined hoist cable note",
                       outcome="failure", quarantined=True, embed=False)

    out = c.recall("hoist cable inspection interval", explain=True)
    explain = out.get("explain")
    assert explain, out
    required = {"relevance", "recency", "salience", "confidence",
                "provenance_class", "dropped_for_budget", "total", "item"}
    for entry in explain:
        missing = required - set(entry)
        assert not missing, (missing, entry)
        assert isinstance(entry["dropped_for_budget"], bool), entry
    classes = {e["provenance_class"] for e in explain}
    assert "document" in classes, classes

    # explanation must not echo memory contents, quarantined or otherwise
    blob = json.dumps(explain, default=str)
    assert claim not in blob
    assert "secret quarantined hoist cable note" not in blob
    return f"{len(explain)} scored items explained; no memory contents in debug output"


def check_context_respects_budget():
    c, _db = _fresh("hh_ma_budget_")
    for i in range(12):
        c.remember_episode(
            context=f"panel stack {i} alignment note " + ("x" * 120),
            result="aligned", outcome="success", embed=False)
    c.semantic.add_belief("panel stack alignment tolerance is 3mm",
                          kind="fact", confidence=0.8, source_class="document")

    out = c.recall("panel stack alignment", limit=20, max_context_chars=400)
    pkg = out["context_package"]
    assert pkg["budget_chars"] == 400, pkg
    assert len(pkg["rendering"]) <= 400, len(pkg["rendering"])
    assert out["context"] == pkg["rendering"]
    assert pkg["token_estimate"] == math.ceil(len(pkg["rendering"]) / 4), pkg
    assert any(e["reason"] == "budget" for e in pkg["excluded"]), pkg["excluded"]
    assert set(pkg) >= {"items", "rendering", "token_estimate", "excluded"}, set(pkg)
    assert len(pkg["items"]) < 13, "budget did not drop anything"

    # a budget smaller than one block renders nothing rather than overflowing
    tight = c.retrieval.compile_context(list(out["items"]), "panel", max_chars=1)
    assert tight["rendering"] == "", tight
    assert tight["token_estimate"] == 0, tight
    return (f"{len(pkg['items'])} items / {len(pkg['rendering'])} chars "
            f"<= {pkg['budget_chars']} budget")


def check_record_outcome_updates_procedure():
    c, _db = _fresh("hh_ma_proc_")
    p = c.create_procedure("torque to spec", description="torque pattern",
                           steps=["stage 1", "stage 2"], confidence=0.5)
    pid = p["procedure_id"]

    r1 = c.record_outcome(pid, True)
    assert r1["success_count"] == 1 and r1["failure_count"] == 0, r1
    c.record_outcome(pid, True)
    r3 = c.record_outcome(pid, True)
    assert r3["success_count"] == 3, r3
    assert r3["status"] == "validated", r3
    assert r3["confidence"] >= 0.85, r3

    # the same operation is reachable through the `cortex` tool surface
    from livingcortex.observability import Observability
    from livingcortex.tools import handle

    p2 = c.create_procedure("inspect hoist", confidence=0.5)
    obs = Observability(c.db, c.cfg, controller=c)
    tool_out = json.loads(handle(c, obs, "record_outcome",
                                 {"procedure_id": p2["procedure_id"],
                                  "success": True}))
    assert tool_out.get("success_count") == 1, tool_out
    assert "record_outcome" in json.dumps(
        _PLUGIN.CORTEX_SCHEMA["parameters"]["properties"]["action"]["enum"])
    return f"{pid} -> validated at confidence {r3['confidence']:.2f}; tool action works"


def check_migration_v4_defaults():
    c, db = _fresh("hh_ma_mig_")
    c.remember_episode(context="pre-existing row written after migration",
                       outcome="success", embed=False)
    c.semantic.add_belief("pre-existing belief", kind="fact")

    conn = sqlite3.connect(db)
    try:
        versions = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
        assert 4 in versions, versions
        for table in ("episodes", "beliefs"):
            cols = {r[1]: r for r in conn.execute(f"PRAGMA table_info({table})")}
            for col, default in (("sensitivity", "'unclassified'"),
                                 ("quarantined", "0"),
                                 ("actor_id", "'primary'")):
                assert col in cols, (table, col, sorted(cols))
                assert str(cols[col][4]) == default, (table, col, cols[col][4])
        row = conn.execute(
            "SELECT sensitivity, quarantined, actor_id FROM episodes LIMIT 1"
        ).fetchone()
        assert row == ("unclassified", 0, "primary"), row
        bel = conn.execute(
            "SELECT sensitivity, quarantined, actor_id FROM beliefs LIMIT 1"
        ).fetchone()
        assert bel == ("unclassified", 0, "primary"), bel
    finally:
        conn.close()
    return "schema v4 applied; defaults unclassified/0/primary on existing-style rows"


def check_untrusted_actor_policy():
    c, db = _fresh("hh_ma_pol_")
    owner_ep = c.remember_episode(
        context="shop policy: blade changes are logged at the bench",
        outcome="success", project="shop", embed=False)

    from livingcortex.config import load_config
    from livingcortex.controller import MemoryController

    cfg = load_config()
    cfg["retrieval"]["vectors_enabled"] = False
    other = MemoryController(cfg, db_path=db)
    other.bind_session(session_id="mcp-session", platform="mcp",
                       agent_context="primary", actor_id="mcp-untrusted")
    mine = other.remember_episode(
        context="untrusted candidate: blade changes are optional",
        outcome="unknown", embed=False)
    assert mine.get("quarantined") is True, mine
    assert mine.get("actor_id") == "mcp-untrusted", mine

    out = other.recall("shop policy blade changes logged at the bench")
    reasons = [e["reason"] for e in out.get("excluded", [])]
    assert owner_ep["episode_id"] not in _ids(out), out.get("items")
    assert "other-actor" in reasons, out.get("excluded")

    # untrusted actors may not purge, even their own row
    denied = other.forget("episode", mine["episode_id"], mode="purge")
    assert denied.get("error"), denied
    assert other.episodic.get_episode(mine["episode_id"]) is not None

    # the owner still sees the shared memory
    owned = c.recall("shop policy blade changes logged at the bench")
    assert owner_ep["episode_id"] in _ids(owned), owned.get("excluded")
    return "untrusted write quarantined; other-actor read denied; purge denied"


def check_v4_migrates_populated_v3_database():
    """A pre-v4 database with real rows must upgrade in place, losing nothing."""
    from livingcortex import schema as schema_mod

    c, db = _fresh("hh_ma_v3_")
    # Build a pre-v4 database the honest way: run only migrations 1..3, insert
    # rows with the old column list, then let the current code open it.
    saved = schema_mod.MIGRATIONS.pop(4)
    try:
        old_db = os.path.join(tempfile.mkdtemp(prefix="hh_ma_old_"), "old.db")
        import sqlite3 as _sq
        conn = _sq.connect(old_db)
        try:
            conn.execute("CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY,"
                         " applied_at TEXT NOT NULL, description TEXT NOT NULL,"
                         " down_sql TEXT NOT NULL DEFAULT '')")
            for version in (1, 2, 3):
                mig = schema_mod.MIGRATIONS[version]
                conn.executescript(mig["up"])
                conn.execute("INSERT INTO schema_migrations(version, applied_at,"
                             " description, down_sql) VALUES (?,?,?,?)",
                             (version, "2020-01-01T00:00:00Z", mig["description"],
                              mig["down"]))
            conn.execute(
                "INSERT INTO episodes(episode_id, ts_start, ts_end, context, outcome,"
                " importance, confidence, status, created_at, updated_at)"
                " VALUES ('E-9999','2020-01-01T00:00:00Z','2020-01-01T00:00:00Z',"
                " 'legacy episode survives migration','success',0.9,0.8,'active',"
                " '2020-01-01T00:00:00Z','2020-01-01T00:00:00Z')")
            conn.execute(
                "INSERT INTO beliefs(belief_id, kind, claim, confidence, importance,"
                " status, created_at, updated_at) VALUES ('B-9999','fact',"
                " 'legacy belief survives migration',0.9,0.6,'active',"
                " '2020-01-01T00:00:00Z','2020-01-01T00:00:00Z')")
            conn.commit()
        finally:
            conn.close()
    finally:
        schema_mod.MIGRATIONS[4] = saved

    from livingcortex.config import load_config
    from livingcortex.controller import MemoryController
    from livingcortex.db import migrate_database

    report = migrate_database(old_db)
    assert os.path.isfile(report["backup"]), report
    c2 = MemoryController(load_config(), db_path=old_db)
    ep = c2.episodic.get_episode("E-9999")
    bel = c2.semantic.get_belief("B-9999")
    assert ep["context"] == "legacy episode survives migration", ep
    assert ep["sensitivity"] == "unclassified" and ep["quarantined"] == 0, ep
    assert ep["actor_id"] == "primary", ep
    assert bel["claim"] == "legacy belief survives migration", bel
    assert bel["sensitivity"] == "unclassified", bel
    # migrated rows are readable by the owner and absent from quarantine
    out = c2.recall("legacy episode survives migration")
    assert any(i.get("episode_id") == "E-9999" for i in out["items"]), out["excluded"]
    return f"pre-v4 DB upgraded in place; {os.path.basename(report['backup'])} backup written"


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

    check("quarantined_memory_not_recalled", check_quarantined_not_recalled)
    check("superseded_belief_loses_to_current", check_superseded_belief_loses)
    check("explain_returns_score_parts", check_explain_has_score_parts)
    check("context_respects_max_context_chars", check_context_respects_budget)
    check("record_outcome_updates_procedure", check_record_outcome_updates_procedure)
    check("migration_v4_defaults", check_migration_v4_defaults)
    check("v4_migrates_populated_v3_database", check_v4_migrates_populated_v3_database)
    check("untrusted_actor_policy", check_untrusted_actor_policy)
    return results


if __name__ == "__main__":
    results = run_all()
    passed = sum(1 for r in results if r["passed"])
    for r in results:
        print(f"{'PASS' if r['passed'] else 'FAIL'}  {r['name']}: {r['detail']}")
    print(f"\n{passed}/{len(results)} passed")
    sys.exit(0 if passed == len(results) else 1)
