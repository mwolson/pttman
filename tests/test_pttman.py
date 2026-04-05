import importlib.machinery
import importlib.util
import os
import pathlib
import tempfile
import threading
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]


def load_module():
    loader = importlib.machinery.SourceFileLoader("pttman_module", str(ROOT / "pttman" / "pttman.py"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    if spec is None:
        raise RuntimeError("Failed to create import spec for pttman")
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


PTTMAN = load_module()

PACTL_LIST_SOURCES_SHORT = (
    "64\talsa_input.usb-046d_BRIO-03.pro-input-0\tPipeWire\ts16le 2ch 48000Hz\tSUSPENDED\n"
    "65\talsa_input.pci-0000_00_1f.3.analog-stereo\tPipeWire\ts16le 2ch 48000Hz\tSUSPENDED\n"
    "86\talsa_output.pci-0000_01_00.1.pro-output-3.monitor\tPipeWire\ts32le 8ch 48000Hz\tIDLE\n"
)


class FakeSocket:
    def __init__(self, queued_messages):
        self.queued_messages = list(queued_messages)
        self.blocking_values = []

    def setblocking(self, value):
        self.blocking_values.append(value)

    def recv(self, _size):
        if self.queued_messages:
            return self.queued_messages.pop(0)
        raise BlockingIOError


class ConfTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._orig_conf_path = PTTMAN.CONF_PATH
        PTTMAN.CONF_PATH = os.path.join(self._tmpdir.name, "pttman.conf")

    def tearDown(self):
        PTTMAN.CONF_PATH = self._orig_conf_path
        self._tmpdir.cleanup()

    def test_load_conf_returns_empty_when_no_file(self):
        self.assertEqual({}, PTTMAN.load_conf())

    def test_load_conf_reads_source(self):
        with open(PTTMAN.CONF_PATH, "w") as f:
            f.write("--source=alsa_input.usb-046d_BRIO-03.pro-input-0\n")
        self.assertEqual({"source": "alsa_input.usb-046d_BRIO-03.pro-input-0"}, PTTMAN.load_conf())

    def test_load_conf_ignores_comments_and_blank_lines(self):
        with open(PTTMAN.CONF_PATH, "w") as f:
            f.write("# a comment\n\n--source=my-source\n")
        self.assertEqual({"source": "my-source"}, PTTMAN.load_conf())

    def test_load_conf_rejects_unknown_flags(self):
        with open(PTTMAN.CONF_PATH, "w") as f:
            f.write("--bogus=value\n")
        with self.assertRaises(SystemExit):
            PTTMAN.load_conf()

    def test_load_conf_rejects_malformed_lines(self):
        with open(PTTMAN.CONF_PATH, "w") as f:
            f.write("not a flag\n")
        with self.assertRaises(SystemExit):
            PTTMAN.load_conf()

    @mock.patch.object(PTTMAN, "signal_daemon")
    def test_set_default_source_creates_file(self, _signal_daemon):
        PTTMAN.run_set_default("source", "my-source")
        with open(PTTMAN.CONF_PATH) as f:
            self.assertEqual("--source=my-source\n", f.read())

    @mock.patch.object(PTTMAN, "signal_daemon")
    def test_set_default_source_replaces_existing(self, _signal_daemon):
        with open(PTTMAN.CONF_PATH, "w") as f:
            f.write("--source=old-source\n")
        PTTMAN.run_set_default("source", "new-source")
        with open(PTTMAN.CONF_PATH) as f:
            self.assertEqual("--source=new-source\n", f.read())

    @mock.patch("builtins.print")
    def test_get_default_source_prints_source(self, mock_print):
        with open(PTTMAN.CONF_PATH, "w") as f:
            f.write("--source=my-source\n")
        PTTMAN.run_get_default("source")
        mock_print.assert_called_once_with("my-source")

    @mock.patch("builtins.print")
    def test_get_default_source_exits_when_no_file(self, _print):
        with self.assertRaises(SystemExit):
            PTTMAN.run_get_default("source")

    @mock.patch("builtins.print")
    def test_get_default_source_exits_when_no_entry(self, _print):
        with open(PTTMAN.CONF_PATH, "w") as f:
            f.write("# empty config\n")
        with self.assertRaises(SystemExit):
            PTTMAN.run_get_default("source")

    def test_load_conf_reads_all_sources(self):
        with open(PTTMAN.CONF_PATH, "w") as f:
            f.write("--all-sources=true\n")
        self.assertEqual({"all_sources": True}, PTTMAN.load_conf())

    def test_load_conf_reads_all_sources_false(self):
        with open(PTTMAN.CONF_PATH, "w") as f:
            f.write("--all-sources=false\n")
        self.assertEqual({"all_sources": False}, PTTMAN.load_conf())

    def test_load_conf_rejects_all_sources_invalid_value(self):
        with open(PTTMAN.CONF_PATH, "w") as f:
            f.write("--all-sources=yes\n")
        with self.assertRaises(SystemExit):
            PTTMAN.load_conf()

    def test_load_conf_rejects_all_sources_with_source(self):
        with open(PTTMAN.CONF_PATH, "w") as f:
            f.write("--all-sources=true\n--source=my-source\n")
        with self.assertRaises(SystemExit):
            PTTMAN.load_conf()

    @mock.patch("builtins.print")
    def test_reload_conf_updates_source(self, _print):
        with open(PTTMAN.CONF_PATH, "w") as f:
            f.write("--source=new-source\n")
        state = {"auto_discover": True, "cli_all_sources": False, "cli_source": None, "sources": ["src1", "src2"]}
        PTTMAN.reload_conf(state)
        self.assertEqual(["new-source"], state["sources"])
        self.assertFalse(state["auto_discover"])

    @mock.patch("builtins.print")
    def test_reload_conf_cli_source_takes_precedence(self, _print):
        with open(PTTMAN.CONF_PATH, "w") as f:
            f.write("--source=new-source\n")
        state = {"auto_discover": False, "cli_all_sources": False, "cli_source": "cli-source", "sources": ["cli-source"]}
        PTTMAN.reload_conf(state)
        self.assertEqual(["cli-source"], state["sources"])

    @mock.patch("builtins.print")
    def test_reload_conf_cli_all_sources_takes_precedence(self, _print):
        with open(PTTMAN.CONF_PATH, "w") as f:
            f.write("--source=new-source\n")
        state = {"auto_discover": True, "cli_all_sources": True, "cli_source": None, "sources": ["src1", "src2"]}
        PTTMAN.reload_conf(state)
        self.assertEqual(["src1", "src2"], state["sources"])

    @mock.patch.object(PTTMAN, "get_all_source_names", return_value=["src1", "src2"])
    @mock.patch("builtins.print")
    def test_reload_conf_no_source_reverts_to_all(self, _print, _get_all):
        with open(PTTMAN.CONF_PATH, "w") as f:
            f.write("# cleared config\n")
        state = {"auto_discover": False, "cli_all_sources": False, "cli_source": None, "sources": ["old-source"]}
        PTTMAN.reload_conf(state)
        self.assertEqual(["src1", "src2"], state["sources"])
        self.assertTrue(state["auto_discover"])


class SourceWatcherTests(unittest.TestCase):
    @mock.patch.object(PTTMAN, "get_all_source_names", return_value=["src1", "src2"])
    @mock.patch("builtins.print")
    def test_refresh_sources_updates_when_auto_discover(self, _print, _get_all):
        state = {"auto_discover": True, "sources": []}
        PTTMAN.refresh_sources(state)
        self.assertEqual(["src1", "src2"], state["sources"])

    @mock.patch.object(PTTMAN, "get_all_source_names", return_value=["src1", "src2"])
    def test_refresh_sources_skips_when_not_auto_discover(self, _get_all):
        state = {"auto_discover": False, "sources": ["pinned"]}
        PTTMAN.refresh_sources(state)
        self.assertEqual(["pinned"], state["sources"])
        _get_all.assert_not_called()

    @mock.patch.object(PTTMAN, "get_all_source_names", return_value=["src1"])
    @mock.patch("builtins.print")
    def test_refresh_sources_no_op_when_unchanged(self, mock_print, _get_all):
        state = {"auto_discover": True, "sources": ["src1"]}
        PTTMAN.refresh_sources(state)
        self.assertEqual(["src1"], state["sources"])
        mock_print.assert_not_called()

    @mock.patch.object(PTTMAN.subprocess, "Popen")
    def test_start_source_watcher_spawns_daemon_thread(self, _popen):
        state = {"auto_discover": True, "sources": []}
        before = threading.active_count()
        PTTMAN.start_source_watcher(state)
        self.assertGreater(threading.active_count(), before)


class ParseArgsTests(unittest.TestCase):
    def test_no_subcommand_is_daemon(self):
        with mock.patch("sys.argv", ["pttman"]):
            args = PTTMAN.parse_args({})
        self.assertIsNone(args.command)

    def test_subcommand_get_default_source(self):
        with mock.patch("sys.argv", ["pttman", "get-default-source"]):
            args = PTTMAN.parse_args({})
        self.assertEqual("get-default-source", args.command)

    def test_subcommand_list_sources(self):
        with mock.patch("sys.argv", ["pttman", "list-sources"]):
            args = PTTMAN.parse_args({})
        self.assertEqual("list-sources", args.command)

    def test_subcommand_mute(self):
        with mock.patch("sys.argv", ["pttman", "mute"]):
            args = PTTMAN.parse_args({})
        self.assertEqual("mute", args.command)

    def test_subcommand_set_default_source(self):
        with mock.patch("sys.argv", ["pttman", "set-default-source", "my-source"]):
            args = PTTMAN.parse_args({})
        self.assertEqual("set-default-source", args.command)
        self.assertEqual("my-source", args.value)

    def test_subcommand_status(self):
        with mock.patch("sys.argv", ["pttman", "status"]):
            args = PTTMAN.parse_args({})
        self.assertEqual("status", args.command)

    def test_subcommand_unmute(self):
        with mock.patch("sys.argv", ["pttman", "unmute"]):
            args = PTTMAN.parse_args({})
        self.assertEqual("unmute", args.command)

    def test_alias_press_maps_to_unmute(self):
        with mock.patch("sys.argv", ["pttman", "press"]):
            args = PTTMAN.parse_args({})
        self.assertEqual("press", args.command)
        self.assertEqual("unmute", PTTMAN.COMMAND_ALIASES.get(args.command, args.command))

    def test_alias_release_maps_to_mute(self):
        with mock.patch("sys.argv", ["pttman", "release"]):
            args = PTTMAN.parse_args({})
        self.assertEqual("release", args.command)
        self.assertEqual("mute", PTTMAN.COMMAND_ALIASES.get(args.command, args.command))

    def test_source_flag(self):
        with mock.patch("sys.argv", ["pttman", "--source", "my-source", "mute"]):
            args = PTTMAN.parse_args({})
        self.assertEqual("my-source", args.source)
        self.assertEqual("my-source", args.cli_source)

    def test_all_sources_flag(self):
        with mock.patch("sys.argv", ["pttman", "--all-sources", "mute"]):
            args = PTTMAN.parse_args({})
        self.assertTrue(args.all_sources)
        self.assertTrue(args.cli_all_sources)

    def test_conf_source_used_as_default(self):
        with mock.patch("sys.argv", ["pttman", "mute"]):
            args = PTTMAN.parse_args({"source": "conf-source"})
        self.assertEqual("conf-source", args.source)
        self.assertIsNone(args.cli_source)

    def test_conf_all_sources_used_as_default(self):
        with mock.patch("sys.argv", ["pttman", "mute"]):
            args = PTTMAN.parse_args({"all_sources": True})
        self.assertTrue(args.all_sources)
        self.assertFalse(args.cli_all_sources)

    def test_cli_source_overrides_conf(self):
        with mock.patch("sys.argv", ["pttman", "--source", "cli-source", "mute"]):
            args = PTTMAN.parse_args({"source": "conf-source"})
        self.assertEqual("cli-source", args.source)
        self.assertEqual("cli-source", args.cli_source)

    def test_cli_all_sources_overrides_conf_source(self):
        with mock.patch("sys.argv", ["pttman", "--all-sources", "mute"]):
            args = PTTMAN.parse_args({"source": "conf-source"})
        self.assertTrue(args.all_sources)
        self.assertIsNone(args.source)


class ResolveSourcesTests(unittest.TestCase):
    @mock.patch.object(PTTMAN, "get_all_source_names", return_value=["src1", "src2"])
    def test_default_is_all_sources(self, _get_all):
        with mock.patch("sys.argv", ["pttman", "mute"]):
            args = PTTMAN.parse_args({})
        self.assertEqual(["src1", "src2"], PTTMAN.resolve_sources(args))

    def test_with_source_flag(self):
        with mock.patch("sys.argv", ["pttman", "--source", "my-source", "mute"]):
            args = PTTMAN.parse_args({})
        self.assertEqual(["my-source"], PTTMAN.resolve_sources(args))

    @mock.patch.object(PTTMAN, "get_all_source_names", return_value=["src1", "src2"])
    def test_with_all_sources_flag(self, _get_all):
        with mock.patch("sys.argv", ["pttman", "--all-sources", "mute"]):
            args = PTTMAN.parse_args({})
        self.assertEqual(["src1", "src2"], PTTMAN.resolve_sources(args))


class PactlTests(unittest.TestCase):
    @mock.patch.object(PTTMAN.subprocess, "check_output", return_value=PACTL_LIST_SOURCES_SHORT)
    def test_get_all_source_names_parses_pactl_output(self, _check_output):
        names = PTTMAN.get_all_source_names()
        self.assertEqual(
            ["alsa_input.usb-046d_BRIO-03.pro-input-0", "alsa_input.pci-0000_00_1f.3.analog-stereo"],
            names,
        )

    @mock.patch.object(PTTMAN.subprocess, "check_output", return_value=PACTL_LIST_SOURCES_SHORT)
    def test_get_all_source_names_filters_monitors(self, _check_output):
        names = PTTMAN.get_all_source_names()
        self.assertFalse(any(".monitor" in n for n in names))

    @mock.patch("builtins.print")
    @mock.patch.object(PTTMAN, "get_mute_state", return_value="muted")
    @mock.patch.object(PTTMAN, "get_default_source_name", return_value="src1")
    @mock.patch.object(PTTMAN, "get_all_source_names", return_value=["src1", "src2"])
    def test_print_status_marks_managed_sources(self, _get_all, _get_default, _get_mute, mock_print):
        PTTMAN.print_status(["@DEFAULT_SOURCE@"])
        calls = [str(c) for c in mock_print.call_args_list]
        self.assertTrue(any("src1" in c and " *" in c for c in calls))
        self.assertTrue(any("src2" in c and " *" not in c for c in calls))

    @mock.patch("builtins.print")
    @mock.patch.object(PTTMAN, "get_mute_state", return_value="unmuted")
    @mock.patch.object(PTTMAN, "get_default_source_name", return_value="src1")
    @mock.patch.object(PTTMAN, "get_all_source_names", return_value=["src1", "src2"])
    def test_print_status_marks_all_when_all_sources(self, _get_all, _get_default, _get_mute, mock_print):
        PTTMAN.print_status(["src1", "src2"])
        calls = [str(c) for c in mock_print.call_args_list]
        self.assertTrue(all(" *" in c for c in calls))

    @mock.patch.object(PTTMAN.subprocess, "run")
    def test_set_mute_calls_pactl(self, mock_run):
        PTTMAN.set_mute(["src1", "src2"], True)
        mock_run.assert_any_call(["pactl", "set-source-mute", "src1", "1"], check=True)
        mock_run.assert_any_call(["pactl", "set-source-mute", "src2", "1"], check=True)

    @mock.patch.object(PTTMAN.subprocess, "run")
    def test_toggle_mute_calls_pactl(self, mock_run):
        PTTMAN.toggle_mute(["src1"])
        mock_run.assert_called_once_with(["pactl", "set-source-mute", "src1", "toggle"], check=True)

    @mock.patch.object(PTTMAN.subprocess, "check_output", return_value="Mute: yes\n")
    def test_get_mute_state_muted(self, _check_output):
        self.assertEqual("muted", PTTMAN.get_mute_state("src1"))

    @mock.patch.object(PTTMAN.subprocess, "check_output", return_value="Mute: no\n")
    def test_get_mute_state_unmuted(self, _check_output):
        self.assertEqual("unmuted", PTTMAN.get_mute_state("src1"))


class SocketTests(unittest.TestCase):
    @mock.patch("builtins.print")
    def test_coalesce_commands_last_valid_command_wins(self, _print):
        fake_socket = FakeSocket([b"bogus", b"unmute", b"mute"])
        state = {"auto_discover": True, "cli_all_sources": False, "cli_source": None, "sources": []}

        effective = PTTMAN.coalesce_commands(fake_socket, "toggle", state)

        self.assertEqual("mute", effective)
        self.assertEqual([False, True], fake_socket.blocking_values)

    @mock.patch.object(PTTMAN, "reload_conf")
    @mock.patch("builtins.print")
    def test_coalesce_commands_handles_reload_without_clobbering(self, _print, mock_reload):
        fake_socket = FakeSocket([b"reload", b"mute"])
        state = {"auto_discover": True, "cli_all_sources": False, "cli_source": None, "sources": []}

        effective = PTTMAN.coalesce_commands(fake_socket, "unmute", state)

        self.assertEqual("mute", effective)
        mock_reload.assert_called_once_with(state)

    @mock.patch.object(PTTMAN, "run_action")
    @mock.patch.object(PTTMAN, "send_action", side_effect=OSError("missing socket"))
    @mock.patch("builtins.print")
    def test_send_or_run_action_falls_back_to_direct_execution(self, _print, _send_action, run_action):
        PTTMAN.send_or_run_action("toggle", ["@DEFAULT_SOURCE@"])

        run_action.assert_called_once_with("toggle", ["@DEFAULT_SOURCE@"])

    def test_send_action_delivers_unix_datagram(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            server = PTTMAN.socket.socket(PTTMAN.socket.AF_UNIX, PTTMAN.socket.SOCK_DGRAM)
            socket_path = pathlib.Path(tmpdir) / "pttman.sock"
            server.bind(str(socket_path))
            try:
                with mock.patch.dict(PTTMAN.os.environ, {"XDG_RUNTIME_DIR": tmpdir}, clear=False):
                    PTTMAN.send_action("mute")

                payload = server.recv(64)
                self.assertEqual(b"mute", payload)
            finally:
                server.close()


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil

        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_get_service_source_returns_valid_unit(self):
        content = PTTMAN.get_service_source()
        self.assertIn("[Unit]", content)
        self.assertIn("[Service]", content)
        self.assertIn("[Install]", content)
        self.assertIn("ExecStart=", content)

    def test_get_service_source_matches_repo_file(self):
        content = PTTMAN.get_service_source()
        repo_path = ROOT / "systemd" / "pttman.service"
        with open(repo_path) as f:
            expected = f.read()
        self.assertEqual(expected, content)

    @mock.patch.object(PTTMAN.subprocess, "run")
    @mock.patch("builtins.print")
    def test_install_service_creates_file_and_enables(self, _print, run_mock):
        systemd_dir = os.path.join(self._tmpdir, "systemd", "user")
        with mock.patch.object(PTTMAN, "SYSTEMD_USER_DIR", systemd_dir):
            PTTMAN.run_install_service()

        service_path = os.path.join(systemd_dir, "pttman.service")
        self.assertTrue(os.path.exists(service_path))
        with open(service_path) as f:
            content = f.read()
        self.assertIn("[Service]", content)

        self.assertEqual(
            [
                mock.call(["systemctl", "--user", "daemon-reload"], check=True),
                mock.call(["systemctl", "--user", "enable", "pttman.service"], check=True),
            ],
            run_mock.call_args_list,
        )

    @mock.patch.object(PTTMAN.subprocess, "run")
    @mock.patch("builtins.print")
    def test_install_service_is_idempotent(self, _print, run_mock):
        systemd_dir = os.path.join(self._tmpdir, "systemd", "user")
        with mock.patch.object(PTTMAN, "SYSTEMD_USER_DIR", systemd_dir):
            PTTMAN.run_install_service()
            PTTMAN.run_install_service()

        service_path = os.path.join(systemd_dir, "pttman.service")
        self.assertTrue(os.path.exists(service_path))

    @mock.patch.object(PTTMAN.subprocess, "run")
    @mock.patch("builtins.print")
    def test_uninstall_service_removes_file(self, _print, run_mock):
        systemd_dir = os.path.join(self._tmpdir, "systemd", "user")
        os.makedirs(systemd_dir)
        service_path = os.path.join(systemd_dir, "pttman.service")
        with open(service_path, "w") as f:
            f.write("[Service]\n")

        with mock.patch.object(PTTMAN, "SYSTEMD_USER_DIR", systemd_dir):
            PTTMAN.run_uninstall_service()

        self.assertFalse(os.path.exists(service_path))
        self.assertEqual(
            [
                mock.call(
                    ["systemctl", "--user", "disable", "--now", "pttman.service"],
                    check=False,
                ),
                mock.call(["systemctl", "--user", "daemon-reload"], check=True),
            ],
            run_mock.call_args_list,
        )

    @mock.patch.object(PTTMAN.subprocess, "run")
    @mock.patch("builtins.print")
    def test_uninstall_service_handles_missing_file(self, _print, run_mock):
        systemd_dir = os.path.join(self._tmpdir, "systemd", "user")
        os.makedirs(systemd_dir)
        with mock.patch.object(PTTMAN, "SYSTEMD_USER_DIR", systemd_dir):
            PTTMAN.run_uninstall_service()

    def test_parse_args_subcommand_install_service(self):
        with mock.patch("sys.argv", ["pttman", "install-service"]):
            args = PTTMAN.parse_args({})
        self.assertEqual("install-service", args.command)

    def test_parse_args_subcommand_uninstall_service(self):
        with mock.patch("sys.argv", ["pttman", "uninstall-service"]):
            args = PTTMAN.parse_args({})
        self.assertEqual("uninstall-service", args.command)


class DetectInitSystemTests(unittest.TestCase):
    @mock.patch.object(
        PTTMAN.shutil,
        "which",
        side_effect=lambda cmd: "/usr/bin/systemctl" if cmd == "systemctl" else None,
    )
    def test_detects_systemd(self, _which):
        self.assertEqual("systemd", PTTMAN.detect_init_system())

    @mock.patch.object(PTTMAN, "get_openrc_version", return_value=(0, 55))
    @mock.patch.object(
        PTTMAN.shutil,
        "which",
        side_effect=lambda cmd: "/usr/sbin/rc-service" if cmd == "rc-service" else None,
    )
    def test_detects_openrc_system(self, _which, _version):
        self.assertEqual("openrc-system", PTTMAN.detect_init_system())

    @mock.patch.object(PTTMAN, "get_openrc_version", return_value=(0, 63))
    @mock.patch.object(
        PTTMAN.shutil,
        "which",
        side_effect=lambda cmd: "/usr/sbin/rc-service" if cmd == "rc-service" else None,
    )
    def test_detects_openrc_user(self, _which, _version):
        self.assertEqual("openrc-user", PTTMAN.detect_init_system())

    @mock.patch.object(PTTMAN.shutil, "which", return_value=None)
    def test_returns_none_if_neither_found(self, _which):
        self.assertIsNone(PTTMAN.detect_init_system())

    @mock.patch.object(PTTMAN, "get_openrc_version", return_value=(0, 63))
    @mock.patch.object(
        PTTMAN.shutil,
        "which",
        side_effect=lambda cmd: {
            "systemctl": "/usr/bin/systemctl",
            "rc-service": "/usr/sbin/rc-service",
        }.get(cmd),
    )
    def test_prefers_systemd_over_openrc(self, _which, _version):
        self.assertEqual("systemd", PTTMAN.detect_init_system())


class GetOpenRCVersionTests(unittest.TestCase):
    @mock.patch.object(PTTMAN.subprocess, "check_output", return_value="openrc (OpenRC) 0.55.1\n")
    def test_parses_version(self, _check_output):
        self.assertEqual((0, 55, 1), PTTMAN.get_openrc_version())

    @mock.patch.object(PTTMAN.subprocess, "check_output", return_value="openrc (OpenRC [DOCKER]) 0.63\n")
    def test_parses_docker_version(self, _check_output):
        self.assertEqual((0, 63), PTTMAN.get_openrc_version())

    @mock.patch.object(PTTMAN.subprocess, "check_output", side_effect=FileNotFoundError)
    def test_returns_zero_on_missing(self, _check_output):
        self.assertEqual((0, 0), PTTMAN.get_openrc_version())


class RootCheckTests(unittest.TestCase):
    @mock.patch.object(PTTMAN.os, "geteuid", return_value=1000)
    def test_require_root_fails_as_non_root(self, _geteuid):
        with self.assertRaises(SystemExit):
            PTTMAN.require_root()

    @mock.patch.object(PTTMAN.os, "geteuid", return_value=0)
    def test_require_root_passes_as_root(self, _geteuid):
        PTTMAN.require_root()

    @mock.patch.object(PTTMAN.os, "geteuid", return_value=0)
    def test_require_non_root_fails_as_root(self, _geteuid):
        with self.assertRaises(SystemExit):
            PTTMAN.require_non_root()

    @mock.patch.object(PTTMAN.os, "geteuid", return_value=1000)
    def test_require_non_root_passes_as_non_root(self, _geteuid):
        PTTMAN.require_non_root()


class OpenRCSystemServiceTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil

        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_get_openrc_system_source_returns_valid_init_script(self):
        content = PTTMAN.get_openrc_system_source()
        self.assertIn("#!/sbin/openrc-run", content)
        self.assertIn("command=", content)
        self.assertIn("depend()", content)

    def test_get_openrc_system_source_matches_repo_file(self):
        content = PTTMAN.get_openrc_system_source()
        repo_path = ROOT / "openrc-system" / "pttman"
        with open(repo_path) as f:
            expected = f.read()
        self.assertEqual(expected, content)

    def _stub_bin_exists(self, path):
        return path == "/usr/local/bin/pttman" or os.path.lexists(path)

    @mock.patch.object(PTTMAN.subprocess, "run")
    @mock.patch("builtins.print")
    def test_install_openrc_creates_file_and_adds_runlevel(self, _print, run_mock):
        init_dir = os.path.join(self._tmpdir, "init.d")
        os.makedirs(init_dir)
        with mock.patch.object(PTTMAN, "OPENRC_SYSTEM_INIT_DIR", init_dir):
            with mock.patch.object(PTTMAN.os.path, "exists", side_effect=self._stub_bin_exists):
                PTTMAN.run_install_openrc_service()

        service_path = os.path.join(init_dir, "pttman")
        self.assertTrue(os.path.exists(service_path))
        self.assertTrue(os.access(service_path, os.X_OK))
        with open(service_path) as f:
            content = f.read()
        self.assertIn("openrc-run", content)

        run_mock.assert_called_once_with(
            ["rc-update", "add", "pttman", "default"],
            check=True,
        )

    @mock.patch.object(PTTMAN.subprocess, "run")
    @mock.patch("builtins.print")
    def test_install_openrc_is_idempotent(self, _print, run_mock):
        init_dir = os.path.join(self._tmpdir, "init.d")
        os.makedirs(init_dir)
        with mock.patch.object(PTTMAN, "OPENRC_SYSTEM_INIT_DIR", init_dir):
            with mock.patch.object(PTTMAN.os.path, "exists", side_effect=self._stub_bin_exists):
                PTTMAN.run_install_openrc_service()
                PTTMAN.run_install_openrc_service()

        service_path = os.path.join(init_dir, "pttman")
        self.assertTrue(os.path.exists(service_path))

    @mock.patch("builtins.print")
    def test_install_openrc_fails_if_binary_missing(self, _print):
        init_dir = os.path.join(self._tmpdir, "init.d")
        os.makedirs(init_dir)
        with mock.patch.object(PTTMAN, "OPENRC_SYSTEM_INIT_DIR", init_dir):
            with self.assertRaises(SystemExit):
                PTTMAN.run_install_openrc_service()

    @mock.patch.object(PTTMAN.subprocess, "run")
    @mock.patch("builtins.print")
    def test_uninstall_openrc_removes_file(self, _print, run_mock):
        init_dir = os.path.join(self._tmpdir, "init.d")
        os.makedirs(init_dir)
        service_path = os.path.join(init_dir, "pttman")
        with open(service_path, "w") as f:
            f.write("#!/sbin/openrc-run\n")

        with mock.patch.object(PTTMAN, "OPENRC_SYSTEM_INIT_DIR", init_dir):
            PTTMAN.run_uninstall_openrc_service()

        self.assertFalse(os.path.exists(service_path))
        self.assertEqual(
            [
                mock.call(["rc-service", "pttman", "stop"], check=False),
                mock.call(["rc-update", "del", "pttman", "default"], check=False),
            ],
            run_mock.call_args_list,
        )

    @mock.patch.object(PTTMAN.subprocess, "run")
    @mock.patch("builtins.print")
    def test_uninstall_openrc_handles_missing_file(self, _print, run_mock):
        init_dir = os.path.join(self._tmpdir, "init.d")
        os.makedirs(init_dir)
        with mock.patch.object(PTTMAN, "OPENRC_SYSTEM_INIT_DIR", init_dir):
            PTTMAN.run_uninstall_openrc_service()


class OpenRCUserServiceTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil

        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_get_openrc_user_source_returns_valid_init_script(self):
        content = PTTMAN.get_openrc_user_source()
        self.assertIn("#!/sbin/openrc-run", content)
        self.assertIn("command=", content)

    def test_get_openrc_user_source_matches_repo_file(self):
        content = PTTMAN.get_openrc_user_source()
        repo_path = ROOT / "openrc-user" / "pttman"
        with open(repo_path) as f:
            expected = f.read()
        self.assertEqual(expected, content)

    @mock.patch.object(PTTMAN.subprocess, "run")
    @mock.patch("builtins.print")
    def test_install_openrc_user_creates_file_and_adds_runlevel(self, _print, run_mock):
        init_dir = os.path.join(self._tmpdir, "rc", "init.d")
        with mock.patch.object(PTTMAN, "OPENRC_USER_INIT_DIR", init_dir):
            with mock.patch.dict(PTTMAN.os.environ, {"XDG_CONFIG_HOME": self._tmpdir}):
                PTTMAN.run_install_openrc_user_service()

        service_path = os.path.join(init_dir, "pttman")
        self.assertTrue(os.path.exists(service_path))
        self.assertTrue(os.access(service_path, os.X_OK))

        run_mock.assert_called_once_with(
            ["rc-update", "--user", "add", "pttman", "default"],
            check=True,
        )

    @mock.patch.object(PTTMAN.subprocess, "run")
    @mock.patch("builtins.print")
    def test_uninstall_openrc_user_removes_file(self, _print, run_mock):
        init_dir = os.path.join(self._tmpdir, "rc", "init.d")
        os.makedirs(init_dir)
        service_path = os.path.join(init_dir, "pttman")
        with open(service_path, "w") as f:
            f.write("#!/sbin/openrc-run\n")

        with mock.patch.object(PTTMAN, "OPENRC_USER_INIT_DIR", init_dir):
            PTTMAN.run_uninstall_openrc_user_service()

        self.assertFalse(os.path.exists(service_path))
        self.assertEqual(
            [
                mock.call(["rc-service", "--user", "pttman", "stop"], check=False),
                mock.call(["rc-update", "--user", "del", "pttman", "default"], check=False),
            ],
            run_mock.call_args_list,
        )

    @mock.patch.object(PTTMAN.subprocess, "run")
    @mock.patch("builtins.print")
    def test_uninstall_openrc_user_handles_missing_file(self, _print, run_mock):
        init_dir = os.path.join(self._tmpdir, "rc", "init.d")
        os.makedirs(init_dir)
        with mock.patch.object(PTTMAN, "OPENRC_USER_INIT_DIR", init_dir):
            PTTMAN.run_uninstall_openrc_user_service()


if __name__ == "__main__":
    unittest.main()
