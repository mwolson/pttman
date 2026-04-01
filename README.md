# pttman

Push-to-talk microphone control for PipeWire and WirePlumber.

`pttman` runs a small user service that serializes mute, unmute, and toggle
requests over a Unix datagram socket so rapid key presses do not race each
other.

## Installation

### Recommended: uv

```bash
uv tool install git+https://github.com/mwolson/pttman
```

This installs `pttman` to `~/.local/bin/`.

Then install and start the systemd service:

```bash
git clone https://github.com/mwolson/pttman.git
cd pttman
mkdir -p ~/.config/systemd/user
cp systemd/pttman.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now pttman.service
```

### Alternative: install.sh

```bash
git clone https://github.com/mwolson/pttman.git
cd pttman
./install.sh
systemctl --user start pttman.service
```

This copies `pttman` to `~/.local/bin/` and installs and enables the user
service.

After installing, point your push-to-talk key at the client binary.

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
      F5:
        skip_key_event: true
        press: { launch: ["/home/your-user/.local/bin/pttman", "--unmute"] }
        release: { launch: ["/home/your-user/.local/bin/pttman", "--mute"] }
```

Pressing F5 tells the daemon to unmute. Releasing F5 tells it to mute again.

You can check the current microphone state with:

```bash
pttman --status
```

### Corsair mice on Arch Linux

If you use a Corsair mouse and want one of its extra buttons to behave like F5,
`ckb-next` is a straightforward way to do it.

On Arch Linux, install `ckb-next` with:

```bash
sudo pacman -S ckb-next
```

Then launch `ckb-next`, select your mouse, pick the button you want to use for
push-to-talk, and remap that button to `F5`.

After that, xremap can keep using the F5 rule above, and your Corsair mouse
button will trigger push-to-talk through `pttman`.

If you specifically want the upstream development build instead of the packaged
release, the `ckb-next` project wiki also lists `ckb-next-git` for Arch-based
systems.

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

## Service

```bash
systemctl --user start pttman.service
systemctl --user status pttman.service
journalctl --user -u pttman.service -f
```

The daemon listens on `$XDG_RUNTIME_DIR/pttman.sock`. If the daemon is not
running, client commands fall back to direct `wpctl` execution.

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
