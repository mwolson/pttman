# pttman

Push-to-talk microphone control for PipeWire.

`pttman` runs a small user service that serializes mute, unmute, and toggle
requests over a Unix datagram socket so rapid key presses do not race each
other.

## Requirements

- PipeWire with PulseAudio compatibility (`pipewire-pulse`)
- `pactl` (from `pipewire-pulse` or `pulseaudio-utils`)
- `systemctl` (for `set-default-source` to signal the daemon)

## Installation

### Recommended: uv

```bash
uv tool install pttman
pttman install-service
systemctl --user start pttman.service
```

This installs `pttman` to `~/.local/bin/`, copies the systemd user service into
place, and enables it. After installing, point your push-to-talk key at the
client binary.

### Alternative: install.sh

```bash
git clone https://github.com/mwolson/pttman.git
cd pttman
./install.sh
systemctl --user start pttman.service
```

This copies `pttman` to `~/.local/bin/` and installs and enables the user
service.

### Optional: set defaults

By default, pttman operates on all audio sources. You can optionally save a
preferred source so that pttman controls only that one:

```bash
pttman list-sources
pttman set-default-source alsa_input.usb-046d_BRIO-03.pro-input-0
```

This writes to `~/.config/pttman.conf` and signals the running daemon to pick up
the change.

### xremap

On Arch Linux, install the xremap variant that matches your desktop environment
(only one should be installed):

```bash
paru -S xremap-gnome-bin     # GNOME
paru -S xremap-hyprland-bin  # Hyprland
paru -S xremap-kde-bin       # KDE Plasma
paru -S xremap-niri-bin      # Niri
paru -S xremap-wlroots-bin   # wlroots-based compositors (sway, etc.)
```

Then configure a push-to-talk key binding:

```yaml
modmap:
  - name: Push-to-talk
    remap:
      F6:
        skip_key_event: true
        press: { launch: ["/home/your-user/.local/bin/pttman", "unmute"] }
        release: { launch: ["/home/your-user/.local/bin/pttman", "mute"] }
```

Pressing F6 (as configured above, which is conveniently labeled with a mic icon
on some laptop keyboards) tells the daemon to unmute. Releasing F6 tells it to
mute again.

You can also route your compositor's mic-mute key through pttman. For example,
in niri's `keybinds.kdl` this implements mic toggle (rather than push-to-talk):

```kdl
XF86AudioMicMute  allow-when-locked=true { spawn "/home/your-user/.local/bin/pttman" "toggle"; }
```

You can check the current microphone state with:

```bash
pttman status
```

### Corsair mice on Arch Linux

If you use a Corsair mouse and want one of its extra buttons to behave like F6,
`ckb-next` is a straightforward way to do it.

On Arch Linux, install `ckb-next` with:

```bash
sudo pacman -S ckb-next
```

Then launch `ckb-next`, select your mouse, pick the button you want to use for
push-to-talk, and remap that button to `F6`.

After that, xremap can keep using the F6 rule above, and your Corsair mouse
button will trigger push-to-talk through `pttman`.

If you specifically want the upstream development build instead of the packaged
release, the `ckb-next` project wiki also lists `ckb-next-git` for Arch-based
systems.

## Commands

pttman uses subcommands for one-off operations. With no subcommand, it runs the
daemon.

```text
pttman                                 Run the daemon (default)
pttman get-default-source              Print the default source from the config file
pttman install-service                 Install and enable the systemd user service
pttman list-sources                    List available audio sources
pttman mute                            Mute the microphone
pttman set-default-source SOURCE       Save default source and signal the daemon
pttman status                          Print the current microphone state
pttman toggle                          Toggle the microphone mute state
pttman uninstall-service               Disable and remove the systemd user service
pttman unmute                          Unmute the microphone
```

Aliases:

- `release` for `mute`
- `press` and `talk` for `unmute`

### Options

These flags apply to the daemon and to action commands (`mute`, `unmute`,
`toggle`, `status`):

```text
--source SOURCE     Audio source name to control (default: config file, then all sources)
--all-sources       Operate on all audio sources (overrides --source from config)
```

`--source` and `--all-sources` are mutually exclusive.

## Configuration File

`pttman` reads defaults from `~/.config/pttman.conf` (or
`$XDG_CONFIG_HOME/pttman.conf`). The file uses one flag per line:

```text
--source=alsa_input.usb-046d_BRIO-03.pro-input-0
```

Supported flags:

- `--source=NAME` -- control only this source
- `--all-sources=true` -- control all sources (the default when no config file
  exists)

These are mutually exclusive. Unrecognized flags cause an error at startup.
Command-line arguments always take precedence over the config file.

When the daemon receives a SIGHUP (sent automatically by `set-default-source`,
or manually via `systemctl --user reload pttman.service`), it reloads the config
file and updates the source for future operations.

## Service

```bash
systemctl --user start pttman.service
systemctl --user status pttman.service
journalctl --user -u pttman.service -f
```

The daemon listens on `$XDG_RUNTIME_DIR/pttman.sock`. If the daemon is not
running, client commands fall back to direct `pactl` execution.

## Development

### Testing

```bash
python3 -m unittest discover -s tests -v
```

### Hooks

```bash
lefthook install
lefthook run pre-commit --all-files
```

The pre-commit hook runs `uvx ruff check`, `uvx ty check`, and the unit test
suite.

## License

MIT
