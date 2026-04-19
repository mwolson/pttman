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

    def test_load_conf_reads_start_muted_true(self):
        with open(PTTMAN.CONF_PATH, "w") as f:
            f.write("--start-muted=true\n")
        self.assertEqual({"start_muted": True}, PTTMAN.load_conf())

    def test_load_conf_reads_start_muted_false(self):
        with open(PTTMAN.CONF_PATH, "w") as f:
            f.write("--start-muted=false\n")
        self.assertEqual({"start_muted": False}, PTTMAN.load_conf())

    def test_load_conf_rejects_start_muted_invalid_value(self):
        with open(PTTMAN.CONF_PATH, "w") as f:
            f.write("--start-muted=sometimes\n")
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

    def test_subcommand_press(self):
        with mock.patch("sys.argv", ["pttman", "press"]):
            args = PTTMAN.parse_args({})
        self.assertEqual("press", args.command)

    def test_subcommand_release(self):
        with mock.patch("sys.argv", ["pttman", "release"]):
            args = PTTMAN.parse_args({})
        self.assertEqual("release", args.command)

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

    def test_start_muted_defaults_to_true(self):
        with mock.patch("sys.argv", ["pttman"]):
            args = PTTMAN.parse_args({})
        self.assertTrue(args.start_muted)
        self.assertIsNone(args.cli_start_muted)

    def test_start_muted_cli_true(self):
        with mock.patch("sys.argv", ["pttman", "--start-muted"]):
            args = PTTMAN.parse_args({})
        self.assertTrue(args.start_muted)
        self.assertTrue(args.cli_start_muted)

    def test_start_muted_cli_false(self):
        with mock.patch("sys.argv", ["pttman", "--no-start-muted"]):
            args = PTTMAN.parse_args({})
        self.assertFalse(args.start_muted)
        self.assertFalse(args.cli_start_muted)

    def test_start_muted_conf_false(self):
        with mock.patch("sys.argv", ["pttman"]):
            args = PTTMAN.parse_args({"start_muted": False})
        self.assertFalse(args.start_muted)
        self.assertIsNone(args.cli_start_muted)

    def test_start_muted_cli_overrides_conf(self):
        with mock.patch("sys.argv", ["pttman", "--start-muted"]):
            args = PTTMAN.parse_args({"start_muted": False})
        self.assertTrue(args.start_muted)
        self.assertTrue(args.cli_start_muted)

    def test_subcommand_resync(self):
        with mock.patch("sys.argv", ["pttman", "resync"]):
            args = PTTMAN.parse_args({})
        self.assertEqual("resync", args.command)


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


class DecodeCommandTests(unittest.TestCase):
    def test_decode_command_accepts_mute(self):
        self.assertEqual("mute", PTTMAN.decode_command(b"mute"))

    def test_decode_command_accepts_press(self):
        self.assertEqual("press", PTTMAN.decode_command(b"press"))

    def test_decode_command_accepts_release(self):
        self.assertEqual("release", PTTMAN.decode_command(b"release"))

    def test_decode_command_accepts_reload(self):
        self.assertEqual("reload", PTTMAN.decode_command(b"reload"))

    def test_decode_command_accepts_resync(self):
        self.assertEqual("resync", PTTMAN.decode_command(b"resync"))

    def test_decode_command_accepts_toggle(self):
        self.assertEqual("toggle", PTTMAN.decode_command(b"toggle"))

    def test_decode_command_accepts_unmute(self):
        self.assertEqual("unmute", PTTMAN.decode_command(b"unmute"))

    def test_decode_command_rejects_unknown(self):
        with self.assertRaises(ValueError):
            PTTMAN.decode_command(b"bogus")


class RunActionWithStateTests(unittest.TestCase):
    def _state(self, **overrides):
        state = {
            "default_mute": True,
            "last_applied_mute": {},
            "per_source_desired": {},
            "sources": ["src1"],
        }
        state.update(overrides)
        return state

    @mock.patch.object(PTTMAN, "set_mute")
    def test_mute_records_preference(self, set_mute_mock):
        state = self._state()
        PTTMAN.run_action_with_state("mute", state)
        set_mute_mock.assert_called_once_with(["src1"], True)
        self.assertEqual({"src1": True}, state["per_source_desired"])
        self.assertEqual({"src1": True}, state["last_applied_mute"])

    @mock.patch.object(PTTMAN, "set_mute")
    def test_unmute_records_preference(self, set_mute_mock):
        state = self._state(
            sources=["src1", "src2"],
            per_source_desired={"src1": True, "src2": True},
        )
        PTTMAN.run_action_with_state("unmute", state)
        set_mute_mock.assert_called_once_with(["src1", "src2"], False)
        self.assertEqual({"src1": False, "src2": False}, state["per_source_desired"])
        self.assertEqual({"src1": False, "src2": False}, state["last_applied_mute"])

    @mock.patch.object(PTTMAN, "set_mute")
    def test_press_does_not_record_preference(self, set_mute_mock):
        state = self._state(per_source_desired={"src1": True})
        PTTMAN.run_action_with_state("press", state)
        set_mute_mock.assert_called_once_with(["src1"], False)
        self.assertEqual({"src1": True}, state["per_source_desired"])
        self.assertEqual({"src1": False}, state["last_applied_mute"])

    @mock.patch.object(PTTMAN, "set_mute")
    def test_release_does_not_record_preference(self, set_mute_mock):
        state = self._state(per_source_desired={"src1": False})
        PTTMAN.run_action_with_state("release", state)
        set_mute_mock.assert_called_once_with(["src1"], True)
        self.assertEqual({"src1": False}, state["per_source_desired"])
        self.assertEqual({"src1": True}, state["last_applied_mute"])

    @mock.patch.object(PTTMAN, "set_mute")
    def test_toggle_mutes_all_when_any_effectively_unmuted(self, set_mute_mock):
        state = self._state(
            sources=["src1", "src2"],
            per_source_desired={"src1": True, "src2": False},
        )
        PTTMAN.run_action_with_state("toggle", state)
        set_mute_mock.assert_called_once_with(["src1", "src2"], True)
        self.assertEqual({"src1": True, "src2": True}, state["per_source_desired"])

    @mock.patch.object(PTTMAN, "set_mute")
    def test_toggle_unmutes_all_when_all_effectively_muted(self, set_mute_mock):
        state = self._state(
            sources=["src1", "src2"],
            per_source_desired={"src1": True, "src2": True},
        )
        PTTMAN.run_action_with_state("toggle", state)
        set_mute_mock.assert_called_once_with(["src1", "src2"], False)
        self.assertEqual({"src1": False, "src2": False}, state["per_source_desired"])

    @mock.patch.object(PTTMAN, "set_mute")
    def test_toggle_uses_default_mute_for_untracked_sources(self, set_mute_mock):
        state = self._state(
            default_mute=False,
            sources=["src1", "src2"],
            per_source_desired={},
        )
        PTTMAN.run_action_with_state("toggle", state)
        set_mute_mock.assert_called_once_with(["src1", "src2"], True)
        self.assertEqual({"src1": True, "src2": True}, state["per_source_desired"])

    @mock.patch.object(PTTMAN, "reapply_desired_state")
    def test_resync_calls_reapply(self, reapply_mock):
        state = self._state()
        PTTMAN.run_action_with_state("resync", state)
        reapply_mock.assert_called_once_with(state)

    def test_unknown_action_raises(self):
        state = self._state()
        with self.assertRaises(ValueError):
            PTTMAN.run_action_with_state("bogus", state)


class EffectiveDesiredTests(unittest.TestCase):
    def test_returns_override_when_present(self):
        state = {"default_mute": True, "per_source_desired": {"src1": False}}
        self.assertFalse(PTTMAN.effective_desired(state, "src1"))

    def test_falls_back_to_default_mute_true(self):
        state = {"default_mute": True, "per_source_desired": {}}
        self.assertTrue(PTTMAN.effective_desired(state, "src1"))

    def test_falls_back_to_default_mute_false(self):
        state = {"default_mute": False, "per_source_desired": {}}
        self.assertFalse(PTTMAN.effective_desired(state, "src1"))

    def test_per_source_override_wins_over_default(self):
        state = {"default_mute": True, "per_source_desired": {"src1": False}}
        self.assertFalse(PTTMAN.effective_desired(state, "src1"))
        self.assertTrue(PTTMAN.effective_desired(state, "src2"))


class ApplyMuteTests(unittest.TestCase):
    @mock.patch.object(PTTMAN, "set_mute")
    def test_records_last_applied(self, set_mute_mock):
        state = {"last_applied_mute": {}}
        PTTMAN.apply_mute(state, ["src1", "src2"], True)
        set_mute_mock.assert_called_once_with(["src1", "src2"], True)
        self.assertEqual({"src1": True, "src2": True}, state["last_applied_mute"])

    @mock.patch.object(PTTMAN, "set_mute")
    def test_noop_when_no_sources(self, set_mute_mock):
        state = {"last_applied_mute": {}}
        PTTMAN.apply_mute(state, [], True)
        set_mute_mock.assert_not_called()
        self.assertEqual({}, state["last_applied_mute"])

    @mock.patch.object(PTTMAN, "set_mute")
    def test_initializes_last_applied_when_missing(self, set_mute_mock):
        state = {}
        PTTMAN.apply_mute(state, ["src1"], False)
        self.assertEqual({"src1": False}, state["last_applied_mute"])


class ReapplyDesiredStateTests(unittest.TestCase):
    @mock.patch("builtins.print")
    @mock.patch.object(PTTMAN, "set_mute")
    def test_noop_when_no_sources(self, set_mute_mock, _print):
        state = {"default_mute": True, "last_applied_mute": {}, "per_source_desired": {}, "sources": []}
        PTTMAN.reapply_desired_state(state)
        set_mute_mock.assert_not_called()

    @mock.patch("builtins.print")
    @mock.patch.object(PTTMAN, "set_mute")
    def test_applies_default_mute_when_no_overrides(self, set_mute_mock, _print):
        state = {
            "default_mute": True,
            "last_applied_mute": {},
            "per_source_desired": {},
            "sources": ["src1"],
        }
        PTTMAN.reapply_desired_state(state)
        set_mute_mock.assert_called_once_with(["src1"], True)
        self.assertEqual({"src1": True}, state["last_applied_mute"])

    @mock.patch("builtins.print")
    @mock.patch.object(PTTMAN, "set_mute")
    def test_applies_default_unmuted_when_no_overrides(self, set_mute_mock, _print):
        state = {
            "default_mute": False,
            "last_applied_mute": {},
            "per_source_desired": {},
            "sources": ["src1"],
        }
        PTTMAN.reapply_desired_state(state)
        set_mute_mock.assert_called_once_with(["src1"], False)
        self.assertEqual({"src1": False}, state["last_applied_mute"])

    @mock.patch("builtins.print")
    @mock.patch.object(PTTMAN, "set_mute")
    def test_mixes_overrides_with_default(self, set_mute_mock, _print):
        state = {
            "default_mute": True,
            "last_applied_mute": {},
            "per_source_desired": {"src1": False},
            "sources": ["src1", "src2"],
        }
        PTTMAN.reapply_desired_state(state)
        self.assertIn(mock.call(["src1"], False), set_mute_mock.call_args_list)
        self.assertIn(mock.call(["src2"], True), set_mute_mock.call_args_list)
        self.assertEqual({"src1": False, "src2": True}, state["last_applied_mute"])

    @mock.patch("builtins.print")
    @mock.patch.object(PTTMAN, "set_mute", side_effect=PTTMAN.subprocess.CalledProcessError(1, ["pactl"]))
    def test_swallows_called_process_error(self, _set_mute, _print):
        state = {
            "default_mute": True,
            "last_applied_mute": {},
            "per_source_desired": {},
            "sources": ["src1"],
        }
        PTTMAN.reapply_desired_state(state)


class RevertExternalChangeTests(unittest.TestCase):
    @mock.patch.object(PTTMAN, "get_mute_state", return_value="muted")
    def test_no_sources_noop(self, get_mute_mock):
        state = {
            "default_mute": True,
            "last_applied_mute": {},
            "per_source_desired": {},
            "sources": [],
        }
        PTTMAN.revert_external_change(state)
        get_mute_mock.assert_not_called()

    @mock.patch.object(PTTMAN, "set_mute")
    @mock.patch.object(PTTMAN, "get_mute_state", return_value="unknown")
    def test_unknown_actual_noop(self, _get_mute, set_mute_mock):
        state = {
            "default_mute": True,
            "last_applied_mute": {"src1": True},
            "per_source_desired": {},
            "sources": ["src1"],
        }
        PTTMAN.revert_external_change(state)
        set_mute_mock.assert_not_called()
        self.assertEqual({"src1": True}, state["last_applied_mute"])

    @mock.patch("builtins.print")
    @mock.patch.object(PTTMAN, "set_mute")
    @mock.patch.object(PTTMAN, "get_mute_state", return_value="muted")
    def test_match_noop(self, _get_mute, set_mute_mock, mock_print):
        state = {
            "default_mute": True,
            "last_applied_mute": {"src1": True},
            "per_source_desired": {},
            "sources": ["src1"],
        }
        PTTMAN.revert_external_change(state)
        set_mute_mock.assert_not_called()
        self.assertEqual({"src1": True}, state["last_applied_mute"])
        mock_print.assert_not_called()

    @mock.patch("builtins.print")
    @mock.patch.object(PTTMAN, "set_mute")
    @mock.patch.object(PTTMAN, "get_mute_state", return_value="unmuted")
    def test_drift_reverts_without_touching_preference(self, _get_mute, set_mute_mock, mock_print):
        state = {
            "default_mute": True,
            "last_applied_mute": {"src1": True},
            "per_source_desired": {"src1": True},
            "sources": ["src1"],
        }
        PTTMAN.revert_external_change(state)
        set_mute_mock.assert_called_once_with(["src1"], True)
        self.assertEqual({"src1": True}, state["last_applied_mute"])
        self.assertEqual({"src1": True}, state["per_source_desired"])
        mock_print.assert_called()

    @mock.patch("builtins.print")
    @mock.patch.object(PTTMAN, "set_mute")
    @mock.patch.object(PTTMAN, "get_mute_state", return_value="unmuted")
    def test_no_last_applied_noop(self, _get_mute, set_mute_mock, mock_print):
        state = {
            "default_mute": True,
            "last_applied_mute": {},
            "per_source_desired": {},
            "sources": ["src1"],
        }
        PTTMAN.revert_external_change(state)
        set_mute_mock.assert_not_called()
        self.assertEqual({}, state["last_applied_mute"])
        mock_print.assert_not_called()

    @mock.patch("builtins.print")
    def test_drift_on_non_first_source_is_reverted(self, _print):
        state = {
            "default_mute": True,
            "last_applied_mute": {"src1": True, "src2": True},
            "per_source_desired": {},
            "sources": ["src1", "src2"],
        }
        actuals = {"src1": "muted", "src2": "unmuted"}
        with mock.patch.object(PTTMAN, "get_mute_state", side_effect=lambda s: actuals[s]), \
                mock.patch.object(PTTMAN, "set_mute") as set_mute_mock:
            PTTMAN.revert_external_change(state)
        set_mute_mock.assert_called_once_with(["src2"], True)
        self.assertEqual({"src1": True, "src2": True}, state["last_applied_mute"])

    @mock.patch("builtins.print")
    def test_iterates_all_sources(self, _print):
        state = {
            "default_mute": True,
            "last_applied_mute": {"src1": True, "src2": False, "src3": True},
            "per_source_desired": {},
            "sources": ["src1", "src2", "src3"],
        }
        actuals = {"src1": "muted", "src2": "muted", "src3": "unmuted"}
        with mock.patch.object(PTTMAN, "get_mute_state", side_effect=lambda s: actuals[s]), \
                mock.patch.object(PTTMAN, "set_mute") as set_mute_mock:
            PTTMAN.revert_external_change(state)
        self.assertEqual(
            [mock.call(["src2"], False), mock.call(["src3"], True)],
            set_mute_mock.call_args_list,
        )
        self.assertEqual(
            {"src1": True, "src2": False, "src3": True},
            state["last_applied_mute"],
        )

    @mock.patch("builtins.print")
    @mock.patch.object(PTTMAN, "get_mute_state", return_value="muted")
    def test_drift_during_press_reverts_to_unmuted(self, _get_mute, mock_print):
        state = {
            "default_mute": True,
            "last_applied_mute": {"src1": False},
            "per_source_desired": {"src1": True},
            "sources": ["src1"],
        }
        with mock.patch.object(PTTMAN, "set_mute") as set_mute_mock:
            PTTMAN.revert_external_change(state)
        set_mute_mock.assert_called_once_with(["src1"], False)
        self.assertEqual({"src1": False}, state["last_applied_mute"])
        self.assertEqual({"src1": True}, state["per_source_desired"])

    @mock.patch("builtins.print")
    @mock.patch.object(
        PTTMAN,
        "set_mute",
        side_effect=PTTMAN.subprocess.CalledProcessError(1, ["pactl"]),
    )
    @mock.patch.object(PTTMAN, "get_mute_state", return_value="unmuted")
    def test_revert_failure_accepts_actual_and_continues(self, _get_mute, _set_mute, _print):
        state = {
            "default_mute": True,
            "last_applied_mute": {"src1": True, "src2": True},
            "per_source_desired": {"src1": True, "src2": True},
            "sources": ["src1", "src2"],
        }
        PTTMAN.revert_external_change(state)
        self.assertEqual({"src1": False, "src2": False}, state["last_applied_mute"])
        self.assertEqual({"src1": True, "src2": True}, state["per_source_desired"])


class ApplyRevertConcurrencyTests(unittest.TestCase):
    @mock.patch("builtins.print")
    def test_revert_during_apply_does_not_race(self, _print):
        """Watcher firing a change event mid-apply_mute must not undo it.

        Simulates the thread-interleaved case: apply_mute holds the lock inside
        set_mute (we pause it there via an event), then revert_external_change
        runs on a separate thread as if the watcher just saw pactl's change
        event for our own write. The revert thread must block until apply_mute
        releases the lock, and once it runs, last_applied is already correct
        so no redundant set_mute happens.
        """
        state = {
            "default_mute": True,
            "last_applied_mute": {"src1": True},
            "per_source_desired": {"src1": True},
            "sources": ["src1"],
        }

        set_mute_calls = []
        apply_in_set_mute = threading.Event()
        apply_can_proceed = threading.Event()

        def fake_set_mute(sources, mute):
            set_mute_calls.append((tuple(sources), mute))
            if len(set_mute_calls) == 1:
                apply_in_set_mute.set()
                apply_can_proceed.wait(timeout=2)

        # pactl reports the new state that apply_mute is in the middle of
        # applying -- this is the point of maximum race risk.
        def fake_get_mute(_source):
            return "unmuted"

        with mock.patch.object(PTTMAN, "set_mute", side_effect=fake_set_mute), \
                mock.patch.object(PTTMAN, "get_mute_state", side_effect=fake_get_mute):
            apply_thread = threading.Thread(
                target=PTTMAN.apply_mute,
                args=(state, ["src1"], False),
            )
            revert_thread = threading.Thread(
                target=PTTMAN.revert_external_change,
                args=(state,),
            )

            apply_thread.start()
            self.assertTrue(apply_in_set_mute.wait(timeout=1))

            revert_thread.start()
            # Give revert_thread a chance to try to grab the lock.
            revert_thread.join(timeout=0.1)
            # It must still be alive, blocked on state['lock'].
            self.assertTrue(revert_thread.is_alive())

            apply_can_proceed.set()
            apply_thread.join(timeout=1)
            revert_thread.join(timeout=1)
            self.assertFalse(apply_thread.is_alive())
            self.assertFalse(revert_thread.is_alive())

        # Exactly one set_mute call: the one from apply_mute. If the race were
        # live, revert would have seen last_applied=True, actual=unmuted, and
        # fired set_mute(["src1"], True) as a spurious "revert".
        self.assertEqual(1, len(set_mute_calls))
        self.assertEqual((("src1",), False), set_mute_calls[0])
        self.assertEqual({"src1": False}, state["last_applied_mute"])
        self.assertEqual({"src1": True}, state["per_source_desired"])


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
