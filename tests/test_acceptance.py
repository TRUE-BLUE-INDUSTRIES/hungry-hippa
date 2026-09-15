"""Living Cortex acceptance tests (§23, adapted).

Runs standalone: registers the plugin dir as the ``hungry_hippa`` package so
it can be imported without the Hermes runtime. Each test maps to the spec:

  T1 episode creation          T6 procedural learning
  T2 visual recall             T7 provenance
  T3 graph relationship        T8 forgetting
  T4 temporal change           T9 consolidation
  T5 contradiction             T10 automatic use (provider loop)

run_all(db_path, embed_enabled=False) -> list of {name, passed, detail}.
"""

from __future__ import annotations

import os
import sys
import types
from pathlib import Path
from typing import Any, Dict, List

PLUGIN_DIR = Path(__file__).resolve().parent.parent


def _import_plugin():
    """Load the plugin: register a package shell with __path__, then execute
    __init__.py. Submodules resolve lazily through the package path, exactly
    like the real Hermes loader's synthetic package does."""
    import importlib.util

    if sys.modules.get("hungry_hippa") is not None and \
            getattr(sys.modules["hungry_hippa"], "__file__", None):
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


def _config_with_vision(cfg: Dict[str, Any]) -> Dict[str, Any]:
    cfg["privacy"]["vision_memory_enabled"] = True
    cfg["privacy"]["audio_memory_enabled"] = True
    cfg["consolidation"]["on_session_end"] = False  # keep tests deterministic
    return cfg


def run_all(db_path: str, embed_enabled: bool = False) -> List[Dict[str, Any]]:
    from hungry_hippa.config import load_config
    from hungry_hippa.controller import MemoryController

    cfg = load_config()
    cfg["retrieval"]["vectors_enabled"] = bool(embed_enabled)
    c = MemoryController(cfg, db_path=db_path)
    c.bind_session(session_id="test-session", platform="cli")
    results: List[Dict[str, Any]] = []

    def check(name: str, fn) -> None:
        try:
            detail = fn() or ""
            results.append({"name": name, "passed": True, "detail": str(detail)[:300]})
        except AssertionError as e:
            results.append({"name": name, "passed": False, "detail": f"assert: {e}"})
        except Exception as e:
            results.append({"name": name, "passed": False,
                            "detail": f"{type(e).__name__}: {e}"})

    # ------------------------------------------------------- T1 episode
    def t1():
        r = c.remember_episode(
            context="3D printed bracket cracked near bolt interface",
            user_request="fix the bracket", actions_taken="recommended larger fillet",
            decisions="4mm local wall + fillet", outcome="success",
            project="prototype_fab", importance_signals=["problem_discovered"],
            source_refs=["session:test"], embed=False)
        assert r.get("episode_id", "").startswith("E-"), r
        e = c.episodic.get_episode(r["episode_id"])
        assert e is not None and e["project"] == "prototype_fab"
        assert e["importance"] >= 0.55, f"importance too low: {e['importance']}"
        hits = c.db.fts_search("bracket cracked", kinds=["episode"])
        assert any(h["target_id"] == r["episode_id"] for h in hits)
        # structured row logged in mutation log
        changes = c.db._run(lambda conn: conn.execute(
            "SELECT COUNT(*) AS n FROM mutation_log WHERE target_id = ?",
            (r["episode_id"],)).fetchone()["n"])
        assert changes >= 1
        return f"episode {r['episode_id']} importance={e['importance']:.2f}"

    check("T1_episode_creation", t1)

    # ------------------------------------------------------- T2 visual
    def t2():
        from hungry_hippa.observability import Observability
        from hungry_hippa.vision import VisualEventMemory
        cfg2 = _config_with_vision(cfg)
        c2 = MemoryController(cfg2, db_path=db_path)
        c2.bind_session(session_id="glasses-session")
        v = VisualEventMemory(c2.db, cfg2, controller=c2)
        h = v.open_episode("problem", context="prototype inspection")
        assert h.get("open"), h
        v.observe(h["handle"], "glasses frame hinge cracked under load", channel="vision")
        closed = v.close_episode(h["handle"], outcome="failure",
                                 result="hinge failed at layer line")
        assert not closed.get("discarded"), closed
        # recall question "what happened when we looked at the prototype"
        out = c2.recall("what happened when we looked at the prototype hinge")
        assert out.get("count", 0) >= 1, out
        return f"recalled {out['count']} items for visual episode"

    check("T2_visual_recall", t2)

    # ------------------------------------------------------- T3 graph
    def t3():
        c.relate("Operator", "WORKS_ON", "Project_V", src_type="person", dst_type="project")
        c.relate("Project_V", "USES", "Printer_A", src_type="project", dst_type="device")
        c.relate("Project_V", "HAD_PROBLEM", "warping", src_type="project", dst_type="problem")
        c.relate("warping", "SOLVED_BY", "heated enclosure",
                 src_type="problem", dst_type="solution")
        # multi-hop: from Operator reach Printer_A within 2 hops
        edges = c.graph.traverse("Operator", hop_limit=2)
        texts = {f"{e['src']}-{e['rel']}-{e['dst']}" for e in edges}
        assert "Project_V-USES-Printer_A" in texts, texts
        assert "Project_V-HAD_PROBLEM-warping" in texts, texts
        assert "warping-SOLVED_BY-heated enclosure" in texts, texts
        return f"multi-hop traversal found {len(edges)} edges"

    check("T3_graph_relationship", t3)

    # ------------------------------------------------------- T4 temporal
    def t4():
        c.graph.relate("ProjectX", "USES", "Method_A")
        c.graph.supersede_relationships_from("ProjectX", "USES", reason="switched")
        c.graph.relate("ProjectX", "USES", "Method_B")
        now_edges = c.graph.query(src="ProjectX", rel="USES")
        assert [e["dst"] for e in now_edges] == ["Method_B"], now_edges
        hist = c.graph.query(src="ProjectX", rel="USES", include_history=True)
        dsts = {e["dst"]: e["status"] for e in hist}
        assert dsts.get("Method_A") == "superseded", dsts
        assert dsts.get("Method_B") == "active", dsts
        return "now=Method_B, before=Method_A (superseded, preserved)"

    check("T4_temporal_change", t4)

    # ------------------------------------------------------- T5 contradiction
    def t5():
        a = c.semantic.add_belief("Printer A prints PLA best at 215C", kind="belief",
                                  confidence=0.9, source_class="tool_result")
        b = c.semantic.contradict(a["belief_id"], "Printer A prints PLA best at 230C",
                                  confidence=0.6, source_class="agent_inference")
        winner = c.semantic.get_belief(a["belief_id"])
        loser = c.semantic.get_belief(b["belief_id"])
        assert winner["status"] == "active" and loser["status"] == "contradicted"
        assert b["belief_id"] in winner["contradictions"]
        # explicit user correction flips it
        c2 = c.semantic.contradict(winner["belief_id"], "Printer A prints PLA best at 230C",
                                   confidence=0.95, source_class="user_explicit")
        active = c.semantic.get_belief(c2["belief_id"])
        assert active["status"] == "active", active["status"]
        assert active["source_class"] == "user_explicit"
        assert c.semantic.get_belief(winner["belief_id"])["status"] == "contradicted"
        return "both claims preserved; explicit user correction won"

    check("T5_contradiction", t5)

    # ------------------------------------------------------- T6 procedural
    def t6():
        for i in range(3):
            c.remember_episode(
                context="wall thickness test", project="bracket_study",
                actions_taken="increase wall to 4mm + fillet", outcome="success",
                importance_signals=["physical_action", "project_relevance"], embed=False)
        c.remember_episode(context="thin wall test", project="bracket_study",
                           actions_taken="2mm wall", outcome="failure",
                           importance_signals=["problem_discovered"], embed=False)
        report = c.consolidate(reason="test")
        procs = c.procedural.list_procedures()
        cands = [p for p in procs if p["status"] == "candidate" and "bracket_study" in p["name"]]
        assert cands, report
        assert any("episode:" in d for d in cands[0]["derived_from"])
        return f"candidate '{cands[0]['name'][:50]}' derived from {len(cands[0]['derived_from'])} episodes"

    check("T6_procedural_learning", t6)

    # ------------------------------------------------------- T7 provenance
    def t7():
        ev = c.add_evidence("measured: bracket survived with 4mm wall",
                            kind="tool_result", source_ref="test-rig")
        b = c.semantic.add_belief("4mm wall + fillet survives for this bracket",
                                  kind="procedural_belief", confidence=0.8,
                                  source_class="tool_result",
                                  evidence_ids=[ev])
        from hungry_hippa.observability import Observability
        obs = Observability(c.db, cfg, controller=c)
        trace = obs.why(b["belief_id"])
        assert trace["evidence"], trace
        assert trace["evidence"][0]["content"].startswith("measured:"), trace
        assert trace["verdict"] == "well-evidenced", trace["verdict"]
        return "belief traced to tool_result evidence"

    check("T7_provenance", t7)

    # ------------------------------------------------------- T8 forgetting
    def t8():
        low = c.remember_episode(context="ambient noise", outcome="unknown",
                                 importance=0.1, embed=False)["episode_id"]
        high = c.remember_episode(context="critical design decision for cabinet",
                                  outcome="success", importance=0.9, embed=False)["episode_id"]
        # age the low item so decay applies
        c.db._run(lambda conn: conn.execute(
            "UPDATE episodes SET updated_at = '2020-01-01T00:00:00Z' WHERE episode_id = ?",
            (low,)), write=True)
        n, msgs = c.forgetting.pass_("test-session")
        low_e = c.episodic.get_episode(low)
        high_e = c.episodic.get_episode(high)
        assert low_e["importance"] < 0.1, low_e["importance"]
        assert high_e["importance"] == 0.9, "high-value item must not decay"
        r = c.forget("episode", low, mode="archival", reason="test")
        assert r.get("archived"), r
        assert c.episodic.get_episode(low)["status"] == "archived"
        return f"decay applied ({n} actions); high-value untouched"

    check("T8_forgetting", t8)

    # ------------------------------------------------------- T9 consolidation
    def t9():
        ev_before = c.add_evidence("raw: print completed at 215C",
                                   kind="tool_result")
        b1 = c.semantic.add_belief("Printer A nozzle 0.4mm is good for PLA",
                                   kind="fact", confidence=0.8, source_class="document",
                                   evidence_ids=[ev_before])
        b2 = c.semantic.add_belief("Printer A nozzle 0.4mm is good for PLA",
                                   kind="fact", confidence=0.5, source_class="agent_inference")
        report = c.consolidate(reason="test-t9")
        b2_after = c.semantic.get_belief(b2["belief_id"])
        b1_after = c.semantic.get_belief(b1["belief_id"])
        assert b2_after["status"] == "superseded", b2_after["status"]
        assert b1_after["status"] == "active"
        # raw evidence untouched
        evs = c.db.get_evidence([ev_before])
        assert evs[0]["content"] == "raw: print completed at 215C"
        assert report["counts"].get("duplicate_detection", 0) >= 1, report
        return "duplicates merged; raw evidence hash-verified intact"

    check("T9_consolidation", t9)

    # ------------------------------------------------------ T10 auto use
    def t10():
        p = _PLUGIN.LivingCortexProvider()
        assert p.is_available(), p.unavailable_reason()
        p.initialize("auto-session", platform="cli", db_path=db_path)
        assert p.get_tool_schemas(), "provider must expose the cortex tool"
        # simulate turns
        p.sync_turn("my drone arm keeps breaking at the bolt holes",
                    "I inspected the SCAD and recommended the gyroid sleeve",
                    messages=[])
        p.sync_turn("check the uav arm print settings",
                    "printed with 4 perimeters and gyroid infill",
                    messages=[])
        closed = p._ctrl.close_session("auto-session")
        assert closed.get("episodes_created"), closed
        # automatic recall path (prefetch) returns useful context
        ctx = p.prefetch("what did we do about the drone arm bolt holes?",
                         session_id="auto-session")
        assert ctx and len(ctx) > 0, "prefetch must auto-recall"
        status = p.recall_status()
        assert status is not None and status.count >= 1, status
        return f"prefetch injected {status.count} memories automatically"

    check("T10_automatic_use", t10)

    return results


if __name__ == "__main__":
    import tempfile

    db = os.path.join(tempfile.gettempdir(), "lc_acceptance.db")
    for f in (db, db + "-wal", db + "-shm"):
        if os.path.exists(f):
            os.remove(f)
    use_embed = "--embed" in sys.argv
    results = run_all(db, embed_enabled=use_embed)
    passed = sum(1 for r in results if r["passed"])
    for r in results:
        print(f"{'PASS' if r['passed'] else 'FAIL'}  {r['name']}: {r['detail']}")
    print(f"\n{passed}/{len(results)} passed")
    sys.exit(0 if passed == len(results) else 1)
