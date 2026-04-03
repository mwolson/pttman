import importlib.machinery
import importlib.util
import pathlib
import tempfile
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]


def load_module():
    loader = importlib.machinery.SourceFileLoader("pttman_module", str(ROOT / "pttman.py"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    if spec is None:
        raise RuntimeError("Failed to create import spec for pttman")
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


PTTMAN = load_module()

WPCTL_STATUS = """Audio
 ├─ Devices:
 │      42. Some Device
 ├─ Sources:
 │  *   45. BRIO
 │      47. Headset Mic
 └─ Streams:
Video
"""


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


class PttmanTests(unittest.TestCase):
    @mock.patch.object(PTTMAN.subprocess, "check_output", return_value=WPCTL_STATUS)
    def test_get_audio_source_ids_parses_sources_and_adds_default(self, _check_output):
        self.assertEqual(["45", "47", "@DEFAULT_AUDIO_SOURCE@"], PTTMAN.get_audio_source_ids())

    @mock.patch("builtins.print")
    def test_coalesce_commands_last_valid_command_wins(self, _print):
        fake_socket = FakeSocket([b"bogus", b"unmute", b"mute"])

        effective = PTTMAN.coalesce_commands(fake_socket, "toggle")

        self.assertEqual("mute", effective)
        self.assertEqual([False, True], fake_socket.blocking_values)

    @mock.patch.object(PTTMAN, "run_action")
    @mock.patch.object(PTTMAN, "send_action", side_effect=OSError("missing socket"))
    @mock.patch("builtins.print")
    def test_send_or_run_action_falls_back_to_direct_execution(self, _print, _send_action, run_action):
        PTTMAN.send_or_run_action("toggle")

        run_action.assert_called_once_with("toggle")

    def test_parse_args_no_subcommand_is_daemon(self):
        with mock.patch("sys.argv", ["pttman"]):
            args = PTTMAN.parse_args()
        self.assertIsNone(args.command)

    def test_parse_args_subcommand_mute(self):
        with mock.patch("sys.argv", ["pttman", "mute"]):
            args = PTTMAN.parse_args()
        self.assertEqual("mute", args.command)

    def test_parse_args_subcommand_status(self):
        with mock.patch("sys.argv", ["pttman", "status"]):
            args = PTTMAN.parse_args()
        self.assertEqual("status", args.command)

    def test_parse_args_subcommand_unmute(self):
        with mock.patch("sys.argv", ["pttman", "unmute"]):
            args = PTTMAN.parse_args()
        self.assertEqual("unmute", args.command)

    def test_parse_args_alias_release_maps_to_mute(self):
        with mock.patch("sys.argv", ["pttman", "release"]):
            args = PTTMAN.parse_args()
        self.assertEqual("release", args.command)
        self.assertEqual("mute", PTTMAN.COMMAND_ALIASES.get(args.command, args.command))

    def test_parse_args_alias_press_maps_to_unmute(self):
        with mock.patch("sys.argv", ["pttman", "press"]):
            args = PTTMAN.parse_args()
        self.assertEqual("press", args.command)
        self.assertEqual("unmute", PTTMAN.COMMAND_ALIASES.get(args.command, args.command))

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


if __name__ == "__main__":
    unittest.main()
