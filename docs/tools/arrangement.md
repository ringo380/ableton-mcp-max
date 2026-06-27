---
layout: default
title: Arrangement & Cues
parent: Tools
nav_order: 10
---

# Arrangement & Cues
{: .no_toc }

Cue points, the arrangement loop, and arrangement-timeline clips.

<details open markdown="block">
  <summary>Tools on this page</summary>
  {: .text-delta }
1. TOC
{:toc}
</details>

---

## get_cue_points

```python
get_cue_points()
```

List arrangement cue points / locators (index, name, time).

## create_cue_point

```python
create_cue_point(time: float)
```

Create a cue point (locator) on the Arrangement at the given time.

Live's only cue API toggles a marker at the playhead, and playhead writes
settle asynchronously, so this is orchestrated as separate commands: read
the current playhead, move it to `time`, toggle a cue there, then restore
the playhead. No-ops (created=false) if a cue already exists at `time`, so
it never removes an existing marker. Verify the actual time (Live may snap
to the grid) with get_cue_points.

Parameters:
- time: Position in beats (>= 0).

## delete_cue_point

```python
delete_cue_point(cue_index: int = None, index: int = None)
```

Delete a cue point (locator) by its index (as listed by get_cue_points).

Orchestrated as separate commands (same reason as create_cue_point): look
up the cue's time, move the playhead there, toggle it off, restore the
playhead.

Parameters:
- cue_index: Index into the ordered cue-point list (>= 0). (`index` is
  accepted as a legacy alias.)

## jump_to_cue

```python
jump_to_cue(direction: str = 'next')
```

Jump to the next or previous arrangement cue point.

Parameters:
- direction: 'next' or 'prev' (aliases: forward/back accepted)

## set_arrangement_loop

```python
set_arrangement_loop(
    enabled: Union[bool, int, str] = None,
    start: float = None,
    length: float = None,
)
```

Configure the arrangement loop brace. Only the parameters you provide are
changed.

Parameters:
- enabled: true/false, on/off, 1/0 (optional)
- start: Loop start in beats, >= 0 (optional)
- length: Loop length in beats, > 0 (optional)

## back_to_arrangement

```python
back_to_arrangement()
```

Re-engage the arrangement timeline after launching session clips (clears
the 'back to arrangement' override).

## get_arrangement_clips

```python
get_arrangement_clips(track_index: int, limit: int = 200)
```

List the clips on a track's Arrangement timeline.

Parameters:
- track_index: Index of the track.
- limit: Max clips to return (default 200). The list is truncated past this
  to stay within size limits; raise `limit` for more.

Returns JSON {track_index, count, returned, truncated, clips:[{index, name,
start_time, end_time, length, is_midi_clip}, ...]}. `count` is the full
total; `clips` holds at most `limit` of them.

## duplicate_clip_to_arrangement

```python
duplicate_clip_to_arrangement(
    track_index: int,
    source_slot_index: int,
    destination_time: float,
)
```

Place a Session-slot clip onto the same track's Arrangement timeline.

The source clip is taken from a Session clip slot on the SAME track and
duplicated onto that track's Arrangement at destination_time.

Parameters:
- track_index: Index of the track.
- source_slot_index: Session clip-slot index on that track (must hold a clip).
- destination_time: Arrangement position in beats (>= 0).

## delete_arrangement_clip

```python
delete_arrangement_clip(track_index: int, clip_index: int)
```

Delete a clip from a track's Arrangement timeline.

Parameters:
- track_index: Index of the track.
- clip_index: Index into get_arrangement_clips' list (>= 0). Deleting
  re-indexes the remaining clips — re-read after.

