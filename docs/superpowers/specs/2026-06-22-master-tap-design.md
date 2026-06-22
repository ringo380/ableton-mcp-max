# Master tap for true post-fader mix measurement (#31)

## Problem

Per-track MCP Tap measurements (`measure_mix`, `balance_mix`, `gain_stage_track`,
per-track `analyze_set(measure=True)`) are PRE-FADER. The Tap is an audio-effect
in the track's device chain, and Ableton's mixer fader sits AFTER the device
chain - so the tap measures the instrument + device-chain output, not the
post-fader level. A fader move does not change the reading, so a fader balance
can't be verified by re-measuring the same per-track taps, and there is no
post-fader program-loudness reference. The only post-fader measurement point is
the master (or a return).

Live evidence (Live 12.4, 6-track House set): per-track integrated LUFS were
essentially identical before vs after large fader moves; the actual output
changed but the pre-fader taps could not see it.

## Decision

- `deploy_taps` auto-adds a MASTER tap by default (`include_master=True`); the
  master tap is the authoritative post-fader balance/loudness reference.
- `measure_mix` and `analyze_set(measure=True)` partition the master tap out of
  the cross-track findings (it would skew loudness_balance / masking as the
  loudest "track") and surface it separately as the post-fader program output.
- Document the pre-fader limitation everywhere it matters.

## Mechanism (no remote-script change needed)

The measurement side already supports a master tap: the tap registry handles
`kind=="master"` / `index==-1`, `measure_loudness` / `read_meter` default to the
master, and `_measure_pass` integrates any connected tap. The handler already
supports `load_browser_item(track_type="master")` and
`delete_device(track_type="master")` (shipped in PR #24). So the change is
server-side only:

- `_load_tap_on_track(track_index, track_type="regular")` forwards `track_type`
  to `load_browser_item`; `track_type="master"` loads the tap on the master bus.
- `deploy_taps(track_indices=None, include_master=True)`: in auto-target mode,
  append `-1` (master) when `include_master`; an explicit `track_indices` list is
  used verbatim (`-1` selects the master; `include_master` is ignored). Per-target
  `track_type` is `"master"` for `-1`, else `"regular"`.
- `_find_taps()` scans the master node's devices too, returning
  `(track_type, track_index, device_index)`; `_delete_device_raw(track_type, ...)`
  and `remove_taps` follow the new tuple shape.
- New pure helper `masking_utils.partition_master(sigs) -> (per_track, master)`
  splits the index `-1` signal out. `measure_mix` returns `data.master` (the
  master tap's `{name,index,kind,signal}` or null) and excludes it from `tracks`
  and from `findings`. `analyze_set` mix_signal gains a `master` field; clipping
  still uses the full signal set (the master peak is a legitimate clip check).

## Limitations carried forward

- `gain_stage_track` on a regular/return track still reads pre-fader: the loop
  converges the fader against an instrument-level reading, so re-measuring won't
  reflect the fader. Use it as an instrument-level gain-stage, or run it on the
  master for true loudness convergence. Documented in the docstring.
- `balance_mix` corrections are right for OUTPUT balance only if the reference
  fader is the anchor, and cannot be re-verified via the per-track taps - verify
  via the master tap. Documented in the docstring.

## Verification

- Offline: `partition_master` unit tests; `deploy_taps` auto-master / opt-out /
  master-only / explicit-verbatim; `remove_taps` master deletion; `measure_mix`
  master partition + null. Full suite green.
- Live: deploy_taps auto-adds the master tap, measure_mix reports `data.master`
  with real program LUFS, and per-track findings exclude the master.
