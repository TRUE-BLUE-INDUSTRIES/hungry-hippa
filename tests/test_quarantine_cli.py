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
import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import types
from pathlib import Path
from typing import Any, Dict, List, Tuple

REPO_DIR = Path(__file__).resolve().parent.parent


sys.path.insert(0, str(Path(__file__).resolve().parent))   # tests/ (shared helpers)
from _package import import_package  # noqa: E402

PACKAGE_DIR = REPO_DIR / "src" / "hungry_hippa"   # src layout
_PLUGIN = import_package()
from hungry_hippa import policy  # noqa: E402
from hungry_hippa import schema as _schema  # noqa: E402
from hungry_hippa import trust  # noqa: E402
from hungry_hippa.cli import hungry_hippa_command  # noqa: E402
from hungry_hippa.config import load_config  # noqa: E402
from hungry_hippa.controller import MemoryController  # noqa: E402

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
    src = (PACKAGE_DIR / "cli.py").read_text(encoding="utf-8")
    approve_src = src.split("def _cmd_quarantine_approve", 1)[1].split("\ndef ", 1)[0]
    verify_src = src.split("def _cmd_verify", 1)[1].split("\ndef ", 1)[0]
    for name, chunk in (("approve", approve_src), ("verify", verify_src)):
        assert "set_verified_class(" in chunk, name
        assert "UPDATE beliefs" not in chunk, name       # no duplicated promotion SQL
    assert "verify_provenance" not in approve_src, "approval audits as its own action"

    # the promotion write itself is the one place that touches those columns
    sem = (PACKAGE_DIR / "semantic.py").read_text(encoding="utf-8")
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


def check_approve_releases_an_episode_too():
    """Episode approval exercises episodic.set_verified_class, which targets a
    different column set than beliefs (episodes have no ``source_class`` column).
    A naive copy of the belief SQL would write rows_changed=0 here."""
    _, db_path = _fresh("hh_quar_approve_ep_")
    ep = _untrusted_episode(db_path, "the web agent walked the north shaft")
    assert _recall_ids(_owner_view(db_path), "north shaft") == []

    out, code = _cli(hungry_hippa_command="quarantine", quarantine_command="approve",
                     target_id=ep["episode_id"], source_class="user_explicit")
    assert code == 0, code
    assert out["approved"] is True and out["rows_changed"] == 1, out

    row = _owner_view(db_path).episodic.get_episode(ep["episode_id"])
    assert not row["quarantined"], row
    assert row["verified_source_class"] == "user_explicit", row
    assert ep["episode_id"] in _recall_ids(_owner_view(db_path), "north shaft")
    # the claim stays inspectable rather than silently rewritten
    assert row["claimed_source_class"] == ep.get("claimed_source_class", ""), row
    return "episode approve clears quarantine and sets verified provenance"


def check_approval_persistence_faults():
    """CLI success requires a durable promotion, not just a helper return."""
    def command(path, *args):
        result = subprocess.run(
            [sys.executable, "-m", "hungry_hippa.cli", *args],
            env=dict(os.environ, HUNGRY_HIPPA_DB=path),
            text=True, capture_output=True, timeout=30)
        assert "Traceback" not in result.stderr, result.stderr
        return result.returncode, json.loads(result.stdout)

    def snapshot(path, table):
        with sqlite3.connect(path) as conn:
            return (conn.execute(f"SELECT * FROM {table}").fetchall(),
                    conn.execute("SELECT * FROM mutation_log").fetchall())

    cases = 0
    for kind, table in (("belief", "beliefs"), ("episode", "episodes")):
        fields = ["quarantined", "verified_source_class", "source_actor",
                  "ingestion_channel", "claimed_source_class"]
        if kind == "belief":
            fields.append("source_class")
        for fault in ("IGNORE", "ABORT", "missing_row", "audit_reversal", *fields):
            ctrl, path = _fresh("hh_quar_fault_")
            text = "Synthetic amber valve uses ceramic seals"
            row = (_untrusted_write(path, text) if kind == "belief"
                   else _untrusted_episode(path, text))
            target = row[kind + "_id"]
            evidence = ctrl.db.add_evidence(text, kind="document",
                                             source_ref="fixture:amber-valve")
            ctrl.db.link_evidence(kind, target, [evidence])
            before = snapshot(path, table)
            if fault in ("IGNORE", "ABORT"):
                timing = "BEFORE"
                body = ("SELECT RAISE(IGNORE);" if fault == "IGNORE" else
                        "SELECT RAISE(ABORT, 'synthetic refusal');")
            elif fault == "missing_row":
                timing = "AFTER"
                body = f"DELETE FROM {table} WHERE {kind}_id=NEW.{kind}_id;"
            elif fault == "audit_reversal":
                timing = "AFTER"
                body = (f"UPDATE {table} SET quarantined=1 "
                        f"WHERE {kind}_id=NEW.target_id;")
            else:
                timing = "AFTER"
                value = ("1" if fault == "quarantined" else "'synthetic-alteration'")
                body = (f"UPDATE {table} SET {fault}={value} "
                        f"WHERE {kind}_id=NEW.{kind}_id;")
            with sqlite3.connect(path) as conn:
                event = ("INSERT ON mutation_log WHEN NEW.action='quarantine_approved'"
                         if fault == "audit_reversal" else
                         f"UPDATE OF quarantined ON {table}")
                conn.execute(f"CREATE TRIGGER stop_promotion {timing} {event} BEGIN {body} END")
            code, out = command(path, "quarantine", "approve", target,
                                "--source-class", "document")
            assert code == 1 and out.get("approved") is False and out.get("error"), (
                kind, fault, code, out)
            assert snapshot(path, table) == before, (kind, fault, "partial write/audit")
            code, recalled = command(path, "recall", "amber valve ceramic seals")
            assert code == 0 and not recalled.get("items"), recalled
            with sqlite3.connect(path) as conn:
                conn.execute("DROP TRIGGER stop_promotion")
            code, out = command(path, "quarantine", "approve", target,
                                "--source-class", "document")
            assert code == 0 and out["approved"] and out["rows_changed"] == 1, out
            code, recalled = command(path, "recall", "amber valve ceramic seals")
            assert code == 0, recalled
            item = next(i for i in recalled["items"] if i.get(kind + "_id") == target)
            assert evidence in item["evidence_ids"], item
            assert item["verified_source_class"] == "document", item
            assert evidence in recalled["sources"], recalled
            with sqlite3.connect(path) as conn:
                assert conn.execute("SELECT source_ref FROM evidence WHERE evidence_id=?",
                                    (evidence,)).fetchone() == ("fixture:amber-valve",)
            # Re-approval stays compatible: the row need not still be quarantined.
            code, out = command(path, "quarantine", "approve", target,
                                "--source-class", "document")
            assert code == 0 and out["approved"], out
            cases += 1
    return f"{cases} promotion faults roll back; fresh CLI retry/recall retains evidence"


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


def check_promotion_audit_persistence():
    """A suppressed operator audit must roll back the promotion, not report success."""
    cases = 0
    for operation, kind in (("verify", "belief"), ("approve", "belief"), ("approve", "episode")):
        for fault in ("IGNORE", "ABORT", "action", "target_kind", "target_id", "detail",
                      "session_id", "timestamp", "extra"):
            ctrl, path = _fresh("hh_promotion_audit_")
            row = (_untrusted_write(path, "Synthetic indigo valve uses ceramic seals")
                   if kind == "belief" else
                   _untrusted_episode(path, "Synthetic indigo valve uses ceramic seals"))
            target = row[kind + "_id"]
            action = "verify_provenance" if operation == "verify" else "quarantine_approved"
            table = "beliefs" if kind == "belief" else "episodes"
            args = (["verify", target] if operation == "verify" else
                    ["quarantine", "approve", target]) + ["--source-class", "document"]

            def command():
                result = subprocess.run([sys.executable, "-m", "hungry_hippa.cli", *args],
                                        env=dict(os.environ, HUNGRY_HIPPA_DB=path),
                                        text=True, capture_output=True, timeout=30)
                assert "Traceback" not in result.stderr, result.stderr
                return result.returncode, json.loads(result.stdout)

            def snapshot():
                with sqlite3.connect(path) as conn:
                    return (conn.execute(f"SELECT * FROM {table}").fetchall(),
                            conn.execute("SELECT * FROM mutation_log").fetchall())

            # An old matching audit is not proof that this attempt was recorded.
            detail = (("operator set verified_source_class=document " if operation == "verify"
                       else "operator released from quarantine; verified_source_class=document ")
                      + f"(claimed was {row.get('claimed_source_class', '')})")
            ctrl.db.log_mutation(action, kind, target, detail, "cli")
            before = snapshot()
            timing = "BEFORE" if fault in ("IGNORE", "ABORT") else "AFTER"
            if fault in ("IGNORE", "ABORT"):
                body = ("SELECT RAISE(IGNORE);" if fault == "IGNORE" else
                        "SELECT RAISE(ABORT, 'synthetic audit refusal');")
            elif fault == "extra":
                body = ("INSERT INTO mutation_log(ts, action, target_kind, target_id, detail, session_id) "
                        "VALUES ('synthetic', 'extra', '', '', '', '');")
            else:
                field = "ts" if fault == "timestamp" else fault
                value = "''" if fault == "timestamp" else "'synthetic-alteration'"
                body = f"UPDATE mutation_log SET {field}={value} WHERE id=NEW.id;"
            with sqlite3.connect(path) as conn:
                conn.execute(f"CREATE TRIGGER stop_audit {timing} INSERT ON mutation_log "
                             f"WHEN NEW.action='{action}' BEGIN {body} END")
            code, out = command()
            assert code == 1 and out.get("error"), (operation, kind, fault, code, out)
            assert snapshot() == before, (operation, kind, fault, "partial promotion/audit")
            with sqlite3.connect(path) as conn:
                conn.execute("DROP TRIGGER stop_audit")
            code, out = command()
            assert code == 0 and out["rows_changed"] == 1, out
            with sqlite3.connect(path) as conn:
                audits = conn.execute("SELECT action, target_kind, target_id, detail, session_id, ts "
                                      "FROM mutation_log WHERE action=? ORDER BY id", (action,)).fetchall()
                persisted = conn.execute(f"SELECT verified_source_class, quarantined FROM {table} "
                                         f"WHERE {kind}_id=?", (target,)).fetchone()
            assert len(audits) == 2 and audits[-1][:3] == (action, kind, target), audits
            assert "verified_source_class=document" in audits[-1][3] and audits[-1][5], audits
            assert audits[-1][4] == "cli" and audits[-1][:5] == audits[0][:5], audits
            assert persisted == ("document", int(operation == "verify")), persisted
            cases += 1
        # Imported provenance is untrusted text; preserve logger redaction/capping.
        from hungry_hippa.limits import redact
        for claimed in ("Authorization: Bearer synthetic_fixture_token", "synthetic " * 400):
            with sqlite3.connect(path) as conn:
                conn.execute(f"UPDATE {table} SET claimed_source_class=? WHERE {kind}_id=?",
                             (claimed, target))
            code, out = command()
            assert code == 0 and out["rows_changed"] == 1, out
            detail = (("operator set verified_source_class=document " if operation == "verify"
                       else "operator released from quarantine; verified_source_class=document ")
                      + f"(claimed was {claimed})")
            expected = redact(detail)[:2000]
            assert expected != detail, "fixture must exercise redaction or truncation"
            with sqlite3.connect(path) as conn:
                audit = conn.execute("SELECT detail FROM mutation_log WHERE action=? ORDER BY id DESC LIMIT 1",
                                     (action,)).fetchone()[0]
            assert audit == expected and len(audit) <= 2000, audit
    return f"{cases} audit faults roll back promotion; fresh CLI retries and redaction/capping pass"


def check_verify_persistence_faults():
    """Standalone verification must not claim a suppressed promotion succeeded."""
    def command(path, *args):
        result = subprocess.run(
            [sys.executable, "-m", "hungry_hippa.cli", *args],
            env=dict(os.environ, HUNGRY_HIPPA_DB=path),
            text=True, capture_output=True, timeout=30)
        assert "Traceback" not in result.stderr, result.stderr
        return result.returncode, json.loads(result.stdout)

    def snapshot(path):
        with sqlite3.connect(path) as conn:
            return (conn.execute("SELECT * FROM beliefs").fetchall(),
                    conn.execute("SELECT * FROM mutation_log").fetchall())

    fields = ("verified_source_class", "source_class", "source_actor",
              "ingestion_channel", "claimed_source_class", "quarantined", "status")
    cases = 0
    for fault in ("IGNORE", "ABORT", "missing_row", "audit_reversal", *fields):
        ctrl, path = _fresh("hh_verify_fault_")
        row = _untrusted_write(path, "Synthetic amber valve uses ceramic seals")
        target = row["belief_id"]
        evidence = ctrl.db.add_evidence("Synthetic valve specification", kind="document",
                                         source_ref="fixture:verify-valve")
        ctrl.db.link_evidence("belief", target, [evidence])
        before = snapshot(path)
        event = "UPDATE OF verified_source_class ON beliefs"
        timing = "AFTER"
        if fault in ("IGNORE", "ABORT"):
            timing = "BEFORE"
            body = ("SELECT RAISE(IGNORE);" if fault == "IGNORE" else
                    "SELECT RAISE(ABORT, 'synthetic refusal');")
        elif fault == "missing_row":
            body = "DELETE FROM beliefs WHERE belief_id=NEW.belief_id;"
        elif fault == "audit_reversal":
            event = "INSERT ON mutation_log WHEN NEW.action='verify_provenance'"
            body = "UPDATE beliefs SET verified_source_class='external_source' WHERE belief_id=NEW.target_id;"
        else:
            value = "0" if fault == "quarantined" else "'synthetic-alteration'"
            body = f"UPDATE beliefs SET {fault}={value} WHERE belief_id=NEW.belief_id;"
        with sqlite3.connect(path) as conn:
            conn.execute(f"CREATE TRIGGER stop_verify {timing} {event} BEGIN {body} END")
        code, out = command(path, "verify", target, "--source-class", "document")
        assert code == 1 and out.get("error"), (fault, code, out)
        assert snapshot(path) == before, (fault, "partial promotion or false audit")
        with sqlite3.connect(path) as conn:
            conn.execute("DROP TRIGGER stop_verify")
        code, out = command(path, "verify", target, "--source-class", "document")
        assert code == 0 and out["rows_changed"] == 1, out
        persisted = _owner_view(path).semantic.get_belief(target)
        assert persisted is not None
        assert persisted["source_actor"] == ctrl.actor_id
        assert persisted["ingestion_channel"] == trust.CHANNEL_CLI
        with sqlite3.connect(path) as conn:
            audits = conn.execute("SELECT target_id, detail FROM mutation_log "
                                  "WHERE action='verify_provenance'").fetchall()
        assert len(audits) == 1 and audits[0][0] == target, audits
        assert "verified_source_class=document" in audits[0][1], audits
        assert persisted["verified_source_class"] == persisted["source_class"] == "document"
        assert persisted["claimed_source_class"] == row["claimed_source_class"]
        assert persisted["quarantined"] and persisted["status"] == "active"
        code, recalled = command(path, "recall", "amber valve ceramic seals")
        assert code == 0 and not recalled["items"], recalled
        code, out = command(path, "verify", target, "--source-class", "document")
        assert code == 0 and out["rows_changed"] == 1, out
        code, out = command(path, "quarantine", "approve", target, "--source-class", "document")
        assert code == 0 and out["approved"], out
        code, recalled = command(path, "recall", "amber valve ceramic seals")
        assert code == 0, recalled
        item = next(i for i in recalled["items"] if i.get("belief_id") == target)
        assert item["verified_source_class"] == "document" and evidence in item["evidence_ids"]
        assert evidence in recalled["sources"], recalled
        with sqlite3.connect(path) as conn:
            assert conn.execute("SELECT source_ref FROM evidence WHERE evidence_id=?",
                                (evidence,)).fetchone() == ("fixture:verify-valve",)
        cases += 1
    for status in ("active", "archived", "superseded"):
        for source_class in ("user_explicit", "document", "tool_result"):
            ctrl, path = _fresh("hh_verify_compat_")
            row = ctrl.semantic.add_belief("Synthetic cobalt valve specification",
                                           source_class="document")
            target = row["belief_id"]
            with sqlite3.connect(path) as conn:
                conn.execute("UPDATE beliefs SET status=? WHERE belief_id=?", (status, target))
            code, out = command(path, "verify", target, "--source-class", source_class)
            assert code == 0 and out["verified_source_class"] == source_class, out
            persisted = _owner_view(path).semantic.get_belief(target)
            assert persisted is not None
            assert persisted["status"] == status and not persisted["quarantined"], persisted
            assert persisted["verified_source_class"] == persisted["source_class"] == source_class
            assert persisted["claimed_source_class"] == row["claimed_source_class"]
            code, recalled = command(path, "recall", "cobalt valve specification")
            assert code == 0, recalled
            assert (target in {i.get("belief_id") for i in recalled["items"]}) == (status == "active")
    return f"{cases} verification faults roll back; retry and lifecycle/class compatibility pass"


def check_rejection_denial_audit():
    from unittest.mock import patch
    ctrl, path = _fresh("hh_reject_denial_")
    row = ctrl.semantic.add_belief("Synthetic operator-only valve specification")
    target = row["belief_id"]
    before = ctrl.semantic.get_belief(target)
    restricted = MemoryController(load_config(), db_path=path)
    restricted.bind_session(session_id="denied-review", platform="test",
                            trust=trust.external_binding(claimed_actor="web-agent", token=""))
    with patch("hungry_hippa.cli._controller", return_value=restricted):
        out, code = _cli(hungry_hippa_command="quarantine", quarantine_command="reject",
                         target_id=target)
    assert code == 1 and out.get("rejected") is False, out
    assert ctrl.semantic.get_belief(target) == before
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM mutation_log WHERE action='forget_denied' AND target_id=?", (target,)).fetchone() == (1,)
        assert conn.execute("SELECT COUNT(*) FROM mutation_log WHERE action='quarantine_rejected' AND target_id=?", (target,)).fetchone() == (0,)
    return "restricted binding denied without mutation; denial audit remains durable"


def check_rejection_persistence_faults():
    """Archival refusal must fail the real CLI and roll back its audit writes."""
    def command(path, *args):
        result = subprocess.run(
            [sys.executable, "-m", "hungry_hippa.cli", *args],
            env=dict(os.environ, HUNGRY_HIPPA_DB=path),
            text=True, capture_output=True, timeout=30)
        assert "Traceback" not in result.stderr, result.stderr
        return result.returncode, json.loads(result.stdout)

    def snapshot(path, table):
        with sqlite3.connect(path) as conn:
            return (conn.execute(f"SELECT * FROM {table}").fetchall(),
                    conn.execute("SELECT * FROM mutation_log").fetchall())

    cases = 0
    for kind, table in (("belief", "beliefs"), ("episode", "episodes")):
        for fault in ("IGNORE", "ABORT", "reversal", "missing_row", "audit_reversal"):
            ctrl, path = _fresh("hh_reject_fault_")
            text = "Synthetic amber valve uses ceramic seals"
            row = (_untrusted_write(path, text) if kind == "belief"
                   else _untrusted_episode(path, text))
            target = row[kind + "_id"]
            evidence = ctrl.db.add_evidence(text, kind="document",
                                            source_ref="fixture:reject-valve")
            ctrl.db.link_evidence(kind, target, [evidence])
            before = snapshot(path, table)
            timing = "AFTER"
            event = f"UPDATE OF status ON {table}"
            if fault in ("IGNORE", "ABORT"):
                timing = "BEFORE"
                body = ("SELECT RAISE(IGNORE);" if fault == "IGNORE" else
                        "SELECT RAISE(ABORT, 'synthetic refusal');")
            elif fault == "missing_row":
                body = f"DELETE FROM {table} WHERE {kind}_id=NEW.{kind}_id;"
            elif fault == "audit_reversal":
                event = "INSERT ON mutation_log WHEN NEW.action='quarantine_rejected'"
                body = f"UPDATE {table} SET status='active' WHERE {kind}_id=NEW.target_id;"
            else:
                body = f"UPDATE {table} SET status='active' WHERE {kind}_id=NEW.{kind}_id;"
            with sqlite3.connect(path) as conn:
                conn.execute(f"CREATE TRIGGER stop_reject {timing} {event} BEGIN {body} END")
            code, out = command(path, "quarantine", "reject", target)
            assert code == 1 and out.get("error") and out.get("rejected") is False, (kind, fault, code, out)
            assert snapshot(path, table) == before, (kind, fault, "partial archival/audit")
            with sqlite3.connect(path) as conn:
                conn.execute("DROP TRIGGER stop_reject")
            # Show the retained source is recallable after explicit approval,
            # then ensure successful rejection removes it in a fresh process.
            code, out = command(path, "quarantine", "approve", target, "--source-class", "document")
            assert code == 0 and out["approved"], out
            code, recalled = command(path, "recall", "amber valve ceramic seals")
            assert code == 0, recalled
            item = next(i for i in recalled["items"] if i.get(kind + "_id") == target)
            assert evidence in item["evidence_ids"] and evidence in recalled["sources"], recalled
            code, out = command(path, "quarantine", "reject", target)
            assert code == 0 and out["rejected"], out
            with sqlite3.connect(path) as conn:
                assert conn.execute(f"SELECT status FROM {table} WHERE {kind}_id=?", (target,)).fetchone() == ("archived",)
                assert conn.execute("SELECT source_ref FROM evidence WHERE evidence_id=?", (evidence,)).fetchone() == ("fixture:reject-valve",)
                assert conn.execute("SELECT COUNT(*) FROM mutation_log WHERE action='quarantine_rejected' AND target_id=?", (target,)).fetchone() == (1,)
            code, recalled = command(path, "recall", "amber valve ceramic seals")
            assert code == 0 and not recalled["items"], recalled
            # Already archived rejection remains a supported reversible no-op.
            code, out = command(path, "quarantine", "reject", target)
            assert code == 0 and out["rejected"], out
            cases += 1
    return f"{cases} archival faults roll back; CLI retry, durable evidence and fresh recall pass"


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
    check("approve_releases_an_episode_too", check_approve_releases_an_episode_too)
    check("approval_persistence_faults", check_approval_persistence_faults)
    check("promotion_audit_persistence", check_promotion_audit_persistence)
    check("verify_persistence_faults", check_verify_persistence_faults)
    check("rejection_denial_audit", check_rejection_denial_audit)
    check("rejection_persistence_faults", check_rejection_persistence_faults)
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
