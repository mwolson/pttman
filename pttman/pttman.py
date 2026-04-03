#!/usr/bin/env python3

import argparse
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time

VERSION = "0.3.2"

ALLOWED_CONF_FLAGS = {"--all-sources", "--source"}

COMMAND_ALIASES = {
    "press": "unmute",
    "release": "mute",
    "talk": "unmute",
}

CONF_PATH = os.path.join(
    os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"),
    "pttman.conf",
)
SYSTEMD_USER_DIR = os.path.join(
    os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"),
    "systemd",
    "user",
)


def main():
    file_args = load_conf()
    args = parse_args(file_args)
    command = COMMAND_ALIASES.get(args.command, args.command)

    if command is None:
        require_commands(["pactl"])
        run_daemon(args)
        return

    if command == "get-default-source":
        run_get_default("source")
        return

    if command == "install-service":
        require_commands(["systemctl"])
        run_install_service()
        return

    if command == "list-sources":
        require_commands(["pactl"])
        run_list_sources(args)
        return

    if command == "set-default-source":
        require_commands(["systemctl"])
        run_set_default("source", args.value)
        return

    if command == "status":
        require_commands(["pactl"])
        print_status(resolve_sources(args))
        return

    if command == "uninstall-service":
        require_commands(["systemctl"])
        run_uninstall_service()
        return

    require_commands(["pactl"])
    send_or_run_action(command, resolve_sources(args))


def parse_args(file_args):
    parser = argparse.ArgumentParser(
        prog="pttman",
        description=(
            "Push-to-talk microphone control with a daemon-backed command queue. "
            "With no command, runs the daemon."
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")

    source_group = parser.add_mutually_exclusive_group()
    source_group.add_argument(
        "--all-sources",
        action="store_true",
        default=False,
        help="operate on all audio sources",
    )
    source_group.add_argument("--source", help="audio source name to control")

    sub = parser.add_subparsers(dest="command", title="commands")
    sub.add_parser("get-default-source", help="print the default source from the config file")
    sub.add_parser("install-service", help="install and enable the systemd user service")
    sub.add_parser("list-sources", help="list available audio sources")
    sub.add_parser("mute", aliases=["release"], help="mute the microphone")
    p = sub.add_parser("set-default-source", help="set the default source and signal the daemon")
    p.add_argument("value", metavar="SOURCE")
    sub.add_parser("status", help="print the current microphone state")
    sub.add_parser("toggle", help="toggle the microphone mute state")
    sub.add_parser("uninstall-service", help="disable and remove the systemd user service")
    sub.add_parser("unmute", aliases=["press", "talk"], help="unmute the microphone")

    args = parser.parse_args()

    args.cli_all_sources = args.all_sources
    args.cli_source = args.source
    if not args.all_sources and not args.source:
        if "all_sources" in file_args:
            args.all_sources = file_args["all_sources"]
        if "source" in file_args:
            args.source = file_args["source"]

    return args


def resolve_sources(args):
    if args.source:
        return [args.source]
    return get_all_source_names()


def load_conf():
    if not os.path.exists(CONF_PATH):
        return {}

    result = {}
    for flag, value in iter_conf_entries(CONF_PATH):
        if flag not in ALLOWED_CONF_FLAGS:
            warn(f"Error: Unsupported flag '{flag}' in {CONF_PATH}")
            sys.exit(1)
        if flag == "--all-sources":
            if value not in ("true", "false"):
                warn(f"Error: --all-sources must be 'true' or 'false' in {CONF_PATH}")
                sys.exit(1)
            result["all_sources"] = value == "true"
        elif flag == "--source":
            result["source"] = value

    if result.get("all_sources") and "source" in result:
        warn(f"Error: --all-sources and --source are mutually exclusive in {CONF_PATH}")
        sys.exit(1)

    return result


def iter_conf_entries(path):
    with open(path) as f:
        for line_num, raw_line in enumerate(f, 1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            match = re.match(r"^(--[a-z][a-z0-9-]*)=(.+)$", line)
            if not match:
                warn(f"Error: Malformed line {line_num} in {path}: {line}")
                sys.exit(1)
            yield match.group(1), match.group(2)


def require_commands(commands):
    missing = [command for command in commands if not shutil.which(command)]
    if missing:
        for command in missing:
            warn(f"Error: '{command}' is required but not found in PATH.")
        sys.exit(1)


def run_daemon(args):
    sources = resolve_sources(args)
    state = {
        "auto_discover": not args.source,
        "cli_all_sources": args.cli_all_sources,
        "cli_source": args.cli_source,
        "sources": sources,
    }

    if args.source:
        log(f"Source: {args.source}")
    else:
        log(f"Operating on all sources: {', '.join(sources)}")

    socket_path = get_socket_path()
    cleanup_socket(socket_path)

    server = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    server.bind(socket_path)

    def handle_sighup(_signum, _frame):
        reload_conf(state)

    def handle_exit(_signum, _frame):
        cleanup_socket(socket_path)
        sys.exit(0)

    signal.signal(signal.SIGHUP, handle_sighup)
    signal.signal(signal.SIGINT, handle_exit)
    signal.signal(signal.SIGTERM, handle_exit)

    start_source_watcher(state)
    log(f"pttman daemon listening on {socket_path}")
    try:
        while True:
            try:
                data = server.recv(64)
                command = coalesce_commands(server, decode_command(data))
                run_action(command, state["sources"])
            except (OSError, ValueError, subprocess.CalledProcessError) as exc:
                warn(f"Warning: {exc}")
    finally:
        server.close()
        cleanup_socket(socket_path)


def reload_conf(state):
    log("Received SIGHUP, reloading config...")
    try:
        file_args = load_conf()
    except SystemExit:
        warn("Warning: Failed to reload config, keeping current settings.")
        return

    if state["cli_source"] or state["cli_all_sources"]:
        log("CLI flags take precedence, keeping current settings.")
        return

    if "source" in file_args:
        new_sources = [file_args["source"]]
        state["auto_discover"] = False
    else:
        new_sources = get_all_source_names()
        state["auto_discover"] = True

    old_sources = state["sources"]
    if old_sources != new_sources:
        log(f"Updated sources: {old_sources} -> {new_sources}")
        state["sources"] = new_sources
    else:
        log("Config reloaded, no changes.")


def start_source_watcher(state):
    def watcher():
        while True:
            try:
                proc = subprocess.Popen(
                    ["pactl", "subscribe"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                )
                if proc.stdout is None:
                    continue
                for line in proc.stdout:
                    if "'new' on source" in line or "'remove' on source" in line:
                        time.sleep(0.5)
                        refresh_sources(state)
                proc.wait()
            except Exception as exc:
                warn(f"Warning: source watcher: {exc}")
            time.sleep(2)

    thread = threading.Thread(target=watcher, daemon=True)
    thread.start()


def refresh_sources(state):
    if not state["auto_discover"]:
        return
    new_sources = get_all_source_names()
    old_sources = state["sources"]
    if old_sources != new_sources:
        log(f"Sources changed: {old_sources} -> {new_sources}")
        state["sources"] = new_sources


def send_or_run_action(action, sources):
    try:
        send_action(action)
    except OSError as exc:
        warn(f"Warning: daemon unavailable, running '{action}' directly ({exc}).")
        run_action(action, sources)


def send_action(action):
    client = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    try:
        client.sendto(action.encode(), get_socket_path())
    finally:
        client.close()


def coalesce_commands(server, initial_command):
    effective = initial_command
    server.setblocking(False)
    try:
        while True:
            try:
                effective = decode_command(server.recv(64))
            except ValueError as exc:
                warn(f"Warning: {exc}")
    except BlockingIOError:
        return effective
    finally:
        server.setblocking(True)


def decode_command(data):
    command = data.decode().strip()
    if command not in {"mute", "toggle", "unmute"}:
        raise ValueError(f"Unsupported action: {command}")
    return command


def run_action(action, sources):
    if action == "mute":
        set_mute(sources, True)
        return
    if action == "unmute":
        set_mute(sources, False)
        return
    if action == "toggle":
        toggle_mute(sources)
        return
    raise ValueError(f"Unsupported action: {action}")


def run_list_sources(args):
    sources = get_all_source_names()
    if not sources:
        warn("Error: No audio sources found.")
        sys.exit(1)

    selected = args.source or get_default_source_name()
    descriptions = get_source_descriptions()

    for name in sources:
        parts = [name]
        desc = descriptions.get(name)
        if desc:
            parts.append(f"({desc})")
        parts.append(get_mute_state(name))
        if name == selected:
            parts.append("*")
        print("  ".join(parts))


def run_get_default(key):
    flag = f"--{key}"
    hint = f"Use 'pttman list-{key}s' to see available options, then 'pttman set-default-{key}' to set one."

    if not os.path.exists(CONF_PATH):
        warn(f"No config file found at {CONF_PATH}")
        warn("Without a default, pttman operates on all sources.")
        warn(hint)
        sys.exit(1)

    for conf_flag, value in iter_conf_entries(CONF_PATH):
        if conf_flag == flag:
            print(value)
            return

    warn(f"No {flag} entry found in {CONF_PATH}")
    warn("Without a default, pttman operates on all sources.")
    warn(hint)
    sys.exit(1)


def run_set_default(key, value):
    flag = f"--{key}"
    flag_prefix = f"{flag}="
    lines = []
    replaced = False

    if os.path.exists(CONF_PATH):
        with open(CONF_PATH) as f:
            for line in f:
                if line.strip().startswith(flag_prefix):
                    lines.append(f"{flag_prefix}{value}\n")
                    replaced = True
                else:
                    lines.append(line)

    if not replaced:
        lines.append(f"{flag_prefix}{value}\n")

    os.makedirs(os.path.dirname(CONF_PATH), exist_ok=True)
    with open(CONF_PATH, "w") as f:
        f.writelines(lines)

    log(f"Wrote {flag_prefix}{value} to {CONF_PATH}")
    signal_daemon()


def signal_daemon():
    try:
        output = subprocess.check_output(
            ["systemctl", "--user", "show", "pttman.service", "-p", "MainPID"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        return

    match = re.match(r"MainPID=(\d+)", output.strip())
    if not match or match.group(1) == "0":
        return

    pid = int(match.group(1))
    try:
        os.kill(pid, signal.SIGHUP)
        log(f"Sent SIGHUP to pttman daemon (PID {pid})")
    except OSError as exc:
        warn(f"Warning: Could not signal daemon (PID {pid}): {exc}")


def run_install_service():
    content = get_service_source()
    service_path = os.path.join(SYSTEMD_USER_DIR, "pttman.service")

    os.makedirs(SYSTEMD_USER_DIR, exist_ok=True)
    with open(service_path, "w") as f:
        f.write(content)
    log(f"Installed {service_path}")

    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "pttman.service"], check=True)
    log("Enabled pttman.service")

    log("")
    log("To start immediately:")
    log("  systemctl --user start pttman.service")
    log("")
    log("To check status:")
    log("  systemctl --user status pttman.service")
    log("  journalctl --user -u pttman.service -f")


def get_service_source():
    try:
        from importlib.resources import files

        return (files("pttman") / "systemd" / "pttman.service").read_text()
    except (FileNotFoundError, TypeError, ModuleNotFoundError):
        pass

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, "systemd", "pttman.service")
    with open(path) as f:
        return f.read()


def run_uninstall_service():
    service_path = os.path.join(SYSTEMD_USER_DIR, "pttman.service")

    subprocess.run(
        ["systemctl", "--user", "disable", "--now", "pttman.service"],
        check=False,
    )

    try:
        os.remove(service_path)
        log(f"Removed {service_path}")
    except FileNotFoundError:
        log(f"No service file at {service_path}")

    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    log("Uninstalled pttman.service")


def get_all_source_names():
    try:
        output = subprocess.check_output(
            ["pactl", "list", "sources", "short"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        return []
    names = []
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            name = parts[1]
            if ".monitor" not in name:
                names.append(name)
    return names


def get_default_source_name():
    try:
        output = subprocess.check_output(
            ["pactl", "get-default-source"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        return "@DEFAULT_SOURCE@"
    return output.strip() or "@DEFAULT_SOURCE@"


def get_source_descriptions():
    try:
        output = subprocess.check_output(
            ["pactl", "list", "sources"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        return {}
    descriptions = {}
    current_name = None
    for line in output.splitlines():
        match = re.match(r"\s*Name:\s*(\S+)", line)
        if match:
            current_name = match.group(1)
            continue
        match = re.match(r"\s*Description:\s*(.+)", line)
        if match and current_name:
            descriptions[current_name] = match.group(1).strip()
            current_name = None
    return descriptions


def get_mute_state(source):
    try:
        output = subprocess.check_output(
            ["pactl", "get-source-mute", source],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        return "unknown"
    return "muted" if "yes" in output else "unmuted"


def set_mute(sources, mute):
    value = "1" if mute else "0"
    for source in sources:
        subprocess.run(["pactl", "set-source-mute", source, value], check=True)


def toggle_mute(sources):
    for source in sources:
        subprocess.run(["pactl", "set-source-mute", source, "toggle"], check=True)


def print_status(sources):
    all_sources = get_all_source_names()
    default_name = get_default_source_name()
    managed = set()
    for s in sources:
        managed.add(default_name if s == "@DEFAULT_SOURCE@" else s)

    for source in all_sources:
        state = get_mute_state(source)
        marker = " *" if source in managed else ""
        print(f"source {source}: {state}{marker}")


def get_socket_path():
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return os.path.join(runtime_dir, "pttman.sock")


def cleanup_socket(socket_path):
    try:
        if os.path.exists(socket_path):
            os.unlink(socket_path)
    except FileNotFoundError:
        pass


def log(message):
    print(message, flush=True)


def warn(message):
    print(message, file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
