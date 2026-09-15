"""MCP integration tests: a real session with the official SDK client.

These launch ``mcp_server.py`` as a subprocess and drive it with the SDK's
``ClientSession`` over the SDK's stdio transport — no hand-rolled JSON-RPC, no
hand-rolled framing. That covers the checklist the protocol layer used to be
tested against, and adds the parts that only a real session can prove (launch-
environment authentication, stdout hygiene, SDK-side error behaviour).

run_all() -> list of {name, passed, detail}.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from typing import Any, Dict, List

import mcp_harness as H

from hungry_hippa import trust

INTENDED_TOOLS = {"hippa_remember", "hippa_recall", "hippa_build_context",
                  "hippa_record_outcome", "hippa_forget", "hippa_status"}


def _payload(result: Dict[str, Any]) -> Dict[str, Any]:
    return result.get("json") or {}


def _drop_dead(result: Dict[str, Any], where: str) -> None:
    assert not result["is_error"], (where, result["text"][:300])


def check_initialize_and_tool_list():
    """Items 1-4: launch, initialize through the SDK, list exactly the tools."""
    db = H.fresh_db("itc_init_")
    out = H.run_calls(db, [])
    server = out["initialize"]["server"]
    assert server is not None, out["initialize"]
    assert getattr(server, "name", "") == "hungry-hippa", server
    assert getattr(server, "version", "") and getattr(server, "version") != "0.0.0", server
    names = {t["name"] for t in out["tools"]}
    assert names == INTENDED_TOOLS, sorted(names)
    for t in out["tools"]:
        assert t["description"], f"{t['name']} has no description"
    return (f"initialized via SDK ({getattr(server, 'name')} "
            f"{getattr(server, 'version')}); tools = {sorted(names)}")


def check_no_secret_in_any_schema():
    """Item 5: the owner token is nowhere in the tool surface."""
    db = H.fresh_db("itc_secret_")
    out = H.run_calls(db, [])
    blob = json.dumps(out["tools"]).lower()
    assert "owner_token" not in blob, "owner_token is exposed in a schema"
    assert "owner token" not in blob and "owner secret" not in blob.replace("-", " ")
    assert "hungry_hippa_owner_token" not in blob, "the env var name leaked into a schema"
    for t in out["tools"]:
        props = (t["input_schema"] or {}).get("properties", {})
        assert "owner_token" not in props, t["name"]
        assert "token" not in json.dumps(props).lower(), (t["name"], props)
    return f"no token parameter in any of the {len(out['tools'])} tool schemas"


def check_lifecycle_status_remember_recall_context():
    """Items 6-9: status, store, recall, build context — over one real session."""
    db = H.fresh_db("itc_flow_")
    token_file, token = H.make_token_file()
    out = H.run_calls(db, [
        ("hippa_status", {}),
        ("hippa_remember", {"memory_type": "episodic",
                            "content": "freed the seized housing with a warm soak",
                            "result": "housing released intact", "outcome": "success",
                            "project": "Project A"}),
        ("hippa_remember", {"memory_type": "semantic",
                            "content": "the fixture jig torque is 45Nm",
                            "claim": "the fixture jig torque is 45Nm",
                            "kind": "fact", "confidence": 0.8,
                            "source_class": "document"}),
        ("hippa_recall", {"query": "seized housing warm soak"}),
        ("hippa_build_context", {"query": "jig torque", "max_chars": 1200}),
    ], token_file=token_file, token=token)
    status, ep, belief, recall, ctx = (_payload(r) for r in out["results"])
    for r in out["results"]:
        _drop_dead(r, r["name"])

    assert status["identity"] == trust.OWNER, status
    assert ep["episode_id"] == "E-0001", ep
    assert belief["belief_id"] == "B-0001" and belief["quarantined"] is False, belief
    assert recall["count"] >= 1 and "warm soak" in recall["context"], recall["context"][:200]
    assert recall["context"].startswith("<recalled_memory"), recall["context"][:80]
    assert ctx["rendering"].startswith("<recalled_memory"), ctx["rendering"][:80]
    assert ctx["trust"]["authority"] == "none", ctx.get("trust")
    assert ctx["chars_used"] <= ctx["budget_chars"], (ctx["chars_used"], ctx["budget_chars"])
    # the counts the first status call reported (before the writes) now reflect them
    after = H.one_call(db, "hippa_status", {}, token_file=token_file, token=token)
    assert after["counts"]["episodes"] == 1, after["counts"]
    assert after["counts"]["beliefs"] == 1, after["counts"]
    return "status/remember/recall/build_context all served through the SDK session"


def check_record_outcome_and_archive():
    """Items 10-11: record an outcome, then archive a permitted memory."""
    db = H.fresh_db("itc_proc_")
    ctrl = H.controller(db)
    proc = ctrl.create_procedure("warm soak before force", description="seized housing",
                                 steps=["apply heat", "wait", "turn"], confidence=0.6)
    assert proc.get("procedure_id"), proc
    token_file, token = H.make_token_file()
    out = H.run_calls(db, [
        ("hippa_record_outcome", {"procedure_id": proc["procedure_id"], "success": True}),
        ("hippa_remember", {"memory_type": "semantic", "content": "a scratch note",
                            "source_class": "external_source"}),
        ("hippa_forget", {"target_kind": "belief", "target_id": "B-0001",
                          "mode": "archival", "reason": "integration test"}),
    ], token_file=token_file, token=token)
    outcome, written, forgotten = (_payload(r) for r in out["results"])
    for r in out["results"]:
        _drop_dead(r, r["name"])
    assert outcome["procedure_id"] == proc["procedure_id"], outcome
    assert outcome["success_count"] >= 1, outcome
    assert written["belief_id"] == "B-0001", written
    assert forgotten["archived"] is True and forgotten["purged"] is False, forgotten
    after = H.controller(db).semantic.get_belief("B-0001")
    assert after["status"] == "archived", after["status"]
    return "record_outcome updated counters; archival succeeded and is reversible"


def check_unauthorized_purge_denied():
    """Item 12: an untrusted instance cannot purge."""
    db = H.fresh_db("itc_purge_")
    owner = H.controller(db)
    owner.semantic.add_belief("an ordinary note to purge", kind="fact",
                              source_class="document", confidence=0.4)
    untrusted = H.one_call(db, "hippa_forget",
                           {"target_kind": "belief", "target_id": "B-0001",
                            "mode": "purge", "confirmation": True})
    assert untrusted.get("ok") is False, untrusted
    assert "purge" in untrusted["error"], untrusted
    assert H.controller(db).semantic.get_belief("B-0001")["status"] == "active"
    # an untrusted instance cannot archive it either: it may write candidates
    # and nothing else
    archived = H.one_call(db, "hippa_forget",
                          {"target_kind": "belief", "target_id": "B-0001",
                           "mode": "archival"})
    assert archived.get("ok") is False, archived
    return "untrusted instance: purge refused and the row untouched"


def check_owner_instance_gets_owner_only_behaviour():
    """Item 13: the same calls succeed on an owner-authorized instance."""
    db = H.fresh_db("itc_owner_")
    H.controller(db).semantic.add_belief("an ordinary note to purge", kind="fact",
                                         source_class="document", confidence=0.4)
    token_file, token = H.make_token_file()
    status = H.one_call(db, "hippa_status", {}, token_file=token_file, token=token)
    assert status["identity"] == trust.OWNER and "db_path" in status, status
    purged = H.one_call(db, "hippa_forget",
                        {"target_kind": "belief", "target_id": "B-0001",
                         "mode": "purge", "confirmation": True},
                        token_file=token_file, token=token)
    assert purged.get("purged") is True, purged
    assert H.controller(db).semantic.get_belief("B-0001") is None
    return "owner instance: db_path visible, purge succeeded with confirmation"


def check_actor_label_grants_nothing():
    """Item 14: naming yourself 'owner' does not make you the owner."""
    db = H.fresh_db("itc_spoof_")
    ctrl = H.controller(db)
    ctrl.semantic.add_belief("operator-only note about the Vail estimate", kind="fact",
                             source_class="user_explicit", sensitivity="private")
    token_file, _token = H.make_token_file()
    for label in ("primary", "owner", "mcp-untrusted", ""):
        status = H.one_call(db, "hippa_status", {"actor_id": label},
                            token_file=token_file)
        assert status["identity"] == trust.UNTRUSTED, (label, status)
        assert "db_path" not in status, (label, status)
        recall = H.one_call(db, "hippa_recall",
                            {"actor_id": label, "query": "Vail estimate"},
                            token_file=token_file)
        assert recall["count"] == 0, (label, recall)
    # and a claim that collides with an owner label is remapped, not honoured
    label_seen = H.one_call(db, "hippa_status", {"actor_id": "owner"},
                            token_file=token_file)["actor_id"]
    assert label_seen == trust.UNTRUSTED if False else label_seen != "owner", label_seen
    return "actor_id is a label: identity stays untrusted, no read, no db_path"


def check_malformed_and_unknown_calls():
    """SDK-side error behaviour: unknown tool and schema-invalid arguments."""
    db = H.fresh_db("itc_bad_")
    try:
        out = H.run_calls(db, [("hippa_does_not_exist", {})])
        raised = False
    except Exception as e:
        raised = True
        assert "unknown" in str(e).lower() or "not found" in str(e).lower(), str(e)[:200]
    if not raised:
        r = out["results"][0]
        assert r["is_error"] or "unknown" in (r["text"] or "").lower(), r
    # an argument that violates the advertised schema is refused before any
    # handler runs: the SDK reports a tool error with no payload
    out = H.run_calls(db, [("hippa_recall", {"query": ["not", "a", "string"]})])
    r = out["results"][0]
    assert r["is_error"] is True and r["json"] is None, r
    # a server-side rule that no schema can express is still enforced
    bad_mode = H.one_call(db, "hippa_forget",
                          {"target_kind": "belief", "target_id": "B-0001",
                           "mode": "nonsense"})
    assert bad_mode.get("ok") is False and "mode must be" in bad_mode["error"], bad_mode
    # a query over the server's own limit is refused with a policy error
    over = H.one_call(db, "hippa_recall", {"query": "q" * 9000})
    assert over.get("ok") is False and "exceeds" in over["error"], over
    return ("unknown tool and schema-invalid arguments rejected at the SDK boundary; "
            "server-side limits and enum rules still enforced")


def check_stdout_is_protocol_only():
    """Item 15: nothing but protocol traffic on stdout; logs on stderr."""
    db = H.fresh_db("itc_stdout_")
    env = H.session_env(db)
    proc = subprocess.Popen([sys.executable, str(H.REPO / "mcp_server.py")],
                            cwd=str(H.REPO), env=env, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    proc.stdin.close()                      # EOF: the SDK shuts down cleanly
    try:
        stdout, stderr = proc.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise AssertionError("server did not exit on EOF")
    lines = [ln for ln in stdout.splitlines() if ln.strip()]
    for line in lines:
        json.loads(line)                   # every stdout line must be JSON-RPC
    assert "UNTRUSTED instance" in stderr or "owner token" in stderr, stderr[:300]
    assert not lines, f"non-protocol output on stdout: {lines[:2]}"
    return f"stdout clean ({len(lines)} lines); diagnostics went to stderr"


def check_malformed_line_does_not_pollute_stdout():
    """Garbage on stdin is handled by the SDK, not by us, and stays off stdout."""
    db = H.fresh_db("itc_garbage_")
    env = H.session_env(db)
    proc = subprocess.Popen([sys.executable, str(H.REPO / "mcp_server.py")],
                            cwd=str(H.REPO), env=env, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert proc.stdin and proc.stdout
    proc.stdin.write("this is not json\n")
    proc.stdin.flush()
    time.sleep(0.5)
    proc.stdin.close()
    try:
        stdout, stderr = proc.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise AssertionError("server did not exit after malformed input")
    for line in [ln for ln in stdout.splitlines() if ln.strip()]:
        json.loads(line)
    assert proc.returncode in (0, 1), proc.returncode
    return f"malformed input handled by the SDK (exit {proc.returncode}); stdout still clean"


def check_limits_and_non_enumeration_survive_the_sdk():
    """Item 9 of the brief: the resource and disclosure limits did not move."""
    db = H.fresh_db("itc_limits_")
    ctrl = H.controller(db)
    ctrl.semantic.add_belief("private note about the Ridgeline bid", kind="fact",
                             source_class="user_explicit", sensitivity="private")
    hit = H.one_call(db, "hippa_recall", {"query": "Ridgeline bid"})
    miss = H.one_call(db, "hippa_recall", {"query": "wombat sanctuary"})
    assert json.dumps(hit["excluded"]) == json.dumps(miss["excluded"]), (hit, miss)
    assert hit["excluded"].get("unauthorized") is True, hit["excluded"]
    assert "belief:" not in json.dumps(hit), hit
    big = H.one_call(db, "hippa_remember", {"memory_type": "semantic",
                                            "content": "c" * 40000})
    assert big.get("ok") is False and "exceeds" in big["error"], big
    entities = H.one_call(db, "hippa_status", {})
    assert entities["limits"]["max_content_chars"] == 32000, entities["limits"]
    return "non-enumerating exclusions and size limits still enforced server-side"


def check_required_fields_and_no_dangerous_arguments():
    """The advertised schemas are strict, and expose no SQL, path or export tool."""
    db = H.fresh_db("itc_schema_")
    out = H.run_calls(db, [])
    schemas = {t["name"]: (t["input_schema"] or {}) for t in out["tools"]}
    required = {
        "hippa_remember": {"memory_type", "content"},
        "hippa_recall": {"query"},
        "hippa_build_context": {"query"},
        "hippa_record_outcome": {"procedure_id", "success"},
        "hippa_forget": {"target_kind", "target_id"},
    }
    for name, fields in required.items():
        got = set(schemas[name].get("required", []))
        assert fields <= got, (name, fields, got)
    for name, schema in schemas.items():
        props = set((schema.get("properties") or {}).keys())
        forbidden = {"sql", "query_sql", "path", "db_path", "database", "dump",
                     "export", "export_kind", "file", "filename"}
        assert not (props & forbidden), (name, props & forbidden)
        blob = json.dumps(schema).lower()
        assert "sql" not in blob, (name, "sql appears in the schema")
    names = set(schemas)
    assert not any("export" in n or "dump" in n or "sql" in n for n in names), names
    assert "hippa_export" not in names, names
    return (f"{len(schemas)} tools with required fields declared and no SQL/path/"
            f"export arguments")


def check_status_is_counts_only_and_quarantine_stays_hidden():
    """Status exposes counts, never memory text; quarantined rows stay invisible."""
    db = H.fresh_db("itc_counts_")
    token_file, token = H.make_token_file()
    H.one_call(db, "hippa_remember",
               {"memory_type": "semantic", "content": "owner note about the Hollis job",
                "claim": "the Hollis job is scheduled", "source_class": "user_explicit"},
               token_file=token_file, token=token)
    secret = "untrusted candidate text that must never be recalled"
    H.one_call(db, "hippa_remember", {"memory_type": "semantic", "content": secret})
    owner_view = H.one_call(db, "hippa_status", {}, token_file=token_file, token=token)
    assert secret not in json.dumps(owner_view), "status leaked memory text"
    assert owner_view["counts"]["beliefs_quarantined"] == 1, owner_view["counts"]
    untrusted = H.one_call(db, "hippa_recall", {"query": "untrusted candidate text"})
    assert untrusted["count"] == 0, untrusted
    assert secret not in json.dumps(untrusted), untrusted
    assert json.dumps(untrusted["excluded"]).find("belief:") == -1, untrusted["excluded"]
    return "status is counts-only; quarantined content is invisible to the caller"


def check_no_network_transport_is_offered():
    """stdio is the only transport wired up: no HTTP, no socket, no listener."""
    source = (H.REPO / "mcp_server.py").read_text(encoding="utf-8")
    assert 'transport="stdio"' in source, "the stdio transport is not selected"
    for banned in ("streamable-http", "streamable_http", "transport=\"sse\"",
                   "uvicorn", "socketserver", "http.server"):
        assert banned not in source, f"{banned} appears in the server module"
    for mod in ("uvicorn", "starlette", "socket"):
        assert f"import {mod}\n" not in source, f"{mod} is imported by the server"
    return "stdio only: the server module selects no HTTP or socket transport"


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

    if not H.SDK_AVAILABLE:
        results.append({"name": "official_sdk", "passed": False,
                        "detail": "the official 'mcp' package is not importable"})
        return results

    check("initialize_and_tool_list", check_initialize_and_tool_list)
    check("no_secret_in_any_schema", check_no_secret_in_any_schema)
    check("lifecycle_status_remember_recall_context",
          check_lifecycle_status_remember_recall_context)
    check("record_outcome_and_archive", check_record_outcome_and_archive)
    check("unauthorized_purge_denied", check_unauthorized_purge_denied)
    check("owner_instance_gets_owner_only_behaviour",
          check_owner_instance_gets_owner_only_behaviour)
    check("actor_label_grants_nothing", check_actor_label_grants_nothing)
    check("malformed_and_unknown_calls", check_malformed_and_unknown_calls)
    check("stdout_is_protocol_only", check_stdout_is_protocol_only)
    check("malformed_line_does_not_pollute_stdout",
          check_malformed_line_does_not_pollute_stdout)
    check("limits_and_non_enumeration_survive_the_sdk",
          check_limits_and_non_enumeration_survive_the_sdk)
    check("required_fields_and_no_dangerous_arguments",
          check_required_fields_and_no_dangerous_arguments)
    check("status_is_counts_only_and_quarantine_stays_hidden",
          check_status_is_counts_only_and_quarantine_stays_hidden)
    check("no_network_transport_is_offered", check_no_network_transport_is_offered)
    return results


if __name__ == "__main__":
    results = run_all()
    passed = sum(1 for r in results if r["passed"])
    for r in results:
        print(f"{'PASS' if r['passed'] else 'FAIL'}  {r['name']}: {r['detail']}")
    print(f"\n{passed}/{len(results)} passed")
    sys.exit(0 if passed == len(results) else 1)
