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
xremap (key press)      --> pttman press   --> sendto(sock, "press")   --> daemon
xremap (key release)    --> pttman release --> sendto(sock, "release") --> daemon
niri (XF86AudioMicMute) --> pttman toggle  --> sendto(sock, "toggle")  --> daemon
```

- Client: sends one datagram to `$XDG_RUNTIME_DIR/pttman.sock` and exits.
- Daemon: binds a Unix datagram socket and processes commands in a single loop.
- Coalescing: when the daemon wakes up, it drains any queued datagrams and the
  last command wins.
- Status: `pttman status` queries `pactl` directly.

## Repo structure

```text
pttman/
  pttman/
    __init__.py
    pttman.py
  install.sh
  integration-tests/
  openrc-system/
    pttman
  openrc-user/
    pttman
  plans/
    implementation.md
    mute-state-tracking.md
  systemd/
    pttman.service
  tests/
    test_pttman.py
  pyproject.toml
  README.md
```

## CLI

The daemon runs when `pttman` is invoked with no subcommand. Action subcommands:

```text
pttman mute / unmute / toggle    # change state and record the preference
pttman press / release           # temporary push-to-talk, preference unchanged
pttman resync                    # reapply the recorded preference
pttman status / list-sources     # read-only inspection
pttman install-service           # install and enable the user service
pttman uninstall-service         # disable and remove the user service
pttman get-default-source        # print the default source from the config file
pttman set-default-source SOURCE # save default source and signal the daemon
```

`press` and `release` are distinct wire actions, not aliases for
`unmute`/`mute`: the daemon applies the same mute bits but skips
`per_source_desired` updates. See `plans/mute-state-tracking.md`.

## Dotfiles integration

1. Add `pttman` as a submodule at `utils/pttman`.
2. Update `scripts/sync` to install and restart `pttman.service` when the
   submodule contents differ from the installed files.
3. Update Niri autostart to restart `pttman.service`.
4. Update xremap to call `/home/mwolson/.local/bin/pttman`.
5. Update the Niri toggle keybind to call `/home/mwolson/.local/bin/pttman`.
6. Remove the old `bin/push-to-talk` wrapper once the service is in place.

## Testing

Unit tests in `tests/test_pttman.py` cover arg parsing, action dispatch, source
watching, socket send/coalesce, and service install/uninstall. Integration tests
under `integration-tests/` exercise the systemd and OpenRC service files
end-to-end in Docker containers. See the README's "Development" section for how
to run them (`bun run test`, `bun run test:integration`, `bun run test:all`).
