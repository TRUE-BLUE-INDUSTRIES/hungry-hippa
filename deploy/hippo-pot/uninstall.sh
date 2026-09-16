#!/usr/bin/env bash
#
# Hippo-Pot uninstaller
#
# Reversible: preserves memory data and configuration by default.
# Use --purge to destroy everything.
#
# Usage:
#   ./deploy/hippo-pot/uninstall.sh          # preserve data
#   ./deploy/hippo-pot/uninstall.sh --purge  # destroy all data
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() { echo -e "${GREEN}[hippo-pot]${NC} $*"; }
warn() { echo -e "${YELLOW}[hippo-pot]${NC} $*"; }
error() { echo -e "${RED}[hippo-pot]${NC} $*" >&2; }

PURGE=false
if [ "${1:-}" = "--purge" ]; then
    PURGE=true
fi

# Confirm purge
if [ "$PURGE" = true ]; then
    echo ""
    echo -e "${RED}WARNING: --purge will DESTROY all memory data.${NC}"
    echo "This is IRREVERSIBLE."
    echo ""
    read -rp "Type 'yes' to confirm: " CONFIRM
    if [ "$CONFIRM" != "yes" ]; then
        echo "Aborted."
        exit 0
    fi
fi

# ---------------------------------------------------------- stop services

stop_services() {
    log "Stopping services..."

    systemctl --user stop hippo-pot-consolidation.timer 2>/dev/null || true
    systemctl --user stop hippo-pot-manager.service 2>/dev/null || true

    systemctl --user disable hippo-pot-consolidation.timer 2>/dev/null || true
    systemctl --user disable hippo-pot-manager.service 2>/dev/null || true

    # Remove unit files
    rm -f "${HOME}/.config/systemd/user/hippo-pot-manager.service"
    rm -f "${HOME}/.config/systemd/user/hippo-pot-consolidation.timer"
    rm -f "${HOME}/.config/systemd/user/hippo-pot-consolidation.service"

    systemctl --user daemon-reload 2>/dev/null || true

    log "Services removed"
}

# ------------------------------------------------------------- remove data

remove_data() {
    if [ "$PURGE" = true ]; then
        log "Purging all data..."

        # Remove database
        rm -f "${HOME}/.local/share/hungry-hippa/hungry_hippa.db"
        rm -f "${HOME}/.local/share/hungry-hippa/hungry_hippa.db-wal"
        rm -f "${HOME}/.local/share/hungry-hippa/hungry_hippa.db-shm"
        rm -f "${HOME}/.local/share/hungry-hippa"/*.bak

        # Remove config and token
        rm -f "${HOME}/.config/hungry-hippa/config.json"
        rm -f "${HOME}/.local/state/hungry-hippa/owner.token"

        # Remove directories (only if empty)
        rmdir "${HOME}/.local/share/hungry-hippa" 2>/dev/null || true
        rmdir "${HOME}/.config/hungry-hippa" 2>/dev/null || true
        rmdir "${HOME}/.local/state/hungry-hippa" 2>/dev/null || true

        log "All data purged"
    else
        log "Data preserved at:"
        echo "  Database: ~/.local/share/hungry-hippa/"
        echo "  Config:   ~/.config/hungry-hippa/"
        echo "  Token:    ~/.local/state/hungry-hippa/"
        echo ""
        echo "To remove data later, run with --purge"
    fi
}

# ------------------------------------------------------------------ main

main() {
    echo ""
    echo "========================================="
    echo "  Hungry Hippa — Hippo-Pot Uninstaller"
    if [ "$PURGE" = true ]; then
        echo -e "  ${RED}MODE: PURGE (destructive)${NC}"
    else
        echo -e "  ${GREEN}MODE: SAFE (preserve data)${NC}"
    fi
    echo "========================================="
    echo ""

    stop_services
    remove_data

    echo ""
    log "Uninstallation complete."

    if [ "$PURGE" = false ]; then
        echo ""
        echo "To reinstall later, run:"
        echo "  ./deploy/hippo-pot/install.sh"
    fi
    echo ""
}

main "$@"
