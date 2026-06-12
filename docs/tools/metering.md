---
layout: default
title: Metering (Audio Tap)
parent: Tools
nav_order: 15
---

# Metering (Audio Tap)
{: .no_toc }

Read master-bus loudness/true-peak from the MCP Audio Tap Max-for-Live device.

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

Check whether the 'MCP Audio Tap' Max-for-Live device is loaded + reachable.

Returns JSON {ok, data}. data.connected is True with device info
(sample_rate, channels) when the tap is running on 9878, else False with a
setup hint. Use this before read_meter/measure_loudness to guide the
one-time setup (drag the device onto the Master track).

## reset_meter

```python
reset_meter()
```

Reset the audio tap's integrating meter (clears the block buffer).

Returns JSON {ok, data:{reset:true}} or {ok:false,error} if the tap is not
connected. Call before playing material you want measured.

## read_meter

```python
read_meter()
```

Read the audio tap's master-bus metering since the last reset.

Returns JSON {ok, data} where data = {integrated_lufs, short_term_lufs,
momentary_lufs, true_peak_dbtp, peak_dbfs, rms_dbfs, block_count,
duration_s}. LUFS fields are null until enough audio has played (momentary
needs >=400 ms, short-term >=3 s; integrated null if all blocks were
silent). Returns {ok:false,error} if the tap is not connected.

## measure_loudness

```python
measure_loudness(seconds: float = None)
```

Reset the meter, play the set, wait, and read back master loudness.

seconds: how long to capture (default 10.0). For an integrated-loudness pass
over a whole song, pass its length. Returns the same payload as read_meter
plus data.played (False if the transport did not advance - e.g. nothing to
play - so a bogus reading is not mistaken for real). {ok:false,error} if the
tap is not connected.

