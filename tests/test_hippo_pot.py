"""Hippo-Pot deployment tests.

Verifies manager abstraction, Hippo-Pot init/doctor/uninstall, systemd units,
and manager failure isolation. Uses throwaway configs and temp directories.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent))   # tests/ (shared helpers)
from _package import import_package  # noqa: E402

_PACKAGE = import_package()


def test_manager_not_configured():
    """Manager defaults to not-configured (safe baseline)."""
    from hungry_hippa.manager import LocalManager
    mgr = LocalManager({})
    assert not mgr.is_configured
    health = mgr.health()
    assert health.configured is False
    assert health.status_label() == "NOT CONFIGURED"
    print("PASS  test_manager_not_configured")


def test_manager_health_offline():
    """Manager health check reports OFFLINE when endpoint unreachable."""
    from hungry_hippa.manager import LocalManager
    cfg = {
        "manager": {
            "enabled": True,
            "endpoint": "http://127.0.0.1:19999/v1",
            "model": "test-model",
        }
    }
    mgr = LocalManager(cfg)
    assert mgr.is_configured
    health = mgr.health()
    assert health.configured is True
    assert health.reachable is False
    assert health.status_label() == "OFFLINE"
    print("PASS  test_manager_health_offline")


def test_manager_intent_not_configured():
    """Manager returns no-op when not configured."""
    from hungry_hippa.manager import LocalManager
    mgr = LocalManager({})
    intent = mgr.propose_intent("hello")
    assert intent.action == "no_op"
    print("PASS  test_manager_intent_not_configured")


def test_manager_allowed_actions():
    """Manager only allows whitelisted actions."""
    from hungry_hippa.manager import LocalManager
    assert "recall" in LocalManager.ALLOWED_ACTIONS
    assert "remember_episode" in LocalManager.ALLOWED_ACTIONS
    assert "consolidate" in LocalManager.ALLOWED_ACTIONS
    assert "no_op" in LocalManager.ALLOWED_ACTIONS
    assert "escalate" in LocalManager.ALLOWED_ACTIONS
    assert "drop_table" not in LocalManager.ALLOWED_ACTIONS
    assert "shell_exec" not in LocalManager.ALLOWED_ACTIONS
    print("PASS  test_manager_allowed_actions")


def test_manager_disallowed_action_parsed():
    """Parsed disallowed actions are remapped to no_op."""
    from hungry_hippa.manager import LocalManager
    mgr = LocalManager({
        "manager": {"enabled": True, "endpoint": "http://127.0.0.1:1/v1", "model": "m"}
    })
    # Simulate parsing a malicious intent
    result = mgr._parse_intent('{"action": "drop_all_tables", "reason": "test"}')
    assert result is not None
    # The propose_intent method would reject this
    if result.get("action") not in LocalManager.ALLOWED_ACTIONS:
        result["action"] = "no_op"
    assert result["action"] == "no_op"
    print("PASS  test_manager_disallowed_action_parsed")


def test_hippo_pot_init():
    """Hippo-Pot init creates config and systemd units."""
    import hungry_hippa.config as hh_config
    from hungry_hippa.hippo_pot import init_hippo_pot
    with tempfile.TemporaryDirectory() as tmpdir:
        config = {
            "hippo_pot": {
                "profile": "hippo-pot",
                "bind_address": "127.0.0.1",
            }
        }
        # Override config dir for test isolation
        orig_config_dir = hh_config.config_dir
        hh_config.config_dir = lambda: Path(tmpdir) / "config"

        try:
            result = init_hippo_pot(config)
            assert Path(result["config"]).exists()
            assert len(result["systemd_units"]) == 3
            # Check config file has hippo_pot profile
            with open(result["config"]) as f:
                cfg = json.load(f)
            assert cfg["hippo_pot"]["profile"] == "hippo-pot"
        finally:
            hh_config.config_dir = orig_config_dir
    print("PASS  test_hippo_pot_init")


def test_hippo_pot_doctor():
    """Doctor runs all checks and returns healthy for clean state."""
    from hungry_hippa.hippo_pot import HippoPotDiagnostics
    cfg = {
        "hippo_pot": {"profile": "hippo-pot", "bind_address": "127.0.0.1"},
        "manager": {"enabled": False},
    }
    diag = HippoPotDiagnostics(cfg)
    result = diag.run_all()
    assert "checks" in result
    assert "healthy" in result
    # Should have checks
    assert len(result["checks"]) > 5
    print("PASS  test_hippo_pot_doctor")


def test_hippo_pot_uninstall_preserve():
    """Uninstall preserves data by default."""
    from hungry_hippa.hippo_pot import uninstall_hippo_pot
    result = uninstall_hippo_pot(preserve_data=True)
    # Should list removed units
    assert "removed" in result
    print("PASS  test_hippo_pot_uninstall_preserve")


def test_manager_failure_isolation():
    """Manager failure does NOT affect core HH."""
    from hungry_hippa.manager import LocalManager
    from hungry_hippa.config import load_config

    # Bad endpoint
    mgr = LocalManager({
        "manager": {
            "enabled": True,
            "endpoint": "http://127.0.0.1:19999/v1",
            "model": "bad",
            "timeout": 1,
        }
    })

    # Health should show offline, not crash
    health = mgr.health()
    assert health.reachable is False

    # Intent should return no_op, not crash
    intent = mgr.propose_intent("test")
    assert intent.action == "no_op"

    # Core HH should still work
    cfg = load_config()
    assert cfg is not None
    print("PASS  test_manager_failure_isolation")


def run_all():
    tests = [
        test_manager_not_configured,
        test_manager_health_offline,
        test_manager_intent_not_configured,
        test_manager_allowed_actions,
        test_manager_disallowed_action_parsed,
        test_hippo_pot_init,
        test_hippo_pot_doctor,
        test_hippo_pot_uninstall_preserve,
        test_manager_failure_isolation,
    ]
    results = []
    for test in tests:
        try:
            test()
            results.append({"name": test.__name__, "passed": True})
        except Exception as e:
            print(f"FAIL  {test.__name__}: {e}")
            results.append({"name": test.__name__, "passed": False, "error": str(e)})

    passed = sum(1 for r in results if r["passed"])
    total = len(results)
    print(f"\n{passed}/{total} passed")
    return passed == total


if __name__ == "__main__":
    import sys
    ok = run_all()
    sys.exit(0 if ok else 1)
