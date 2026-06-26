---
name: ableton-mixing
description: Balancing levels, gain staging, panning, sends/returns, and headroom in an Ableton Live set. Use when mixing, balancing tracks, fixing levels, setting up reverb/delay sends, or chasing headroom/clipping.
---

# Ableton mixing

Goal: a balanced, headroom-safe mix before mastering. Work from measurement, not guesswork.

## Tools
- Measure first: `measure_mix` (per-track levels/balance snapshot), `read_meter` /
  `read_track_meter` (live metering), `check_clipping` (find tracks/master over 0 dBFS).
- Act: `gain_stage_track` and `adjust_track_gain` (trim toward target headroom),
  `balance_mix` (rebalance toward a reference distribution), `set_mixer_property`
  (volume/pan/sends), `get_mixer` / `get_routing` (inspect).
- Sends/returns: create reverb/delay on a return track (`create_return_track` +
  `load_instrument_or_effect` with `track_type='return'`), then dial `sends[i]` via
  `set_mixer_property`. Reach return-device params with the `track_type`-aware device tools.

## Principles
- Target ~ -6 dBFS of headroom on the master before the limiter; no track should pin the
  meter. Stage gain BEFORE EQ/compression so downstream devices see sane levels.
- Pan for width, not for fixing masking - carve with EQ first.
- Reverb/delay belong on returns (shared, CPU-cheap), not as inserts on every track.

## Gotchas
- Device-tool asymmetry: `get_device_parameters`/`set_device_parameter` are regular-track
  only; use the `track_type`-aware tools for return/master devices.
- Mixer writes can lag their read-back - confirm with a separate `get_mixer`.
- Re-read `get_session_info` first; track indices change between sessions.

## Checklist
- [ ] Measured the mix (`measure_mix` / `check_clipping`) before touching faders.
- [ ] No clipping on tracks or master; ~ -6 dBFS master headroom preserved.
- [ ] Time-based FX on returns, not duplicated as inserts.
- [ ] Logged the moves to decisions.md.
