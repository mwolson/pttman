# Agent Instructions

## Project overview

pttman (push-to-talk-manager) is a Rust daemon and client for reliable
microphone mute/unmute on Linux with PipeWire/WirePlumber or PulseAudio. It
serializes push-to-talk key events through a Unix datagram socket and reapplies
the intended mute state after source changes.

## Planning

Prefer to write plans in the `plans/` directory.

## Conventions

- Single-binary Rust crate with a small number of focused modules.
- Minimal dependencies. No tokio. Shell out to `pactl` and init-system tools.
- Keep code comments minimal.
- When making changes to data in existing code, try to keep things in
  alphabetical order when it's reasonable to do so.
- Prefer top-down control flow: caller first, then callee.
- When writing bash scripts: `#!/bin/bash`, 4 spaces for indentation,
  fail-fast dependency checks.

## Key files

- `src/main.rs` -- clap parse and command dispatch
- `src/cli.rs` -- `Cli`, subcommands, and override capture
- `src/config.rs` -- `~/.config/pttman.conf` parser and defaults
- `src/daemon.rs` -- daemon loop, command coalescing, and mute state model
- `src/pactl.rs` -- `PactlRunner` trait and source/mute helpers
- `src/socket.rs` -- Unix datagram client and socket path
- `src/service/` -- install/uninstall dispatch by init system
- `src/service_files.rs` -- `include_str!` copies of unit/init scripts
- `systemd/pttman.service` -- systemd user service
- `openrc-user/pttman` -- OpenRC 0.60+ user init script
- `openrc-system/pttman` -- OpenRC pre-0.60 system init script
- `install.sh` -- convenience installer for source builds

## Dev loop tools

### Toolchain

The Rust toolchain is pinned via `rust-toolchain.toml` (channel, profile, and
components). `rustup` auto-installs it on first `cargo` invocation.

### Running tests

```sh
bun run test
```

### Building

```sh
cargo build --release
cargo run
```

### Pre-commit hooks

Lefthook runs these checks on commit:

- `md-format` -- Prettier formatting for Markdown files
- `cargo-fmt` -- `cargo fmt --all -- --check`
- `cargo-clippy` -- `cargo clippy --all-targets -- -D warnings`
- `cargo-test` -- full unit test suite

Run checks against the working tree:

```sh
bun run hooks:check
```

## Releasing

### Pre-release steps

1. Check for uncommitted changes:

   ```sh
   git status
   ```

2. Fetch latest tags:

   ```sh
   git fetch --tags
   ```

3. Run `bun run hooks:check` and confirm everything passes.

4. Update the version in `Cargo.toml` and `package.json`. Run
   `cargo update -p pttman` to refresh `Cargo.lock`. Commit all three files
   with message `chore: bump version to <version>`.

5. Push the version-bump commit and verify CI passes before tagging.

### Creating the release

When the user provides a version:

1. Create and push the tag:

   ```sh
   git tag v<version>
   git push origin v<version>
   ```

2. Wait for `publish.yml` to pass before drafting release notes.

3. Examine each commit since the last tag.

4. The publish workflow creates a draft GitHub release with platform tarballs.
   Enhance the draft notes and publish the release. Start with a short summary,
   group related changes under descriptive headings, and avoid a single generic
   `## Changes` section when the release has multiple themes. Keep the "Full
   Changelog" link when GitHub generated one. Do not include routine
   verification sections or lists of check commands in public release notes;
   report validation in the chat handoff instead.

5. Tell the user to review the published release:

   ```text
   https://github.com/mwolson/pttman/releases
   ```
