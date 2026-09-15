"""Identity-binding tests: claimed identity must not create trust.

Finding (hardening pass 1): an MCP client could set ``actor_id`` to ``"primary"``
and be believed — reading the owner's private memories, receiving the database
path, and purging owner beliefs.

The model now: the **server launch context** authenticates.
``mcp_server.py`` reads ``HUNGRY_HIPPA_OWNER_TOKEN`` from its own environment once
at start-up and verifies it against the operator's ``0600`` token file. An owner
session therefore launches the server with the token in its environment; an
untrusted session launches it without one, and no tool argument changes that.

Every check here drives a real MCP session through the official SDK.

run_all() -> list of {name, passed, detail}.
"""

from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List

import mcp_harness as H

from hungry_hippa import policy, trust


def _seed_private(db: str, claim: str = "private note about the Ridgeline bid") -> str:
    ctrl = H.controller(db)
    r = ctrl.semantic.add_belief(claim, kind="fact", source_class="user_explicit",
                                 confidence=0.95, sensitivity="private")
    return r["belief_id"]


def check_claimed_owner_is_not_owner():
    """An untrusted server instance cannot be made an owner by a label."""
    db = H.fresh_db()
    bid = _seed_private(db)
    token_file, _token = H.make_token_file()      # exists, but we do not present it
    status = H.one_call(db, "hippa_status", {"actor_id": "primary"}, token_file=token_file)
    recall = H.one_call(db, "hippa_recall", {"actor_id": "primary", "query": "Ridgeline"},
                        token_file=token_file)
    forget = H.one_call(db, "hippa_forget",
                        {"actor_id": "primary", "target_kind": "belief",
                         "target_id": bid, "mode": "purge", "confirmation": True},
                        token_file=token_file)
    assert status["identity"] == trust.UNTRUSTED, status
    assert status["actor_id"] != "primary", status
    assert "db_path" not in status, "untrusted caller received the database path"
    assert recall["count"] == 0, recall
    assert forget["ok"] is False and "denied" in forget["error"], forget
    assert H.controller(db).semantic.get_belief(bid)["status"] == "active", "row modified"
    return "actor_id=primary on an untrusted instance: no read, no db_path, no purge"


def check_untrusted_cannot_read_private_or_self_promote():
    """No argument promotes the caller: not a label, an alias, a flag or a token."""
    db = H.fresh_db()
    _seed_private(db)
    token_file, _token = H.make_token_file()
    for args, why in (
        ({"actor_id": "primary", "query": "Ridgeline"}, "owner label"),
        ({"actor_id": "owner", "query": "Ridgeline"}, "owner alias"),
        ({"actor_id": "primary", "query": "Ridgeline", "sensitivity": "private"},
         "sensitivity on a read"),
        ({"actor_id": "primary", "query": "Ridgeline", "include_quarantined": True},
         "quarantine flag"),
    ):
        out = H.one_call(db, "hippa_recall", args, token_file=token_file)
        assert out.get("count") == 0, (why, out)
    wrote = H.one_call(db, "hippa_remember",
                       {"actor_id": "primary", "memory_type": "semantic",
                        "content": "untrusted attempt at a trusted label",
                        "source_class": "user_explicit", "sensitivity": "private"},
                       token_file=token_file)
    assert wrote["quarantined"] is True, wrote
    assert wrote["sensitivity"] == "unclassified", wrote
    assert wrote["identity"] == trust.UNTRUSTED, wrote
    assert wrote["verified_source_class"] == "external_source", wrote
    return "label, alias, flags and claimed source class all fail to promote"


def check_trusted_owner_instance_still_works():
    """An owner-authorized instance keeps full function, and never leaks the token."""
    db = H.fresh_db()
    bid = _seed_private(db)
    token_file, token = H.make_token_file()
    out = H.run_calls(db, [
        ("hippa_status", {"actor_id": "primary"}),
        ("hippa_recall", {"actor_id": "primary", "query": "Ridgeline bid"}),
        ("hippa_forget", {"actor_id": "primary", "target_kind": "belief",
                          "target_id": bid, "mode": "archive".replace("archive", "archival"),
                          "reason": "regression test"}),
    ], token_file=token_file, token=token)
    status, recall, forget = (r["json"] or {} for r in out["results"])
    blob = json.dumps([r["text"] for r in out["results"]])
    assert status["identity"] == trust.OWNER, status
    assert status["provenance"] == trust.PROVENANCE_USER, status
    assert "db_path" in status, status
    assert recall["count"] >= 1, recall
    assert forget["ok"] is True and forget["archived"] is True, forget
    assert token not in blob, "the owner token was echoed back to the caller"
    return "owner instance: reads, archives, sees db_path; token never echoed"


def check_token_file_is_private_and_not_logged():
    """The token file is 0600 and its value reaches no log, memory or response."""
    token_file, token = H.make_token_file()
    mode = stat.S_IMODE(os.stat(token_file).st_mode)
    assert mode == 0o600, f"token file mode {oct(mode)}"
    assert len(token) >= 32, len(token)

    db = H.fresh_db()
    H.one_call(db, "hippa_remember",
               {"actor_id": "primary", "memory_type": "semantic",
                "content": "owner note while the token is in scope"},
               token_file=token_file, token=token)
    import sqlite3
    conn = sqlite3.connect(db)
    try:
        audit = conn.execute("SELECT action, detail FROM mutation_log").fetchall()
        memory = conn.execute("SELECT claim FROM beliefs").fetchall()
    finally:
        conn.close()
    haystack = json.dumps(audit) + json.dumps(memory)
    assert token not in haystack, "the owner token reached the audit log or a memory row"
    return f"token file mode {oct(mode)}; token value absent from audit log and memories"


def check_binding_is_channel_derived_in_process():
    """In-process code is owner, the model is agent-provenance, external is not."""
    db = H.fresh_db()
    local = H.controller(db, binding=trust.local_binding())
    assert local.is_owner and local.provenance == trust.PROVENANCE_USER

    agent = H.controller(db, binding=trust.agent_binding())
    assert agent.is_owner, "the operator's own agent keeps owner identity"
    assert agent.provenance == trust.PROVENANCE_AGENT, agent.provenance

    system = H.controller(db, binding=trust.system_binding())
    assert not system.is_owner, "system work is not the operator"
    assert system.identity == trust.SYSTEM, system.identity
    assert system.provenance == trust.PROVENANCE_AGENT_CONSOLIDATION

    ext = H.controller(db, binding=trust.external_binding("nobody"))
    assert not ext.is_owner and ext.provenance == trust.PROVENANCE_EXTERNAL

    # a rebind without a binding must not silently change trust
    ext.bind_session(session_id="s2", platform="mcp", agent_context="primary")
    assert not ext.is_owner, "rebind escalated trust"
    assert ext.provenance == trust.PROVENANCE_EXTERNAL
    return "channel-derived identity, three levels, no escalation on rebind"


def check_owner_label_collision_is_remapped():
    """An untrusted label cannot alias the owner's rows."""
    db = H.fresh_db()
    _seed_private(db, "owner note about the Cedar run")
    binding = trust.external_binding("primary")
    assert binding.identity == trust.UNTRUSTED, binding
    assert binding.actor_id == policy.UNTRUSTED_ACTOR, binding
    allowed, reason = policy.may_read({"actor_id": "primary", "quarantined": 0,
                                       "sensitivity": "unclassified"},
                                      "primary", identity=trust.UNTRUSTED)
    assert allowed is False and reason == policy.REASON_OTHER_ACTOR, (allowed, reason)
    token_file, _token = H.make_token_file()
    out = H.one_call(db, "hippa_recall", {"actor_id": "primary", "query": "Cedar run"},
                     token_file=token_file)
    assert out["count"] == 0, out
    return "owner-label claim is remapped to the untrusted actor; no row aliasing"


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

    check("claimed_owner_is_not_owner", check_claimed_owner_is_not_owner)
    check("untrusted_cannot_read_private_or_self_promote",
          check_untrusted_cannot_read_private_or_self_promote)
    check("trusted_owner_instance_still_works", check_trusted_owner_instance_still_works)
    check("token_file_is_private_and_not_logged", check_token_file_is_private_and_not_logged)
    check("binding_is_channel_derived_in_process", check_binding_is_channel_derived_in_process)
    check("owner_label_collision_is_remapped", check_owner_label_collision_is_remapped)
    return results


if __name__ == "__main__":
    results = run_all()
    passed = sum(1 for r in results if r["passed"])
    for r in results:
        print(f"{'PASS' if r['passed'] else 'FAIL'}  {r['name']}: {r['detail']}")
    print(f"\n{passed}/{len(results)} passed")
    sys.exit(0 if passed == len(results) else 1)
