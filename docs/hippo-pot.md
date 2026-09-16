# Hippo-Pot Deployment

A Hippo-Pot is a dedicated deployment of Hungry Hippa running as an always-available appliance on a Linux machine.

## Purpose

This document covers the Hippo-Pot deployment profile: how to install, configure, operate, and uninstall Hungry Hippa as a persistent appliance service on a Linux machine.

**Key principle: Hermes is not required to operate a Hippo-Pot.**

Hungry Hippa runs independently. Hermes is only used during the build phase.

## Architecture

```
       AI / MCP Clients / Other Machines
                    |
               MCP / HTTP
                    |
                    v
          +-------------------+
          |   Hungry Hippa    |
          |                   |
          | ingest            |
          | retrieval         |
          | memory            |
          | evidence          |
          | provenance        |
          | trust boundaries  |
          | MCP/API           |
          | security          |
          +---------+---------+
                    |
              Manager API
                    |
                    v
          +-------------------+
          | Small Local Model |
          | replaceable       |
          | lightweight       |
          +---------+---------+
                    |
             route/escalate
```

## Requirements

- Linux (tested on Pop!_OS 24.04 with COSMIC desktop)
- Python 3.10+
- SQLite (bundled with Python)
- systemd user session (for service management)
- ~100 MB disk space for Hungry Hippa + dependencies
- Additional space for memory database (varies by use)

### Memory Constraints

Target reference machine: Lenovo Yoga, 8 GB RAM.

- Hungry Hippa itself uses minimal memory (~50-100 MB)
- The local manager model (if running) should be small (1-3 GB)
- Avoid Docker, Kubernetes, Redis, Postgres, Elasticsearch
- Measure actual memory consumption

## Installation

### Quick Install

```bash
cd /path/to/hungry-hippa
./deploy/hippo-pot/install.sh
```

### Manual Install

```bash
# 1. Create virtualenv
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# 2. Initialize Hippo-Pot
hungry-hippa init --profile hippo-pot

# 3. Create owner token
hungry-hippa owner-token

# 4. Fix database permissions
hungry-hippa fix-permissions

# 5. Enable services
systemctl --user enable --now hippo-pot-manager.service
systemctl --user enable --now hippo-pot-consolidation.timer

# 6. Verify
hungry-hippa doctor
```

## Commands

### `hungry-hippa init --profile hippo-pot`

Initializes the Hippo-Pot deployment profile:
- Creates `~/.config/hungry-hippa/config.json` with Hippo-Pot defaults
- Installs systemd user units for manager and consolidation timer
- Merges with existing configuration if present

### `hungry-hippa start`

Starts Hippo-Pot services (manager service + consolidation timer).

### `hungry-hippa stop`

Stops Hippo-Pot services.

### `hungry-hippa restart`

Restarts Hippo-Pot services.

### `hungry-hippa status`

Shows Hungry Hippa health and table counts. When running as a Hippo-Pot, includes:
- Core status (ONLINE/DEGRADED)
- MCP server status
- Manager status (ONLINE/OFFLINE/NOT CONFIGURED)
- Memory store health
- Service state

### `hungry-hippa doctor`

Runs deep diagnostics:
- Service state (systemd units)
- Configuration validity
- Storage permissions and paths
- Database connectivity and schema
- Ports and bind addresses
- API responsiveness
- MCP server buildability
- Manager endpoint health
- Disk space and RAM
- Security issues

### `hungry-hippa uninstall`

Removes Hippo-Pot systemd units. By default, preserves all data.

```bash
hungry-hippa uninstall          # Safe: keeps data
hungry-hippa uninstall --purge  # Destructive: removes everything
```

## Services

### `hippo-pot-manager.service`

The local manager process. Currently a placeholder — when the manager endpoint is configured, this service will manage the local LLM process.

Configuration in `~/.config/hungry-hippa/config.json`:

```json
{
  "manager": {
    "provider": "openai-compatible",
    "endpoint": "http://127.0.0.1:8080/v1",
    "model": "local-manager",
    "temperature": 0.1,
    "context_window": 8192,
    "enabled": true
  }
}
```

Supported providers:
- `openai-compatible` — any OpenAI-compatible endpoint (llama.cpp, Ollama, LM Studio, vLLM)

### `hippo-pot-consolidation.timer`

Triggers the daily consolidation ("sleep pass") on schedule. Default: 04:00 local time.

### `hippo-pot-consolidation.service`

One-shot service that runs consolidation when triggered by the timer.

## Configuration

### Files

| File | Purpose |
|---|---|
| `~/.config/hungry-hippa/config.json` | Main configuration |
| `~/.local/share/hungry-hippa/hungry_hippa.db` | SQLite memory database |
| `~/.local/state/hungry-hippa/owner.token` | Owner authorization token |

### Manager Configuration

```json
{
  "manager": {
    "provider": "openai-compatible",
    "endpoint": "http://127.0.0.1:8080/v1",
    "model": "local-manager",
    "temperature": 0.1,
    "context_window": 8192,
    "enabled": true,
    "timeout": 10
  }
}
```

### Hippo-Pot Profile

```json
{
  "hippo_pot": {
    "profile": "hippo-pot",
    "bind_address": "127.0.0.1",
    "auto_consolidate": true,
    "consolidation_schedule": "0 4 * * *"
  }
}
```

### Environment Variables

| Variable | Purpose |
|---|---|
| `HUNGRY_HIPPA_DB` | Override database path |
| `HUNGRY_HIPPA_OWNER_TOKEN` | Owner token (set in MCP server's launch environment) |
| `HUNGRY_HIPPA_MAX_MCP_CALLS` | Per-process MCP call budget |

## Networking

**Default: local-only.** Services bind to `127.0.0.1`.

To enable LAN operation, configure `hippo_pot.bind_address` in `config.json`. LAN operation must be explicit — the system never exposes itself to the public internet by default.

Security rules:
- No public internet exposure
- No router/UPnP changes
- No firewall modifications
- Authentication follows existing Hungry Hippa trust-boundary conventions

## Manager Authority Limits

The small manager model proposes intent but does NOT directly control:

- Raw database writes
- Schema modification
- Evidence/provenance integrity
- Access control, trust boundaries
- Destructive deletion
- Authentication/permissions

Hungry Hippa validates and executes all actions. A hallucinating small model cannot bypass the system's security model.

### Failure Isolation

A manager-model failure MUST NOT take down Hungry Hippa. The system handles:
- Manager unavailable
- Manager timeout
- Malformed manager response
- Manager process crash

Hungry Hippa remains alive and reports degraded manager status.

## Security

- Database is plaintext SQLite (0600 permissions, not encryption)
- Use OS/disk encryption for sensitive data
- No application-level encryption (by design — the store is local-first)
- Owner token: 32 random bytes in 0600 file
- Sensitivity labels are read-policy, not encryption

## Resource Requirements

Approximate idle RAM usage:
- Hungry Hippa MCP server (per-client): ~50-100 MB
- Systemd services: negligible
- Local manager model (optional): 1-3 GB (varies by model)

Disk space:
- Hungry Hippa + dependencies: ~100 MB
- Memory database: varies (warning at 512 MB)

## Troubleshooting

### Services don't start at boot

```bash
# Enable linger for user services
sudo loginctl enable-linger $(whoami)
```

### Manager shows OFFLINE

The manager is optional. If configured but unreachable:
1. Check endpoint URL in config.json
2. Verify the local LLM is running
3. Check `hungry-hippa doctor` output

### Consolidation not running

```bash
# Check timer status
systemctl --user status hippo-pot-consolidation.timer

# Run manually
hungry-hippa consolidate
```

### Database permissions warning

```bash
hungry-hippa fix-permissions
```

## Uninstallation

### Safe uninstall (preserves data)

```bash
hungry-hippa uninstall
```

or

```bash
./deploy/hippo-pot/uninstall.sh
```

This removes systemd units but keeps:
- Memory database (`~/.local/share/hungry-hippa/`)
- Configuration (`~/.config/hungry-hippa/`)
- Owner token (`~/.local/state/hungry-hippa/`)

### Full purge (destroys data)

```bash
hungry-hippa uninstall --purge
```

or

```bash
./deploy/hippo-pot/uninstall.sh --purge
```

This removes everything including all memories. Irreversible.

## Upgrade Path

1. Stop services: `hungry-hippa stop`
2. Pull latest code: `git pull`
3. Reinstall package: `pip install -e .`
4. Re-run init: `hungry-hippa init --profile hippo-pot`
5. Restart services: `hungry-hippa start`
6. Verify: `hungry-hippa doctor`

## Acceptance Test

After installation and reboot:

```bash
hungry-hippa status
```

Should show healthy core system.

```bash
hungry-hippa doctor
```

All core checks should pass.

Store a test memory:

```bash
# Via MCP or directly through recall after storing
```

The manager may show `NOT CONFIGURED`. This is acceptable at this stage.
