# Max-for-Live Audio Tap (Master Loudness / True-Peak) - Design

**Created**: 2026-06-12
**Status**: Approved (ready for implementation plan)

## Overview

Add a **Max for Live audio-tap device** that measures the Master bus and exposes
its metering to the MCP server, closing the one field-wide gap the LOM cannot
fill: **audio signal data**. The Live Object Model exposes structure and parameter
values but no peak/RMS/LUFS/spectrum, which is exactly why the shipped
`analyze_set` feature reserves a `signal` slot on every track + master and honestly
defers every loudness / true-peak / masking rule under "Needs metering."

This project fills the **master** half of that slot: integrated / short-term /
momentary **LUFS** + **true-peak** + peak/RMS dBFS, delivered over a second socket
(`9878`) from a Max for Live device, computed by a pure, pytest-tested Python
module. When the tap is present, the deferred `mastering.loudness_target` rule
flips from "Needs metering" to a real pass/fail; when it is absent, behavior is
unchanged (graceful deferral).

### Scope (v1)

**In:** master-bus loudness/true-peak only. **Out (additive later, protocol shaped
to allow them):** per-track metering, spectral/FFT masking analysis, UI streaming,
auto-mastering. No per-track devices, no raw-audio streaming.

## Decisions (from brainstorming)

1. **Scope:** Master-bus loudness/true-peak (option A). Per-track (B) and spectral
   (C) are explicitly deferred; the block-stats protocol adds fields for them
   without a redesign.
2. **Measurement model:** a **free-running, reset-able integrating meter** as the
   core (`reset_meter` / `read_meter`), plus a `measure_loudness(seconds)`
   convenience wrapper that resets -> starts playback -> waits -> reads. Not a
   single fixed model - both the precise "measure the whole song" pass and cheap
   live reads are available.
3. **Transport:** a **second TCP socket on 9878**, served by **Node-for-Max**,
   completely decoupled from the 9877 Remote Script. Same `{ok,data}` envelope and
   connection/retry model as the existing `AbletonConnection`. (OSC and file-bridge
   rejected: OSC is push/fire-and-forget and awkward for request/response;
   file-bridge is polling-laggy and racy on the integrated-pass handoff.)
4. **Compute split:** **thin relay, Python integrates** (option B). Max DSP domain
   computes the cheap, stable per-block stats (K-weighted mean-square + oversampled
   true-peak); Node-for-Max keeps a dumb reset-able rolling buffer and serves it;
   **Python `loudness_utils.py` does the BS.1770 gating + integration** so the only
   logic that can be subtly wrong is pure Python under the existing pytest harness.

## Architecture

```
Master track -- [MCP Audio Tap.amxd] --+
                  | Max DSP domain      |  Node-for-Max (tap-server.js)
                  | K-weight + mean-sq  |  TCP :9878, {ok,data} JSON
                  | + 4x true-peak -----+-> rolling buffer of block-stats
                                        |     reset / read / ping  (no math)
                                        v
        Python MCP server  <-- AudioTapConnection (localhost:9878)
                  |
                  +- loudness_utils.py   (pure: gating + integration, pytest)
                  +- new tools  --> feed master `signal` into analyze_set
```

The 9878 path never touches the Remote Script. The Remote Script (9877) is
unchanged by this project.

## Components

### 1. `MCP Audio Tap.amxd` (Max for Live Audio Effect)

Dropped on the Master track once (same one-time-setup class as selecting the
Control Surface). Per channel (L/R):

- **K-weighting** (ITU-R BS.1770 / EBU R128): high-shelf pre-filter + RLB
  high-pass, implemented with `biquad~` stages.
- **Mean-square** per ~100 ms block (~10 blocks/s): square the K-weighted signal
  and accumulate per block.
- **True-peak**: 4x oversampled peak (`peakamp~` on an upsampled path) per block.

The patch does **only** stable DSP primitives - no gating, no integration. Each
block it pushes `{ms_k_l, ms_k_r, tp}` into the embedded `node.script`.

### 2. `tap-server.js` (Node-for-Max relay)

- Opens TCP `:9878`.
- Maintains a **reset-able rolling buffer** of block-stats, capped at ~1 hr of
  blocks (reports `truncated` per the repo's reader-limit convention).
- Commands (no math): `ping`, `reset`, `read`.

### 3. Python server side

- **`tap_connection.py`** - `AudioTapConnection`, a near-copy of `AbletonConnection`
  pointed at 9878: connect, reconnect-once, idempotent-read retry, timeout,
  `{ok,data}` parse. Refused connection (device absent) is a graceful, expected
  state, not an error.
- **`loudness_utils.py`** - pure, pytest-tested. Inputs: list of per-block
  K-weighted mean-squares + per-block true-peak + sample rate. Outputs:
  - momentary LUFS (400 ms / ~4 blocks sliding),
  - short-term LUFS (3 s / ~30 blocks sliding),
  - **integrated LUFS** (absolute -70 LUFS gate, then relative -10 LU gate over the
    ungated blocks),
  - true-peak max -> dBTP,
  - peak / RMS dBFS.
  Sample-rate-aware: block duration and filter assumptions derive from the device's
  reported SR.
- **New MCP tools:**
  - `get_audio_tap_status` - ping 9878; report `connected` + device meta, or
    `connected:false` + a setup hint. The AI's probe for the one-time setup.
  - `reset_meter` - reset the device buffer.
  - `read_meter` - read buffered blocks, compute via `loudness_utils`, return the
    metering payload.
  - `measure_loudness(seconds=None)` - orchestrate reset -> `start_playback` ->
    wait `seconds` (or until transport stops) -> `read_meter`. Reuses existing
    transport tools.
- **Analysis wire-in:** `normalize_snapshot` fills `master.signal` from a
  `read_meter` when the tap is connected, so `mastering.loudness_target` (and a new
  true-peak rule) evaluate for real. Tap absent -> `signal` stays `null` -> rule
  stays deferred (current behavior preserved).

## Wire protocol (9878, `{ok,data}` envelope)

- `{"command":"ping"}` -> `{ok:true, data:{device:"mcp-audio-tap", version,
  sample_rate, channels}}`
- `{"command":"reset"}` -> `{ok:true, data:{reset:true}}`
- `{"command":"read"}` -> `{ok:true, data:{sample_rate, since_reset_s, block_count,
  truncated, blocks:[{ms_k_l, ms_k_r, tp}, ...], peak, rms}}`

~10 floats/s; a 10-min pass is ~6000 blocks (~100 KB JSON). Capped at ~1 hr with
`truncated` set.

### Computed tool payload (`read_meter` / `measure_loudness`)

`{integrated_lufs, short_term_lufs, momentary_lufs, true_peak_dbtp, peak_dbfs,
rms_dbfs, block_count, duration_s}` (`measure_loudness` also returns `played:bool`).

## Error handling

- **Tap not loaded / 9878 refused:** `get_audio_tap_status` returns
  `{ok:true, data:{connected:false, hint:"Drop 'MCP Audio Tap' onto the Master
  track"}}`; `reset_meter`/`read_meter`/`measure_loudness` return
  `{ok:false, error:"audio tap not connected - ..."}`. `analyze_set` never crashes;
  master `signal` stays `null`, the rule stays deferred.
- **Connection retry** mirrors the 9877 model: reconnect once; reads are idempotent
  so retry is safe.
- **`measure_loudness` with nothing playing:** if the transport does not advance,
  return the result but set `played:false` so the AI does not report a bogus
  -70 LUFS as a real measurement.
- **Non-48k sample rates:** the device reports its SR in `ping`/`read`;
  `loudness_utils` derives block duration and the K-filter assumption from it.
  Exact `biquad~` coefficients at 44.1/96k are a live-verify item.

## Testing

- **`tests/test_loudness_utils.py`** (where correctness is proven) - synthetic
  block sequences with known answers: a -23 LUFS reference tone; silence (absolute
  gate drops it); a loud+quiet mix (relative gate); true-peak inter-sample
  overshoot.
- **`tests/test_tap_connection.py`** - FakeSocket harness mirroring
  `tests/test_connection.py`: reconnect, refused-connection -> graceful,
  `{ok,data}` parse.
- Offline gate unchanged: `uv run --with pytest pytest -q` + `py_compile` / server
  import.
- **Cannot pytest the `.amxd` or Node** - live-verify only: load on Master, play a
  known clip, compare `measure_loudness` integrated LUFS against Live's own meter /
  a reference (e.g. Youlean) within +/-0.5 LU.

## Distribution & setup

- New **`m4l/`** dir: `MCP Audio Tap.amxd` (binary - committed, no AI traces in the
  patch metadata) + `tap-server.js`.
- One-time user step (same class as "select the Control Surface"): drag the device
  onto the Master. Documented in the install guide + a short skill note. Legitimate
  plugin ship artifact (the no-Claude-files rule covers personal config, not ship
  artifacts).
- `get_audio_tap_status` is the AI's probe to detect presence and guide the user
  through the one-time drop.

## Open live-verify risks (flagged, not blockers)

- Exact K-weighting `biquad~` coefficients at non-48k sample rates.
- Node-for-Max thread/timer behavior for the per-block push (~10/s).
- True-peak 4x oversampling CPU cost on the master.

All three are verifiable only once the `.amxd` exists.

## Out of scope (YAGNI)

Per-track metering, spectral/FFT masking, phase/correlation, UI streaming,
recording, auto-mastering. The block-stats protocol is shaped so per-track and
spectral additions are field additions, not a redesign.
