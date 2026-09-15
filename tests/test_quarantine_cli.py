"""Quarantine review CLI tests.

Quarantine is how an untrusted writer's memory is held back: the write still lands,
but recall, belief listing and consolidation all skip it. Until now the only way to
see or release those rows was a SQL prompt on the database file, which meant the one
decision that needs a human — "is this trustworthy?" — had no operator interface.

These tests cover the `hungry-hippa quarantine` commands added for that:

  list | show | approve | reject

Design rules the tests enforce:

  * review is an operator action (owner / local binding), never a model channel;
  * approval reuses the existing verification semantics
    (``trust.verified_source_class`` + the single promotion write
    ``SemanticMemory.set_verified_class``) rather than re-implementing them, and the
    operator's assertion is what gets recorded as verified provenance while the
    original claim is preserved;
  * rejection reuses the existing archival path — it is reversible and never purges;
  * MCP stays exactly six tools: no approve/reject/quarantine tool is exposed, and the
    model-facing in-process tool gains no such action.

run_all() -> list of {name, passed, detail}.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
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
from hungry_hippa import policy  # noqa: E402
from hungry_hippa import schema as _schema  # noqa: E402
from hungry_hippa import trust  # noqa: E402
from hungry_hippa.cli import hungry_hippa_command  # noqa: E402
from hungry_hippa.config import load_config  # noqa: E402
from hungry_hippa.controller import MemoryController  # noqa: E402

sys.path.insert(0, str(REPO_DIR / "tests"))
import mcp_harness as _harness  # noqa: E402  (imports the package itself)


# --------------------------------------------------------------------------- helpers

def _fresh(prefix: str) -> Tuple[MemoryController, str]:
    """A throwaway database plus an operator-bound controller.

    Never the operator's real database: every path here comes from ``tempfile``.
    """
    db_path = os.path.join(tempfile.mkdtemp(prefix=prefix), "hungry_hippa.db")
    os.environ["HUNGRY_HIPPA_DB"] = db_path
    ctrl = MemoryController(load_config(), db_path=db_path)
    ctrl.bind_session(session_id="cli_test", platform="cli", trust=trust.local_binding())
    return ctrl, db_path


def _untrusted_write(db_path: str, claim: str, *, kind: str = "fact",
                     confidence: float = 0.9) -> Dict[str, Any]:
    """Store a belief the way an untrusted MCP caller would: it must be quarantined."""
    ctrl = MemoryController(load_config(), db_path=db_path)
    ctrl.bind_session(session_id="untrusted", platform="test",
                      trust=trust.external_binding(claimed_actor="web-agent", token=""))
    assert ctrl.identity == trust.UNTRUSTED, ctrl.identity
    return ctrl.semantic.add_belief(claim, kind=kind, confidence=confidence,
                                    actor_id=ctrl.actor_id, identity=ctrl.identity,
                                    provenance=ctrl.provenance)


def _untrusted_episode(db_path: str, context: str) -> Dict[str, Any]:
    ctrl = MemoryController(load_config(), db_path=db_path)
    ctrl.bind_session(session_id="untrusted", platform="test",
                      trust=trust.external_binding(claimed_actor="web-agent", token=""))
    return ctrl.episodic.remember_episode(context=context, actor_id=ctrl.actor_id,
                                          identity=ctrl.identity,
                                          provenance=ctrl.provenance)


def _cli(**kwargs) -> Tuple[Any, int]:
    """Run a CLI command in-process; returns (parsed stdout or raw text, exit code)."""
    args = types.SimpleNamespace(**kwargs)
    buf = io.StringIO()
    code = 0
    with contextlib.redirect_stdout(buf):
        try:
            hungry_hippa_command(args)
        except SystemExit as e:                     # clean CLI error path
            code = int(e.code or 0)
    raw = buf.getvalue().strip()
    try:
        return json.loads(raw), code
    except json.JSONDecodeError:
        return raw, code


def _owner_view(db_path: str) -> MemoryController:
    ctrl = MemoryController(load_config(), db_path=db_path)
    ctrl.bind_session(session_id="owner", platform="cli", trust=trust.local_binding())
    return ctrl


def _recall_ids(ctrl: MemoryController, query: str) -> List[str]:
    out = ctrl.recall(query)
    return [str(i.get("belief_id") or i.get("episode_id") or "") for i in out.get("items", [])]


# ---------------------------------------------------------------------------- checks

def check_untrusted_write_appears_in_list():
    _, db_path = _fresh("hh_quar_list_")
    belief = _untrusted_write(db_path, "the north shaft layout was revised by the web agent")
    _untrusted_episode(db_path, "an untrusted episode about the north shaft")

    out, code = _cli(hungry_hippa_command="quarantine", quarantine_command="list",
                     limit=10, kind="")
    assert code == 0, code
    ids = {r["id"]: r for r in out["quarantined"]}
    assert belief["belief_id"] in ids, ids
    row = ids[belief["belief_id"]]
    # every field the operator needs to judge the row, and nothing that leaks more
    for field in ("kind", "actor", "claimed_source_class", "verified_source_class",
                  "content", "created_at"):
        assert field in row, (field, row)
    assert row["kind"] == "belief" and row["actor"] == "web-agent", row
    assert row["claimed_source_class"] == "agent_inference", row
    assert row["verified_source_class"] == trust.EXTERNAL_SOURCE_CLASS, row
    assert len(row["content"]) <= 121 and "north shaft layout" in row["content"], row

    # --kind filters, and a quarantined row is not visible to default recall
    only_episodes, _ = _cli(hungry_hippa_command="quarantine", quarantine_command="list",
                            limit=10, kind="episode")
    assert all(r["kind"] == "episode" for r in only_episodes["quarantined"]), only_episodes
    assert _recall_ids(_owner_view(db_path), "north shaft layout revised") == []
    return f"list shows {len(ids)} quarantined row(s) with provenance; default recall is empty"


def check_show_returns_the_row():
    _, db_path = _fresh("hh_quar_show_")
    belief = _untrusted_write(db_path, "the web agent claims the north shaft was revised")
    out, code = _cli(hungry_hippa_command="quarantine", quarantine_command="show",
                     target_id=belief["belief_id"])
    assert code == 0, code
    assert out["id"] == belief["belief_id"] and out["kind"] == "belief", out
    assert out["quarantined"] is True, out
    assert out["actor"] == "web-agent", out
    assert out["verified_source_class"] == trust.EXTERNAL_SOURCE_CLASS, out
    assert "north shaft" in out["content"], out
    assert out["created_at"] and out["status"], out
    return "show returns the row's content, actor, provenance and timestamps"


def check_approve_releases_and_recall_sees_it():
    _, db_path = _fresh("hh_quar_approve_")
    belief = _untrusted_write(db_path, "the north shaft layout was revised by the web agent")
    assert _recall_ids(_owner_view(db_path), "north shaft layout revised") == []

    out, code = _cli(hungry_hippa_command="quarantine", quarantine_command="approve",
                     target_id=belief["belief_id"], source_class="user_explicit")
    assert code == 0, code
    assert out["approved"] is True and out["rows_changed"] == 1, out

    row = _owner_view(db_path).semantic.get_belief(belief["belief_id"])
    assert not row["quarantined"], row
    assert row["verified_source_class"] == "user_explicit", row
    assert belief["belief_id"] in _recall_ids(_owner_view(db_path), "north shaft layout revised")

    listed, _ = _cli(hungry_hippa_command="quarantine", quarantine_command="list",
                     limit=10, kind="")
    assert belief["belief_id"] not in {r["id"] for r in listed["quarantined"]}, listed
    return "approve clears quarantine and the row is recall-visible again"


def check_approve_uses_existing_verification_semantics():
    _, db_path = _fresh("hh_quar_verify_")
    belief = _untrusted_write(db_path, "the web agent relayed a document about the north shaft")

    # the operator's asserted class is what gets recorded as verified provenance,
    # decided by the same rule the runtime already uses — not a second rule
    out, _ = _cli(hungry_hippa_command="quarantine", quarantine_command="approve",
                  target_id=belief["belief_id"], source_class="document")
    row = _owner_view(db_path).semantic.get_belief(belief["belief_id"])
    expected = trust.verified_source_class("document", trust.PROVENANCE_USER)
    assert row["verified_source_class"] == expected == "document", row
    assert out["verified_source_class"] == expected, out
    # the original claim is preserved so the promotion stays inspectable
    assert row["claimed_source_class"] == "agent_inference", row

    # single implementation: both entry points call the same promotion write, and
    # neither re-implements the verification SQL
    src = (PLUGIN_DIR / "cli.py").read_text(encoding="utf-8")
    approve_src = src.split("def _cmd_quarantine_approve", 1)[1].split("\ndef ", 1)[0]
    verify_src = src.split("def _cmd_verify", 1)[1].split("\ndef ", 1)[0]
    for name, chunk in (("approve", approve_src), ("verify", verify_src)):
        assert "set_verified_class(" in chunk, name
        assert "UPDATE beliefs" not in chunk, name       # no duplicated promotion SQL
    assert "verify_provenance" not in approve_src, "approval audits as its own action"

    # the promotion write itself is the one place that touches those columns
    sem = (PLUGIN_DIR / "semantic.py").read_text(encoding="utf-8")
    assert sem.count("UPDATE beliefs SET") >= 1
    assert "def set_verified_class" in sem

    # approval is an operator action: a model/external channel may not approve
    model_ctrl = MemoryController(load_config(), db_path=db_path)
    model_ctrl.bind_session(session_id="agent", platform="test",
                            trust=trust.agent_binding("agent"))
    assert policy.may_capability(policy.CAP_APPROVE, provenance=model_ctrl.provenance,
                                 identity=model_ctrl.identity) is False
    assert policy.may_capability(policy.CAP_APPROVE, provenance="user",
                                 identity=trust.OWNER) is True
    return "approval reuses trust.verified_source_class + the single promotion write"


def check_reject_removes_from_default_recall():
    _, db_path = _fresh("hh_quar_reject_")
    belief = _untrusted_write(db_path, "the web agent asserts the north shaft was revised")
    _cli(hungry_hippa_command="quarantine", quarantine_command="approve",
         target_id=belief["belief_id"], source_class="user_explicit")
    assert belief["belief_id"] in _recall_ids(_owner_view(db_path), "north shaft revised")

    out, code = _cli(hungry_hippa_command="quarantine", quarantine_command="reject",
                     target_id=belief["belief_id"], mode="archival")
    assert code == 0, code
    assert out["rejected"] is True and out["mode"] == "archival", out
    assert _recall_ids(_owner_view(db_path), "north shaft revised") == []
    return "reject takes the memory out of default recall"


def check_rejected_data_is_archived_not_purged():
    _, db_path = _fresh("hh_quar_archive_")
    ep = _untrusted_episode(db_path, "an untrusted episode the operator will reject")
    out, code = _cli(hungry_hippa_command="quarantine", quarantine_command="reject",
                     target_id=ep["episode_id"], mode="archival")
    assert code == 0 and out["rejected"] is True, out

    row = _owner_view(db_path).episodic.get_episode(ep["episode_id"])
    assert row is not None, "rejected memory must still exist: rejection is not purge"
    assert row["status"] == "archived", row
    assert row["context"], row

    # audit trail: an archival, plus the quarantine decision itself
    audit = _owner_view(db_path).db._run(lambda conn: [
        dict(r) for r in conn.execute(
            "SELECT action, target_id FROM mutation_log ORDER BY rowid")])
    actions = [a["action"] for a in audit]
    assert "quarantine_rejected" in actions, actions
    assert any(a in actions for a in ("forget", "archive", "forgotten")), actions

    # purge is deliberately not reachable through the quarantine commands
    refused, code = _cli(hungry_hippa_command="quarantine", quarantine_command="reject",
                         target_id=ep["episode_id"], mode="purge")
    assert code == 1 and "archival" in str(refused), refused
    assert _owner_view(db_path).episodic.get_episode(ep["episode_id"]) is not None
    return "rejected data stays archived and audited; purge is not offered"


def check_mcp_cannot_approve_or_reject():
    _, db_path = _fresh("hh_quar_mcp_")
    belief = _untrusted_write(db_path, "the web agent asserts the north shaft was revised")

    # the MCP surface is exactly the six tools — no quarantine administration
    mod = _harness.import_mcp_server()
    app = mod.build_server(controller=_owner_view(db_path), owner_token="")
    import asyncio

    tools = asyncio.run(app.list_tools())
    names = sorted(t.name for t in tools)
    assert names == ["hippa_build_context", "hippa_forget", "hippa_recall",
                     "hippa_record_outcome", "hippa_remember", "hippa_status"], names
    # administration means: no argument that decides a quarantine, and no tool that
    # offers the decision. Reading quarantined rows (`include_quarantined`) and
    # reporting counts are pre-existing read-only surfaces, not administration.
    admin_props = {"approve", "reject", "quarantine", "quarantine_action", "verify",
                   "promote", "owner_token", "token"}
    for tool in tools:
        props = set((tool.input_schema or {}).get("properties", {}))
        assert not (props & admin_props), (tool.name, sorted(props & admin_props))
        assert not any(w in tool.name for w in ("approve", "reject", "quarantine",
                                                "verify", "promote")), tool.name
        desc = (tool.description or "").lower()
        for verb in ("approve", "reject", "release from quarantine", "unquarantine"):
            assert verb not in desc, (tool.name, verb)

    # ...and the model-facing in-process tool gains no approve/reject action either
    from hungry_hippa import tools as _tools
    actions = set(_tools.TOOL_ACTIONS) if hasattr(_tools, "TOOL_ACTIONS") else set()
    if not actions:  # the schema is the source of truth when the list is absent
        blob2 = json.dumps(_tools.CORTEX_SCHEMA).lower()
        for forbidden in ("approve", "quarantine", "reject"):
            assert forbidden not in blob2, forbidden
    else:
        assert not (actions & {"approve", "quarantine", "reject", "verify"}), actions

    # the operator can still do what MCP cannot
    out, code = _cli(hungry_hippa_command="quarantine", quarantine_command="approve",
                     target_id=belief["belief_id"], source_class="user_explicit")
    assert code == 0 and out["approved"] is True, out
    return "MCP exposes exactly six tools and no approve/reject/quarantine capability"


def check_unknown_ids_fail_cleanly():
    _, db_path = _fresh("hh_quar_unknown_")
    for action in ("show", "approve", "reject"):
        out, code = _cli(hungry_hippa_command="quarantine", quarantine_command=action,
                         target_id="B-9999", source_class="user_explicit", mode="archival")
        assert code == 1, (action, code, out)
        assert isinstance(out, dict) and "unknown memory B-9999" in out.get("error", ""), out
        assert "Traceback" not in str(out), out

    # a bad source class is refused rather than silently stored
    belief = _untrusted_write(db_path, "the web agent asserts the north shaft was revised")
    out, code = _cli(hungry_hippa_command="quarantine", quarantine_command="approve",
                     target_id=belief["belief_id"], source_class="agent_inference")
    assert code == 1 and "source_class" in str(out.get("error", "")), out
    row = _owner_view(db_path).semantic.get_belief(belief["belief_id"])
    assert row["quarantined"], "a refused approval must not release the row"
    return "unknown ids and invalid classes exit 1 with a clean error"


# ------------------------------------------------------------------------- runner

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

    check("untrusted_write_appears_in_quarantine_list", check_untrusted_write_appears_in_list)
    check("show_returns_the_row", check_show_returns_the_row)
    check("approve_releases_and_recall_sees_it", check_approve_releases_and_recall_sees_it)
    check("approve_uses_existing_verification_semantics",
          check_approve_uses_existing_verification_semantics)
    check("reject_removes_from_default_recall", check_reject_removes_from_default_recall)
    check("rejected_data_is_archived_not_purged", check_rejected_data_is_archived_not_purged)
    check("mcp_cannot_approve_or_reject", check_mcp_cannot_approve_or_reject)
    check("unknown_ids_fail_cleanly", check_unknown_ids_fail_cleanly)
    return results


if __name__ == "__main__":
    results = run_all()
    passed = sum(1 for r in results if r["passed"])
    for r in results:
        print(f"{'PASS' if r['passed'] else 'FAIL'}  {r['name']}: {r['detail']}")
    print(f"\n{passed}/{len(results)} passed")
    sys.exit(0 if passed == len(results) else 1)
