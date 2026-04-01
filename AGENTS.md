# Agent Instructions

## Project overview

pttman (push-to-talk-manager) is a daemon + client for reliable microphone
mute/unmute on Linux with PipeWire/WirePlumber. It replaces a simpler
push-to-talk script that had race conditions under rapid button presses.

See `plans/implementation.md` for the design and integration plan.

## Planning

Prefer to write plans in the `plans/` directory.

## Conventions

- Single Python 3 script (`pttman`) containing both client and daemon.
- No external Python dependencies -- stdlib only.
- Follow the existing install.sh / systemd service pattern: install the script
  to `~/.local/bin/`, install the service to `~/.config/systemd/user/`, and
  enable it with `systemctl --user`.
- Keep code comments minimal.
- When making changes to data in existing code, try to keep things in
  alphabetical order when it's reasonable to do so.
- Prefer top-down control flow: caller first, then callee.
- When writing bash scripts: `#!/bin/bash`, 4-space indentation, fail-fast
  dependency checks.

## Key files

- `pttman` -- main script (client + daemon)
- `install.sh` -- installs binary + systemd service
- `systemd/pttman.service` -- systemd user service definition
- `plans/implementation.md` -- architecture and integration plan

## Dev loop tools

### Running tests

Run unit tests with:

```sh
bun run test
```

This executes `python3 -m unittest discover -s tests -v`.

### Pre-commit hooks

Lefthook runs the following checks on commit (see `lefthook.yaml`):

- `md-format` -- Prettier formatting for Markdown files
- `ruff-check` -- linting via `uvx ruff check`
- `ty-check` -- type checking via `uvx ty check`
- `unit-tests` -- full unit test suite

Run the full pre-commit suite manually with:

```sh
bun run hooks:pre-commit
```

Or against all files (not just staged):

```sh
bun run hooks:pre-commit:all
```

## Releasing

### Pre-release steps

1. Check for uncommitted changes:

   ```sh
   git status
   ```

   If there are uncommitted changes, offer to commit them before proceeding.

2. Fetch latest tags to ensure we have the complete history:

   ```sh
   git fetch --tags
   ```

3. Update the version in both `package.json` and the `VERSION` constant in
   `pttman`, then commit the version bump separately from other changes with
   message `chore: bump version to <version>`.

4. Ask the user what tag name they want. Provide examples based on the current
   version:
   - If current version is `0.2.0`:
     - Minor update (new features): `0.3.0`
     - Bugfix update (patches): `0.2.1`

### Creating the release

When the user provides a version (or indicates major/minor/bugfix):

1. Create and push the tag:

   ```sh
   git tag v<version>
   git push origin v<version>
   ```

2. Examine each commit since the last tag to understand the full context:

   ```sh
   git log <previous-tag>..HEAD --oneline
   ```

   For each commit, run `git show <commit>` to see the full commit message and
   diff. Commit messages may be terse or only show the first line in `--oneline`
   output, so examining the full commit is essential for accurate release notes.

3. Create a draft GitHub release:

   ```sh
   gh release create v<version> --draft --title "v<version>" --generate-notes
   ```

4. Enhance the release notes with more context:
   - Use insights from examining each commit in step 2
   - Group related changes under descriptive headings (e.g., "### Refactored X",
     "### Fixed Y")
   - Use bullet lists within each section to describe the changes
   - Include a brief summary of what changed and why it matters
   - Keep the "Full Changelog" link at the bottom
   - Update the release with `gh release edit v<version> --notes "..."`

   Ordering guidelines:
   - Put user-visible changes first (new features, bug fixes, breaking changes)
   - Put under-the-hood changes later (refactoring, internal improvements, docs)
   - Within each section, order by user impact (most impactful first)

5. Tell the user to review the draft release and provide a link:

   ```
   https://github.com/mwolson/pttman/releases
   ```
