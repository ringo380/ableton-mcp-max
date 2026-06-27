---
layout: default
title: Composition
parent: Tools
nav_order: 19
---

# Composition
{: .no_toc }

Generate musical material into clip slots (chords, bass, melody, drums) and transform existing clips (humanize, swing, quantize-to-scale, arpeggiate, harmonize). Key/scale read from the set when not given.

<details open markdown="block">
  <summary>Tools on this page</summary>
  {: .text-delta }
1. TOC
{:toc}
</details>

---

## generate_chord_progression

```python
generate_chord_progression(
    track_index: int,
    clip_index: int,
    progression: List[str],
    key: str = None,
    scale: str = None,
    bars: int = 4,
    octave: int = 3,
    durations: List[float] = None,
    replace: bool = False,
)
```

Generate a chord progression into a session clip slot. Creates the MIDI
clip if the slot is empty (length = bars*4 beats), else requires replace=true.

Parameters:
- track_index / clip_index: where to write
- progression: roman numerals ('I','vi','IV','V') and/or chord symbols
  ('Cmaj7','Am7'); romans resolve diatonically to key/scale
- key/scale: optional; if both omitted, the set's key/scale is read
- bars: clip length in 4/4 bars (default 4)
- octave: Ableton octave label, C3=60 (default 3)
- durations: optional per-chord beat lengths (default: evenly split)
- replace: overwrite an occupied slot (default false)

## generate_bassline

```python
generate_bassline(
    track_index: int,
    clip_index: int,
    progression: List[str] = None,
    style: str = 'root',
    key: str = None,
    scale: str = None,
    bars: int = 4,
    octave: int = 1,
    seed: int = None,
    replace: bool = False,
)
```

Generate a bassline into a session clip slot. With a progression the bass
follows the chord roots; without one it lays one scale-root per bar.

Parameters:
- progression: optional chord list (roman/symbol) for harmonic context
- style: root | octaves | arp | walking (walking needs a progression)
- key/scale: optional; if both omitted, the set's key/scale is read
- octave: Ableton octave label (default 1)
- seed: optional int for reproducible randomness
- replace: overwrite an occupied slot

## generate_melody

```python
generate_melody(
    track_index: int,
    clip_index: int,
    key: str = None,
    scale: str = None,
    bars: int = 4,
    contour: str = 'arch',
    density: float = 0.5,
    octave: int = 4,
    seed: int = None,
    replace: bool = False,
)
```

Generate an in-scale monophonic melody into a session clip slot.

Parameters:
- key/scale: optional; if both omitted, the set's key/scale is read
- contour: up | down | arch | valley | random
- density: 0..1 probability each eighth-note slot sounds (default 0.5)
- octave: Ableton octave label (default 4 = around middle C)
- seed: optional int for reproducible randomness
- replace: overwrite an occupied slot

## generate_drum_pattern

```python
generate_drum_pattern(
    track_index: int,
    clip_index: int,
    style: str = 'four_on_floor',
    bars: int = 4,
    fills: bool = False,
    seed: int = None,
    replace: bool = False,
)
```

Generate a drum pattern (GM drum map) into a session clip slot. Intended
for a Drum Rack track (kick=36, snare=38, closed hat=42, ...).

Parameters:
- track_index / clip_index: where to write
- style: four_on_floor | basic_rock | breakbeat | hihat_8ths | boom_bap
- bars: clip length in 4/4 bars (default 4)
- fills: add a seeded snare fill in the last bar
- seed: optional int for reproducible randomness
- replace: overwrite an occupied slot

## humanize_clip

```python
humanize_clip(
    track_index: int,
    clip_index: int,
    timing: float = 0.02,
    velocity: float = 8.0,
    seed: int = None,
)
```

Humanize a clip: jitter note onsets (+/- timing beats) and velocities
(+/- velocity). Rewrites the clip's notes in place.

Parameters:
- track_index / clip_index: locate the clip
- timing: max onset jitter in beats (default 0.02)
- velocity: max velocity jitter (default 8)
- seed: optional int for reproducible jitter

## swing_clip

```python
swing_clip(
    track_index: int,
    clip_index: int,
    amount: Union[float, int, str],
    grid: str = '1/16',
)
```

Apply swing (shuffle) to a clip by delaying off-beat notes. Bakes a real,
non-faked swung feel into already-generated notes; reversible with `undo`.

Parameters:
- track_index / clip_index: locate the clip
- amount: swing strength. A fraction 0.0-1.0 (0 = straight, 1 = max), OR an
  MPC-style percent (50 = straight, 66 ~ triplet, 75 = max) passed as a
  number > 1 or a string like "66%".
- grid: swing grid, "1/8" or "1/16" (default "1/16"). Off-beat steps on this
  grid are delayed; on-beats are left in place.

Works best on grid-quantized parts (generated basslines, drums, melodies).

## quantize_clip_to_scale

```python
quantize_clip_to_scale(
    track_index: int,
    clip_index: int,
    key: str = None,
    scale: str = None,
)
```

Snap every note in a clip to the nearest in-scale pitch.

Parameters:
- track_index / clip_index: locate the clip
- key/scale: optional; if both omitted, the set's key/scale is read

## arpeggiate_clip

```python
arpeggiate_clip(
    track_index: int,
    clip_index: int,
    mode: str = 'up',
    rate: float = 0.25,
    gate: float = 0.9,
    seed: int = None,
)
```

Arpeggiate a clip: expand simultaneous notes (chords) into sequential
notes. Single (non-chord) notes pass through unchanged. Rewrites the clip.

Parameters:
- track_index / clip_index: locate the clip
- mode: up | down | updown | random | strum
- rate: step spacing in beats (default 0.25 = sixteenth)
- gate: note length as a fraction of rate (default 0.9)
- seed: optional int (only used by mode=random)

## harmonize_clip

```python
harmonize_clip(
    track_index: int,
    clip_index: int,
    intervals: List[int] = None,
    degrees: List[int] = None,
    key: str = None,
    scale: str = None,
)
```

Add a harmony voice to each note in a clip. Provide exactly ONE of
intervals (fixed semitone offsets, snapped to scale) or degrees (scale-step
offsets, kept diatonic).

Parameters:
- track_index / clip_index: locate the clip
- intervals: e.g. [4,7] adds a third and fifth above, snapped to scale
- degrees: e.g. [2] adds a note two scale-steps up (a diatonic third)
- key/scale: optional; if both omitted, the set's key/scale is read

## set_song_scale

```python
set_song_scale(key: str, scale: str = 'major')
```

Set the song's global scale - the "Scale" indicator in Live's control
bar (root note + scale name). Aligns Live's scale-aware features (Scale
highlight, scale-snapping MIDI tools) to the intended key. This does NOT
move any existing notes - use quantize_clip_to_scale for that.

Parameters:
- key: root note name (C, C#, Db, D, ... B)
- scale: a Live scale name or alias (e.g. major, minor, Dorian, Minor Blues,
  Harmonic Minor, Whole Tone); defaults to major

Note: Song.root_note/scale_name lag their own read-back, so the confirmation
is taken from a separate follow-up read of the song scale.

## set_arrangement_automation

```python
set_arrangement_automation(lanes: List[Dict[str, Any]], reload: bool = True)
```

Write Arrangement-timeline automation (device-parameter / rack-macro
breakpoint envelopes bound to song position) by patching the set's .als file
and reloading Live in place. This is the ONLY way to author arrangement
automation — the LOM cannot (clip envelopes are session-only).

The set MUST be saved to a real file first (an Untitled set errors — use
save_set_as). Live is briefly focused (System Events) for the in-place
reload, and the open set is reloaded from disk (~5s); one MCP call right
after may transiently fail and self-heal.

lanes: list of automation lanes, each a dict:
  - track_index (int): the OWNING track (regular Midi/Audio, document order).
  - device_index (int, default 0): device on that track.
  - parameter (int|str): parameter index or name (case-insensitive). Macros
    are addressed by their parameter name ("Macro 1", etc.).
  - track_type (str, default 'regular'): 'regular' | 'return' | 'master'.
  - points (list[{time, value}]): breakpoints. time in BEATS; value in the
    parameter's NATIVE units (clamped to its range). >=1 required; sorted
    automatically; duplicate times = a vertical step.
  - replace (bool, default True): replace any existing arrangement envelope
    for this parameter (idempotent rewrites).
reload: reload the set in place when done (default True). False leaves the
  patched envelope on disk only (reload Live yourself to see it).

Targeting uses a VALUE PROBE: each param is briefly set to a unique sentinel,
the set is saved, and the matching value in the .als locates the parameter —
so it works for macros, native params, nested-in-rack params, and AU/VST
plugins alike. Quantized (stepped) params are NOT supported in v1.

Returns JSON {ok, data:{set_path, reloaded, lanes:[{track_index,
device_index, parameter, pointee_id?, points_written?, ok, error?}]}}.
A lane that can't be resolved is reported ok:false and skipped; siblings
still apply.

