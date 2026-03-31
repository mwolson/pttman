# Agent Instructions

## Project overview

pttman (push-to-talk-manager) is a daemon + client for reliable microphone
mute/unmute on Linux with PipeWire/WirePlumber. It replaces a simpler
push-to-talk script that had race conditions under rapid button presses.

See `plans/implementation.md` for the design and integration plan.

## Conventions

- Single Python 3 script (`pttman`) containing both client and daemon.
- No external Python dependencies -- stdlib only.
- Follow the install.sh / systemd service pattern from the `aproman` project in
  the dotfiles repo at `~/dotfiles/utils/aproman/`.
- Keep code comments minimal. The user is a Staff Engineer.
- Prefer top-down control flow: caller first, then callee.
- When writing bash scripts: `#!/bin/bash`, 4-space indentation, fail-fast
  dependency checks.

## Key files

- `pttman` -- main script (client + daemon)
- `install.sh` -- installs binary + systemd service
- `systemd/pttman.service` -- systemd user service definition
- `plans/implementation.md` -- architecture and integration plan
