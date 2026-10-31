"""Hungry Hippa memory-architecture tests (Phase 3).

Throwaway temp databases only — never the operator's own database.

Covers the additive Phase 3 behaviour: schema-v4 defaults, quarantine,
actor policy, explainable ranking, the context compiler budget, and
record_outcome on the `cortex` tool surface.

run_all() -> list of {name, passed, detail}; ``python tests/test_memory_architecture.py``
prints one line per check and exits non-zero on failure.
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Tuple

REPO_DIR = Path(__file__).resolve().parent.parent


sys.path.insert(0, str(Path(__file__).resolve().parent))   # tests/ (shared helpers)
from _package import import_package  # noqa: E402

PACKAGE_DIR = REPO_DIR / "src" / "hungry_hippa"   # src layout
_PLUGIN = import_package()


def _fresh(prefix: str = "hh_ma_", **cfg_overrides: Any) -> Tuple[Any, str]:
    """A controller on a brand-new temp database (vectors off, offline)."""
    from hungry_hippa.config import load_config
    from hungry_hippa.controller import MemoryController

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


def check_active_fts_window_preserves_policy():
    c, path = _fresh("hh_ma_active_fts_")
    retired = []
    for status in ("archived", "superseded"):
        b = c.semantic.add_belief("cobalt history", source_class="document")
        e = c.remember_episode(context="cobalt history", embed=False)
        with sqlite3.connect(path) as conn:
            conn.execute("UPDATE beliefs SET status=? WHERE belief_id=?", (status, b["belief_id"]))
            conn.execute("UPDATE episodes SET status=? WHERE episode_id=?", (status, e["episode_id"]))
        retired.extend([b["belief_id"], e["episode_id"]])
    active = c.remember_episode(context="cobalt current workshop log", embed=False)
    hidden = c.remember_episode(context="cobalt restricted review log", quarantined=True, embed=False)
    before = c.db.fts_search("cobalt", limit=20)
    hits = c.db.fts_search("cobalt", kinds=["belief", "episode"], limit=20, active_only=True)
    assert {h["target_id"] for h in hits} == {active["episode_id"], hidden["episode_id"]}, hits
    assert c.db.fts_search("cobalt", limit=20) == before
    assert len(before) == 6
    out = c.recall("cobalt", limit=1)
    assert _ids(out) == [active["episode_id"]], out
    review = c.recall("cobalt", limit=10, include_quarantined=True)
    assert hidden["episode_id"] in _ids(review), review
    assert not set(retired) & set(_ids(review)), review
    assert review["context_package"]["trust"]["authority"] == "none"
    return "active episode window excludes retired rows, retains history and enforces quarantine"


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
    from hungry_hippa.observability import Observability
    from hungry_hippa.tools import handle

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

    from hungry_hippa.config import load_config
    from hungry_hippa.controller import MemoryController

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
    # An unauthorized caller gets no item-level exclusions at all: ids and counts
    # are an existence oracle (tests/test_existence_oracle.py).
    assert out.get("excluded") == {"unauthorized": True,
                                   "note": "excluded items are not enumerated for this caller"}, \
        out.get("excluded")
    assert owner_ep["episode_id"] not in _ids(out), out.get("items")
    assert owner_ep["episode_id"] not in json.dumps(out), out

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
    from hungry_hippa import schema as schema_mod

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

    from hungry_hippa.config import load_config
    from hungry_hippa.controller import MemoryController
    from hungry_hippa.db import migrate_database

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


def check_quarantine_cannot_starve_active_window():
    """Unapproved matches must not hide a durable approved memory at limit one."""
    import subprocess

    for kind in ("belief", "episode"):
        c, db = _fresh("hh_ma_quarantine_window_")
        hidden = []
        for i in range(6):
            if kind == "belief":
                row = c.semantic.add_belief("zircon fixture", quarantined=True,
                                            source_class="document")
            else:
                row = c.remember_episode(context="zircon fixture", quarantined=True,
                                         embed=False)
            hidden.append(row[f"{kind}_id"])
        text = "zircon fixture approved manual specifies a copper alignment pin"
        if kind == "belief":
            gold = c.semantic.add_belief(text, source_class="document",
                                        derived_from=["invented-approved-manual"])
        else:
            gold = c.remember_episode(context=text, claimed_source_class="document",
                                      source_refs=["invented-approved-manual"], embed=False)
        gold_id = gold[f"{kind}_id"]
        before = c.db.fts_search("zircon fixture", limit=20, active_only=True)
        assert gold_id not in [h["target_id"] for h in before[:2]], before
        code = """
import json, sys
from hungry_hippa.config import load_config
from hungry_hippa.controller import MemoryController
cfg = load_config()
cfg['retrieval']['vectors_enabled'] = False
cfg['manager'] = {'enabled': False}
c = MemoryController(cfg, db_path=sys.argv[1])
c.bind_session(session_id='quarantine-window-reader', platform='cli', actor_id='primary')
print(json.dumps(c.recall('zircon fixture', limit=1, explain=True)))
"""
        result = subprocess.run([sys.executable, "-c", code, db], capture_output=True,
                                text=True, timeout=30, check=True)
        out = json.loads(result.stdout)
        assert _ids(out) == [gold_id], (kind, out)
        assert "copper alignment pin" in out["context"], out
        assert "document" in out["context"] and out["sources"], out
        assert "invented-approved-manual" in out["sources"], out
        assert not set(hidden) & set(_ids(out)), out
        assert any(e["reason"] == "quarantined" for e in out["excluded"]), out
        review = c.recall("zircon fixture", limit=20, include_quarantined=True)
        assert set(hidden) & set(_ids(review)), review
        reviewed_or_deduplicated = set(_ids(review)) | {
            e["item"].split(":", 1)[1] for e in review["excluded"]
            if e["reason"] == "duplicate"
        }
        assert set(hidden).issubset(reviewed_or_deduplicated), review
        assert "[QUARANTINED]" in review["context"], review
        assert c.db.fts_search("zircon fixture", limit=20, active_only=True) == before
        # The new low-level flag is independent of active-only selection.
        with sqlite3.connect(db) as conn:
            table = "beliefs" if kind == "belief" else "episodes"
            conn.execute(f"UPDATE {table} SET status='archived' WHERE {kind}_id=?", (gold_id,))
        history = c.db.fts_search("zircon fixture", limit=20, exclude_quarantined=True)
        assert [h["target_id"] for h in history] == [gold_id], history
        assert c.db.fts_search("zircon fixture", limit=20, active_only=True,
                               exclude_quarantined=True) == []
    return "quarantine crowding cannot hide approved beliefs/episodes in fresh-process recall"


def check_growth_recall_across_process():
    """A precise durable fact must survive competing routine episode hits."""
    import subprocess

    c, db = _fresh("hh_ma_growth_")
    fixture = json.loads((REPO_DIR / "eval" / "fixtures.json").read_text())["growth"]
    for i in range(100):
        c.remember_episode(
            context=f"{fixture['topics'][i % len(fixture['topics'])]} (record {i})",
            project=f"Project {chr(65 + i % 2)}", outcome="success", embed=False)
    belief = c.semantic.add_belief(
        f"the fixture jig torque value is {fixture['expect'][0]}",
        kind="fact", confidence=0.9, source_class="document",
        derived_from=["invented-fixture-manual"])
    hits = c.db.fts_search(fixture["question"], kinds=["episode", "belief"], limit=12)
    assert hits[0]["target_id"] == belief["belief_id"], hits
    assert hits[0]["score"] < 0, hits
    # A new interpreter opens the durable store: not just another controller.
    code = """
import json, sys
from hungry_hippa.config import load_config
from hungry_hippa.controller import MemoryController
cfg = load_config()
cfg['retrieval']['vectors_enabled'] = False
cfg['manager'] = {'enabled': False}
c = MemoryController(cfg, db_path=sys.argv[1])
c.bind_session(session_id='second-process', platform='cli')
print(json.dumps(c.recall(sys.argv[2], explain=True)))
"""
    result = subprocess.run([sys.executable, "-c", code, db, fixture["question"]],
                            capture_output=True, text=True, timeout=30, check=True)
    recalled = json.loads(result.stdout)
    assert fixture["expect"][0] in recalled["context"], recalled["context"]
    assert belief["belief_id"] in _ids(recalled), recalled["items"]
    assert "invented-fixture-manual" in recalled["sources"], recalled["sources"]
    assert "document" in recalled["context"], recalled["context"]
    assert len(recalled["context"]) <= c.cfg["retrieval"]["max_context_chars"]
    return "best FTS fact survives 100 episodes and second-process recall with provenance"


def check_retention_counts_only_success():
    from hungry_hippa.forgetting import ForgettingPolicy

    for fault in ("IGNORE", "ABORT"):
        c, path = _fresh("hh_retention_")
        ids = [c.remember_episode(context=f"invented retention fixture {i}",
                                  embed=False)["episode_id"] for i in range(3)]
        with sqlite3.connect(path) as conn:
            conn.execute("UPDATE episodes SET importance=0.2, last_accessed='2000-01-01T00:00:00'")
            conn.execute("UPDATE episodes SET importance=0.9 WHERE episode_id=?", (ids[2],))
            conn.execute(f"CREATE TRIGGER refuse_retention BEFORE UPDATE OF status ON episodes "
                         f"WHEN OLD.episode_id='{ids[0]}' BEGIN SELECT RAISE({fault}"
                         + (", 'invented refusal'" if fault == "ABORT" else "") + "); END")
        policy = ForgettingPolicy(c.db, {"forgetting": {
            "auto_archival_after_unused_days": 1, "importance_decay_enabled": False,
            "compression_enabled": False}}, episodic=c.episodic)
        actions, messages = policy.pass_("retention-test")
        assert actions == 1, (fault, actions, messages)
        assert messages == ["forgetting: archived 1 unused episodes"], messages
        with sqlite3.connect(path) as conn:
            statuses = dict(conn.execute("SELECT episode_id,status FROM episodes"))
            assert statuses == {ids[0]: "active", ids[1]: "archived", ids[2]: "active"}, statuses
            audits = conn.execute("SELECT target_id FROM mutation_log WHERE action='forget'").fetchall()
            assert audits == [(ids[1],)], audits
            conn.execute("DROP TRIGGER refuse_retention")
        assert policy.pass_("retention-retry") == (1, ["forgetting: archived 1 unused episodes"])
        assert policy.pass_("retention-repeat") == (0, [])
    return "IGNORE/ABORT failures excluded from counts and success audits; retry and high-value protection preserved"


def check_retention_audit_effects():
    from hungry_hippa.forgetting import ForgettingPolicy

    for action in ("episode_archived", "forget"):
        c, path = _fresh("hh_retention_audit_")
        eid = c.remember_episode(context="invented amber retention log",
                                 source_refs=["invented-retention-source"],
                                 claimed_source_class="document", embed=False)["episode_id"]
        with sqlite3.connect(path) as conn:
            conn.execute("UPDATE episodes SET importance=0.2, last_accessed='2000-01-01T00:00:00'")
            conn.execute(f"CREATE TRIGGER reverse_retention AFTER INSERT ON mutation_log "
                         f"WHEN NEW.action='{action}' AND NEW.target_id='{eid}' BEGIN "
                         f"UPDATE episodes SET status='active' WHERE episode_id='{eid}'; END")
        def snapshot():
            with sqlite3.connect(path) as conn:
                return {table: conn.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
                        for table in ("episodes", "mutation_log")}
        before = snapshot()
        policy = ForgettingPolicy(c.db, {"forgetting": {
            "auto_archival_after_unused_days": 1, "importance_decay_enabled": False,
            "compression_enabled": False}}, episodic=c.episodic)
        result = policy.pass_("retention-audit-test")
        assert result == (0, []), (action, result)
        assert snapshot() == before, action
        with sqlite3.connect(path) as conn:
            conn.execute("DROP TRIGGER reverse_retention")
        assert policy.pass_("retention-audit-retry") == (1, ["forgetting: archived 1 unused episodes"])
        assert policy.pass_("retention-audit-repeat") == (0, [])
        with sqlite3.connect(path) as conn:
            assert conn.execute("SELECT status FROM episodes WHERE episode_id=?", (eid,)).fetchone() == ("archived",)
            audits = conn.execute("SELECT action,detail,session_id FROM mutation_log "
                                  "WHERE action IN ('episode_archived','forget') ORDER BY id").fetchall()
            assert audits == [("episode_archived", "unused", "retention-audit-retry"),
                              ("forget", "action=archival reason=unused", "retention-audit-retry")], audits
    return "nested/forget audit reversals roll back retention; retry persists status and both audits"


def check_retention_transaction_ownership():
    from hungry_hippa.forgetting import ForgettingPolicy

    for outer in (False, True):
        c, path = _fresh("hh_retention_ownership_")
        ids = [c.remember_episode(context=f"invented retention transaction {i}",
                                  embed=False)["episode_id"] for i in range(2)]
        with sqlite3.connect(path) as conn:
            conn.execute("UPDATE episodes SET importance=0.2, last_accessed='2000-01-01T00:00:00'")
            conn.execute(f"CREATE TRIGGER reverse_second AFTER INSERT ON mutation_log "
                         f"WHEN NEW.action='forget' AND NEW.target_id='{ids[1]}' BEGIN "
                         f"UPDATE episodes SET status='active' WHERE episode_id='{ids[1]}'; END")
            before = {table: conn.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
                      for table in ("episodes", "mutation_log")}
        policy = ForgettingPolicy(c.db, {"forgetting": {
            "auto_archival_after_unused_days": 1, "importance_decay_enabled": False,
            "compression_enabled": False}}, episodic=c.episodic)
        if outer:
            caught = False
            rolled_back = False
            try:
                with c.db.transaction():
                    try:
                        policy.pass_("retention-outer")
                    except RuntimeError:
                        caught = True
            except RuntimeError:
                rolled_back = True
            assert caught and rolled_back, (caught, rolled_back)
            with sqlite3.connect(path) as conn:
                after = {table: conn.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
                         for table in before}
            assert after == before
        else:
            assert policy.pass_("retention-owned") == (1, ["forgetting: archived 1 unused episodes"])
            with sqlite3.connect(path) as conn:
                assert dict(conn.execute("SELECT episode_id,status FROM episodes")) == {
                    ids[0]: "archived", ids[1]: "active"}
                audits = conn.execute("SELECT target_id FROM mutation_log WHERE action IN "
                                      "('forget','episode_archived') ORDER BY id").fetchall()
                assert audits == [(ids[0],), (ids[0],)], audits
        with sqlite3.connect(path) as conn:
            conn.execute("DROP TRIGGER reverse_second")
        expected = 2 if outer else 1
        assert policy.pass_("retention-recovery") == (
            expected, [f"forgetting: archived {expected} unused episodes"])
        assert policy.pass_("retention-repeat") == (0, [])
    return "independent archives survive later failure; caught caller-owned failure poisons whole pass"


def check_retention_rechecks_eligibility():
    from hungry_hippa.forgetting import ForgettingPolicy

    for column, value in (("importance", 0.9), ("last_accessed", "2999-01-01T00:00:00"),
                          ("status", "compressed")):
        c, path = _fresh("hh_retention_race_")
        eid = c.remember_episode(context="invented retention eligibility fixture",
                                 embed=False)["episode_id"]
        with sqlite3.connect(path) as conn:
            conn.execute("UPDATE episodes SET importance=0.2, last_accessed='2000-01-01T00:00:00'")
        policy = ForgettingPolicy(c.db, {"forgetting": {
            "auto_archival_after_unused_days": 1, "importance_decay_enabled": False,
            "compression_enabled": False}}, episodic=c.episodic)
        original = c.db._run
        changed = []
        def change_after_selection(fn, *args, **kwargs):
            result = original(fn, *args, **kwargs)
            if fn.__name__ == "_q" and not changed:
                # Independent SQLite connection commits after the selection snapshot.
                with sqlite3.connect(path, timeout=0) as conn:
                    conn.execute(f"UPDATE episodes SET {column}=? WHERE episode_id=?", (value, eid))
                    changed.append(conn.execute("SELECT * FROM episodes").fetchall())
            return result
        c.db._run = change_after_selection
        assert policy.pass_("retention-race") == (0, []), column
        c.db._run = original
        assert changed, "selection barrier was not exercised"
        with sqlite3.connect(path) as conn:
            assert conn.execute("SELECT * FROM episodes").fetchall() == changed[0], column
            assert conn.execute("SELECT COUNT(*) FROM mutation_log WHERE action IN "
                                "('forget','episode_archived')").fetchone()[0] == 0
            conn.execute("UPDATE episodes SET importance=0.2, status='active', "
                         "last_accessed='2000-01-01T00:00:00'")
        assert policy.pass_("retention-retry") == (1, ["forgetting: archived 1 unused episodes"])
        assert policy.pass_("retention-repeat") == (0, [])
    return "retention rechecks importance, access time and status after stale selection"


def check_retention_eligibility_lock():
    import subprocess
    from hungry_hippa.forgetting import ForgettingPolicy

    writer = """
import sqlite3, sys
try:
    with sqlite3.connect(sys.argv[1], timeout=0) as conn:
        conn.execute("UPDATE episodes SET importance=0.9")
except sqlite3.OperationalError as exc:
    assert 'locked' in str(exc), str(exc)
    print('locked')
else:
    print('updated')
"""
    for outer in (False, True):
        c, path = _fresh("hh_retention_lock_")
        c.remember_episode(context="invented retention lock fixture", embed=False)
        with sqlite3.connect(path) as conn:
            conn.execute("UPDATE episodes SET importance=0.2, last_accessed='2000-01-01T00:00:00'")
        policy = ForgettingPolicy(c.db, {"forgetting": {
            "auto_archival_after_unused_days": 1, "importance_decay_enabled": False,
            "compression_enabled": False}}, episodic=c.episodic)
        def attempt():
            return subprocess.run([sys.executable, "-c", writer, path], check=True,
                                  capture_output=True, text=True, timeout=15).stdout.strip()
        original = c.db._run
        attempts = []
        def after_read(fn, *args, **kwargs):
            result = original(fn, *args, **kwargs)
            if fn.__name__ == "_eligible":
                attempts.append(attempt())
            return result
        c.db._run = after_read
        if outer:
            with c.db.transaction():
                result = policy.pass_("retention-lock")
        else:
            result = policy.pass_("retention-lock")
        c.db._run = original
        assert attempts == ["locked"], attempts
        assert result == (1, ["forgetting: archived 1 unused episodes"]), result
        assert attempt() == "updated", "writer failed after commit"
    return "independent process blocked after eligibility read in owned/reused transactions; recovers after commit"


def check_decay_rejects_stale_selection():
    from hungry_hippa.forgetting import ForgettingPolicy

    for column, value in (("importance", 0.9), ("importance", 0.4),
                          ("updated_at", "2999-01-01T00:00:00"),
                          ("status", "archived")):
        c, path = _fresh("hh_decay_race_")
        eid = c.remember_episode(context="invented decay eligibility fixture",
                                 embed=False)["episode_id"]
        with sqlite3.connect(path) as conn:
            conn.execute("UPDATE episodes SET importance=0.2, updated_at='2000-01-01T00:00:00'")
        policy = ForgettingPolicy(c.db, {"forgetting": {
            "importance_decay_enabled": True, "compression_enabled": False}}, episodic=c.episodic)
        original = c.db._run
        changed = []
        def change_after_selection(fn, *args, **kwargs):
            result = original(fn, *args, **kwargs)
            if fn.__name__ == "_q" and not changed:
                with sqlite3.connect(path, timeout=0) as conn:
                    conn.execute(f"UPDATE episodes SET {column}=? WHERE episode_id=?", (value, eid))
                    changed.append(conn.execute("SELECT * FROM episodes").fetchall())
            return result
        c.db._run = change_after_selection
        assert policy.pass_("decay-race") == (0, []), (column, value)
        c.db._run = original
        assert changed, "selection barrier was not exercised"
        with sqlite3.connect(path) as conn:
            assert conn.execute("SELECT * FROM episodes").fetchall() == changed[0]
            conn.execute("UPDATE episodes SET importance=0.2, status='active', "
                         "updated_at='2000-01-01T00:00:00'")
        assert policy.pass_("decay-retry") == (1, ["forgetting: importance decay applied to 1 episodes"])
        assert policy.pass_("decay-repeat") == (0, [])
        with sqlite3.connect(path) as conn:
            assert abs(conn.execute("SELECT importance FROM episodes").fetchone()[0] - 0.14) < 1e-9
    return "stale importance/status/update time skips decay without overwriting committed changes; retry works"


def check_decay_persistence():
    from hungry_hippa.forgetting import ForgettingPolicy

    faults = (
        ("AFTER", "UPDATE episodes SET importance=OLD.importance WHERE episode_id=NEW.episode_id;"),
        ("AFTER", "UPDATE episodes SET updated_at=OLD.updated_at WHERE episode_id=NEW.episode_id;"),
        ("AFTER", "UPDATE episodes SET status='archived' WHERE episode_id=NEW.episode_id;"),
        ("AFTER", "DELETE FROM episodes WHERE episode_id=NEW.episode_id;"),
        ("BEFORE", "SELECT RAISE(IGNORE);"),
        ("BEFORE", "SELECT RAISE(ABORT, 'invented decay refusal');"),
    )
    for timing, body in faults:
        c, path = _fresh("hh_decay_persistence_")
        eid = c.remember_episode(context="invented decay persistence fixture", embed=False)["episode_id"]
        with sqlite3.connect(path) as conn:
            conn.execute("UPDATE episodes SET importance=0.2, updated_at='2000-01-01T00:00:00'")
            before = conn.execute("SELECT * FROM episodes").fetchall()
            conn.execute(f"CREATE TRIGGER decay_fault {timing} UPDATE OF importance ON episodes "
                         f"WHEN NEW.importance < OLD.importance BEGIN {body} END")
        policy = ForgettingPolicy(c.db, {"forgetting": {
            "importance_decay_enabled": True, "compression_enabled": False}}, episodic=c.episodic)
        assert policy.pass_("decay-fault") == (0, []), (timing, body)
        with sqlite3.connect(path) as conn:
            assert conn.execute("SELECT * FROM episodes").fetchall() == before, body
            conn.execute("DROP TRIGGER decay_fault")
        assert policy.pass_("decay-retry") == (1, ["forgetting: importance decay applied to 1 episodes"])
        assert policy.pass_("decay-repeat") == (0, [])
        with sqlite3.connect(path) as conn:
            row = conn.execute("SELECT importance, status, updated_at FROM episodes WHERE episode_id=?", (eid,)).fetchone()
            assert abs(row[0] - 0.14) < 1e-9 and row[1] == "active" and row[2] != '2000-01-01T00:00:00', row
    return "decay refusal/reversal/removal rolls back without success counts; retry persists and repeat skips"


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

    check("quarantine_cannot_starve_active_window", check_quarantine_cannot_starve_active_window)
    check("active_fts_window_preserves_policy", check_active_fts_window_preserves_policy)
    check("quarantined_memory_not_recalled", check_quarantined_not_recalled)
    check("superseded_belief_loses_to_current", check_superseded_belief_loses)
    check("explain_returns_score_parts", check_explain_has_score_parts)
    check("context_respects_max_context_chars", check_context_respects_budget)
    check("record_outcome_updates_procedure", check_record_outcome_updates_procedure)
    check("migration_v4_defaults", check_migration_v4_defaults)
    check("v4_migrates_populated_v3_database", check_v4_migrates_populated_v3_database)
    check("untrusted_actor_policy", check_untrusted_actor_policy)
    check("growth_recall_across_process", check_growth_recall_across_process)
    check("retention_counts_only_success", check_retention_counts_only_success)
    check("retention_audit_effects", check_retention_audit_effects)
    check("retention_transaction_ownership", check_retention_transaction_ownership)
    check("retention_rechecks_eligibility", check_retention_rechecks_eligibility)
    check("decay_rejects_stale_selection", check_decay_rejects_stale_selection)
    check("decay_persistence", check_decay_persistence)
    check("retention_eligibility_lock", check_retention_eligibility_lock)
    return results


if __name__ == "__main__":
    results = run_all()
    passed = sum(1 for r in results if r["passed"])
    for r in results:
        print(f"{'PASS' if r['passed'] else 'FAIL'}  {r['name']}: {r['detail']}")
    print(f"\n{passed}/{len(results)} passed")
    sys.exit(0 if passed == len(results) else 1)
