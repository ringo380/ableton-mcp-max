# Per-Track Signal Taps via a General Bridge Device

**Created:** 2026-06-13
**Status:** Design approved
**Target release:** v0.8.0 (breaking device change - see Master-tap unification)

## Overview

The Live Object Model exposes no audio signal, so all cross-track mix analysis
is currently impossible: `analyze_set`'s only `signal_required` rules
(`mastering.loudness_target`, `mastering.true_peak`) are master-level and were
satisfied by the v0.7.0 master audio tap. The `mixing.json` rules are `manual`
judgment calls with no signal backing.

This feature adds **per-track signal taps** that report each instrumented
track's loudness, peak/crest, spectral profile, and stereo characteristics to
the MCP server, powering a new generation of **signal-backed cross-track mixing
rules** (spectral masking, loudness balance, per-track headroom, stereo
correlation). It does so by establishing a reusable **general bridge**: a
Python-hosted registry that any number of self-identifying Max-for-Live devices
connect into. This bridge is intended to be the foundation for later M4L
capability tiers (sample-accurate modulation, generative MIDI) beyond this spec.

Primary goal (confirmed): **cross-track mix analysis powering a richer
`analyze_set`**. Accuracy bar: **advisory / good-enough**, not mastering-grade.

## Goals

- A reusable bidirectional bridge: one MCP-hosted socket, N self-identifying M4L
  client devices, reorder/rename-proof identity.
- Per-track capture of: K-weighted loudness, sample-peak + crest, wideband RMS,
  an 8-band log-spaced spectral profile, and stereo (L/R + mid/side) energy.
- New signal-backed `mixing.*` rules computed by pure, unit-tested Python.
- Scripted deployment of taps onto tracks via the existing browser-load tooling.
- A deterministic timed measure pass that `analyze_set` (and a `measure_mix`
  tool) use to gather simultaneous per-track signal during playback.
- Unify the v0.7.0 master tap into this one device type and registry.

## Non-goals

- Mastering-grade metering accuracy (advisory bar is sufficient).
- FFT-grade spectral resolution (8 log bands is the chosen resolution).
- Real-time control loops crossing the socket (audio-rate work stays in Max;
  only summaries/commands cross the wire). Modulation/generative tiers are out
  of scope for this spec - the bridge is designed to host them later.
- Auto-instantiating M4L devices via any LOM call other than browser-load.

## Decisions (from brainstorming)

| Decision | Choice |
|----------|--------|
| Primary job | Cross-track mix analysis feeding `analyze_set` |
| Signal set | Levels + spectral bands + stereo |
| Deployment | Scripted auto-deploy via User Library + browser-load |
| Transport topology | Python-hosted registry; devices are TCP clients (invert) |
| Measure model | Deterministic timed measure pass (transport restored after) |
| Master tap | Unify - one self-identifying device type; master = track id `master`; v0.8.0 breaking |
| Spectral method | 8-band log-spaced biquad filterbank (not FFT) - script-buildable |

## Architecture

### Topology

The MCP server (Python) gains a **background thread hosting a TCP registry
server** on one well-known port. Each tap device is a Node-for-Max **client**
that, on load:

1. Reads its own track identity from inside Max via the LOM (`this_device` →
   parent track: name, index, kind, color) plus a generated stable `uuid`.
2. Connects out to the registry and sends a `hello` frame with that identity.
3. Streams per-100ms stat blocks over the persistent connection.

Python keeps a **per-connection ring buffer keyed by track `uuid`**. Tools read
those buffers; the measure pass resets them, plays, and reads. This inverts the
v0.7.0 relay (device-was-server) so that N devices scale on one port, free of
the EADDRINUSE collision class and reorder fragility of port-per-device.

### Components (each independently testable)

- **`m4l/` unified tap device** - new self-identifying device:
  `MCP Tap.amxd` + editable `MCP Tap.maxpat` source + `registry-client.js`
  (Node-for-Max client + relay). The device is a dumb relay; all analysis math
  is Python-side. Built by grafting the DSP chain onto a known-good M4L wrapper
  (the `ampf`/`meta`/`ptch` chunk format; keep template `plugin~`/`plugout~` +
  wrapper, swap `boxes`/`lines`), per the established `.amxd` build recipe.
- **`tap_registry.py`** (new, server-side) - the listening thread, the
  `connections[uuid]` map, per-track ring buffers, newline-delimited JSON frame
  parsing, stale-connection eviction. Unit-tested with a FakeSocket harness
  mirroring `tests/test_connection.py` / `tests/test_batch.py`.
- **`spectrum_utils.py`** (new, pure) - band-vector math (normalize, integrate,
  per-band loudness), stdlib-only, unit-tested.
- **`masking_utils.py`** (new, pure) - cross-track pairwise band-overlap masking
  score, loudness-balance spread, per-track headroom/crest, stereo correlation.
  Stdlib-only, unit-tested (mirrors `loudness_utils.py`).
- **server.py** - new MCP tools + reimplemented existing metering tools +
  extended `analyze_set`.
- **remote_script** - the registry is Python-side and does not touch the Remote
  Script for signal; the Remote Script is only involved for `deploy_taps`
  (browser-load) and identity reads if needed, reusing existing handlers.

## Wire protocol

Newline-delimited JSON frames, both directions, preserving the `{ok,data}`
envelope convention.

Device → registry:

```
{"type":"hello","track":{"uuid":"...","name":"Bass","index":2,"kind":"midi","color":123},
 "device":"mcp-tap","version":"2.0.0","sample_rate":48000}
```

then every 100 ms:

```
{"type":"block","data":{
   "ms_k_l":..., "ms_k_r":...,        // K-weighted mean-square per channel (loudness)
   "peak":...,                         // sample-peak (linear) this block
   "rms":...,                          // wideband RMS (linear) this block
   "bands":[b0,...,b7],                // 8-band log-spaced energy vector
   "mid":..., "side":...               // mid/side energy (stereo width/correlation)
}}
```

Registry → device: `{"command":"reset"}` (clear that device's accumulators),
`{"command":"ping"}`. **Reads are served from Python's buffer**, never
round-tripped to the device.

### Registry state

`connections[uuid] = {identity, ring_buffer, last_seen, sample_rate}`.
Identity (name/index) is captured at `hello`. Stale connections (no block within
a configurable timeout) are marked disconnected; their last buffer is retained
until the next reset. Track `index`/`name` may be re-resolved on demand via a
lightweight LOM read when a tool needs current mapping (uuid remains the stable
key, so reorders never lose data).

## Data flow - the measure pass

`measure_mix(window_s=15, region=None)` (also what `analyze_set` calls
internally):

1. Snapshot transport state (playhead, loop on/off + brace, play status).
2. `reset` all connected taps.
3. Start playback over the chosen window: default ~15 s from current position,
   or the current loop brace if active; `region` may name a locator-to-locator
   range. Configurable.
4. Wait the window (server-side sleep - this is the one tool that blocks
   meaningfully; documented).
5. Read all per-track ring buffers.
6. Stop playback and restore transport state.
7. Hand buffers to `spectrum_utils`/`masking_utils` → per-track integrated
   `signal` objects + cross-track findings.

Restoration uses the established separate-read settle discipline (song-property
writes lag their own read-back).

## Signals & DSP

**Per-block payload** (above): K-weighted mean-square L/R, sample-peak,
wideband RMS, 8-band energy vector, mid/side energy.

**Spectral method:** an **8-band log-spaced filterbank** - per band: biquad
bandpass → square (`*~`) → `average~` window - summed/packed into the `bands`
array. Bands (nominal): sub, low, low-mid, mid, high-mid, presence, brilliance,
air. Chosen over FFT because it is far more reliably **script-buildable** into an
`.amxd` via the graft-onto-template approach than a `pfft~` subpatcher, and 8 log
bands give ample resolution for advisory masking flags. Band count is the YAGNI
dial.

**Stereo:** mid = (L+R)/2, side = (L-R)/2; per-block mid/side energy yields width
and a correlation proxy in Python.

**Largest implementation risk:** this is a much bigger DSP graph than the master
tap (8 bands × bandpass+square+average × 2 ch, plus K-weighting, peak, M/S).
Mitigation: phased build (levels+stereo device first to prove the bridge, then
add bands) and a documented fallback if the band graft proves unwieldy.

## New MCP tools

- `deploy_taps(track_indices=None)` - browser-loads the tap device onto the given
  tracks (or all audio/instrument tracks when `None`). Depends on the
  User-Library `.amxd` + `load_browser_item` (see Risk spike 1).
- `remove_taps(track_indices=None)` - `delete_device` the taps.
- `list_taps()` - registry view: connected tracks, last-seen, buffer fill.
- `read_track_meter(track_index)` - per-track levels/spectrum/stereo snapshot
  (per-track analog of `read_meter`).
- `measure_mix(window_s=15, region=None)` - the measure pass; returns per-track
  integrated `signal` + computed cross-track findings.
- **Reimplemented against the registry:** `measure_loudness`, `read_meter`,
  `get_audio_tap_status`, `reset_meter` (master = track id `master`).

## New rules (`mixing.json`, signal-backed)

The measure pass fills each track's reserved `signal` field; `evaluate_rules`
already gates `signal_required` rules, so these evaluate when taps are present
and defer honestly otherwise.

- `mixing.spectral_masking` - pairwise band-overlap score between tracks; flags
  pairs competing hard in the same bands (e.g. kick vs bass in sub/low).
- `mixing.loudness_balance` - per-track integrated-loudness spread; flags tracks
  far outside the mix's relative balance.
- `mixing.headroom_per_track` - per-track peak/crest; flags near-clipping or
  over-compressed tracks.
- `mixing.stereo_correlation` - flags negative correlation (mono-compat risk) or
  near-mono elements (advisory, low-confidence).

The `/ableton:analyze` skill gets updated guidance to offer a measure pass when
taps are connected.

## Master-tap unification (breaking change)

The v0.7.0 master tap (device = server on 9878, single-purpose, levels-only) is
replaced by the unified self-identifying device reporting to the registry; master
is simply the tap whose track identity is `master`. The four existing metering
tools are reimplemented against the registry. This is a **breaking device
change**: users must re-place the device. Ships as **v0.8.0** with a migration
note in `m4l/README.md` and the docs site.

## Testing

**Offline (pytest gate):**
- `masking_utils` / `spectrum_utils` pure math: synthetic band vectors → known
  overlap scores, balance spreads, correlation values.
- `tap_registry`: frame parsing, identity map, ring-buffer fill/evict, stale
  eviction - FakeSocket harness mirroring `test_connection.py`/`test_batch.py`.
- New rule evaluation via synthetic per-track `signal` snapshots.
- Tool-shape tests (`{ok,data}` envelopes, arg validation).
- `py_compile` remote handler; `import ableton_mcp_max.server`.

**Risk spikes (BEFORE committing to the full build):**
1. **Browser-load of an `.amxd`** actually instantiates the M4L device on a track
   via `load_browser_item`. The one unproven assumption behind `deploy_taps`. If
   it fails, fall back to manual-drag + auto-discover (`deploy_taps` degrades to a
   helper that reports where to drop).
2. **Device-side LOM self-identification** - confirm `this_device` → parent-track
   read works inside Node-for-Max / `live.path` and returns name + index
   reliably.

**Live verification:**
- Deploy taps on a multi-track set; `measure_mix` during playback.
- Sanity-check band profiles (kick = low energy, hat = high).
- Cross-validate loudness balance against ear / Live meters.
- Confirm masking flags on a deliberately mud-stacked pair.
- Transport restored after the pass.

## Build order (phased; each phase = subagent-driven TDD with spec+quality review)

1. **Bridge + levels-only unified device** - `tap_registry.py`, protocol,
   self-identifying device replacing the master tap. Proves the bridge end to end.
2. **Spectral bands** - add the 8-band filterbank + `spectrum_utils.py`.
3. **Stereo** - add mid/side + correlation math.
4. **Cross-track rules + `measure_mix`** - `masking_utils.py`, new `mixing.*`
   rules, `analyze_set` integration.
5. **`deploy_taps`/`remove_taps`/`list_taps` + docs** - scripted deployment,
   docs-site regen, README + migration note, tool-index/landing-count refresh.

## Open risks

- Risk spike 1 (browser-load instantiation) gates `deploy_taps`'s design.
- The 8-band DSP graft is the largest authoring risk (mitigated by phasing).
- Registry lifecycle: the MCP server restarts on Claude Code restart; devices
  must retry their outbound connection (`registry-client.js` reconnect loop).
- K-weighting coefficients are 48 kHz-specific (inherited from the master tap);
  non-48k drift remains a documented live-verify item.
- The measure pass changes transport state during analysis; must restore
  reliably despite song-property write-lag.
