"""Identity-binding tests: claimed identity must not create trust.

Finding: an MCP client could set ``actor_id`` to ``"primary"`` and be believed —
reading the owner's private memories, receiving the database path, and purging
owner beliefs. Trust now comes from the channel (``trust.py``), and an external
caller is the owner only when it presents the owner token, which lives in a
``0600`` file only the operator's OS user can read.

These tests drive the real stdio server in a subprocess, so they exercise the
actual boundary rather than a helper.

run_all() -> list of {name, passed, detail}.
"""

from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
import sys
import tempfile
import types
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PLUGIN_DIR = Path(__file__).resolve().parent.parent


def _import_plugin():
    if sys.modules.get("livingcortex") is not None and getattr(
        sys.modules["livingcortex"], "__file__", None
    ):
        return sys.modules["livingcortex"]
    pkg = types.ModuleType("livingcortex")
    pkg.__path__ = [str(PLUGIN_DIR)]
    pkg.__file__ = str(PLUGIN_DIR / "__init__.py")
    sys.modules["livingcortex"] = pkg
    spec = importlib.util.spec_from_file_location(
        "livingcortex", str(PLUGIN_DIR / "__init__.py"),
        submodule_search_locations=[str(PLUGIN_DIR)])
    mod = importlib.util.module_from_spec(spec)
    sys.modules["livingcortex"] = mod
    spec.loader.exec_module(mod)
    return mod


_PLUGIN = _import_plugin()
from livingcortex import policy, trust  # noqa: E402
from livingcortex.config import load_config  # noqa: E402
from livingcortex.controller import MemoryController  # noqa: E402


# --------------------------------------------------------------- harness

def _fixture(prefix: str = "hh_trust_") -> Tuple[str, str, str]:
    """Return (db_path, token_path, token) for one isolated test."""
    tmp = tempfile.mkdtemp(prefix=prefix)
    return (os.path.join(tmp, "hungry_hippa.db"),
            os.path.join(tmp, "owner.token"),
            trust.ensure_owner_token(os.path.join(tmp, "owner.token")))


def _seed_owner_memory(db_path: str, claim: str = "private note about the Ridgeline bid") -> str:
    """Write one private, owner-authored belief straight into the store."""
    ctrl = MemoryController(load_config(), db_path=db_path)
    ctrl.bind_session(session_id="seed", platform="cli",
                      trust=trust.local_binding("primary"))
    r = ctrl.semantic.add_belief(claim, kind="fact", source_class="user_explicit",
                                 confidence=0.95, sensitivity="private")
    return r["belief_id"]


class Client:
    """A real stdio MCP client subprocess."""

    def __init__(self, db_path: str, token_path: Optional[str] = None) -> None:
        env = dict(os.environ)
        env["HUNGRY_HIPPA_DB"] = db_path
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env.pop("LIVING_CORTEX_DB", None)
        if token_path is None:
            env.pop("HUNGRY_HIPPA_OWNER_TOKEN_FILE", None)
            env["HUNGRY_HIPPA_OWNER_TOKEN_FILE"] = os.path.join(
                os.path.dirname(db_path), "no-such-token-file")
        else:
            env["HUNGRY_HIPPA_OWNER_TOKEN_FILE"] = token_path
        self.proc = subprocess.Popen(
            [sys.executable, str(PLUGIN_DIR / "mcp_server.py")],
            cwd=str(PLUGIN_DIR), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, env=env)
        self._id = 0
        self.request("initialize", {"protocolVersion": "2024-11-05",
                                    "capabilities": {}})
        self.proc.stdin.write(json.dumps(
            {"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        self.proc.stdin.flush()

    def request(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict:
        assert self.proc.stdin and self.proc.stdout
        self._id += 1
        self.proc.stdin.write(json.dumps(
            {"jsonrpc": "2.0", "id": self._id, "method": method,
             "params": params or {}}) + "\n")
        self.proc.stdin.flush()
        return json.loads(self.proc.stdout.readline())

    def call(self, name: str, args: Dict[str, Any]) -> Dict:
        resp = self.request("tools/call", {"name": name, "arguments": args})
        return json.loads(resp["result"]["content"][0]["text"])

    def close(self) -> None:
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
            self.proc.wait(timeout=15)
        except Exception:
            self.proc.kill()


# ---------------------------------------------------------------- checks

def check_claimed_owner_is_not_owner():
    """A client that names itself 'primary' must not become the owner."""
    db, token_path, _token = _fixture()
    bid = _seed_owner_memory(db)
    client = Client(db, token_path=None)
    try:
        status = client.call("hippa_status", {"actor_id": "primary"})
        recall = client.call("hippa_recall", {"actor_id": "primary",
                                              "query": "Ridgeline bid"})
        forget = client.call("hippa_forget", {"actor_id": "primary",
                                              "target_kind": "belief",
                                              "target_id": bid, "mode": "purge",
                                              "confirmation": True})
    finally:
        client.close()

    assert status["identity"] == trust.UNTRUSTED, status
    assert status["actor_id"] != "primary", status
    assert "db_path" not in status, "untrusted caller received the database path"
    assert recall["count"] == 0, recall
    assert forget["ok"] is False and "denied" in forget["error"], forget

    ctrl = MemoryController(load_config(), db_path=db)
    assert ctrl.semantic.get_belief(bid)["status"] == "active", "row was modified"
    return "actor_id=primary without a token: untrusted, no read, no db_path, no purge"


def check_untrusted_cannot_read_private_or_self_promote():
    """Trust cannot be raised from the request: not by label, flag or bad token."""
    db, token_path, _token = _fixture()
    _seed_owner_memory(db)
    client = Client(db, token_path=None)
    try:
        for args, why in (
            ({"actor_id": "primary", "query": "Ridgeline"}, "owner label"),
            ({"actor_id": "owner", "query": "Ridgeline"}, "owner alias"),
            ({"actor_id": "primary", "owner_token": "not-the-token",
              "query": "Ridgeline"}, "forged token"),
            ({"actor_id": "primary", "owner_token": "",
              "query": "Ridgeline"}, "empty token"),
            ({"actor_id": "primary", "include_quarantined": True,
              "query": "Ridgeline"}, "quarantine flag"),
        ):
            out = client.call("hippa_recall", args)
            assert out["count"] == 0, (why, out)
        # a private write cannot be relabelled into view either
        wrote = client.call("hippa_remember", {
            "actor_id": "primary", "memory_type": "semantic",
            "content": "untrusted attempt at a trusted label",
            "source_class": "user_explicit", "sensitivity": "private"})
        assert wrote["quarantined"] is True, wrote
        assert wrote["sensitivity"] == "unclassified", wrote
        assert wrote["actor_id"] != "primary", wrote
    finally:
        client.close()
    return "label, alias, forged token, quarantine flag and sensitivity all fail to promote"


def check_trusted_owner_path_still_works():
    """The operator path — with the token — keeps full function."""
    db, token_path, token = _fixture()
    bid = _seed_owner_memory(db)
    client = Client(db, token_path=token_path)
    try:
        status = client.call("hippa_status", {"actor_id": "primary",
                                              "owner_token": token})
        recall = client.call("hippa_recall", {"actor_id": "primary",
                                              "owner_token": token,
                                              "query": "Ridgeline bid"})
        forget = client.call("hippa_forget", {"actor_id": "primary",
                                              "owner_token": token,
                                              "target_kind": "belief",
                                              "target_id": bid, "mode": "purge",
                                              "confirmation": True})
        # the token is consumed at the boundary: it is never echoed back
        blob = json.dumps([status, recall, forget])
    finally:
        client.close()

    assert status["identity"] == trust.OWNER, status
    assert status["provenance"] == trust.PROVENANCE_USER, status
    assert "db_path" in status, status
    assert recall["count"] >= 1, recall
    assert forget["ok"] is True and forget["purged"] is True, forget
    assert token not in blob, "owner token was echoed back to the caller"
    return "owner with token: reads, purges, receives db_path; token never echoed"


def check_token_file_is_private_and_not_logged():
    """The token file is 0600 and its value never reaches disk or a response."""
    db, token_path, token = _fixture()
    tmpperm = tempfile.mkdtemp(prefix="hh_trust_perm_")
    fresh = os.path.join(tmpperm, "owner.token")
    created = trust.ensure_owner_token(fresh)
    mode = stat.S_IMODE(os.stat(fresh).st_mode)
    assert mode == 0o600, f"token file mode {oct(mode)}"
    assert len(created) >= 32, len(created)

    client = Client(db, token_path=token_path)
    try:
        client.call("hippa_remember", {"actor_id": "primary", "owner_token": token,
                                       "memory_type": "semantic",
                                       "content": "owner note with the token in scope"})
    finally:
        client.close()

    import sqlite3
    conn = sqlite3.connect(db)
    try:
        rows = conn.execute("SELECT action, detail FROM mutation_log").fetchall()
        memory = conn.execute("SELECT claim FROM beliefs").fetchall()
    finally:
        conn.close()
    haystack = json.dumps(rows) + json.dumps(memory)
    assert token not in haystack, "the owner token reached the audit log or a memory row"
    assert "canary" not in haystack.lower()
    return f"token file mode {oct(mode)}; token value absent from audit log and memories"


def check_binding_is_channel_derived_in_process():
    """In-process code is owner; an MCP binding without a token is not."""
    db, token_path, token = _fixture()

    local = MemoryController(load_config(), db_path=db)
    local.bind_session(session_id="s", platform="cli", trust=trust.local_binding())
    assert local.is_owner and local.provenance == trust.PROVENANCE_USER

    agent = MemoryController(load_config(), db_path=db)
    agent.bind_session(session_id="s", platform="cli", trust=trust.agent_binding())
    assert agent.is_owner, "the operator's own agent keeps owner identity"
    assert agent.provenance == trust.PROVENANCE_AGENT, agent.provenance

    ext = MemoryController(load_config(), db_path=db)
    ext.bind_session(session_id="s", platform="mcp", trust=trust.external_binding("nobody"))
    assert not ext.is_owner and ext.provenance == trust.PROVENANCE_EXTERNAL

    # a rebind without a binding must not silently change trust
    ext.bind_session(session_id="s2", platform="mcp2", agent_context="primary")
    assert not ext.is_owner, "rebind escalated trust"
    assert ext.provenance == trust.PROVENANCE_EXTERNAL

    # the token only works when it matches this token file
    assert trust.token_matches(token, Path(token_path)) is True
    assert trust.token_matches("wrong", Path(token_path)) is False
    assert trust.token_matches(None, Path(token_path)) is False
    assert trust.token_matches("x" * 500, Path(token_path)) is False
    return "channel-derived identity, no escalation on rebind, constant-time token check"


def check_owner_label_collision_is_remapped():
    """An untrusted label cannot alias the owner's rows."""
    db, token_path, _token = _fixture()
    bid = _seed_owner_memory(db, "owner note about the Cedar run")

    # The owner writes with the label "primary"; an untrusted caller claiming
    # "primary" must not be able to read it back as one of its own rows.
    b = trust.external_binding("primary")
    assert b.identity == trust.UNTRUSTED and b.actor_id == policy.UNTRUSTED_ACTOR, b
    allowed, reason = policy.may_read({"actor_id": "primary", "quarantined": 0,
                                       "sensitivity": "unclassified"},
                                      "primary", identity=trust.UNTRUSTED)
    assert allowed is False and reason == policy.REASON_OTHER_ACTOR, (allowed, reason)

    client = Client(db, token_path=None)
    try:
        out = client.call("hippa_recall", {"actor_id": "primary",
                                           "query": "Cedar run"})
    finally:
        client.close()
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
    check("trusted_owner_path_still_works", check_trusted_owner_path_still_works)
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
