#!/bin/bash

set -euo pipefail

if ! command -v systemctl >/dev/null 2>&1; then
    echo "Error: 'systemctl' is required but not found in PATH." >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

BIN_DIR="$HOME/.local/bin"
SYSTEMD_USER_DIR="$HOME/.config/systemd/user"

echo "Installing pttman..."

mkdir -p "$BIN_DIR"
cp "$SCRIPT_DIR/pttman.py" "$BIN_DIR/pttman"
chmod +x "$BIN_DIR/pttman"
echo "  Installed $BIN_DIR/pttman"

mkdir -p "$SYSTEMD_USER_DIR"
cp "$SCRIPT_DIR/systemd/pttman.service" "$SYSTEMD_USER_DIR/"
echo "  Installed $SYSTEMD_USER_DIR/pttman.service"

systemctl --user daemon-reload
systemctl --user enable pttman.service
echo "  Enabled pttman.service"

echo ""
echo "Done. To start immediately:"
echo "  systemctl --user start pttman.service"
echo ""
echo "To check status:"
echo "  systemctl --user status pttman.service"
echo "  journalctl --user -u pttman.service -f"
