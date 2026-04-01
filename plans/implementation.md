# pttman (push-to-talk-manager) -- Implementation Plan

## Background

The existing `~/dotfiles/bin/push-to-talk` script is invoked by xremap on every
F5 press and release. Rapid clicking spawns multiple concurrent processes that
all inspect `wpctl status` and interleave `wpctl set-mute` calls, which leaves
microphone state inconsistent.

The fix is a daemon + client architecture. The daemon serializes all mute/unmute
operations in one process, and the client becomes a fire-and-forget Unix
datagram send.

## Architecture

```text
xremap (F5 press)   --> pttman --unmute --> sendto(sock, "unmute") --> daemon
xremap (F5 release) --> pttman --mute   --> sendto(sock, "mute")   --> daemon
niri (Ctrl+\)       --> pttman --toggle --> sendto(sock, "toggle") --> daemon
```

- Client: sends one datagram to `$XDG_RUNTIME_DIR/pttman.sock` and exits.
- Daemon: binds a Unix datagram socket and processes commands in a single loop.
- Coalescing: when the daemon wakes up, it drains any queued datagrams and the
  last command wins.
- Status: `pttman --status` queries `wpctl` directly.

## Repo structure

```text
pttman/
  pttman
  install.sh
  systemd/
    pttman.service
  plans/
    implementation.md
  README.md
```

## CLI

```text
pttman --daemon
pttman --mute
pttman --unmute
pttman --toggle
pttman --status
```

Aliases to keep:

- `--release` for `--mute`
- `--press` and `--talk` for `--unmute`

## Dotfiles integration

1. Add `pttman` as a submodule at `utils/pttman`.
2. Update `scripts/sync` to install and restart `pttman.service` when the
   submodule contents differ from the installed files.
3. Update Niri autostart to restart `pttman.service`.
4. Update xremap to call `/home/mwolson/.local/bin/pttman`.
5. Update the Niri toggle keybind to call `/home/mwolson/.local/bin/pttman`.
6. Remove the old `bin/push-to-talk` wrapper once the service is in place.

## Testing checklist

- [ ] `pttman --daemon` starts and binds the socket
- [ ] `pttman --mute` and `pttman --unmute` change mic state
- [ ] `pttman --toggle` works
- [ ] `pttman --status` prints source states
- [ ] Rapid F5 clicking does not pile up processes
- [ ] The final release event mutes reliably
- [ ] Client falls back to direct execution if the daemon is not running
- [ ] Socket cleanup works on daemon exit
