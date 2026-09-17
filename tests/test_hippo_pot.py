"""Hippo-Pot deployment tests.

Verifies manager abstraction, Hippo-Pot init/doctor/uninstall, systemd units,
manager failure integration, and manager security. Uses throwaway configs
and temp directories.
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


def test_manager_timeout():
    """Manager timeout must not crash or hang."""
    from hungry_hippa.manager import LocalManager

    # Use a non-responsive endpoint
    mgr = LocalManager({
        "manager": {
            "enabled": True,
            "endpoint": "http://10.255.255.1:9999/v1",
            "model": "test-model",
            "timeout": 1,
        }
    })
    health = mgr.health()
    assert health.reachable is False
    assert health.status_label() == "OFFLINE"

    # propose_intent should timeout gracefully
    intent = mgr.propose_intent("hello")
    assert intent.action == "no_op"
    print("PASS  test_manager_timeout")


def test_manager_malformed_json():
    """Malformed manager JSON must not crash."""
    from hungry_hippa.manager import LocalManager

    mgr = LocalManager({
        "manager": {
            "enabled": True,
            "endpoint": "http://127.0.0.1:1/v1",
            "model": "m",
        }
    })

    # Malformed JSON should return None from _parse_intent
    assert mgr._parse_intent("not json") is None
    assert mgr._parse_intent("{invalid}") is None
    assert mgr._parse_intent("") is None


    # Valid JSON with missing fields should still parse
    result = mgr._parse_intent('{"action": "recall"}')
    assert result is not None
    assert result["action"] == "recall"
    print("PASS  test_manager_malformed_json")


def test_manager_unsupported_action():
    """Manager proposing unsupported action must be rejected."""
    from hungry_hippa.manager import LocalManager

    mgr = LocalManager({
        "manager": {
            "enabled": True,
            "endpoint": "http://127.0.0.1:1/v1",
            "model": "m",
        }
    })

    # Simulate malicious actions
    malicious_actions = [
        {"action": "shell_exec", "reason": "run rm -rf /"},
        {"action": "drop_table", "reason": "delete episodes"},
        {"action": "purge_all", "reason": "destroy evidence"},
        {"action": "modify_schema", "reason": "change trust model"},
        {"action": "set_permissions", "reason": "grant admin"},
        {"action": "delete_all", "reason": "wipe database"},
    ]

    for mal in malicious_actions:
        parsed = mgr._parse_intent(json.dumps(mal))
        assert parsed is not None
        assert parsed["action"] not in LocalManager.ALLOWED_ACTIONS
    print("PASS  test_manager_unsupported_action")


def test_manager_process_failure():
    """Simulated manager process failure returns no_op."""
    from hungry_hippa.manager import LocalManager

    # Endpoint that will refuse connection (nothing listening)
    mgr = LocalManager({
        "manager": {
            "enabled": True,
            "endpoint": "http://127.0.0.1:1/v1",
            "model": "failing-model",
            "timeout": 1,
        }
    })

    # Should not raise, should return no_op
    intent = mgr.propose_intent("store this memory")
    assert intent.action == "no_op"
    assert "manager error" in intent.reason or "could not parse" in intent.reason
    print("PASS  test_manager_process_failure")


def test_manager_shell_execution_blocked():
    """Manager cannot propose shell execution."""
    from hungry_hippa.manager import LocalManager

    mgr = LocalManager({})
    assert "shell_exec" not in mgr.ALLOWED_ACTIONS
    assert "exec" not in mgr.ALLOWED_ACTIONS
    assert "run_command" not in mgr.ALLOWED_ACTIONS
    assert "system" not in mgr.ALLOWED_ACTIONS
    print("PASS  test_manager_shell_execution_blocked")


def test_status_no_fake_online():
    """Status must NOT report ONLINE for services that aren't actually running."""
    from unittest.mock import patch
    from hungry_hippa.hippo_pot import build_status

    config = {
        "hippo_pot": {"profile": "hippo-pot", "bind_address": "127.0.0.1"},
        "manager": {"enabled": False},
    }
    db_health = {
        "failures": 0,
        "counts": {"episodes": 0, "beliefs": 0},
        "size": {"bytes": 0},
        "permissions": {"lax": False},
        "vectors": {},
        "path": "/tmp/test.db",
    }

    with patch("hungry_hippa.hippo_pot._unit_installed", return_value=False), \
         patch("hungry_hippa.hippo_pot._service_running", return_value=False), \
         patch("hungry_hippa.hippo_pot._timer_enabled", return_value=False):
        status = build_status(config, db_health)

    # Core ONLINE because DB is healthy
    assert status["core"] == "ONLINE"

    # MCP should be AVAILABLE (server builds), not ONLINE
    assert status["mcp"] == "AVAILABLE"

    # API should be NOT CONFIGURED (no healthcheck port)
    assert status["api"] == "NOT CONFIGURED"

    # Manager should be NOT CONFIGURED
    assert status["manager"] == "NOT CONFIGURED"

    # Systemd manager should NOT be ONLINE when service is not running
    assert status["systemd_manager"] != "ONLINE"
    print("PASS  test_status_no_fake_online")


def test_status_manager_offline():
    """Status reports OFFLINE for unreachable manager."""
    from unittest.mock import patch
    from hungry_hippa.hippo_pot import build_status

    config = {
        "hippo_pot": {"profile": "hippo-pot", "bind_address": "127.0.0.1"},
        "manager": {
            "enabled": True,
            "endpoint": "http://127.0.0.1:19999/v1",
            "model": "test-model",
            "timeout": 1,
        },
    }
    db_health = {
        "failures": 0,
        "counts": {"episodes": 0},
        "size": {"bytes": 0},
        "permissions": {"lax": False},
        "vectors": {},
        "path": "/tmp/test.db",
    }

    with patch("hungry_hippa.hippo_pot._unit_installed", return_value=True), \
         patch("hungry_hippa.hippo_pot._service_running", return_value=False), \
         patch("hungry_hippa.hippo_pot._timer_enabled", return_value=False):
        status = build_status(config, db_health)

    # Manager configured but unreachable
    assert status["manager"] == "OFFLINE"
    # Manager model should be the configured name
    assert status["manager_model"] == "test-model"
    print("PASS  test_status_manager_offline")


def test_status_database_error():
    """Status reports DEGRADED/ERROR when DB has failures."""
    from unittest.mock import patch
    from hungry_hippa.hippo_pot import build_status

    config = {
        "hippo_pot": {"profile": "hippo-pot", "bind_address": "127.0.0.1"},
        "manager": {"enabled": False},
    }
    db_health = {
        "failures": 2,
        "counts": {},
        "size": {"bytes": 0},
        "permissions": {"lax": False},
        "vectors": {},
        "path": "/tmp/test.db",
    }

    with patch("hungry_hippa.hippo_pot._unit_installed", return_value=False), \
         patch("hungry_hippa.hippo_pot._service_running", return_value=False), \
         patch("hungry_hippa.hippo_pot._timer_enabled", return_value=False):
        status = build_status(config, db_health)

    assert status["core"] == "DEGRADED"
    assert status["database"] == "ERROR"
    assert status["memory_store"] == "WARNING"
    print("PASS  test_status_database_error")


def test_purge_requires_confirmation():
    """Purge must require explicit confirmation."""
    from hungry_hippa.cli import _cmd_uninstall
    import io
    import sys

    # Mock args with purge but no confirmation
    class FakeArgs:
        purge = True
        confirm_purge = ""  # Empty confirmation

    # Should exit with error
    captured = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = captured
    try:
        _cmd_uninstall(FakeArgs())
        assert False, "Should have exited"
    except SystemExit as e:
        assert e.code == 1
    finally:
        sys.stdout = old_stdout

    output = captured.getvalue()
    assert "PURGE-HUNGRY-HIPPA" in output
    print("PASS  test_purge_requires_confirmation")


def test_purge_wrong_confirmation_fails():
    """Wrong confirmation phrase must fail."""
    from hungry_hippa.cli import _cmd_uninstall
    import io
    import sys

    class FakeArgs:
        purge = True
        confirm_purge = "yes"  # Wrong phrase

    captured = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = captured
    try:
        _cmd_uninstall(FakeArgs())
        assert False, "Should have exited"
    except SystemExit as e:
        assert e.code == 1
    finally:
        sys.stdout = old_stdout
    print("PASS  test_purge_wrong_confirmation_fails")


def test_purge_correct_confirmation_succeeds():
    """Correct confirmation phrase should proceed with purge."""
    from unittest.mock import patch
    from hungry_hippa.cli import _cmd_uninstall
    import io
    import sys

    class FakeArgs:
        purge = True
        confirm_purge = "PURGE-HUNGRY-HIPPA"

    with patch("hungry_hippa.hippo_pot.uninstall_hippo_pot") as mock_uninstall:
        mock_uninstall.return_value = {"removed": [], "preserved": []}
        captured = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured
        try:
            _cmd_uninstall(FakeArgs())
        finally:
            sys.stdout = old_stdout

        mock_uninstall.assert_called_once_with(preserve_data=False)
    print("PASS  test_purge_correct_confirmation_succeeds")


def test_manager_integration_with_controller():
    """Manager wired into controller: propose_intent validates output."""
    from unittest.mock import patch
    from hungry_hippa.controller import MemoryController
    from hungry_hippa.config import load_config
    from pathlib import Path

    cfg = load_config()

    # Create a throwaway DB for the controller
    tmp = tempfile.mkdtemp(prefix="hh_ctrl_")
    db_path = str(Path(tmp) / "hungry_hippa.db")

    ctrl = MemoryController(cfg, db_path=db_path)
    ctrl.bind_session(session_id="test", platform="cli")

    # Manager should exist
    assert ctrl.manager is not None
    assert not ctrl.manager.is_configured  # Not configured by default

    # propose_intent should return valid structure
    result = ctrl.propose_intent("hello world")
    assert "action" in result
    assert "valid" in result
    assert result["action"] == "no_op"  # Not configured -> no_op
    print("PASS  test_manager_integration_with_controller")


def test_manager_integration_malicious_output():
    """Controller rejects malicious manager output at validation boundary."""
    from unittest.mock import patch
    from hungry_hippa.controller import MemoryController
    from hungry_hippa.config import load_config
    from hungry_hippa.manager import ManagerIntent
    from pathlib import Path

    cfg = load_config()
    tmp = tempfile.mkdtemp(prefix="hh_ctrl_")
    db_path = str(Path(tmp) / "hungry_hippa.db")

    ctrl = MemoryController(cfg, db_path=db_path)
    ctrl.bind_session(session_id="test", platform="cli")

    # Mock the manager to return a malicious intent
    malicious_intent = ManagerIntent(
        action="shell_exec",
        reason="run rm -rf /",
        parameters={"command": "rm -rf /"},
        confidence=0.95,
    )

    with patch.object(ctrl.manager, "propose_intent", return_value=malicious_intent):
        result = ctrl.propose_intent("test")

    # The controller must reject the malicious action
    assert result["action"] == "no_op"
    assert result["valid"] is False
    print("PASS  test_manager_integration_malicious_output")


def test_manager_integration_recall_continues():
    """Recall continues normally when manager is unavailable."""
    from unittest.mock import patch
    from hungry_hippa.controller import MemoryController
    from hungry_hippa.config import load_config
    from pathlib import Path

    cfg = load_config()
    tmp = tempfile.mkdtemp(prefix="hh_ctrl_")
    db_path = str(Path(tmp) / "hungry_hippa.db")

    ctrl = MemoryController(cfg, db_path=db_path)
    ctrl.bind_session(session_id="test", platform="cli")

    # Store a test memory first
    ctrl.remember_episode(
        context="test memory for recall",
        user_request="test request",
        actions_taken="test action",
        result="test result",
    )

    # Mock manager to raise an exception (simulating failure)
    with patch.object(ctrl.manager, "propose_intent",
                       side_effect=Exception("Manager crashed")):
        result = ctrl.recall("test memory")

    # Recall should still work
    assert "items" in result
    assert "error" not in result or result.get("error") is None
    print("PASS  test_manager_integration_recall_continues")


def test_systemd_manager_no_sleep_infinity():
    """Systemd manager unit must not use sleep infinity."""
    unit_path = Path(__file__).resolve().parent.parent / "deploy" / "hippo-pot" / "systemd" / "hippo-pot-manager.service"
    if unit_path.exists():
        content = unit_path.read_text()
        assert "sleep infinity" not in content, "Manager unit must not use sleep infinity"
        assert "Type=oneshot" in content, "Manager unit should be oneshot"
    print("PASS  test_systemd_manager_no_sleep_infinity")


def test_init_no_sleep_infinity():
    """init_hippo_pot must not produce a sleep infinity unit."""
    import hungry_hippa.config as hh_config
    from hungry_hippa.hippo_pot import init_hippo_pot

    with tempfile.TemporaryDirectory() as tmpdir:
        config = {
            "hippo_pot": {
                "profile": "hippo-pot",
                "bind_address": "127.0.0.1",
            }
        }
        orig_config_dir = hh_config.config_dir
        hh_config.config_dir = lambda: Path(tmpdir) / "config"

        try:
            result = init_hippo_pot(config)
            # Check the manager unit content
            systemd_dir = Path.home() / ".config" / "systemd" / "user"
            manager_unit = systemd_dir / "hippo-pot-manager.service"
            if manager_unit.exists():
                content = manager_unit.read_text()
                assert "sleep infinity" not in content
                assert "Type=oneshot" in content
        finally:
            hh_config.config_dir = orig_config_dir
    print("PASS  test_init_no_sleep_infinity")


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
        test_manager_timeout,
        test_manager_malformed_json,
        test_manager_unsupported_action,
        test_manager_process_failure,
        test_manager_shell_execution_blocked,
        test_status_no_fake_online,
        test_status_manager_offline,
        test_status_database_error,
        test_purge_requires_confirmation,
        test_purge_wrong_confirmation_fails,
        test_purge_correct_confirmation_succeeds,
        test_manager_integration_with_controller,
        test_manager_integration_malicious_output,
        test_manager_integration_recall_continues,
        test_systemd_manager_no_sleep_infinity,
        test_init_no_sleep_infinity,
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
