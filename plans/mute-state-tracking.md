# Mute state tracking and resync

## Problem

Multiple issues combine to silently unmute mics:

1. The daemon has no opinion about initial state, so whatever state the mic was
   in before pttman started (often unmuted) is what stays.
2. When aproman restarts pipewire/pipewire-pulse after suspend or a node error,
   sources are recreated fresh (usually unmuted). The daemon has no feedback
   loop to reapply whatever state the user wanted.
3. New or reconnected sources (USB mic hotplug, bluetooth reconnect, or the
   fresh sources after a pipewire restart) come up in whatever state WirePlumber
   and stream-restore decide, not what the user wanted.
4. External tools drive `pactl`/`wpctl set-source-mute` without telling pttman.
   Investigation ruled Vesktop/Discord/Vencord out (they only flip WebRTC
   `MediaStreamTrack.enabled`, never the host source mute). noctalia shell is
   the real external actor: its mic-mute quick menu calls
   `wpctl set-mute @DEFAULT_AUDIO_SOURCE@ 0|1`, and its volume slider calls
   `wpctl set-mute ... 0 && wpctl set-volume ... N%`, so any stray scroll on the
   input volume slider unmutes the source as a side effect.

## Design

### State shape

```python
state = {
    "auto_discover": bool,
    "cli_all_sources": bool,
    "cli_source": str | None,
    "default_mute": bool,                  # from --start-muted
    "last_applied_mute": dict[str, bool],  # what we last told pactl per source
    "per_source_desired": dict[str, bool], # explicit pttman mute/unmute overrides
    "sources": list[str],
}
```

`effective_desired(source)` returns `per_source_desired[source]` if present,
else `default_mute`. This lets the user mix "mute everything by default" with
"but leave this specific USB mic unmuted" via explicit
`pttman --source X unmute`.

### Initial mute and hotplug

`--start-muted` (BooleanOptionalAction, default `True`) sets `default_mute`. The
value is also read from `~/.config/pttman.conf` as `--start-muted=true|false`.

On daemon startup, if `default_mute=True`, apply mute to all managed sources.

On hotplug (new source event from `pactl subscribe`): reapply
`effective_desired` per source. New sources not in `per_source_desired` get
`default_mute`, so hotplugged devices follow the global default without extra
configuration.

### Action semantics

| CLI command      | Daemon action | Effect on sources                           | Records preference?                       |
| ---------------- | ------------- | ------------------------------------------- | ----------------------------------------- |
| `pttman mute`    | `mute`        | `set_mute(sources, True)`                   | Yes, sets `per_source_desired[s] = True`  |
| `pttman unmute`  | `unmute`      | `set_mute(sources, False)`                  | Yes, sets `per_source_desired[s] = False` |
| `pttman toggle`  | `toggle`      | Coherent swing based on `effective_desired` | Yes                                       |
| `pttman press`   | `press`       | `set_mute(sources, False)`                  | No, temporary PTT                         |
| `pttman release` | `release`     | `set_mute(sources, True)`                   | No, temporary PTT                         |
| `pttman resync`  | `resync`      | Reapplies `effective_desired` per source    | No (reapply path)                         |

Toggle uses coherent swing: if any source is effectively unmuted, mute all;
otherwise unmute all. This keeps multi-source setups behaving predictably under
the XF86AudioMicMute key.

`press` and `release` are distinct wire actions (not just client-side aliases
for `unmute`/`mute`). The daemon applies the same mute bits but skips
`per_source_desired` updates, so `--start-muted` or the last recorded preference
survives a key press-release cycle untouched.

### External change detection

The watcher subscribes to `pactl subscribe` and calls `revert_external_change`
on `'change' on source` events. `pactl subscribe` does not tell us which source
changed, so the function iterates all managed sources, comparing actual mute
state to `last_applied_mute[source]`. On mismatch, it calls
`apply_mute(state, [source], last_applied_mute[source])` to revert the external
change within milliseconds. `per_source_desired` is never touched on this path:
external tools do not get to write the preference.

This is the "assertive posture" given the noctalia volume-slider finding: an
accidental unmute gets reverted before it can matter. The trade-off is that
intentional noctalia toggles also do not stick, but the user can run
`pttman mute`/`unmute` from the shell to change the preference.

Reverting to `last_applied_mute` (not `per_source_desired`) matters for two
reasons. First, it avoids a revert loop on our own `set-source-mute` calls,
which also fire change events. Two mechanisms cooperate here:
`_apply_mute_locked` updates `last_applied_mute` _before_ calling `set_mute`,
and a `threading.Lock` on `state["lock"]` serializes `apply_mute`,
`reapply_desired_state`, and `revert_external_change`. The watcher therefore
sees `last_applied_mute` consistent with the pactl state produced by our own
writes, rather than racing with the per-source dict update after `set_mute`
returns. Second, `last_applied_mute` gives press / release the right target
during a PTT cycle: it tracks the currently intended mute bit (including the
press's temporary unmute), while `per_source_desired` tracks the long-term
preference. If an external tool mutes during a press, we revert back to unmuted
rather than snapping to the saved preference.

Iterating all sources per event is O(N) pactl queries, but N is small in
practice (2-4 mics) and events only fire on actual changes, so the cost is
negligible.

### Reapply on structural events

`pactl subscribe` exits cleanly when pipewire-pulse restarts (empirically
confirmed: it reports `Connection failure: Connection terminated` and exits;
sources are queryable again within ~30ms). The watcher uses this as its signal:

- When the `pactl subscribe` subprocess exits, the watcher reconnects and
  unconditionally reapplies effective desired state.
- On `new`/`remove` source events during a live subscription, the watcher
  reapplies (hotplug path). This is not relied on for restarts since those
  events fire during the gap when subscribe is dead.

The reconnect loop uses exponential backoff starting at 50ms, capped at 400ms,
reset whenever a subscribe stays alive for at least a second. Reapply window is
~50ms in the common case, measured at ~57ms end-to-end on a pipewire restart.

No settle delay between reconnection and reapply: sources come back essentially
instantly. If we see reapply failures in practice, address them with targeted
healthchecks rather than a blanket sleep.

### CLI additions

- `pttman resync` - ask the daemon to reapply `effective_desired` for all
  managed sources. Errors if the daemon is not running (there is no state to
  resync to). The auto-revert path covers the common drift cases, so `resync` is
  mostly a manual fallback for unusual situations (e.g. a source we have not
  touched yet where `last_applied_mute` is unset, or a change event the watcher
  missed during a subscribe-reconnect gap).

## Files touched

- `pttman/pttman.py` - state shape, action dispatch, watcher callbacks,
  `effective_desired` / `apply_mute` / `revert_external_change` helpers.
- `tests/test_pttman.py` - coverage for the new state shape, press/release
  semantics, toggle coherent swing, hotplug-uses-default-mute, external change
  auto-revert across all managed sources without preference writes.
- `README.md` - documents `--start-muted`, `press`/`release` as distinct from
  `mute`/`unmute`, and the `resync` command.

aproman is deliberately not touched: the passive watcher reconnect is fast
enough (~50-100ms reapply window on a typical restart) that a cross-project
active signal is not worth the coupling.
