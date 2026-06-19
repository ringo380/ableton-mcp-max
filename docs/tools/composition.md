---
layout: default
title: Composition
parent: Tools
nav_order: 18
---

# Composition
{: .no_toc }

Generate musical material into clip slots (chords, bass, melody, drums) and transform existing clips (humanize, quantize-to-scale, arpeggiate, harmonize). Key/scale read from the set when not given.

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

