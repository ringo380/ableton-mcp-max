---
layout: default
title: Transport & Playback
parent: Tools
nav_order: 8
---

# Transport & Playback
{: .no_toc }

Tempo, groove, metronome, recording, punch, and the playhead.

<details open markdown="block">
  <summary>Tools on this page</summary>
  {: .text-delta }
1. TOC
{:toc}
</details>

---

## set_tempo

```python
set_tempo(tempo: float)
```

Set the tempo of the Ableton session.

Parameters:
- tempo: The new tempo in BPM

## start_playback

```python
start_playback()
```

Start playing the Ableton session.

## stop_playback

```python
stop_playback()
```

Stop playing the Ableton session.

## continue_playback

```python
continue_playback()
```

Resume playback from the current position (unlike start_playback, which
restarts from the top).

## get_transport

```python
get_transport()
```

Get transport / arrangement state: is_playing, current_song_time, tempo,
time signature, metronome, arrangement loop (on/start/length), record_mode,
session_record, punch_in/out, and (Phase 10) groove_amount, swing_amount,
clip_trigger_quantization, midi_recording_quantization, count_in_duration
(read-only), nudge_up, nudge_down, and (Phase 11) can_capture_midi,
is_counting_in, session_record_status (all read-only).

## set_groove_amount

```python
set_groove_amount(amount: Union[float, int, str])
```

Set the global groove amount (how strongly clip grooves are applied).

Parameters:
- amount: 0.0-1.0 (clamped). Live displays this as 0-100%.

Note: the returned dict can be stale (song-property-write lag); confirm via
get_transport.

## set_swing_amount

```python
set_swing_amount(amount: Union[float, int, str])
```

Set the global swing amount applied when adding/quantizing notes.

Parameters:
- amount: 0.0-1.0 (clamped).

Note: confirm via get_transport (song-property-write lag).

## set_midi_recording_quantization

```python
set_midi_recording_quantization(value: Union[int, str])
```

Set the global MIDI-recording quantization.

Parameters:
- value: an int (Live.Song.RecordingQuantization) or a name: none, 1/4, 1/8,
  1/8t, 1/8+1/8t, 1/16, 1/16t, 1/16+1/16t, 1/32.

Note: confirm via get_transport (song-property-write lag).

## set_nudge

```python
set_nudge(direction: str, active: Union[bool, int, str])
```

Hold or release a tempo-nudge button (temporarily speeds up / slows down to
re-align with an external source).

Parameters:
- direction: "up" or "down"
- active: true to press/hold, false to release (true/false, on/off, 1/0)

Note: confirm via get_transport (song-property-write lag).

## capture_midi

```python
capture_midi(destination: str = 'auto')
```

Capture recently played MIDI material from audible tracks into a clip
(Live's "Capture MIDI"). Needs material to capture — check can_capture_midi
(via get_transport) first.

Parameters:
- destination: "auto" (Session or Arrangement depending on the visible view),
  "session", or "arrangement".

Note: confirm the captured clip via get_session_info / get_clip_info — the
returned dict can be stale (song-property-write lag). Raises a limitation
error if capturing into Session would need a new scene that can't be created.

## trigger_session_record

```python
trigger_session_record(record_length: Union[float, int, str, None] = None)
```

Trigger a new Session recording (records into armed tracks' clip slots).
Arming/recording auto-starts playback — stop promptly in tests.

Parameters:
- record_length: optional fixed length in beats (> 0). Omit for an
  open-ended recording (Live's default).

Note: confirm via get_transport (session_record / song-property-write lag).

## stop_all_clips

```python
stop_all_clips(
    track_index: Optional[int] = None,
    quantized: Union[bool, int, str] = True,
)
```

Stop playing clips. With no track_index, stops all clips in the set while the
song keeps playing; with track_index, stops only that track's running and
triggered clips.

Parameters:
- track_index: optional 0-based regular-track index. Omit to stop all tracks.
- quantized: honor global launch quantization (true) or stop immediately
  (false). Default true.

## tap_tempo

```python
tap_tempo()
```

Trigger Live's tap-tempo (one tap). Call repeatedly in time to set a tempo;
a single tap nudges the tempo toward the tap interval.

Note: confirm the resulting tempo via get_transport.

## set_metronome

```python
set_metronome(on: Union[bool, int, str])
```

Turn the metronome on or off.

Parameters:
- on: true/false, on/off, 1/0

## set_arrangement_record

```python
set_arrangement_record(on: Union[bool, int, str])
```

Arm or disarm arrangement record (record_mode).

Parameters:
- on: true/false, on/off, 1/0

## set_session_record

```python
set_session_record(on: Union[bool, int, str])
```

Turn session record on or off.

Parameters:
- on: true/false, on/off, 1/0

## set_punch

```python
set_punch(
    punch_in: Union[bool, int, str] = None,
    punch_out: Union[bool, int, str] = None,
)
```

Set the arrangement punch-in/out flags. Only the parameters you provide are
changed.

Parameters:
- punch_in: true/false, on/off, 1/0 (optional)
- punch_out: true/false, on/off, 1/0 (optional)

## set_song_position

```python
set_song_position(time_beats: float)
```

Jump the playhead to an absolute position.

Parameters:
- time_beats: Position in beats (must be >= 0)

## jump_by

```python
jump_by(beats: float)
```

Nudge the playhead by a relative amount.

Parameters:
- beats: Beats to move (negative moves backward)

