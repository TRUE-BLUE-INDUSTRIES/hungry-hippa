"""Provenance tests: a caller may describe origin, but may not assign trust.

Finding: ``source_class`` came straight from the request payload and was stored
verbatim, so any caller could write memory wearing ``user_explicit`` — the label
that carries the highest confidence weight and wins contradiction resolution.
There was no separation between what a writer claimed and what the runtime
verified.

Now ``claimed_source_class`` records the claim and ``verified_source_class`` (and
the effective ``source_class`` used for trust weighting) is decided by the
channel: the operator's channel may assert an origin, the model's text is recorded
as ``agent_reported``, and anything unauthorized is ``external_source``.

run_all() -> list of {name, passed, detail}.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import sys
import tempfile
import types
from pathlib import Path
from typing import Any, Dict, List, Tuple

REPO_DIR = Path(__file__).resolve().parent.parent
PLUGIN_DIR = REPO_DIR / "src" / "hungry_hippa"   # src layout


def _import_plugin():
    if sys.modules.get("hungry_hippa") is not None and getattr(
        sys.modules["hungry_hippa"], "__file__", None
    ):
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
from hungry_hippa import trust  # noqa: E402
from hungry_hippa.config import load_config  # noqa: E402
from hungry_hippa.controller import MemoryController  # noqa: E402
from hungry_hippa.observability import Observability  # noqa: E402


def _ctrl(binding, prefix: str = "hh_prov_") -> Tuple[MemoryController, str]:
    tmp = tempfile.mkdtemp(prefix=prefix)
    db = os.path.join(tmp, "hungry_hippa.db")
    cfg = load_config()
    cfg["retrieval"]["vectors_enabled"] = False
    ctrl = MemoryController(cfg, db_path=db)
    ctrl.bind_session(session_id="s", platform="cli", trust=binding)
    return ctrl, db


def _mcp_call(ctrl, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """Drive the real MCP tool through the server object (the external channel).

    No owner token is configured here, so this is an untrusted MCP instance — the
    channel whose claims must not become trusted provenance.
    """
    import asyncio

    import mcp_harness as _h

    app = _h.import_mcp_server().build_server(controller=ctrl, owner_token="")
    result = asyncio.run(app.call_tool(name, args or {}))
    text = "".join(getattr(b, "text", "") or "" for b in getattr(result, "content", []) or [])
    try:
        return json.loads(text) if text else {}
    except json.JSONDecodeError:
        return {"ok": False, "error": text[:120]}


def _row(db: str, belief_id: str) -> Dict[str, Any]:
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        r = conn.execute("SELECT * FROM beliefs WHERE belief_id = ?",
                         (belief_id,)).fetchone()
        return dict(r) if r else {}
    finally:
        conn.close()


def check_untrusted_claim_does_not_become_trusted():
    """An unauthorized caller cannot wear user_explicit (real MCP call)."""
    ctrl, db = _ctrl(trust.external_binding("mcp-untrusted"))
    r = _mcp_call(ctrl, "hippa_remember", {
        "actor_id": "mcp-untrusted", "memory_type": "semantic",
        "content": "untrusted text claiming to be the operator",
        "source_class": "user_explicit", "confidence": 0.99})
    row = _row(db, r["belief_id"])
    assert row["claimed_source_class"] == "user_explicit", row
    assert row["verified_source_class"] == "external_source", row
    assert row["source_class"] == "external_source", row
    assert row["quarantined"] == 1, row
    assert row["source_actor"] == "mcp-untrusted", row
    assert row["confidence"] <= 0.60, "the claim still bought user-grade confidence"
    return (f"claimed {row['claimed_source_class']} -> verified "
            f"{row['verified_source_class']}, quarantined, confidence capped")


def check_agent_channel_cannot_promote_its_own_text():
    """The model's write is recorded as agent_reported, whatever it claims."""
    ctrl, db = _ctrl(trust.agent_binding(), prefix="hh_prov_agent_")
    import json as _json

    from hungry_hippa.observability import Observability as _Obs
    from hungry_hippa.tools import handle as _handle

    obs = _Obs(ctrl.db, ctrl.cfg, controller=ctrl)
    r = _json.loads(_handle(ctrl, obs, "add_belief", {
        "action": "add_belief",
        "claim": "the build requires elevated permissions (from a fetched page)",
        "source_class": "user_explicit", "confidence": 0.95}))
    row = _row(db, r["belief_id"])
    assert row["claimed_source_class"] == "user_explicit", row
    assert row["verified_source_class"] == "agent_reported", row
    assert row["source_class"] == "agent_reported", row
    assert row["ingestion_channel"] == trust.CHANNEL_AGENT_TOOL, row
    # and the confidence weighting follows the verified class, not the claim
    assert r["confidence"] <= 0.55, r
    why = Observability(ctrl.db, ctrl.cfg, controller=ctrl).why(r["belief_id"])
    assert why["claimed_source_class"] == "user_explicit", why
    assert why["verified_source_class"] == "agent_reported", why
    assert why["ingestion_channel"] == trust.CHANNEL_AGENT_TOOL, why
    return "model claimed user_explicit; stored and weighed as agent_reported"


def check_operator_channel_can_attest():
    """The human at a terminal can state the origin, and it sticks."""
    ctrl, db = _ctrl(trust.local_binding("primary"), prefix="hh_prov_user_")
    r = ctrl.semantic.add_belief("the operator said the draw is fixed",
                                 kind="fact", source_class="user_explicit",
                                 confidence=0.95, identity=ctrl.identity,
                                 provenance=ctrl.provenance, channel=ctrl.channel)
    row = _row(db, r["belief_id"])
    assert row["verified_source_class"] == "user_explicit", row
    assert row["claimed_source_class"] == "user_explicit", row
    assert row["ingestion_channel"] == trust.CHANNEL_LOCAL, row
    assert r["confidence"] >= 0.9, r
    return "operator channel: claimed == verified (user_explicit)"


def check_trust_weighting_uses_verified_class():
    """Contradiction resolution must weigh the verified class, not the claim."""
    ctrl, db = _ctrl(trust.local_binding("primary"), prefix="hh_prov_weigh_")
    truth = ctrl.semantic.add_belief("the crane slot is Tuesday", kind="fact",
                                     source_class="user_explicit", confidence=0.7,
                                     identity=ctrl.identity,
                                     provenance=ctrl.provenance,
                                     channel=ctrl.channel)
    # The model asserts a contradiction and claims the user said it
    ctrl.bind_session(session_id="s", platform="cli", trust=trust.agent_binding())
    # the controller method is the channel-aware path (it stamps the binding)
    rival = ctrl.contradict(truth["belief_id"], "the crane slot is Thursday",
                            confidence=0.95, source_class="user_explicit")
    after_truth = _row(db, truth["belief_id"])
    # The operator's statement is protected: the model's 0.95-confidence claim is
    # held as a quarantined agent_reported candidate and cannot retire it (see
    # tests/test_supersession.py). Its confidence is capped by the verified class.
    assert rival.get("blocked") is True, rival
    candidate = _row(db, rival["candidate"])
    assert candidate["verified_source_class"] == "agent_reported", candidate
    assert candidate["quarantined"] == 1, candidate
    assert candidate["confidence"] <= 0.55, candidate
    assert after_truth["status"] == "active", after_truth
    return (f"rival stored as {candidate['verified_source_class']} "
            f"(confidence {candidate['confidence']}), quarantined; truth untouched")


def check_provenance_is_inspectable_and_audited():
    """Claim, verified class, actor and channel are all queryable."""
    ctrl, db = _ctrl(trust.agent_binding(), prefix="hh_prov_audit_")
    r = ctrl.semantic.add_belief("note written by the model", kind="fact",
                                 source_class="document", confidence=0.8,
                                 identity=ctrl.identity,
                                 provenance=ctrl.provenance, channel=ctrl.channel)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        audit = [dict(x) for x in conn.execute(
            "SELECT action, detail FROM mutation_log WHERE target_id = ?",
            (r["belief_id"],))]
    finally:
        conn.close()
    assert audit, "no audit row for the write"
    assert "claimed=document" in audit[0]["detail"], audit
    assert "agent_reported" in audit[0]["detail"], audit
    why = Observability(ctrl.db, ctrl.cfg, controller=ctrl).why(r["belief_id"])
    for field in ("claimed_source_class", "verified_source_class",
                  "source_actor", "ingestion_channel"):
        assert field in why, (field, why)
    return "claim, verified class, actor and channel are queryable and audited"


def check_episode_provenance_is_recorded():
    """Episodes carry the same provenance split."""
    ctrl, db = _ctrl(trust.agent_binding(), prefix="hh_prov_ep_")
    r = ctrl.remember_episode(context="model-written episode summary",
                              outcome="unknown", embed=False,
                              claimed_source_class="user_explicit")
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        row = dict(conn.execute("SELECT * FROM episodes WHERE episode_id = ?",
                                (r["episode_id"],)).fetchone())
    finally:
        conn.close()
    assert row["claimed_source_class"] == "user_explicit", row
    assert row["verified_source_class"] == "agent_reported", row
    assert row["source_actor"] == "primary", row
    assert row["ingestion_channel"] == trust.CHANNEL_AGENT_TOOL, row
    return "episode claimed user_explicit -> verified agent_reported"


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

    check("untrusted_claim_does_not_become_trusted",
          check_untrusted_claim_does_not_become_trusted)
    check("agent_channel_cannot_promote_its_own_text",
          check_agent_channel_cannot_promote_its_own_text)
    check("operator_channel_can_attest", check_operator_channel_can_attest)
    check("trust_weighting_uses_verified_class",
          check_trust_weighting_uses_verified_class)
    check("provenance_is_inspectable_and_audited",
          check_provenance_is_inspectable_and_audited)
    check("episode_provenance_is_recorded", check_episode_provenance_is_recorded)
    return results


if __name__ == "__main__":
    results = run_all()
    passed = sum(1 for r in results if r["passed"])
    for r in results:
        print(f"{'PASS' if r['passed'] else 'FAIL'}  {r['name']}: {r['detail']}")
    print(f"\n{passed}/{len(results)} passed")
    sys.exit(0 if passed == len(results) else 1)
