#!/usr/bin/env bash
#
# Hippo-Pot installer for Hungry Hippa
#
# This script installs or updates a Hippo-Pot deployment on a clean Linux
# machine. It is mostly idempotent and safe to rerun.
#
# Usage:
#   ./deploy/hippo-pot/install.sh
#
# What it does:
#   1. Verifies prerequisites (Python 3.10+, pip, systemd user session)
#   2. Creates a virtualenv and installs hungry-hippa + dependencies
#   3. Initializes the Hungry Hippa database (if not already present)
#   4. Generates the owner token (for MCP server authorization)
#   5. Installs systemd user units (manager + consolidation timer)
#   6. Enables and starts services
#   7. Runs the Hippo-Pot self-check
#
# This script is explicit about sudo — it does NOT require root for most
# operations, only for installing system packages if they are missing.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log() { echo -e "${GREEN}[hippo-pot]${NC} $*"; }
warn() { echo -e "${YELLOW}[hippo-pot]${NC} $*"; }
error() { echo -e "${RED}[hippo-pot]${NC} $*" >&2; }

# --------------------------------------------------------------------- checks

check_prerequisites() {
    log "Checking prerequisites..."

    # Python 3.10+
    if command -v python3 &>/dev/null; then
        py_version=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
        py_major=$(echo "$py_version" | cut -d. -f1)
        py_minor=$(echo "$py_version" | cut -d. -f2)
        if [ "$py_major" -lt 3 ] || { [ "$py_major" -eq 3 ] && [ "$py_minor" -lt 10 ]; }; then
            error "Python 3.10+ required, found $py_version"
            exit 1
        fi
        log "  Python $py_version OK"
    else
        error "Python 3 not found"
        exit 1
    fi

    # pip or uv
    if command -v uv &>/dev/null; then
        INSTALLER="uv"
        log "  uv found (will use for package installation)"
    elif command -v pip3 &>/dev/null; then
        INSTALLER="pip"
        log "  pip3 found"
    else
        warn "Neither uv nor pip3 found. Attempting uv install..."
        if command -v curl &>/dev/null; then
            curl -LsSf https://astral.sh/uv/install.sh | sh
            export PATH="$HOME/.local/bin:$PATH"
            INSTALLER="uv"
        else
            error "Cannot install packages: uv or pip3 required"
            exit 1
        fi
    fi

    # systemd user session
    if command -v systemctl &>/dev/null; then
        if systemctl --user show-environment &>/dev/null 2>&1; then
            log "  systemd user session available"
        else
            warn "systemd user session not fully available — services may not auto-start on boot"
            warn "  (this is OK for WSL containers; on a full Linux install, loginctl enable-linger \$USER)"
        fi
    else
        warn "systemd not found — service management disabled"
    fi

    # SQLite
    if python3 -c "import sqlite3; print(sqlite3.sqlite_version)" &>/dev/null; then
        log "  SQLite $(python3 -c 'import sqlite3; print(sqlite3.sqlite_version)') OK"
    else
        error "SQLite Python module not available"
        exit 1
    fi
}

# ----------------------------------------------------------------- install

install_package() {
    log "Installing Hungry Hippa..."

    cd "${REPO_ROOT}"

    # Create virtualenv if needed
    if [ ! -d ".venv" ]; then
        if [ "$INSTALLER" = "uv" ]; then
            uv venv
        else
            python3 -m venv .venv
        fi
    fi

    source .venv/bin/activate

    if [ "$INSTALLER" = "uv" ]; then
        uv pip install -e .
    else
        pip install -e .
    fi

    log "Hungry Hippa installed at: ${REPO_ROOT}"
}

# ----------------------------------------------------------------- init

init_hippo_pot() {
    log "Initializing Hippo-Pot..."

    cd "${REPO_ROOT}"
    source .venv/bin/activate

    # Initialize the Hippo-Pot profile (creates config, installs systemd units)
    hungry-hippa init --profile hippo-pot

    # Create owner token (if not already present)
    if [ ! -f "${HOME}/.local/state/hungry-hippa/owner.token" ]; then
        hungry-hippa owner-token
        log "Owner token created"
    else
        log "Owner token already exists"
    fi

    # Fix database permissions (idempotent)
    hungry-hippa fix-permissions 2>/dev/null || true
}

# ------------------------------------------------------------- services

setup_services() {
    log "Setting up systemd services..."

    # Reload to pick up new units
    systemctl --user daemon-reload 2>/dev/null || true

    # Enable linger so user services start at boot (not just login)
    if command -v loginctl &>/dev/null; then
        if [ -n "${SUDO_USER:-}" ]; then
            sudo loginctl enable-linger "${SUDO_USER}" 2>/dev/null || \
                warn "Could not enable linger (services won't start at boot, only at login)"
        else
            loginctl enable-linger "$(whoami)" 2>/dev/null || \
                warn "Could not enable linger"
        fi
    fi

    # Enable services
    systemctl --user enable hippo-pot-manager.service 2>/dev/null || warn "Could not enable manager service"
    systemctl --user enable hippo-pot-consolidation.timer 2>/dev/null || warn "Could not enable consolidation timer"

    # Start services
    systemctl --user start hippo-pot-manager.service 2>/dev/null || warn "Could not start manager service"
    systemctl --user start hippo-pot-consolidation.timer 2>/dev/null || warn "Could not start consolidation timer"

    log "Services configured"
}

# ------------------------------------------------------------------ verify

verify_install() {
    log "Verifying installation..."

    cd "${REPO_ROOT}"
    source .venv/bin/activate

    # Run doctor
    if hungry-hippa doctor 2>&1 | tail -5; then
        log "Self-check passed"
    else
        error "Self-check failed — review output above"
        exit 1
    fi

    # Run selftest
    if hungry-hippa selftest 2>&1 | tail -3; then
        log "Acceptance tests passed"
    else
        error "Acceptance tests failed"
        exit 1
    fi
}

# ------------------------------------------------------------------ main

main() {
    echo ""
    echo "========================================="
    echo "  Hungry Hippa — Hippo-Pot Installer"
    echo "========================================="
    echo ""

    check_prerequisites
    echo ""
    install_package
    echo ""
    init_hippo_pot
    echo ""
    setup_services
    echo ""
    verify_install
    echo ""

    log "Hippo-Pot installation complete!"
    echo ""
    echo "Useful commands:"
    echo "  hungry-hippa status      — show health"
    echo "  hungry-hippa doctor      — run diagnostics"
    echo "  hungry-hippa recall 'x'  — test recall"
    echo "  hungry-hippa selftest    — run acceptance suite"
    echo "  hungry-hippa stop        — stop services"
    echo "  hungry-hippa start       — start services"
    echo "  hungry-hippa uninstall   — reversible uninstall"
    echo ""
    echo "Manager configuration (optional):"
    echo "  Edit: ~/.config/hungry-hippa/config.json"
    echo "  Set manager.endpoint to your local LLM endpoint"
    echo "  Then: hungry-hippa restart"
    echo ""
}

main "$@"
