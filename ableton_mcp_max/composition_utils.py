"""Pure server-side music-theory + MIDI generation/transformation helpers.

No Live dependency (the Remote Script in Live's embedded Python cannot import
this). Generators return lists of note dicts in the shape
clip_utils.normalize_note accepts ({pitch, start_time, duration, velocity}).

Octave convention matches Ableton's note labels: MIDI pitch =
pitch_class + 12 * (octave + 2). So octave=3 -> C3 = MIDI 60 (middle C as Live
shows it).
"""

import random
import re

_NOTE_TO_SEMITONE = {
    "C": 0, "B#": 0, "C#": 1, "DB": 1, "D": 2, "D#": 3, "EB": 3,
    "E": 4, "FB": 4, "F": 5, "E#": 5, "F#": 6, "GB": 6, "G": 7,
    "G#": 8, "AB": 8, "A": 9, "A#": 10, "BB": 10, "B": 11, "CB": 11,
}

SCALE_INTERVALS = {
    "major": [0, 2, 4, 5, 7, 9, 11],
    "natural_minor": [0, 2, 3, 5, 7, 8, 10],
    "harmonic_minor": [0, 2, 3, 5, 7, 8, 11],
    "melodic_minor": [0, 2, 3, 5, 7, 9, 11],
    "dorian": [0, 2, 3, 5, 7, 9, 10],
    "phrygian": [0, 1, 3, 5, 7, 8, 10],
    "lydian": [0, 2, 4, 6, 7, 9, 11],
    "mixolydian": [0, 2, 4, 5, 7, 9, 10],
    "locrian": [0, 1, 3, 5, 6, 8, 10],
    "major_pentatonic": [0, 2, 4, 7, 9],
    "minor_pentatonic": [0, 3, 5, 7, 10],
    "blues": [0, 3, 5, 6, 7, 10],
    "whole_tone": [0, 2, 4, 6, 8, 10],
    "chromatic": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11],
}

_SCALE_ALIASES = {
    "min": "natural_minor", "minor": "natural_minor", "aeolian": "natural_minor",
    "maj": "major", "ionian": "major",
    "pentatonic": "major_pentatonic", "major_pent": "major_pentatonic",
    "minor_pent": "minor_pentatonic", "pent_minor": "minor_pentatonic",
}


def parse_key(key):
    """Note name ('C', 'c#', 'Db', 'Eb', 'B') -> root pitch-class 0-11."""
    k = str(key).strip().upper()
    if k not in _NOTE_TO_SEMITONE:
        raise ValueError(
            "Unknown key %r; use C, C#, Db, D, ... B" % (key,))
    return _NOTE_TO_SEMITONE[k]


def parse_scale(scale):
    """Scale name (with aliases) -> list of semitone intervals from the root."""
    s = str(scale).strip().lower().replace(" ", "_").replace("-", "_")
    s = _SCALE_ALIASES.get(s, s)
    if s not in SCALE_INTERVALS:
        raise ValueError(
            "Unknown scale %r; known: %s" % (scale, ", ".join(sorted(SCALE_INTERVALS))))
    return list(SCALE_INTERVALS[s])


def resolve_key_scale(key=None, scale=None, song_scale=None):
    """Resolve (root, intervals). Explicit params win. If both omitted, use the
    set's root_note + scale_intervals (song_scale dict from get_song_scale). If
    that is missing/empty, fall back to C natural_minor.

    If only `key` is given, the scale defaults to major; if only `scale` is
    given, the root defaults to C (0)."""
    if key is None and scale is None:
        if song_scale:
            ints = song_scale.get("scale_intervals") or []
            ints = [int(i) % 12 for i in ints]
            if ints:
                return int(song_scale.get("root_note", 0)) % 12, ints
        return 0, list(SCALE_INTERVALS["natural_minor"])
    root = parse_key(key) if key is not None else 0
    intervals = parse_scale(scale) if scale is not None else list(SCALE_INTERVALS["major"])
    return root, intervals


def _octave_base(octave):
    """MIDI pitch of C in the given Ableton-labelled octave (C3 = 60)."""
    return 12 * (int(octave) + 2)


def _clamp_pitch(p):
    return max(0, min(127, int(p)))


def scale_pitches(root, intervals, lo=0, hi=127):
    """All MIDI pitches in [lo, hi] whose pitch-class is in the scale."""
    members = set((root + i) % 12 for i in intervals)
    return [p for p in range(lo, hi + 1) if p % 12 in members]


def degree_to_pitch(root, intervals, degree, octave):
    """Scale degree (0-based, may exceed len for higher octaves) -> MIDI pitch."""
    if not intervals:
        raise ValueError("intervals must be non-empty")
    n = len(intervals)
    oct_shift, idx = divmod(int(degree), n)
    return _clamp_pitch(_octave_base(octave) + root + intervals[idx] + 12 * oct_shift)


def snap_to_scale(pitch, root, intervals):
    """Move pitch to the nearest in-scale pitch (prefer downward on a tie)."""
    if not intervals:
        raise ValueError("intervals must be non-empty")
    members = set((root + i) % 12 for i in intervals)
    p = int(pitch)
    if p % 12 in members:
        return _clamp_pitch(p)
    for d in range(1, 7):
        for cand in (p - d, p + d):
            if 0 <= cand <= 127 and cand % 12 in members:
                return cand
    return _clamp_pitch(p)
