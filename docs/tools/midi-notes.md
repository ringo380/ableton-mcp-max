---
layout: default
title: MIDI Notes
parent: Tools
nav_order: 4
---

# MIDI Notes
{: .no_toc }

Read and edit notes inside MIDI clips via the Live 11 extended note API.

<details open markdown="block">
  <summary>Tools on this page</summary>
  {: .text-delta }
1. TOC
{:toc}
</details>

---

## add_notes_to_clip

```python
add_notes_to_clip(
    track_index: int,
    clip_index: int,
    notes: List[Dict[str, Union[int, float, bool]]],
)
```

Add MIDI notes to a clip (MIDI clips only). Uses the Live 11+ extended note
API (no editor dialog).

Parameters:
- track_index: The index of the track containing the clip
- clip_index: The index of the clip slot containing the clip
- notes: List of note dictionaries. Required-ish fields: pitch, start_time,
  duration, velocity, mute. Optional Live 11+ fields (sensible defaults):
  probability (0.0-1.0), velocity_deviation, release_velocity (0-127).

## get_clip_notes

```python
get_clip_notes(
    track_index: int,
    clip_index: int,
    from_time: float = 0.0,
    time_span: float = -1.0,
    from_pitch: int = 0,
    pitch_span: int = 128,
)
```

Read MIDI notes from a clip (MIDI clips only). Uses the Live 11+ extended note
API. Returns a list of note dicts {note_id, pitch, start_time, duration,
velocity, mute, probability, velocity_deviation, release_velocity}. The
note_id can be passed to modify_clip_notes to edit a note in place.

Parameters:
- track_index / clip_index: locate the clip
- from_time: start of the time window in beats (default 0.0)
- time_span: length of the window in beats; -1 (default) = whole clip length
- from_pitch: lowest pitch to include (default 0)
- pitch_span: number of pitches to include (default 128 = all)

## replace_clip_notes

```python
replace_clip_notes(
    track_index: int,
    clip_index: int,
    notes: List[Dict[str, Union[int, float, bool]]],
)
```

Replace ALL notes in a MIDI clip with the given notes (clears existing notes
first, then adds these). MIDI clips only. Uses the Live 11+ extended note API.

Parameters:
- track_index / clip_index: locate the clip
- notes: list of note dicts with pitch, start_time, duration, velocity, mute,
  and optional probability / velocity_deviation / release_velocity.

## remove_clip_notes

```python
remove_clip_notes(
    track_index: int,
    clip_index: int,
    from_time: float = 0.0,
    time_span: float = -1.0,
    from_pitch: int = 0,
    pitch_span: int = 128,
)
```

Remove MIDI notes within a time/pitch window from a clip (MIDI clips only).
Defaults remove every note in the clip.

Parameters:
- track_index / clip_index: locate the clip
- from_time: start of the time window in beats (default 0.0)
- time_span: length of the window in beats; -1 (default) = whole clip length
- from_pitch: lowest pitch to include (default 0)
- pitch_span: number of pitches to include (default 128 = all)

## modify_clip_notes

```python
modify_clip_notes(
    track_index: int,
    clip_index: int,
    notes: List[Dict[str, Union[int, float, bool]]],
)
```

Edit existing notes in a MIDI clip in place, by note_id (MIDI clips only).
Notes not referenced are left untouched -- no remove-and-re-add. Uses Live
11's apply_note_modifications.

Parameters:
- track_index / clip_index: locate the clip
- notes: list of dicts, each REQUIRING a note_id (from get_clip_notes) plus
  any fields to change: pitch, start_time, duration, velocity, mute,
  probability, velocity_deviation, release_velocity. Omitted fields are
  left as-is on that note.

