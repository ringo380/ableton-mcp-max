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

## get_groove_pool

```python
get_groove_pool()
```

List the grooves currently in Live's Groove Pool.

Returns each groove's pool index + name. Use an index or name with
`assign_groove_to_clip`. The pool is populated by dragging grooves (or a
.agr file) into the Groove Pool in Live; there is no LOM/MCP path to load a
factory groove into the pool, so an empty pool means none have been added.

## assign_groove_to_clip

```python
assign_groove_to_clip(track_index: int, clip_index: int, groove: Union[int, str])
```

Assign a groove from the Groove Pool to a clip (swings/shuffles playback).

Unlike `swing_clip` (which bakes timing into the notes), this binds a Live
groove to the clip so its feel is applied non-destructively at playback;
`set_groove_amount` then scales how strongly it is applied.

Parameters:
- track_index / clip_index: locate the clip (regular tracks; MIDI or audio).
- groove: which Groove-Pool groove to assign - a pool index (int, from
  `get_groove_pool`) or an exact groove name (str). A numeric string is
  treated as a name, not an index.

The groove must already be in the Groove Pool (see `get_groove_pool`); drag
one in first if the pool is empty. Reversible with `undo`. Clearing a clip's
groove via this tool is not supported (Live's API rejects a null groove).

## load_groove_to_pool

```python
load_groove_to_pool(name_or_path: str)
```

Add a factory or User-Library groove (.agr) to Live's Groove Pool.

Resolves `name_or_path` (a groove name from `search_grooves`, or a full
.agr path), then loads it into the pool via a temporary carrier clip so
`assign_groove_to_clip` has something to bind. Returns the groove's POOL
name + index (the pool name is the .agr's internal name, which may differ
from the filename).

If a groove with that pool name is already present, this is a no-op
(`already_present: true`) - Live offers no way to REMOVE a pool groove via
the API, so duplicates are avoided rather than cleaned up. To remove a
groove, right-click it in Live's Groove Pool -> Remove; unsaved sets drop
added grooves on close.

About half of Ableton's factory grooves are stored in a proprietary BINARY
.agr format this backdoor cannot load; those return a clear error (drag them
in by hand). `search_grooves` flags each groove's `loadable` so you can pick
one that works. User-Library and ~half the factory grooves are plain XML and
load fine.

Parameters:
- name_or_path: groove name (case-insensitive, from `search_grooves`) or an
  absolute .agr path.

## search_grooves

```python
search_grooves(query: str = '', limit: int = 50, sources: list = None)
```

Search Live's groove library (.agr files) by name and category.

There is no LOM/browser path to LIST grooves, so this filesystem-walks the
running Live's factory Core Library/Grooves and/or the User Library. Use a
returned `name` with `load_groove_to_pool` to add it to the Groove Pool.

Parameters:
- query: space-separated terms (OR) matched against name + folder. Empty
  string matches everything.
- limit: max results (default 50).
- sources: which trees to walk: ["factory","user"] (default both).

Returns JSON {ok, data:{count, returned, items:[{name, file, category,
path, source, loadable}]}}. `loadable` is False for the ~half of factory
grooves stored in a binary .agr format that `load_groove_to_pool` cannot
add (drag those in by hand); True grooves load fine.

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

