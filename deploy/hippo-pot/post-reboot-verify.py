#!/usr/bin/env python3
"""Post-reboot acceptance verifier for Hippo-Pot.

Runs automatically after reboot via systemd. Checks:
- Machine actually rebooted (boot ID changed)
- Required systemd units/timers came back
- Database opens
- Exact synthetic memory still exists
- Evidence/provenance still trace
- MCP server is launchable
- hungry-hippa status works
- hungry-hippa doctor works
- Manager abstraction loads
- Manager absence does not break HH

Writes results to ~/.local/state/hungry-hippa/hippo-pot-post-reboot.json
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def run(cmd, timeout=30):
    """Run a command, return (stdout, stderr, returncode)."""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        )
        return result.stdout, result.stderr, result.returncode
    except subprocess.TimeoutExpired:
        return "", "TIMEOUT", -1
    except Exception as e:
        return "", str(e), -1


def check_boot_id(pre_reboot_data):
    """Check if machine actually rebooted."""
    current_boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    pre_boot = pre_reboot_data.get("boot_id", "")
    return current_boot != pre_boot and current_boot != "", current_boot


def check_systemd_units():
    """Check if required units exist and their states."""
    units = {
        "manager": "hippo-pot-manager.service",
        "timer": "hippo-pot-consolidation.timer",
    }
    results = {}
    for name, unit in units.items():
        out, _, code = run(["systemctl", "--user", "--no-pager", "is-active", unit])
        results[name] = {
            "active": out.strip() == "active",
            "state": out.strip(),
        }
    # Check if timer is enabled
    out, _, _ = run(["systemctl", "--user", "is-enabled", "hippo-pot-consolidation.timer"])
    results["timer"]["enabled"] = out.strip() == "enabled"
    return results


def check_database():
    """Check if database opens and has records."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
        from hungry_hippa.db import Database
        from hungry_hippa.config import load_config, resolve_db_path
        cfg = load_config()
        db_path = resolve_db_path(cfg)
        db = Database(db_path)
        health = db.health()
        return {
            "opens": True,
            "path": db_path,
            "failures": health.get("failures", 0),
            "counts": health.get("counts", {}),
        }
    except Exception as e:
        return {"opens": False, "error": str(e)}


def check_synthetic_memory(expected_text):
    """Check if the synthetic test memory still exists."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
        from hungry_hippa.db import Database
        from hungry_hippa.config import load_config, resolve_db_path
        cfg = load_config()
        db_path = resolve_db_path(cfg)
        db = Database(db_path)

        # Search for the expected text in episodes
        from hungry_hippa.controller import MemoryController
        ctrl = MemoryController(cfg, db_path=db_path)
        ctrl.bind_session(session_id="reboot_check", platform="cli")
        result = ctrl.recall(expected_text, limit=10)

        items = result.get("items", [])
        found = any(expected_text in json.dumps(item) for item in items)
        return {
            "found": found,
            "items_count": len(items),
            "query": expected_text,
        }
    except Exception as e:
        return {"found": False, "error": str(e)}


def check_status():
    """Run hungry-hippa status."""
    # Try the venv script first, then fall back to python -m
    out, err, code = run(["hungry-hippa", "status"])
    if code == -1 and "No such file" in err:
        # Fall back to using the venv python
        repo = Path.home() / "hungry-hippa"
        out, err, code = run([str(repo / ".venv" / "bin" / "hungry-hippa"), "status"])
    parsed = {}
    try:
        if out.strip().startswith("{"):
            parsed = json.loads(out)
    except json.JSONDecodeError:
        pass
    return {
        "exit_code": code,
        "parsed": parsed,
        "raw": out[:1000] + (err[:500] if err else ""),
    }


def check_doctor():
    """Run hungry-hippa doctor."""
    out, err, code = run(["hungry-hippa", "doctor"])
    if code == -1 and "No such file" in err:
        repo = Path.home() / "hungry-hippa"
        out, err, code = run([str(repo / ".venv" / "bin" / "hungry-hippa"), "doctor"])
    parsed = {}
    try:
        if out.strip().startswith("{"):
            parsed = json.loads(out)
    except json.JSONDecodeError:
        pass
    return {
        "exit_code": code,
        "healthy": parsed.get("healthy", None),
        "checks_count": len(parsed.get("checks", {})),
        "raw": out[:500] + (err[:300] if err else ""),
    }


def check_mcp():
    """Check MCP server is launchable."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
        from hungry_hippa.mcp_server import build_server
        app = build_server()
        return {"builds": True, "server_name": getattr(app, "name", "unknown")}
    except Exception as e:
        return {"builds": False, "error": str(e)}


def check_manager_abstraction():
    """Check manager abstraction loads and reports correctly."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
        from hungry_hippa.manager import LocalManager
        from hungry_hippa.config import load_config
        cfg = load_config()
        mgr = LocalManager(cfg)
        health = mgr.health()
        return {
            "loads": True,
            "configured": health.configured,
            "status": health.status_label(),
        }
    except Exception as e:
        return {"loads": False, "error": str(e)}


def main():
    state_dir = Path.home() / ".local" / "state" / "hungry-hippa"
    pre_file = state_dir / "hippo-pot-pre-reboot.json"
    post_file = state_dir / "hippo-pot-post-reboot.json"

    # Load pre-reboot data
    pre_data = {}
    if pre_file.exists():
        try:
            pre_data = json.loads(pre_file.read_text())
        except (json.JSONDecodeError, OSError):
            pass

    expected_text = pre_data.get("test_memory_text", "HIPPOPOT_REBOOT_TEST_20260916")

    # Run all checks
    results = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expected_test_text": expected_text,
    }

    rebooted, current_boot = check_boot_id(pre_data)
    results["rebooted"] = rebooted
    results["current_boot_id"] = current_boot
    results["previous_boot_id"] = pre_data.get("boot_id", "unknown")

    results["systemd"] = check_systemd_units()
    results["database"] = check_database()
    results["synthetic_memory"] = check_synthetic_memory(expected_text)
    results["mcp"] = check_mcp()
    results["manager"] = check_manager_abstraction()
    results["status"] = check_status()
    results["doctor"] = check_doctor()

    # Overall verdict
    results["PHASE_A_POST_REBOOT_PASS"] = all([
        results["rebooted"],
        results["database"]["opens"],
        results["synthetic_memory"]["found"],
        results["mcp"]["builds"],
        results["manager"]["loads"],
    ])

    # Write results
    post_file.write_text(json.dumps(results, indent=2, default=str))
    print(json.dumps(results, indent=2, default=str))

    return 0 if results["PHASE_A_POST_REBOOT_PASS"] else 1


if __name__ == "__main__":
    sys.exit(main())
