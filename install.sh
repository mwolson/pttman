#!/bin/bash

set -euo pipefail

if ! command -v cargo >/dev/null 2>&1; then
    echo "Error: 'cargo' is required but not found in PATH." >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$HOME/.local/bin"

echo "Building pttman..."
cargo build --release --manifest-path "$SCRIPT_DIR/Cargo.toml"

echo "Installing pttman..."
mkdir -p "$BIN_DIR"
cp "$SCRIPT_DIR/target/release/pttman" "$BIN_DIR/pttman"
chmod +x "$BIN_DIR/pttman"
echo "  Installed $BIN_DIR/pttman"

"$BIN_DIR/pttman" install-service
