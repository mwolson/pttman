#!/bin/bash
set -euo pipefail

for cmd in docker; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        echo "Error: '$cmd' is required but not found in PATH." >&2
        exit 1
    fi
done

if ! docker compose version >/dev/null 2>&1; then
    echo "Error: 'docker compose' (v2) is required but not available." >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

cleanup() {
    docker compose down --timeout 5 2>/dev/null || true
}
trap cleanup EXIT

result=0

echo "Building test images..."
docker compose build

# --- OpenRC System ---

echo ""
if docker compose run --rm test-openrc-system; then
    echo ""
    echo "OpenRC (system): PASSED"
else
    echo ""
    echo "OpenRC (system): FAILED"
    result=1
fi

# --- OpenRC User ---

echo ""
if docker compose run --rm test-openrc-user; then
    echo ""
    echo "OpenRC (user): PASSED"
else
    echo ""
    echo "OpenRC (user): FAILED"
    result=1
fi

# --- systemd ---

echo ""
echo "Starting systemd container..."
docker compose up -d test-systemd

echo "Waiting for systemd to initialize..."
ready=false
for i in $(seq 1 30); do
    state=$(docker compose exec -T test-systemd systemctl is-system-running 2>/dev/null || true)
    case "$state" in
        running|degraded)
            ready=true
            break
            ;;
    esac
    sleep 1
done

if [[ "$ready" != "true" ]]; then
    echo "Error: timed out waiting for systemd (last state: ${state:-unknown})" >&2
    result=1
else
    if docker compose exec -T test-systemd /opt/test.sh; then
        echo ""
        echo "systemd: PASSED"
    else
        echo ""
        echo "systemd: FAILED"
        result=1
    fi
fi

exit $result
