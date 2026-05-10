#!/bin/bash
set -euo pipefail

if [[ "$(id -u)" == "0" ]]; then
    export XDG_RUNTIME_DIR=/run/user/1000
    mkdir -p "$XDG_RUNTIME_DIR"
    chown testuser:testuser "$XDG_RUNTIME_DIR"
    exec su testuser -s /bin/bash "$0"
fi

export PATH="/usr/local/bin:$PATH"
export XDG_RUNTIME_DIR=/run/user/1000

pass=0
fail=0
errors=""

run_test() {
    local name="$1"
    shift
    printf "  %-50s " "$name"
    local output
    if output=$(eval "$*" 2>&1); then
        echo "ok"
        pass=$((pass + 1))
    else
        echo "FAIL"
        fail=$((fail + 1))
        errors="${errors}  - ${name}\n"
        if [[ -n "$output" ]]; then
            printf "    %s\n" "$output"
        fi
    fi
}

echo "=== OpenRC User Integration Tests ==="
echo ""

mkdir -p "$XDG_RUNTIME_DIR/openrc"
touch "$XDG_RUNTIME_DIR/openrc/softlevel"
openrc --user 2>/dev/null || true

mkdir -p "$HOME/.config/rc/runlevels/default"
mkdir -p "$HOME/.config/rc/conf.d"
cat > "$HOME/.config/rc/conf.d/pttman" << CONF
output_log="$HOME/pttman.log"
error_log="$HOME/pttman.log"
CONF

echo "Install service:"
run_test "install-service succeeds" \
    'pttman install-service'
run_test "init script installed" \
    "test -x $HOME/.config/rc/init.d/pttman"
run_test "listed in default runlevel" \
    "rc-update --user show default 2>&1 | grep -q pttman"

echo ""
echo "Service lifecycle:"
run_test "start service" \
    "rc-service --user pttman start"
run_test "status reports started" \
    "rc-service --user pttman status 2>&1 | grep -q started"
run_test "pttman process is running" \
    "pgrep -f pttman >/dev/null"
run_test "stop service" \
    "rc-service --user pttman stop"
run_test "status reports stopped" \
    "(rc-service --user pttman status 2>&1 || true) | grep -q stopped"

echo ""
echo "Config reload via socket:"
run_test "start service for reload test" \
    "rc-service --user pttman start"
run_test "daemon socket is ready" \
    'for _ in $(seq 1 5); do test -S $XDG_RUNTIME_DIR/pttman.sock && exit 0; sleep 1; done; exit 1'
run_test "set-default-source succeeds" \
    "pttman set-default-source test_source"
run_test "daemon reloaded config" \
    'for _ in $(seq 1 5); do grep -q "Reloading config" '"$HOME/pttman.log"' 2>/dev/null && exit 0; sleep 1; done; exit 1'
run_test "config file written" \
    "grep -q 'source=test_source' $HOME/.config/pttman.conf"
run_test "daemon still running after reload" \
    "pgrep -f pttman >/dev/null"
run_test "stop after reload test" \
    "rc-service --user pttman stop"

echo ""
echo "Uninstall service:"
run_test "uninstall-service succeeds" \
    "pttman uninstall-service"
run_test "init script removed" \
    "! test -f $HOME/.config/rc/init.d/pttman"
run_test "not listed in default runlevel" \
    "! rc-update --user show default 2>&1 | grep -q pttman"

echo ""
echo "Results: ${pass} passed, ${fail} failed"
if [[ -n "$errors" ]]; then
    echo ""
    echo "Failures:"
    printf "%b" "$errors"
    exit 1
fi
