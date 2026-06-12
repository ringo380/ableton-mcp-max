# MCP Audio Tap (Max for Live)

Master-bus loudness/true-peak meter for the ableton MCP. Drop **MCP Audio Tap**
onto the **Master** track (one-time setup). It serves metering over TCP
`localhost:9878`; the MCP tools `get_audio_tap_status` / `reset_meter` /
`read_meter` / `measure_loudness` read it, and `analyze_set` uses it to evaluate
the loudness/true-peak mastering rules (otherwise deferred as "needs metering").

## Install
1. Ensure Ableton Live **Suite** (Max for Live) is installed.
2. Drag `MCP Audio Tap.amxd` onto the Master track. Leave it enabled.
3. Run `get_audio_tap_status` from the MCP - it should report `connected: true`.

## How it works
- The Max patch applies BS.1770 K-weighting to the master signal and emits a
  per-100ms block of stats (K-weighted mean-square per channel + an oversampled
  true-peak) to the embedded `node.script` (`tap-server.js`).
- `tap-server.js` keeps a reset-able rolling buffer (~1 hour cap) and serves
  `ping` / `reset` / `read` as `{ok,data}` JSON over `localhost:9878`.
- All gating + integration math (absolute -70 LUFS gate, relative -10 LU gate,
  integration, momentary/short-term windows, dBTP) lives in the Python
  `ableton_mcp_max/loudness_utils.py` - the device stays a dumb relay.

## Building / editing the device
`tap-server.js` is the source of truth for the relay. To rebuild the `.amxd`
patch around it, see the construction recipe in
`docs/superpowers/plans/2026-06-12-m4l-audio-tap.md` (Task 5): `plugin~` ->
two-stage `biquad~` K-weighting -> per-block mean-square via `metro 100` +
`snapshot~` -> 4x-oversampled `peakamp~` for true-peak -> formatted `block`/`sr`/
`peak`/`rms` messages into `[node.script tap-server.js]`.

## Sample-rate note
The K-weighting coefficients in the device are the standard 48 kHz set. At
44.1/96 kHz the integrated number drifts slightly; re-derive the `biquad~`
coefficients per sample rate if precise non-48k measurement is required. The
device reports its actual sample rate in `ping`/`read`, and `loudness_utils`
derives the block duration from it.
