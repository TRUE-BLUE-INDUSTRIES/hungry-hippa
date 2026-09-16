#!/usr/bin/env bash
#
# Hippo-Pot health check script.
#
# Returns 0 if the Hippo-Pot is healthy, 1 otherwise.
# Designed to be run by systemd or monitoring tools.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

cd "${REPO_ROOT}"
source .venv/bin/activate 2>/dev/null || true

# Run doctor and check the result
OUTPUT=$(hungry-hippa doctor 2>/dev/null) && DOCTOR_EXIT=0 || DOCTOR_EXIT=$?

if [ "$DOCTOR_EXIT" = "0" ]; then
    # Check for healthy marker in output
    if echo "$OUTPUT" | grep -q '"healthy": true'; then
        echo "OK: Hippo-Pot is healthy"
        exit 0
    fi
fi

echo "FAIL: Hippo-Pot health check failed"
echo "$OUTPUT" | tail -30
exit 1
