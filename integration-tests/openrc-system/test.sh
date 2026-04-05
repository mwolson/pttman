#!/bin/bash
set -euo pipefail

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

echo "=== OpenRC Integration Tests ==="
echo ""

# Initialize OpenRC runtime (needed in containers)
mkdir -p /run/openrc /run/user/0
touch /run/openrc/softlevel
openrc 2>/dev/null || true

# Set up environment for pttman daemon
mkdir -p /etc/conf.d
cat > /etc/conf.d/pttman << 'CONF'
output_log="/tmp/pttman.log"
error_log="/tmp/pttman.log"
supervise_daemon_args="--env XDG_RUNTIME_DIR=/run/user/0"
CONF

echo "Install service:"
run_test "install-service succeeds" \
    'pttman install-service'
run_test "init script installed" \
    'test -x /etc/init.d/pttman'
run_test "init script has openrc-run shebang" \
    'head -1 /etc/init.d/pttman | grep -q openrc-run'
run_test "init script defines description" \
    'grep -q "^description=" /etc/init.d/pttman'
run_test "init script defines command" \
    'grep -q "^command=" /etc/init.d/pttman'
run_test "init script defines depend()" \
    'grep -q "^depend()" /etc/init.d/pttman'
run_test "listed in default runlevel" \
    'rc-update show default 2>&1 | grep -q pttman'

echo ""
echo "Service lifecycle:"
run_test "start service" \
    'rc-service pttman start'
run_test "status reports started" \
    'rc-service pttman status 2>&1 | grep -q started'
run_test "pttman process is running" \
    'pgrep -f "pttman" >/dev/null'
run_test "stop service" \
    'rc-service pttman stop'
run_test "status reports stopped" \
    '(rc-service pttman status 2>&1 || true) | grep -q stopped'
run_test "pttman process is not running" \
    '! pgrep -f "/usr/local/bin/pttman" >/dev/null'
run_test "restart service" \
    'rc-service pttman start'
run_test "status reports started after restart" \
    'rc-service pttman status 2>&1 | grep -q started'
run_test "stop after restart" \
    'rc-service pttman stop'

echo ""
echo "Config reload via socket:"
run_test "start service for reload test" \
    'rc-service pttman start'
run_test "daemon socket is ready" \
    'for i in $(seq 1 5); do test -S /run/user/0/pttman.sock && exit 0; sleep 1; done; exit 1'
run_test "set-default-source succeeds" \
    'XDG_RUNTIME_DIR=/run/user/0 pttman set-default-source test_source'
run_test "daemon reloaded config" \
    'for i in $(seq 1 5); do grep -q "Reloading config" /tmp/pttman.log 2>/dev/null && exit 0; sleep 1; done; exit 1'
run_test "config file written" \
    'grep -q "source=test_source" ~/.config/pttman.conf'
run_test "daemon still running after reload" \
    'pgrep -f "pttman" >/dev/null'
run_test "stop after reload test" \
    'rc-service pttman stop'

echo ""
echo "Uninstall service:"
run_test "uninstall-service succeeds" \
    'pttman uninstall-service'
run_test "init script removed" \
    '! test -f /etc/init.d/pttman'
run_test "not listed in default runlevel" \
    '! rc-update show default 2>&1 | grep -q pttman'

echo ""
echo "Results: ${pass} passed, ${fail} failed"
if [[ -n "$errors" ]]; then
    echo ""
    echo "Failures:"
    printf "$errors"
    exit 1
fi
