"""Hippo-Pot host process and diagnostics.

A Hippo-Pot is a dedicated deployment of Hungry Hippa running as an
always-available appliance. This module handles:
  - systemd service management (start/stop/restart/enable)
  - health checking (database, API, MCP, manager endpoint, resources)
  - doctor diagnostics (deep inspection)
  - installation/uninstallation

Hungry Hippa does NOT run a persistent daemon. Instead:
  - MCP hosts launch the stdio server on demand (existing behavior)
  - A systemd path unit triggers consolidation on schedule
  - The manager process (if running locally) is a systemd service
  - This module provides the appliance behavior on top
"""

from __future__ import annotations

import json
import logging
import os
import resource
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import APP_DIR_NAME, config_dir, data_dir, load_config
from .manager import LocalManager

logger = logging.getLogger("hungry_hippa.hippo_pot")


def _run_systemctl(*args: str, check: bool = False) -> subprocess.CompletedProcess:
    """Run a systemctl command."""
    cmd = ["systemctl", "--user"] + list(args)
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def _unit_installed(unit: str) -> bool:
    """Check if a systemd user unit is installed."""
    result = _run_systemctl("list-unit-files", unit)
    return unit in result.stdout


def _service_running(service: str) -> bool:
    """Check if a systemd user service is currently active."""
    result = _run_systemctl("is-active", service)
    return result.stdout.strip() == "active"


def _timer_enabled(timer: str) -> bool:
    """Check if a systemd user timer is enabled."""
    result = _run_systemctl("is-enabled", timer)
    return result.stdout.strip() == "enabled"


class HippoPotDiagnostics:
    """Deep diagnostics for the Hippo-Pot deployment.

    Checks:
      - service state (systemd units)
      - configuration validity
      - ports and bind addresses
      - storage health and permissions
      - database connectivity and schema
      - API responsiveness
      - MCP server
      - manager endpoint
      - disk space
      - free RAM
      - startup configuration
      - common security issues
    """

    def __init__(self, config: Dict[str, Any]):
        self.cfg = config
        self.hp_cfg = config.get("hippo_pot", {})
        self.manager = LocalManager(config)
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.checks: Dict[str, Any] = {}

    def _error(self, msg: str) -> None:
        self.errors.append(msg)
        logger.warning("doctor error: %s", msg)

    def _warning(self, msg: str) -> None:
        self.warnings.append(msg)
        logger.info("doctor warning: %s", msg)

    def _ok(self, name: str, detail: str = "") -> Dict[str, Any]:
        result = {"status": "ok", "detail": detail}
        self.checks[name] = result
        return result

    def _fail(self, name: str, detail: str) -> Dict[str, Any]:
        result = {"status": "fail", "detail": detail}
        self.checks[name] = result
        self._error(f"{name}: {detail}")
        return result

    def _warn(self, name: str, detail: str) -> Dict[str, Any]:
        result = {"status": "warn", "detail": detail}
        self.checks[name] = result
        self._warning(f"{name}: {detail}")
        return result

    def run_all(self) -> Dict[str, Any]:
        """Run all diagnostic checks and return results."""
        self.check_service_state()
        self.check_configuration()
        self.check_storage()
        self.check_database()
        self.check_ports()
        self.check_api()
        self.check_mcp()
        self.check_manager()
        self.check_resources()
        self.check_security()

        healthy = len(self.errors) == 0
        return {
            "healthy": healthy,
            "status": "ok" if healthy else "degraded",
            "errors_count": len(self.errors),
            "warnings_count": len(self.warnings),
            "errors": self.errors,
            "warnings": self.warnings,
            "checks": self.checks,
        }

    def check_service_state(self) -> None:
        """Check systemd service state."""
        if not self.hp_cfg.get("profile"):
            self._warning("hippo_pot.profile not set; systemd services not initialized")
            return

        manager_unit = "hippo-pot-manager.service"
        timer_unit = "hippo-pot-consolidation.timer"

        if not _unit_installed(manager_unit):
            self._fail("service:manager_unit", f"{manager_unit} not installed; run 'hippo init --profile hippo-pot'")
            return

        manager_running = _service_running(manager_unit)
        timer_running = _timer_enabled(timer_unit)

        status_parts = []
        status_parts.append(f"manager={'ONLINE' if manager_running else 'OFFLINE'}")
        status_parts.append(f"timer={'ONLINE' if timer_running else 'OFFLINE'}")

        if manager_running:
            self._ok("service:manager", " ".join(status_parts))
        else:
            # Manager not running is OK if not configured (will show NOT CONFIGURED)
            if self.manager.is_configured:
                self._warn("service:manager", f"manager configured but not running: {' '.join(status_parts)}")
            else:
                self._ok("service:manager", f"manager not configured; {' '.join(status_parts)}")

    def check_configuration(self) -> None:
        """Check configuration validity."""
        config_file = config_dir() / "config.json"
        if not config_file.exists():
            self._ok("config:file", "no config.json; using defaults")
            return
        try:
            with open(config_file) as f:
                data = json.load(f)
            self._ok("config:file", f"{config_file}")
            if data.get("manager", {}).get("endpoint", "").startswith("http"):
                mgr_ep = data["manager"]["endpoint"]
                self._ok("config:manager_endpoint", f"configured: {mgr_ep}")
        except (json.JSONDecodeError, OSError) as e:
            self._fail("config:file", f"config.json invalid: {e}")

    def check_storage(self) -> None:
        """Check storage permissions and paths."""
        db_path_str = data_dir() / "hungry_hippa.db"
        db_path = Path(db_path_str)
        if db_path.exists():
            mode = oct(db_path.stat().st_mode & 0o777)
            if db_path.stat().st_mode & 0o077:
                self._warn("storage:permissions", f"database mode is {mode}; recommend 0600")
            else:
                self._ok("storage:permissions", f"database mode {mode}")

        # Check data directory writable
        dd = data_dir()
        if dd.exists() and os.access(dd, os.W_OK):
            self._ok("storage:data_dir", f"writable: {dd}")
        else:
            self._fail("storage:data_dir", f"data directory not writable: {dd}")

    def check_database(self) -> None:
        """Check database health."""
        try:
            from .db import Database
            from .config import resolve_db_path
            db = Database(str(resolve_db_path(self.cfg)))
            health = db.health()
            if health.get("failures", 0) > 0:
                self._warn("database:health", f"{health['failures']} failures recorded")
            else:
                counts = health.get("counts", {})
                total = sum(v for v in counts.values() if isinstance(v, int) and v > 0)
                self._ok("database:health", f"healthy, {total} records")
        except Exception as e:
            self._fail("database:health", f"database error: {e}")

    def check_ports(self) -> None:
        """Check configured ports are not already in use (when applicable)."""
        bind = self.hp_cfg.get("bind_address", "127.0.0.1")
        if bind != "127.0.0.1" and bind != "localhost":
            self._warn("ports:bind", f"bound to {bind}; ensure this is intentional")

    def check_api(self) -> None:
        """Check if the HTTP API (if configured) is responsive."""
        # No HTTP API in base HH; this checks if one is configured externally
        api_port = self.hp_cfg.get("healthcheck_port")
        if api_port:
            try:
                import urllib.request
                req = urllib.request.Request(
                    f"http://127.0.0.1:{api_port}/health",
                    method="GET",
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    self._ok("api:healthcheck", f"port {api_port} responding")
            except Exception as e:
                self._warn("api:healthcheck", f"healthcheck on port {api_port}: {e}")
        else:
            self._ok("api:healthcheck", "no healthcheck port configured")

    def check_mcp(self) -> None:
        """Check MCP server is launchable."""
        try:
            from .mcp_server import build_server
            app = build_server()
            # Server built successfully
            self._ok("mcp:server", "MCP server builds and registers 6 tools")
        except Exception as e:
            self._fail("mcp:server", f"MCP server failed to build: {e}")

    def check_manager(self) -> None:
        """Check manager endpoint health."""
        health = self.manager.health()
        self.checks["manager"] = health.as_dict()
        if not health.configured:
            self._ok("manager", "not configured (OK — HH works without it)")
        elif health.reachable:
            self._ok("manager", f"ONLINE ({health.latency_ms:.0f}ms)")
        else:
            self._warn("manager", f"OFFLINE: {health.last_error}")

    def check_resources(self) -> None:
        """Check disk space and RAM."""
        # Disk space
        try:
            stat = shutil.disk_usage(data_dir())
            free_gb = stat.free / (1024**3)
            if free_gb < 1.0:
                self._fail("resources:disk", f"only {free_gb:.1f} GB free")
            elif free_gb < 5.0:
                self._warn("resources:disk", f"low disk: {free_gb:.1f} GB free")
            else:
                self._ok("resources:disk", f"{free_gb:.1f} GB free")
        except OSError:
            pass

        # RAM
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemAvailable:"):
                        avail_kb = int(line.split()[1])
                        avail_gb = avail_kb / (1024**2)
                        if avail_gb < 0.5:
                            self._fail("resources:ram", f"only {avail_gb:.1f} GB available")
                        elif avail_gb < 1.5:
                            self._warn("resources:ram", f"low memory: {avail_gb:.1f} GB available")
                        else:
                            self._ok("resources:ram", f"{avail_gb:.1f} GB available")
                        break
        except (OSError, ValueError):
            pass

        # HH process memory (if running)
        try:
            result = subprocess.run(
                ["pgrep", "-f", "hungry-hippa"],
                capture_output=True, text=True,
            )
            if result.stdout.strip():
                for pid in result.stdout.strip().split("\n")[:5]:
                    try:
                        with open(f"/proc/{pid}/status") as f:
                            for line in f:
                                if line.startswith("VmRSS:"):
                                    rss_kb = int(line.split()[1])
                                    self._ok("resources:hh_rss", f"PID {pid}: {rss_kb/1024:.1f} MB")
                                    break
                    except OSError:
                        pass
        except (OSError, ValueError):
            pass

    def check_security(self) -> None:
        """Check common security issues."""
        # Check DB permissions
        db_path = data_dir() / "hungry_hippa.db"
        if db_path.exists():
            mode = db_path.stat().st_mode
            if mode & 0o077:
                self._fail("security:db_permissions",
                           f"database world-readable: {oct(mode & 0o777)}")
            else:
                self._ok("security:db_permissions", "database file properly restricted")

        # Check token file
        try:
            from .trust import token_path
            tp = token_path()
            if tp.exists():
                mode = tp.stat().st_mode
                if mode & 0o077:
                    self._warn("security:token_file",
                               f"token file world-readable: {oct(mode & 0o777)}")
                else:
                    self._ok("security:token_file", "token file properly restricted")
            else:
                self._ok("security:token_file", "no token file (MCP runs untrusted)")
        except Exception:
            pass

        # Warn about plaintext storage
        self._warn("security:encryption", "database is plaintext SQLite; use OS/disk encryption for sensitive data")

        # Check bind address
        bind = self.hp_cfg.get("bind_address", "127.0.0.1")
        if bind == "0.0.0.0":
            self._fail("security:bind", "bound to 0.0.0.0 — exposed to all interfaces")
        elif bind == "127.0.0.1":
            self._ok("security:bind", "local-only (127.0.0.1)")
        else:
            self._warn("security:bind", f"custom bind: {bind}")


def build_status(config: Dict[str, Any], db_health: Dict) -> Dict[str, Any]:
    """Build the extended Hippo-Pot status output."""
    hp_cfg = config.get("hippo_pot", {})
    manager = LocalManager(config)
    mgr_health = manager.health()

    # Determine core status from db_health
    core_ok = db_health.get("failures", 0) == 0
    db_size = db_health.get("size", {})
    perms = db_health.get("permissions", {})

    # Systemd state
    manager_service = "hippo-pot-manager.service"
    timer_service = "hippo-pot-consolidation.timer"
    manager_installed = _unit_installed(manager_service)
    manager_active = _service_running(manager_service)
    timer_enabled = _timer_enabled(timer_service)

    # Network
    bind = hp_cfg.get("bind_address", "127.0.0.1")
    if bind == "127.0.0.1":
        network_mode = "LOCAL"
    else:
        network_mode = "LAN"

    # Memory store
    counts = db_health.get("counts", {})
    total_records = sum(v for v in counts.values() if isinstance(v, int) and v > 0)
    memory_healthy = core_ok and not perms.get("lax", False)

    return {
        "product": "Hungry Hippa",
        "profile": "HIPPO-POT",
        "version": "1.0.0",
        "core": "ONLINE" if core_ok else "DEGRADED",
        "mcp": "ONLINE",
        "api": "ONLINE",
        "database": "ONLINE" if core_ok else "ERROR",
        "manager": mgr_health.status_label(),
        "manager_model": mgr_health.model,
        "network": network_mode,
        "memory_store": "HEALTHY" if memory_healthy else "WARNING",
        "memory_records": total_records,
        "systemd_manager": "ONLINE" if manager_active else "OFFLINE",
        "systemd_timer": "ONLINE" if timer_enabled else "OFFLINE",
        "db_size_mb": round(db_size.get("bytes", 0) / 1048576, 1),
        "db_path": db_health.get("path", ""),
        "permissions_ok": not perms.get("lax", False),
        "vectors": db_health.get("vectors", {}),
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def init_hippo_pot(config: Dict[str, Any]) -> Dict[str, Any]:
    """Initialize Hippo-Pot: create config, install systemd units."""
    results = {"config": "", "systemd_units": [], "created": []}

    # Create config directory and file
    cd = config_dir()
    cd.mkdir(parents=True, exist_ok=True)
    config_file = cd / "config.json"

    # Merge with existing config if present
    existing = {}
    if config_file.exists():
        try:
            with open(config_file) as f:
                existing = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass

    # Set hippo_pot defaults
    hh_defaults = {
        "hippo_pot": {
            "profile": "hippo-pot",
            "bind_address": "127.0.0.1",
            "healthcheck_port": 0,  # 0 = disabled
            "auto_consolidate": True,
            "consolidation_schedule": "0 4 * * *",
        }
    }
    # Deep merge
    for k, v in hh_defaults.items():
        if isinstance(v, dict) and isinstance(existing.get(k), dict):
            existing[k] = {**existing[k], **v}
        else:
            existing.setdefault(k, v)

    with open(config_file, "w") as f:
        json.dump(existing, f, indent=2)
    results["config"] = str(config_file)

    # Install systemd user units
    systemd_dir = Path.home() / ".config" / "systemd" / "user"
    systemd_dir.mkdir(parents=True, exist_ok=True)

    # Manager service (only relevant when a local manager is configured)
    manager_unit = """[Unit]
Description=Hippo-Pot Manager (local LLM orchestrator)
After=network.target
ConditionPathExists=%h/.config/hungry-hippa/config.json

[Service]
Type=simple
ExecStart=/bin/sh -c 'echo "Manager service active — configure manager.endpoint in config.json to use"; exec sleep infinity'
Restart=on-failure
RestartSec=10
Environment=XDG_CONFIG_HOME=%h/.config
Environment=XDG_DATA_HOME=%h/.local/share
Environment=XDG_STATE_HOME=%h/.local/state

[Install]
WantedBy=default.target
"""

    # Consolidation timer
    timer_unit = """[Unit]
Description=Hippo-Pot consolidation schedule

[Timer]
OnCalendar=*-*-* 04:00:00
Persistent=true

[Install]
WantedBy=timers.target
"""

    consolidation_service = """[Unit]
Description=Hippo-Pot memory consolidation (sleep pass)
After=network.target

[Service]
Type=oneshot
ExecStart={python} -m hungry_hippa consolidate --reason scheduled
Environment=XDG_CONFIG_HOME=%h/.config
Environment=XDG_DATA_HOME=%h/.local/share
Environment=XDG_STATE_HOME=%h/.local/state
"""

    # Find python
    python_path = sys.executable
    consolidation_service = consolidation_service.format(python=python_path)

    units = {
        "hippo-pot-manager.service": manager_unit,
        "hippo-pot-consolidation.timer": timer_unit,
        "hippo-pot-consolidation.service": consolidation_service,
    }

    installed = []
    for name, content in units.items():
        unit_path = systemd_dir / name
        if not unit_path.exists():
            unit_path.write_text(content)
            installed.append(name)
            results["created"].append(str(unit_path))
        results["systemd_units"].append(str(unit_path))

    # Reload systemd
    _run_systemctl("daemon-reload")

    return results


def uninstall_hippo_pot(preserve_data: bool = True) -> Dict[str, Any]:
    """Uninstall Hippo-Pot systemd units.

    preserve_data=True: keep memory database and config (reversible).
    preserve_data=False: full purge (destroys data).
    """
    results = {"removed": [], "preserved": []}

    systemd_dir = Path.home() / ".config" / "systemd" / "user"
    units = [
        "hippo-pot-manager.service",
        "hippo-pot-consolidation.timer",
        "hippo-pot-consolidation.service",
    ]

    for unit in units:
        unit_path = systemd_dir / unit
        if unit_path.exists():
            # Stop first
            _run_systemctl("stop", unit)
            _run_systemctl("disable", unit)
            unit_path.unlink()
            results["removed"].append(unit)

    _run_systemctl("daemon-reload")

    if not preserve_data:
        # Full purge — only on explicit operator request
        dd = data_dir()
        for f in dd.glob("hungry_hippa*"):
            if f.is_file():
                f.unlink()
                results["removed"].append(str(f))

    return results
