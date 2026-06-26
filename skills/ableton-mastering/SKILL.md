---
name: ableton-mastering
description: Finalizing a mix to a target loudness with limiting, metering, and reference matching on the Ableton master chain. Use when mastering, hitting a LUFS target, taming true-peaks, or matching a reference loudness.
---

# Ableton mastering

Goal: hit a platform loudness target while preserving dynamics and avoiding true-peak
clipping. Master only a clean, headroom-safe mix.

## Tools
- Measure: `measure_loudness` (integrated LUFS / peaks), `check_clipping`,
  the master audio tap for metering.
- Master chain: inspect/adjust with the `track_type='master'` device tools
  (`get_device_info`, `get_device_parameters`/`set_device_parameter` are regular-only -
  use `get_rack_macros`/`set_chain_property`/`set_device_on` for the master rack/limiter).
- Load master devices with `load_instrument_or_effect` / `load_preset` (`track_type='master'`).

## Principles
- Read `loudness-targets.md` and pick the target from the project brief (default -14 LUFS,
  -1 dBTP if unstated).
- Gain into the limiter, do not slam it; aim for <= 3 dB gain reduction on peaks.
- Re-measure after every change - master by the meter, then by ear against a reference.

## Gotchas
- `measure_loudness` needs audio actually playing through the master.
- Master-device raw param read/write is not available via `set_device_parameter`; drive
  the limiter through the rack/chain tools.

## Checklist
- [ ] Target read from brief (or default applied + noted).
- [ ] Integrated LUFS within ~1 LU of target; true-peak <= -1 dBTP.
- [ ] Compared against a reference track.
- [ ] Logged target + final readings to decisions.md.
