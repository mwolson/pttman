# pttman

Push-to-talk microphone control for PipeWire and WirePlumber.

`pttman` runs a small user service that serializes mute, unmute, and toggle
requests over a Unix datagram socket so rapid key presses do not race each
other.

## Commands

```text
pttman --daemon
pttman --mute
pttman --unmute
pttman --toggle
pttman --status
```

Aliases:

- `--release` for `--mute`
- `--press` and `--talk` for `--unmute`

## Installation

```bash
git clone https://github.com/mwolson/pttman.git
cd pttman
./install.sh
```

## Service

```bash
systemctl --user start pttman.service
systemctl --user status pttman.service
journalctl --user -u pttman.service -f
```

The daemon listens on `$XDG_RUNTIME_DIR/pttman.sock`. If the daemon is not
running, client commands fall back to direct `wpctl` execution.

## Testing

```bash
python3 -m unittest discover -s tests -v
```

## Hooks

```bash
lefthook install
lefthook run pre-commit --all-files
```

The pre-commit hook runs `uvx ruff check`, `uvx ty check`, and the unit test
suite.
