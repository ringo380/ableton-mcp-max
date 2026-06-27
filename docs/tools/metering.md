---
layout: default
title: Metering (Audio Tap)
parent: Tools
nav_order: 18
---

# Metering (Audio Tap)
{: .no_toc }

Per-track and master loudness/true-peak/spectrum/stereo from the MCP Tap Max-for-Live devices, plus cross-track mix analysis.

<details open markdown="block">
  <summary>Tools on this page</summary>
  {: .text-delta }
1. TOC
{:toc}
</details>

---

## get_audio_tap_status

```python
get_audio_tap_status()
```

Report per-track tap registry connectivity.

Returns JSON {ok, data:{connected, tracks}}. connected is True when at least
one 'MCP Audio Tap' device is streaming into the registry on 9878; tracks is
the list of connected tap identities (uuid/name/index/kind + sample_rate +
block_count). Empty/False until a tap device is loaded onto a track.

## list_taps

```python
list_taps()
```

List the connected per-track taps.

Returns JSON {ok, data:{count, tracks}} where tracks is the list of tap
identities (uuid/name/index/kind + sample_rate + block_count) currently
streaming into the registry.

## reset_meter

```python
reset_meter(track_index: int = None)
```

Reset tap accumulators (clears buffered blocks).

track_index: omit to reset every connected tap; pass -1 for the master tap
or a track index to reset just that one. Returns JSON {ok, data:{reset:true}}.
Call before playing material you want measured.

## read_meter

```python
read_meter()
```

Master tap signal summary (compat shim for read_track_meter(-1)).

Delegates to read_track_meter for the master tap. Returns JSON {ok, data}
with the integrated/momentary/short-term LUFS, true-peak dBTP, linear
peak/rms, crest, block_count and sample_rate. {ok:false,error} if no master
tap is connected.

## read_track_meter

```python
read_track_meter(track_index: int = -1)
```

Integrate a track's buffered tap blocks into a signal summary.

track_index: -1 for the master tap (default), or a track index whose 'MCP
Audio Tap' device is streaming. Returns JSON {ok, data:{integrated_lufs,
momentary_lufs, short_term_lufs, true_peak_dbtp, peak, rms, crest,
block_count, sample_rate}}. LUFS/dBTP are computed via BS.1770 gating over
the buffered 100 ms K-weighted blocks (loudness fields are null until enough
blocks exist - momentary needs 0.4 s, short-term 3 s). peak/rms are linear;
crest is peak-to-rms in dB. An empty buffer returns ok with block_count 0 and
null metrics. {ok:false,error} if no tap is connected for that track.

## measure_loudness

```python
measure_loudness(seconds: float = None)
```

Reset the master meter, play the set, wait, and read back loudness.

seconds: how long to capture (default 10.0). For an integrated-loudness pass
over a whole song, pass its length. Returns the same signal-summary payload
as read_meter plus data.played (False if the transport did not advance - e.g.
nothing to play - so a bogus reading is not mistaken for real).
{ok:false,error} if no master tap is connected.

## measure_mix

```python
measure_mix(window_s: float = 15.0, region: str = None)
```

Timed multi-track measure pass -> per-track signals + cross-track findings.

Resets every connected tap, plays the set for window_s seconds (via the same
transport seam as measure_loudness), then integrates each tap's buffered
blocks into a per-track signal (LUFS/dBTP/peak/rms/crest plus the 8-band
spectrum and stereo width/correlation). region is reserved for a future
arrangement-window capture.

IMPORTANT - per-track taps are PRE-FADER: the MCP Tap is an audio-effect in
the track's device chain and Ableton's mixer fader sits AFTER the device
chain, so each per-track signal reflects the instrument + device-chain output,
NOT the post-fader level. A fader move does not change its track's reading.
The only post-fader measurement point is the master (or a return), so the
master tap's signal (data.master) is the authoritative balance/loudness
reference. Deploy one with deploy_taps (it auto-adds a master tap by default).

Returns JSON {ok, data:{window_s, tracks, master, findings}}:
- tracks: [{name, index, kind, signal:{...}}] one per connected PER-TRACK tap
  (the master tap is excluded here and reported under `master`).
- master: the master tap's {name, index, kind, signal} (post-fader program
  output), or null when no master tap is connected.
- findings: cross-track analysis from masking_utils over the per-track signals
  - masking (pairwise spectral overlap), balance (tracks sitting too far below
  the loudest), headroom (near-clip / over-compressed), stereo (mono-compat
  risk). Each is a (possibly empty) list. The master is NOT compared against
  instruments here (it would skew balance/masking).

With no taps connected this still returns ok with empty tracks, null master,
and empty findings (not an error). Track names blank-reported by the device
are backfilled from the LOM track index.

## deploy_taps

```python
deploy_taps(track_indices: List[int] = None, include_master: bool = True)
```

Load the MCP Tap metering device onto tracks for per-track analysis.

track_indices: omit to auto-target every regular audio track + every MIDI
track holding an instrument; or pass explicit track indices. Use -1 for the
master bus (e.g. track_indices=[-1] taps the master only). The device must be
present in the User Library (copy m4l/'MCP Tap.amxd' there once); see
m4l/README.md.

include_master (default True): in auto-target mode (track_indices omitted),
also drop a tap on the master bus. The master tap is the only POST-FADER
measurement point, so it is the authoritative balance/loudness reference -
per-track taps are pre-fader (instrument + device-chain output, ahead of the
fader) and do not reflect fader moves. Pass include_master=False to skip it.
When track_indices is given explicitly, include_master is ignored (add -1 to
the list yourself).

Returns JSON {ok, data:{targets, deployed:[{track_index,device}],
failed:[{track_index,error}]}}. If EVERY load fails (e.g. the device isn't in
the browser), data.manual is true with a drag-it-yourself message listing the
target tracks - the registry still works once the device is dragged on by
hand. After deploying, run measure_mix or analyze_set(measure=True).

A slow Max-for-Live / Node-for-Max boot (notably Live 12 / Max 8.6) can
outlast the socket read timeout, so the load reply is lost even though the
device loaded + connected. When a load times out, deploy_taps polls the tap
registry and, if a tap connects on that track, records it as deployed with
"confirmed_via": "registry" instead of failing.

## remove_taps

```python
remove_taps()
```

Remove every loaded MCP Tap device from the set (delete by name match).

Scans all regular tracks AND the master bus for devices named 'MCP Tap' and
deletes them (per-track, highest device index first so re-indexing is safe).
Returns JSON {ok, data:{removed_count,
removed:[{track_type,track_index,device_index}], errors:[...]}}. No-op
(removed_count 0) when none are loaded.

