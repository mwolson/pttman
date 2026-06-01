# pttman

Reliable push-to-talk and mic-mute for PipeWire.

`pttman` is a small user service that keeps microphone mute state predictable:

- Rapid mute, unmute, and toggle key presses are serialized through a Unix
  datagram socket, so quick press-release cycles cannot race into the wrong
  state.
- The intended mute state is reapplied after PipeWire source changes.
- Accidental unmutes from other tools are reverted quickly.

This is the Rust implementation. The previous Python implementation lives at
https://github.com/mwolson/pttman-py.

## Requirements

- PipeWire with PulseAudio compatibility or PulseAudio
- `pactl`
- One of: systemd or OpenRC

## Installation

### cargo

```bash
cargo install pttman
pttman install-service
```

Start the service:

```bash
systemctl --user start pttman.service          # systemd
rc-service --user pttman start                 # OpenRC 0.60+
sudo rc-service pttman start                   # older OpenRC
```

### Prebuilt binary

Download the tarball for your platform from the
[GitHub releases page](https://github.com/mwolson/pttman/releases), extract it,
and move `pttman` to `~/.local/bin/` or `/usr/local/bin/`. Then run:

```bash
pttman install-service
```

### install.sh (systemd, source build)

```bash
git clone https://github.com/mwolson/pttman.git
cd pttman
./install.sh
systemctl --user start pttman.service
```

`install.sh` runs `cargo build --release`, copies the binary to
`~/.local/bin/`, and calls `pttman install-service`.

## Commands

```text
pttman                                 Run the daemon (default)
pttman get-default-source              Print the default source from the config file
pttman install-service                 Install and enable the service (systemd or OpenRC)
pttman list-sources                    List available audio sources
pttman mute                            Mute the microphone and record it as the preference
pttman press                           Temporarily unmute (push-to-talk, does not change preference)
pttman release                         Temporarily mute (push-to-talk, does not change preference)
pttman resync                          Ask the daemon to reapply its desired mute state
pttman set-default-source SOURCE       Save default source and signal the daemon
pttman status                          Print the current microphone state
pttman toggle                          Toggle the microphone mute state and record the new state as the preference
pttman uninstall-service               Disable and remove the service (systemd or OpenRC)
pttman unmute                          Unmute the microphone and record it as the preference
```

### Options

These flags apply to the daemon and action commands:

```text
--source SOURCE     Audio source name to control (default: config file, then all sources)
--all-sources       Operate on all audio sources (overrides --source from config)
--start-muted       Mute managed sources when the daemon starts (default: true)
--no-start-muted    Leave mic state untouched when the daemon starts
```

## Configuration File

`pttman` reads defaults from `~/.config/pttman.conf` or
`$XDG_CONFIG_HOME/pttman.conf`. The file uses one flag per line:

```text
--source=alsa_input.usb-046d_BRIO-03.pro-input-0
--ptt-hold-timeout=2m
```

Supported flags:

- `--source=NAME` controls only this source
- `--all-sources=true` controls all sources
- `--ptt-hold-timeout=off|DURATION` sets the maximum time a `press` command may
  keep the mic unmuted before the daemon mutes it. It defaults to `off`.
  Durations accept `ms`, `s`, `m`, and `h` suffixes. Bare numbers are seconds.
- `--start-muted=true|false` controls whether the daemon mutes managed sources
  at startup

`--source` and `--all-sources=true` are mutually exclusive. Command-line
arguments always take precedence over the config file.

## Push-to-talk bindings

Use `pttman press` on key down and `pttman release` on key up:

```yaml
F5:
  skip_key_event: true
  press: { launch: ["pttman", "press"] }
  release: { launch: ["pttman", "release"] }
```

For missed key-up events, add a timeout such as `--ptt-hold-timeout=2m` to the
config file.

## Development

```bash
bun run test
bun run hooks:check
```

## License

MIT
