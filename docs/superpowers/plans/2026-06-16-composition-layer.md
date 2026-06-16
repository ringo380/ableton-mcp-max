# Composition Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 8 server-side MIDI composition tools (4 generators + 4 transformers) plus one Remote Script read command, all driven by a new pure music-theory module.

**Architecture:** All music-theory + note-building math lives in a new pure module `ableton_mcp_max/composition_utils.py` (offline-tested, imported by `server.py` only). Server tools wrap those pure functions with the existing clip write path (`create_clip`/`add_notes_to_clip`/`replace_clip_notes`/`get_clip_notes`). The only Remote Script change is a new inline read command `get_song_scale` that powers the auto-read-the-set's-key path.

**Tech Stack:** Python 3 (server, normal CPython - `random` available), FastMCP `@mcp.tool()`, pytest (offline), Live Object Model (Remote Script, Py2/3.7-safe).

**Spec:** `docs/superpowers/specs/2026-06-16-composition-layer-design.md`

**Conventions to follow (from the spec + codebase):**
- Note dict shape is whatever `clip_utils.normalize_note` accepts; builders emit minimal dicts `{"pitch","start_time","duration","velocity"}` and the server passes them through `add_notes_to_clip`/`replace_clip_notes` which already normalize.
- **Octave convention = Ableton's labels:** MIDI pitch = `pitch_class + 12*(octave+2)`, so `octave=3` → C3 = MIDI 60 (middle C as Ableton shows it). Document this in the module docstring.
- Time is in beats; 4/4 assumed, so `bars * 4.0` beats per clip.
- Run tests with: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q`
- Do NOT reformat existing files. New files may be clean.

---

## File Structure

- **Create** `ableton_mcp_max/composition_utils.py` - pure module: key/scale model, chord model, generators, transformers, seeded-RNG helper.
- **Create** `tests/test_composition_scales.py` - key parsing, scale tables, resolve/snap.
- **Create** `tests/test_composition_chords.py` - roman/symbol → pitch sets.
- **Create** `tests/test_composition_generators.py` - chord prog (exact), bassline/melody/drums (invariants + seed reproducibility).
- **Create** `tests/test_composition_transformers.py` - humanize/quantize/arpeggiate/harmonize.
- **Modify** `remote_script/AbletonMCP/__init__.py` - add `get_song_scale` dispatch + impl (one read command).
- **Modify** `ableton_mcp_max/server.py` - import composition_utils, add `_song_scale()` + `_emit_to_slot()` helpers, add 8 `@mcp.tool()` functions.
- **Modify** `PROGRESS.md` - record the phase.
- **Regenerate** docs via `scripts/gen_docs_site.py` + `scripts/build_tool_index.py`; hand-edit counts in `docs/index.md`.

---

## Task 1: Key/scale model in composition_utils

**Files:**
- Create: `ableton_mcp_max/composition_utils.py`
- Test: `tests/test_composition_scales.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_composition_scales.py
import pytest
from ableton_mcp_max.composition_utils import (
    parse_key, parse_scale, resolve_key_scale, scale_pitches,
    degree_to_pitch, snap_to_scale, SCALE_INTERVALS,
)


def test_parse_key_accepts_sharps_flats_case():
    assert parse_key("C") == 0
    assert parse_key("c#") == 1
    assert parse_key("Db") == 1
    assert parse_key("B") == 11
    assert parse_key("eb") == 3


def test_parse_key_unknown_raises():
    with pytest.raises(ValueError):
        parse_key("H")


def test_parse_scale_named_and_aliases():
    assert parse_scale("major") == [0, 2, 4, 5, 7, 9, 11]
    assert parse_scale("minor") == [0, 2, 3, 5, 7, 8, 10]   # alias -> natural_minor
    assert parse_scale("Dorian") == [0, 2, 3, 5, 7, 9, 10]


def test_resolve_explicit_params_win():
    root, intervals = resolve_key_scale(key="D", scale="dorian", song_scale=None)
    assert root == 2
    assert intervals == [0, 2, 3, 5, 7, 9, 10]


def test_resolve_reads_set_when_omitted():
    song = {"root_note": 7, "scale_intervals": [0, 2, 4, 5, 7, 9, 11], "scale_name": "Major"}
    root, intervals = resolve_key_scale(key=None, scale=None, song_scale=song)
    assert root == 7
    assert intervals == [0, 2, 4, 5, 7, 9, 11]


def test_resolve_falls_back_to_c_minor():
    root, intervals = resolve_key_scale(key=None, scale=None, song_scale=None)
    assert root == 0
    assert intervals == SCALE_INTERVALS["natural_minor"]


def test_scale_pitches_filters_to_members_in_range():
    pitches = scale_pitches(0, [0, 4, 7], 60, 72)   # C, E, G
    assert pitches == [60, 64, 67, 72]


def test_degree_to_pitch_wraps_octaves():
    # C major, octave 3 -> C3 = 60
    assert degree_to_pitch(0, [0, 2, 4, 5, 7, 9, 11], 0, 3) == 60
    assert degree_to_pitch(0, [0, 2, 4, 5, 7, 9, 11], 7, 3) == 72  # next octave root


def test_snap_to_scale_moves_to_nearest_member():
    # C major: C#(61) -> C(60), prefer lower on tie
    assert snap_to_scale(61, 0, [0, 2, 4, 5, 7, 9, 11]) == 60
    assert snap_to_scale(60, 0, [0, 2, 4, 5, 7, 9, 11]) == 60
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_composition_scales.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'ableton_mcp_max.composition_utils'`

- [ ] **Step 3: Write minimal implementation**

```python
# ableton_mcp_max/composition_utils.py
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
    that is missing/empty, fall back to C natural_minor."""
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
    n = len(intervals)
    oct_shift, idx = divmod(int(degree), n)
    return _clamp_pitch(_octave_base(octave) + root + intervals[idx] + 12 * oct_shift)


def snap_to_scale(pitch, root, intervals):
    """Move pitch to the nearest in-scale pitch (prefer downward on a tie)."""
    members = set((root + i) % 12 for i in intervals)
    p = int(pitch)
    if p % 12 in members:
        return _clamp_pitch(p)
    for d in range(1, 7):
        for cand in (p - d, p + d):
            if 0 <= cand <= 127 and cand % 12 in members:
                return cand
    return _clamp_pitch(p)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_composition_scales.py -q`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/composition_utils.py tests/test_composition_scales.py
git commit -m "feat: composition_utils key/scale model"
```

---

## Task 2: Chord model (roman numerals + chord symbols)

**Files:**
- Modify: `ableton_mcp_max/composition_utils.py`
- Test: `tests/test_composition_chords.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_composition_chords.py
import pytest
from ableton_mcp_max.composition_utils import build_chord


C_MAJOR = [0, 2, 4, 5, 7, 9, 11]


def test_roman_triads_are_diatonic():
    # C major, octave 3 (C3=60): I = C E G
    assert build_chord("I", 0, C_MAJOR, 3) == [60, 64, 67]
    # ii = D F A (minor, derived from the scale, not hardcoded)
    assert build_chord("ii", 0, C_MAJOR, 3) == [62, 65, 69]
    # V = G B D
    assert build_chord("V", 0, C_MAJOR, 3) == [67, 71, 74]


def test_roman_seventh_adds_fourth_tone():
    # V7 in C major = G B D F
    assert build_chord("V7", 0, C_MAJOR, 3) == [67, 71, 74, 77]


def test_literal_symbol_independent_of_key():
    # Am7 regardless of the song key: A C E G
    assert build_chord("Am7", 0, C_MAJOR, 3) == [69, 72, 76, 79]
    # Cmaj7 = C E G B
    assert build_chord("Cmaj7", 0, C_MAJOR, 3) == [60, 64, 67, 71]


def test_unknown_symbol_raises():
    with pytest.raises(ValueError):
        build_chord("Zsus", 0, C_MAJOR, 3)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_composition_chords.py -q`
Expected: FAIL with `ImportError: cannot import name 'build_chord'`

- [ ] **Step 3: Write minimal implementation** (append to `composition_utils.py`)

```python
_ROMAN_DEGREE = {"i": 0, "ii": 1, "iii": 2, "iv": 3, "v": 4, "vi": 5, "vii": 6}

_CHORD_QUALITIES = {
    "": [0, 4, 7], "maj": [0, 4, 7], "m": [0, 3, 7], "min": [0, 3, 7],
    "dim": [0, 3, 6], "aug": [0, 4, 8],
    "maj7": [0, 4, 7, 11], "7": [0, 4, 7, 10], "m7": [0, 3, 7, 10],
    "min7": [0, 3, 7, 10], "dim7": [0, 3, 6, 9], "m7b5": [0, 3, 6, 10],
    "6": [0, 4, 7, 9], "m6": [0, 3, 7, 9],
}


def _is_roman(symbol):
    core = re.sub(r"[^a-zA-Z]", "", symbol)
    return core != "" and all(c in "ivIV" for c in core)


def _build_roman_chord(symbol, root, intervals, octave):
    s = symbol.strip()
    seventh = s.endswith("7")
    core = s[:-1] if seventh else s
    core = core.rstrip("o°+ø").lower()   # strip dim/aug/half-dim marks
    if core not in _ROMAN_DEGREE:
        raise ValueError("Unknown roman numeral %r" % (symbol,))
    deg = _ROMAN_DEGREE[core]
    steps = [0, 2, 4] + ([6] if seventh else [])
    # Build the chord by stacking diatonic thirds; quality comes from the scale.
    return [degree_to_pitch(root, intervals, deg + st, octave) for st in steps]


def _build_symbol_chord(symbol, octave):
    m = re.match(r"^([A-Ga-g][#b]?)(.*)$", symbol.strip())
    if not m:
        raise ValueError("Unparseable chord symbol %r" % (symbol,))
    pc = parse_key(m.group(1))
    qual = m.group(2)
    if qual not in _CHORD_QUALITIES:
        raise ValueError("Unknown chord quality %r in %r" % (qual, symbol))
    base = _octave_base(octave) + pc
    return [_clamp_pitch(base + iv) for iv in _CHORD_QUALITIES[qual]]


def build_chord(symbol, root, intervals, octave):
    """Build a chord (list of MIDI pitches). A roman numeral ('I', 'ii', 'V7')
    is resolved diatonically against (root, intervals); a chord symbol
    ('Cmaj7', 'Am7') is absolute and ignores the key."""
    if _is_roman(symbol):
        return _build_roman_chord(symbol, root, intervals, octave)
    return _build_symbol_chord(symbol, octave)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_composition_chords.py -q`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/composition_utils.py tests/test_composition_chords.py
git commit -m "feat: composition_utils chord model (roman + symbols)"
```

---

## Task 3: Generators - chord progression & bassline

**Files:**
- Modify: `ableton_mcp_max/composition_utils.py`
- Test: `tests/test_composition_generators.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_composition_generators.py
import random
import pytest
from ableton_mcp_max.composition_utils import (
    build_chord_progression, build_bassline, scale_pitches,
)

C_MAJOR = [0, 2, 4, 5, 7, 9, 11]


def test_chord_progression_exact_layout():
    notes = build_chord_progression(["I", "V"], 0, C_MAJOR, bars=2, octave=3)
    # 2 bars / 2 chords -> 4 beats each; I=C E G at t0, V=G B D at t4
    assert notes == [
        {"pitch": 60, "start_time": 0.0, "duration": 4.0, "velocity": 100},
        {"pitch": 64, "start_time": 0.0, "duration": 4.0, "velocity": 100},
        {"pitch": 67, "start_time": 0.0, "duration": 4.0, "velocity": 100},
        {"pitch": 67, "start_time": 4.0, "duration": 4.0, "velocity": 100},
        {"pitch": 71, "start_time": 4.0, "duration": 4.0, "velocity": 100},
        {"pitch": 74, "start_time": 4.0, "duration": 4.0, "velocity": 100},
    ]


def test_chord_progression_empty_raises():
    with pytest.raises(ValueError):
        build_chord_progression([], 0, C_MAJOR, bars=4, octave=3)


def test_bassline_root_follows_progression():
    notes = build_bassline(progression=["I", "IV"], style="root", root=0,
                           intervals=C_MAJOR, bars=2, octave=1)
    assert [n["pitch"] for n in notes] == [36, 41]   # C1, F1
    assert [n["start_time"] for n in notes] == [0.0, 4.0]


def test_bassline_no_progression_one_root_per_bar():
    notes = build_bassline(progression=None, style="root", root=0,
                           intervals=C_MAJOR, bars=2, octave=1)
    assert [n["pitch"] for n in notes] == [36, 36]
    assert [n["start_time"] for n in notes] == [0.0, 4.0]


def test_bassline_arp_in_chord():
    notes = build_bassline(progression=["I"], style="arp", root=0,
                           intervals=C_MAJOR, bars=1, octave=1, rng=random.Random(1))
    allowed = set(scale_pitches(0, C_MAJOR, 0, 127))
    assert all(n["pitch"] in allowed for n in notes)
    assert len(notes) == 3   # triad arpeggiated
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_composition_generators.py -q`
Expected: FAIL with `ImportError: cannot import name 'build_chord_progression'`

- [ ] **Step 3: Write minimal implementation** (append to `composition_utils.py`)

```python
_BAR_BEATS = 4.0   # 4/4 assumed


def _note(pitch, start, duration, velocity):
    return {
        "pitch": _clamp_pitch(pitch),
        "start_time": round(float(start), 6),
        "duration": round(float(duration), 6),
        "velocity": float(velocity),
    }


def make_rng(seed=None):
    """Seeded RNG: int seed -> reproducible; None -> fresh/system-seeded."""
    return random.Random(seed)


def build_chord_progression(progression, root, intervals, bars=4, octave=3,
                            durations=None, velocity=100):
    """Lay a chord per slot across `bars` bars (4/4). Returns note dicts."""
    if not progression:
        raise ValueError("progression must be a non-empty list")
    total = bars * _BAR_BEATS
    n = len(progression)
    if durations is None:
        durations = [total / n] * n
    notes = []
    t = 0.0
    for sym, dur in zip(progression, durations):
        for p in build_chord(sym, root, intervals, octave):
            notes.append(_note(p, t, dur, velocity))
        t += dur
    return notes


def build_bassline(progression=None, style="root", root=0, intervals=None,
                   bars=4, octave=1, rng=None):
    """Bass notes. With a progression, follow the chord roots; without one, one
    scale-root per bar. Styles: root, octaves, arp, walking."""
    intervals = intervals or SCALE_INTERVALS["natural_minor"]
    rng = rng or make_rng()
    notes = []
    if not progression:
        rp = _octave_base(octave) + root
        for b in range(bars):
            notes.append(_note(rp, b * _BAR_BEATS, _BAR_BEATS, 100))
        return notes
    seg = (bars * _BAR_BEATS) / len(progression)
    for i, sym in enumerate(progression):
        chord = build_chord(sym, root, intervals, octave)
        base = chord[0]
        t0 = i * seg
        if style == "root":
            notes.append(_note(base, t0, seg, 100))
        elif style == "octaves":
            half = seg / 2.0
            notes.append(_note(base, t0, half, 100))
            notes.append(_note(base + 12, t0 + half, half, 90))
        elif style == "arp":
            step = seg / len(chord)
            for j, p in enumerate(chord):
                notes.append(_note(p, t0 + j * step, step, 95))
        elif style == "walking":
            nxt = build_chord(progression[(i + 1) % len(progression)],
                              root, intervals, octave)[0]
            quarters = max(1, int(round(seg)))
            pool = scale_pitches(root, intervals, min(base, nxt), max(base, nxt) + 1) or [base]
            for j in range(quarters):
                p = base if j == 0 else pool[min(j, len(pool) - 1)]
                notes.append(_note(p, t0 + j, 1.0, 90))
        else:
            raise ValueError("Unknown bassline style %r" % (style,))
    return notes
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_composition_generators.py -q`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/composition_utils.py tests/test_composition_generators.py
git commit -m "feat: composition_utils chord-progression + bassline generators"
```

---

## Task 4: Generators - melody & drum pattern

**Files:**
- Modify: `ableton_mcp_max/composition_utils.py`
- Test: `tests/test_composition_generators.py` (append)

- [ ] **Step 1: Write the failing test** (append to `tests/test_composition_generators.py`)

```python
from ableton_mcp_max.composition_utils import (
    build_melody, build_drum_pattern, GM_DRUMS,
)


def test_melody_in_scale_and_in_time():
    notes = build_melody(0, C_MAJOR, bars=2, contour="arch", density=0.6,
                         octave=4, rng=random.Random(42))
    allowed = set(scale_pitches(0, C_MAJOR, 0, 127))
    assert notes, "expected some notes"
    assert all(n["pitch"] in allowed for n in notes)
    assert all(0.0 <= n["start_time"] < 8.0 for n in notes)   # 2 bars = 8 beats


def test_melody_seed_is_reproducible():
    a = build_melody(0, C_MAJOR, bars=4, octave=4, rng=random.Random(7))
    b = build_melody(0, C_MAJOR, bars=4, octave=4, rng=random.Random(7))
    assert a == b


def test_drum_four_on_floor_has_kick_on_every_beat():
    notes = build_drum_pattern(style="four_on_floor", bars=1)
    kicks = sorted(n["start_time"] for n in notes if n["pitch"] == GM_DRUMS["kick"])
    assert kicks == [0.0, 1.0, 2.0, 3.0]
    assert all(n["pitch"] in set(GM_DRUMS.values()) for n in notes)


def test_drum_fill_is_deterministic_with_seed():
    a = build_drum_pattern(style="basic_rock", bars=2, fills=True, rng=random.Random(3))
    b = build_drum_pattern(style="basic_rock", bars=2, fills=True, rng=random.Random(3))
    assert a == b
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_composition_generators.py -q`
Expected: FAIL with `ImportError: cannot import name 'build_melody'`

- [ ] **Step 3: Write minimal implementation** (append to `composition_utils.py`)

```python
GM_DRUMS = {
    "kick": 36, "snare": 38, "closed_hat": 42, "open_hat": 46,
    "clap": 39, "rim": 37, "low_tom": 45, "mid_tom": 47, "hi_tom": 50,
    "crash": 49, "ride": 51,
}

_CONTOUR_TARGETS = {
    # fractional position 0..1 -> desired normalized height -1..1
    "up": lambda f: -1.0 + 2.0 * f,
    "down": lambda f: 1.0 - 2.0 * f,
    "arch": lambda f: 1.0 - abs(2.0 * f - 1.0) * 2.0 + 1.0 - 1.0,  # peak mid
    "valley": lambda f: abs(2.0 * f - 1.0) * 2.0 - 1.0,           # dip mid
    "random": lambda f: 0.0,
}


def build_melody(root, intervals, bars=4, contour="arch", density=0.5,
                 octave=4, rng=None):
    """A monophonic in-scale melody of eighth notes. `density` is the
    probability a slot sounds (vs rests). `contour` biases the pitch drift."""
    rng = rng or make_rng()
    if contour not in _CONTOUR_TARGETS:
        raise ValueError("Unknown contour %r" % (contour,))
    step = 0.5
    slots = int(round(bars * _BAR_BEATS / step))
    lo = _octave_base(octave)
    pitches = scale_pitches(root, intervals, lo, lo + 12)
    if not pitches:
        pitches = [lo]
    target_fn = _CONTOUR_TARGETS[contour]
    idx = len(pitches) // 2
    notes = []
    for s in range(slots):
        if rng.random() > density:
            continue
        frac = s / float(max(1, slots - 1))
        target_idx = int(round((target_fn(frac) + 1.0) / 2.0 * (len(pitches) - 1)))
        drift = rng.choice([-1, 0, 1])
        idx = max(0, min(len(pitches) - 1, (idx + drift + target_idx) // 2))
        notes.append(_note(pitches[idx], s * step, step, rng.randint(80, 110)))
    return notes


def _drum_bar(style, t0, accent_last_beat=False):
    out = []

    def hit(name, beat, vel):
        out.append(_note(GM_DRUMS[name], t0 + beat, 0.25, vel))

    if style == "four_on_floor":
        for b in range(4):
            hit("kick", b, 110)
        for e in range(8):
            hit("closed_hat", e * 0.5, 95 if e % 2 == 0 else 80)
        hit("snare", 1, 100)
        hit("snare", 3, 100)
    elif style == "basic_rock":
        hit("kick", 0, 110)
        hit("kick", 2, 105)
        hit("snare", 1, 100)
        hit("snare", 3, 100)
        for e in range(8):
            hit("closed_hat", e * 0.5, 90 if e % 2 == 0 else 75)
    elif style == "breakbeat":
        hit("kick", 0, 110)
        hit("kick", 1.5, 100)
        hit("kick", 2.5, 100)
        hit("snare", 1, 105)
        hit("snare", 3, 105)
        for e in range(8):
            hit("closed_hat", e * 0.5, 85)
    elif style == "hihat_8ths":
        hit("kick", 0, 110)
        hit("snare", 2, 100)
        for e in range(8):
            hit("closed_hat", e * 0.5, 90 if e % 2 == 0 else 75)
    elif style == "boom_bap":
        hit("kick", 0, 112)
        hit("kick", 2.5, 100)
        hit("snare", 1, 105)
        hit("snare", 3, 105)
        for e in range(8):
            hit("closed_hat", e * 0.5, 88 if e % 2 == 0 else 72)
    else:
        raise ValueError("Unknown drum style %r" % (style,))
    return out


def build_drum_pattern(style="four_on_floor", bars=4, fills=False, rng=None):
    """A drum pattern over `bars` bars using the GM drum map. With fills=True a
    seeded snare fill replaces beat 4 of the last bar."""
    rng = rng or make_rng()
    notes = []
    for b in range(bars):
        t0 = b * _BAR_BEATS
        bar = _drum_bar(style, t0)
        if fills and b == bars - 1:
            bar = [n for n in bar if n["start_time"] < t0 + 3.0]
            sub = rng.choice([0.25, 0.5])
            k = int(round(1.0 / sub))
            for j in range(k):
                bar.append(_note(GM_DRUMS["snare"], t0 + 3.0 + j * sub, sub,
                                 rng.randint(85, 120)))
        notes.extend(bar)
    return notes
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_composition_generators.py -q`
Expected: PASS (9 tests total in file)

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/composition_utils.py tests/test_composition_generators.py
git commit -m "feat: composition_utils melody + drum-pattern generators"
```

---

## Task 5: Transformers - humanize & quantize-to-scale

**Files:**
- Modify: `ableton_mcp_max/composition_utils.py`
- Test: `tests/test_composition_transformers.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_composition_transformers.py
import random
import pytest
from ableton_mcp_max.composition_utils import (
    humanize, quantize_to_scale,
)

C_MAJOR = [0, 2, 4, 5, 7, 9, 11]


def _notes():
    return [
        {"pitch": 60, "start_time": 0.0, "duration": 1.0, "velocity": 100},
        {"pitch": 61, "start_time": 1.0, "duration": 1.0, "velocity": 100},
    ]


def test_humanize_bounds_and_reproducible():
    a = humanize(_notes(), timing=0.05, velocity=10, rng=random.Random(5))
    b = humanize(_notes(), timing=0.05, velocity=10, rng=random.Random(5))
    assert a == b
    for orig, h in zip(_notes(), a):
        assert abs(h["start_time"] - orig["start_time"]) <= 0.05 + 1e-9
        assert h["start_time"] >= 0.0
        assert 1.0 <= h["velocity"] <= 127.0


def test_quantize_snaps_pitches_into_scale():
    out = quantize_to_scale(_notes(), 0, C_MAJOR)
    assert [n["pitch"] for n in out] == [60, 60]   # 61 (C#) -> 60 (C)
    # other fields preserved
    assert out[1]["start_time"] == 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_composition_transformers.py -q`
Expected: FAIL with `ImportError: cannot import name 'humanize'`

- [ ] **Step 3: Write minimal implementation** (append to `composition_utils.py`)

```python
def humanize(notes, timing=0.02, velocity=8, rng=None):
    """Jitter onset (+/- timing beats) and velocity (+/- velocity). Pure."""
    rng = rng or make_rng()
    out = []
    for n in notes:
        m = dict(n)
        st = float(n.get("start_time", 0.0)) + rng.uniform(-timing, timing)
        m["start_time"] = round(max(0.0, st), 6)
        v = float(n.get("velocity", 100)) + rng.uniform(-velocity, velocity)
        m["velocity"] = max(1.0, min(127.0, v))
        out.append(m)
    return out


def quantize_to_scale(notes, root, intervals):
    """Snap every note's pitch to the nearest in-scale tone. Pure."""
    out = []
    for n in notes:
        m = dict(n)
        m["pitch"] = snap_to_scale(int(n.get("pitch", 60)), root, intervals)
        out.append(m)
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_composition_transformers.py -q`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/composition_utils.py tests/test_composition_transformers.py
git commit -m "feat: composition_utils humanize + quantize-to-scale transformers"
```

---

## Task 6: Transformers - arpeggiate & harmonize

**Files:**
- Modify: `ableton_mcp_max/composition_utils.py`
- Test: `tests/test_composition_transformers.py` (append)

- [ ] **Step 1: Write the failing test** (append)

```python
from ableton_mcp_max.composition_utils import arpeggiate, harmonize


def _triad():
    # C E G all at t0 for 1 beat
    return [
        {"pitch": 60, "start_time": 0.0, "duration": 1.0, "velocity": 100},
        {"pitch": 64, "start_time": 0.0, "duration": 1.0, "velocity": 100},
        {"pitch": 67, "start_time": 0.0, "duration": 1.0, "velocity": 100},
    ]


def test_arpeggiate_up_sequences_pitches():
    out = arpeggiate(_triad(), mode="up", rate=0.25, gate=0.9)
    # span 1.0 / rate 0.25 = 4 steps cycling C E G C
    assert [n["pitch"] for n in out] == [60, 64, 67, 60]
    assert [n["start_time"] for n in out] == [0.0, 0.25, 0.5, 0.75]


def test_arpeggiate_down_reverses():
    out = arpeggiate(_triad(), mode="down", rate=0.5, gate=1.0)
    assert [n["pitch"] for n in out][:2] == [67, 64]


def test_harmonize_fixed_intervals_snapped_to_scale():
    src = [{"pitch": 60, "start_time": 0.0, "duration": 1.0, "velocity": 100}]
    out = harmonize(src, 0, C_MAJOR, intervals=[4])   # +4 semis = E (in scale)
    assert sorted(n["pitch"] for n in out) == [60, 64]


def test_harmonize_requires_exactly_one_mode():
    src = [{"pitch": 60, "start_time": 0.0, "duration": 1.0, "velocity": 100}]
    with pytest.raises(ValueError):
        harmonize(src, 0, C_MAJOR, intervals=[4], degrees=[2])
    with pytest.raises(ValueError):
        harmonize(src, 0, C_MAJOR)


def test_harmonize_scale_degrees_stay_diatonic():
    src = [{"pitch": 60, "start_time": 0.0, "duration": 1.0, "velocity": 100}]
    out = harmonize(src, 0, C_MAJOR, degrees=[2])   # a third up the scale = E
    assert sorted(n["pitch"] for n in out) == [60, 64]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_composition_transformers.py -q`
Expected: FAIL with `ImportError: cannot import name 'arpeggiate'`

- [ ] **Step 3: Write minimal implementation** (append to `composition_utils.py`)

```python
def _arp_order(pitches, mode, rng):
    if mode == "down":
        return list(reversed(pitches))
    if mode == "updown" and len(pitches) > 2:
        return list(pitches) + list(reversed(pitches[1:-1]))
    if mode == "random":
        seq = list(pitches)
        (rng or make_rng()).shuffle(seq)
        return seq
    return list(pitches)   # up / strum / updown(<=2)


def arpeggiate(notes, mode="up", rate=0.25, gate=0.9, rng=None):
    """Expand simultaneous notes (chords) into sequential notes. Notes sharing a
    start_time form a chord; each is played over the chord's duration at `rate`
    spacing. mode='strum' instead staggers onsets tightly, keeping sustain."""
    groups = {}
    for n in notes:
        groups.setdefault(round(float(n.get("start_time", 0.0)), 6), []).append(n)
    out = []
    for st in sorted(groups):
        chord = groups[st]
        pitches = sorted(set(int(n["pitch"]) for n in chord))
        span = max(float(n.get("duration", rate)) for n in chord)
        vel = float(chord[0].get("velocity", 100))
        if mode == "strum":
            for j, p in enumerate(_arp_order(pitches, "up", rng)):
                out.append(_note(p, st + j * (rate * 0.1), span, vel))
            continue
        order = _arp_order(pitches, mode, rng)
        steps = max(1, int(round(span / rate)))
        for k in range(steps):
            out.append(_note(order[k % len(order)], st + k * rate, rate * gate, vel))
    return out


def _shift_by_scale_degrees(pitch, degrees, scale_root, scale_intervals):
    snapped = snap_to_scale(pitch, scale_root, scale_intervals)
    members = sorted(set((scale_root + i) % 12 for i in scale_intervals))
    pc = snapped % 12
    base_idx = members.index(pc)
    n = len(members)
    oct_shift, new_idx = divmod(base_idx + degrees, n)
    new_pc = members[new_idx]
    return _clamp_pitch(snapped - pc + new_pc + 12 * oct_shift)


def harmonize(notes, scale_root, scale_intervals, intervals=None, degrees=None):
    """Add a harmony voice per note. Provide exactly ONE of:
    - intervals: fixed semitone offsets, each snapped into the scale.
    - degrees: scale-step offsets (kept diatonic).
    The original notes are preserved; harmony voices are added.

    Note: the scale is passed as scale_root/scale_intervals (not `intervals`,
    which is the harmonize semitone-offset argument) to avoid a name collision.
    The tests call harmonize(src, 0, C_MAJOR, intervals=[4]) - positionally
    scale_root=0, scale_intervals=C_MAJOR - so no test change is needed."""
    if (intervals is None) == (degrees is None):
        raise ValueError("provide exactly one of intervals / degrees")
    out = []
    for n in notes:
        out.append(dict(n))
        p = int(n.get("pitch", 60))
        if intervals is not None:
            for iv in intervals:
                m = dict(n)
                m["pitch"] = snap_to_scale(p + iv, scale_root, scale_intervals)
                out.append(m)
        else:
            for d in degrees:
                m = dict(n)
                m["pitch"] = _shift_by_scale_degrees(p, d, scale_root, scale_intervals)
                out.append(m)
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_composition_transformers.py -q`
Expected: PASS (7 tests total in file)

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/composition_utils.py tests/test_composition_transformers.py
git commit -m "feat: composition_utils arpeggiate + harmonize transformers"
```

---

## Task 7: Remote Script `get_song_scale` read command

**Files:**
- Modify: `remote_script/AbletonMCP/__init__.py` (dispatch near line 595; impl near line 821 after `_get_application_version`)

- [ ] **Step 1: Add the dispatch branch**

In `_process_command`, after the `get_application_version` branch (around line 595):

```python
            elif command_type == "get_song_scale":
                response["result"] = self._get_song_scale()
```

- [ ] **Step 2: Add the implementation method**

After `_get_application_version` (around line 829):

```python
    def _get_song_scale(self):
        """Report the set's current key/scale for control surfaces (read-only).
        scale_intervals is a list of semitone offsets from the root (e.g. Major
        -> [0,2,4,5,7,9,11]). Guarded: older Live or missing endpoints degrade to
        defaults rather than raising."""
        song = self._song
        result = {"scale_name": None, "root_note": 0, "scale_intervals": []}
        try:
            result["scale_name"] = song.scale_name
        except Exception:
            pass
        try:
            result["root_note"] = int(song.root_note)
        except Exception:
            pass
        try:
            result["scale_intervals"] = [int(i) for i in song.scale_intervals]
        except Exception:
            pass
        return result
```

- [ ] **Step 3: Syntax-check the Remote Script**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python -m py_compile remote_script/AbletonMCP/__init__.py`
Expected: no output (success)

- [ ] **Step 4: Commit**

```bash
git add remote_script/AbletonMCP/__init__.py
git commit -m "feat: remote script get_song_scale read command"
```

> **Live-verify (deferred to the live pass, Task 10):** after `bash scripts/install_remote_script.sh` + a Live bounce, the `get_song_scale` path is exercised by `generate_*` with no key/scale. Not offline-testable.

---

## Task 8: Server generator tools + shared helpers

**Files:**
- Modify: `ableton_mcp_max/server.py` (import near the other `*_utils` imports; helpers near other private helpers; tools in the clip/MIDI section after `add_notes_to_clip`)

- [ ] **Step 1: Add the import**

Near the top imports (where `clip_utils` is imported), add:

```python
from ableton_mcp_max import composition_utils as comp
```

- [ ] **Step 2: Add shared helpers** (place near `_ok`/`_err`)

```python
def _song_scale():
    """Best-effort read of the set's key/scale via the Remote Script. Returns a
    dict {scale_name, root_note, scale_intervals} or None on any failure."""
    try:
        ableton = get_ableton_connection()
        return ableton.send_command("get_song_scale", {})
    except Exception as e:
        logger.warning("get_song_scale failed: %s", e)
        return None


def _resolve_scale(key, scale):
    """Resolve (root, intervals): explicit params win; else read the set."""
    song_scale = None
    if key is None and scale is None:
        song_scale = _song_scale()
    return comp.resolve_key_scale(key=key, scale=scale, song_scale=song_scale)


def _emit_to_slot(track_index, clip_slot_index, notes, bars, replace):
    """Create the clip if the slot is empty, else require replace=True; then
    write `notes`. Returns the count written. Raises on an occupied slot when
    replace is False."""
    ableton = get_ableton_connection()
    info = ableton.send_command(
        "get_clip_info", {"track_index": track_index, "clip_index": clip_slot_index})
    has_clip = bool(info) and not (isinstance(info, dict) and info.get("error"))
    if has_clip:
        if not replace:
            raise ValueError("slot occupied; pass replace=true to overwrite")
        ableton.send_command("replace_clip_notes", {
            "track_index": track_index, "clip_index": clip_slot_index,
            "notes": [normalize_note(n) for n in notes]})
    else:
        ableton.send_command("create_clip", {
            "track_index": track_index, "clip_index": clip_slot_index,
            "length": float(bars) * 4.0})
        ableton.send_command("add_notes_to_clip", {
            "track_index": track_index, "clip_index": clip_slot_index,
            "notes": [normalize_note(n) for n in notes]})
    return len(notes)
```

> **Implementer note:** confirm `get_clip_info` on an empty slot returns a falsy/`error` payload (it routes through the same `_err`/`_ok` envelope). If instead it raises, wrap the `get_clip_info` call in try/except treating an exception as "no clip". Adjust `has_clip` accordingly. Verify against `get_clip_info` handler behavior before relying on the dict shape.

- [ ] **Step 3: Add the four generator tools** (after `add_notes_to_clip`, ~line 2043)

```python
@mcp.tool()
def generate_chord_progression(
    ctx: Context, track_index: int, clip_slot_index: int,
    progression: List[str], key: str = None, scale: str = None,
    bars: int = 4, octave: int = 3, durations: List[float] = None,
    replace: bool = False,
) -> str:
    """Generate a chord progression into a session clip slot. Creates the MIDI
    clip if the slot is empty (length = bars*4 beats), else requires replace=true.

    Parameters:
    - track_index / clip_slot_index: where to write
    - progression: roman numerals ('I','vi','IV','V') and/or chord symbols
      ('Cmaj7','Am7'); romans resolve diatonically to key/scale
    - key/scale: optional; if both omitted, the set's key/scale is read
    - bars: clip length in 4/4 bars (default 4)
    - octave: Ableton octave label, C3=60 (default 3)
    - durations: optional per-chord beat lengths (default: evenly split)
    - replace: overwrite an occupied slot (default false)
    """
    try:
        root, intervals = _resolve_scale(key, scale)
        notes = comp.build_chord_progression(
            progression, root, intervals, bars=bars, octave=octave,
            durations=durations)
        count = _emit_to_slot(track_index, clip_slot_index, notes, bars, replace)
        return _ok({"notes_added": count, "bars": bars,
                    "chords": len(progression)})
    except Exception as e:
        logger.error("Error generating chord progression: %s", e)
        return _err("Error generating chord progression: %s" % e)


@mcp.tool()
def generate_bassline(
    ctx: Context, track_index: int, clip_slot_index: int,
    progression: List[str] = None, style: str = "root",
    key: str = None, scale: str = None, bars: int = 4, octave: int = 1,
    seed: int = None, replace: bool = False,
) -> str:
    """Generate a bassline into a session clip slot. With a progression the bass
    follows the chord roots; without one it lays one scale-root per bar.

    Parameters:
    - progression: optional chord list (roman/symbol) for harmonic context
    - style: root | octaves | arp | walking (walking needs a progression)
    - key/scale: optional; if both omitted, the set's key/scale is read
    - octave: Ableton octave label (default 1)
    - seed: optional int for reproducible randomness
    - replace: overwrite an occupied slot
    """
    try:
        root, intervals = _resolve_scale(key, scale)
        notes = comp.build_bassline(
            progression=progression, style=style, root=root, intervals=intervals,
            bars=bars, octave=octave, rng=comp.make_rng(seed))
        count = _emit_to_slot(track_index, clip_slot_index, notes, bars, replace)
        return _ok({"notes_added": count, "bars": bars, "style": style})
    except Exception as e:
        logger.error("Error generating bassline: %s", e)
        return _err("Error generating bassline: %s" % e)


@mcp.tool()
def generate_melody(
    ctx: Context, track_index: int, clip_slot_index: int,
    key: str = None, scale: str = None, bars: int = 4,
    contour: str = "arch", density: float = 0.5, octave: int = 4,
    seed: int = None, replace: bool = False,
) -> str:
    """Generate an in-scale monophonic melody into a session clip slot.

    Parameters:
    - key/scale: optional; if both omitted, the set's key/scale is read
    - contour: up | down | arch | valley | random
    - density: 0..1 probability each eighth-note slot sounds (default 0.5)
    - octave: Ableton octave label (default 4 = around middle C)
    - seed: optional int for reproducible randomness
    - replace: overwrite an occupied slot
    """
    try:
        root, intervals = _resolve_scale(key, scale)
        notes = comp.build_melody(
            root, intervals, bars=bars, contour=contour, density=density,
            octave=octave, rng=comp.make_rng(seed))
        count = _emit_to_slot(track_index, clip_slot_index, notes, bars, replace)
        return _ok({"notes_added": count, "bars": bars, "contour": contour})
    except Exception as e:
        logger.error("Error generating melody: %s", e)
        return _err("Error generating melody: %s" % e)


@mcp.tool()
def generate_drum_pattern(
    ctx: Context, track_index: int, clip_slot_index: int,
    style: str = "four_on_floor", bars: int = 4, fills: bool = False,
    seed: int = None, replace: bool = False,
) -> str:
    """Generate a drum pattern (GM drum map) into a session clip slot. Intended
    for a Drum Rack track (kick=36, snare=38, closed hat=42, ...).

    Parameters:
    - style: four_on_floor | basic_rock | breakbeat | hihat_8ths | boom_bap
    - bars: clip length in 4/4 bars (default 4)
    - fills: add a seeded snare fill in the last bar
    - seed: optional int for reproducible randomness
    - replace: overwrite an occupied slot
    """
    try:
        notes = comp.build_drum_pattern(
            style=style, bars=bars, fills=fills, rng=comp.make_rng(seed))
        count = _emit_to_slot(track_index, clip_slot_index, notes, bars, replace)
        return _ok({"notes_added": count, "bars": bars, "style": style})
    except Exception as e:
        logger.error("Error generating drum pattern: %s", e)
        return _err("Error generating drum pattern: %s" % e)
```

- [ ] **Step 4: Syntax-check the server imports**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python -c "import ableton_mcp_max.server"`
Expected: no error

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/server.py
git commit -m "feat: server generator tools (chords/bass/melody/drums)"
```

---

## Task 9: Server transformer tools

**Files:**
- Modify: `ableton_mcp_max/server.py` (after the generator tools)

- [ ] **Step 1: Add a read-transform-write helper** (near `_emit_to_slot`)

```python
def _transform_clip(track_index, clip_slot_index, fn):
    """Read the clip's notes, apply fn(notes)->notes, write them back. Raises if
    the clip is empty/absent."""
    ableton = get_ableton_connection()
    result = ableton.send_command("get_clip_notes", {
        "track_index": track_index, "clip_index": clip_slot_index,
        "from_time": 0.0, "time_span": -1.0, "from_pitch": 0, "pitch_span": 128})
    notes = result.get("notes") if isinstance(result, dict) else result
    if not notes:
        raise ValueError("no notes in clip (empty or absent)")
    new_notes = fn([dict(n) for n in notes])
    ableton.send_command("replace_clip_notes", {
        "track_index": track_index, "clip_index": clip_slot_index,
        "notes": [normalize_note(n) for n in new_notes]})
    return len(new_notes)
```

> **Implementer note:** confirm the `get_clip_notes` payload shape (it returns the handler's result; inspect `_get_clip_notes` in the Remote Script - it may return a bare list or a dict with a `notes` key). The helper handles both; adjust if neither matches.

- [ ] **Step 2: Add the four transformer tools**

```python
@mcp.tool()
def humanize_clip(
    ctx: Context, track_index: int, clip_slot_index: int,
    timing: float = 0.02, velocity: float = 8.0, seed: int = None,
) -> str:
    """Humanize a clip: jitter note onsets (+/- timing beats) and velocities
    (+/- velocity). Rewrites the clip's notes in place.

    Parameters:
    - timing: max onset jitter in beats (default 0.02)
    - velocity: max velocity jitter (default 8)
    - seed: optional int for reproducible jitter
    """
    try:
        rng = comp.make_rng(seed)
        count = _transform_clip(
            track_index, clip_slot_index,
            lambda ns: comp.humanize(ns, timing=timing, velocity=velocity, rng=rng))
        return _ok({"notes": count})
    except Exception as e:
        logger.error("Error humanizing clip: %s", e)
        return _err("Error humanizing clip: %s" % e)


@mcp.tool()
def quantize_clip_to_scale(
    ctx: Context, track_index: int, clip_slot_index: int,
    key: str = None, scale: str = None,
) -> str:
    """Snap every note in a clip to the nearest in-scale pitch.

    Parameters:
    - key/scale: optional; if both omitted, the set's key/scale is read
    """
    try:
        root, intervals = _resolve_scale(key, scale)
        count = _transform_clip(
            track_index, clip_slot_index,
            lambda ns: comp.quantize_to_scale(ns, root, intervals))
        return _ok({"notes": count})
    except Exception as e:
        logger.error("Error quantizing clip to scale: %s", e)
        return _err("Error quantizing clip to scale: %s" % e)


@mcp.tool()
def arpeggiate_clip(
    ctx: Context, track_index: int, clip_slot_index: int,
    mode: str = "up", rate: float = 0.25, gate: float = 0.9, seed: int = None,
) -> str:
    """Arpeggiate a clip: expand simultaneous notes (chords) into sequential
    notes. Rewrites the clip's notes.

    Parameters:
    - mode: up | down | updown | random | strum
    - rate: step spacing in beats (default 0.25 = sixteenth)
    - gate: note length as a fraction of rate (default 0.9)
    - seed: optional int (only used by mode=random)
    """
    try:
        rng = comp.make_rng(seed)
        count = _transform_clip(
            track_index, clip_slot_index,
            lambda ns: comp.arpeggiate(ns, mode=mode, rate=rate, gate=gate, rng=rng))
        return _ok({"notes": count, "mode": mode})
    except Exception as e:
        logger.error("Error arpeggiating clip: %s", e)
        return _err("Error arpeggiating clip: %s" % e)


@mcp.tool()
def harmonize_clip(
    ctx: Context, track_index: int, clip_slot_index: int,
    intervals: List[int] = None, degrees: List[int] = None,
    key: str = None, scale: str = None,
) -> str:
    """Add a harmony voice to each note in a clip. Provide exactly ONE of
    intervals (fixed semitone offsets, snapped to scale) or degrees (scale-step
    offsets, kept diatonic).

    Parameters:
    - intervals: e.g. [4,7] adds a third and fifth above, snapped to scale
    - degrees: e.g. [2] adds a note two scale-steps up (a diatonic third)
    - key/scale: optional; if both omitted, the set's key/scale is read
    """
    try:
        root, scale_intervals = _resolve_scale(key, scale)
        count = _transform_clip(
            track_index, clip_slot_index,
            lambda ns: comp.harmonize(ns, root, scale_intervals,
                                      intervals=intervals, degrees=degrees))
        return _ok({"notes": count})
    except Exception as e:
        logger.error("Error harmonizing clip: %s", e)
        return _err("Error harmonizing clip: %s" % e)
```

- [ ] **Step 3: Syntax-check + full offline suite**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python -c "import ableton_mcp_max.server" && PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q`
Expected: import OK; full suite PASS (previous 518 + new composition tests)

- [ ] **Step 4: Commit**

```bash
git add ableton_mcp_max/server.py
git commit -m "feat: server transformer tools (humanize/quantize/arp/harmonize)"
```

---

## Task 10: Docs, counts, live-verify, PROGRESS

**Files:**
- Modify: `docs/index.md` (hand-edit counts), generated docs, `PROGRESS.md`

- [ ] **Step 1: Regenerate the tool docs**

Run:
```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python scripts/build_tool_index.py
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python scripts/gen_docs_site.py
```
Expected: `docs/tools/`, `docs/tools/index.md`, `commands/tool-index.md` regenerated; new tool count = 126.

- [ ] **Step 2: Hand-edit the hardcoded counts in `docs/index.md`**

Update all 5 hardcoded spots (description, tagline, two `stats__num`, the "exposes the N `@mcp.tool()`" line) from 118 → 126 and category count +1 (Composition). Verify:

Run: `grep -n "118\|17 categor\|16 categor" docs/index.md`
Expected: no stale `118`; counts read 126 + the new category total.

- [ ] **Step 3: Live-verify pass (requires RS reinstall + Live bounce)**

```bash
bash scripts/install_remote_script.sh
```
Then bounce Live (the `restart_live` MCP tool / `/ableton:restart`) and restart Claude Code (server.py changed). Using the AbletonDev tools against the open set:
1. `create_midi_track` (scratch).
2. `generate_chord_progression(track_index=<scratch>, clip_slot_index=0, progression=["I","V","vi","IV"])` with NO key/scale → exercises `get_song_scale`. `get_clip_notes` to confirm in-key triads.
3. `generate_bassline(..., clip_slot_index=1, progression=["I","V","vi","IV"], style="root")`.
4. `generate_melody(..., clip_slot_index=2, seed=42)`; `generate_drum_pattern(..., clip_slot_index=3, style="four_on_floor")`.
5. `humanize_clip` then `quantize_clip_to_scale` on slot 2; `arpeggiate_clip` and `harmonize_clip` on slot 0 (use replace where needed).
6. `delete_track` the scratch track to clean up.

Record exact results (key read back, note counts, any surprises) in PROGRESS.md.

- [ ] **Step 4: Update PROGRESS.md**

Add a top section dated 2026-06-16 describing the composition layer: 8 tools + `get_song_scale`, `composition_utils.py`, tool count 118→126, offline suite total, live-verify results. Note the release is still pending (bundles #0 + gap C + #1).

- [ ] **Step 5: Commit**

```bash
git add docs/ commands/tool-index.md PROGRESS.md
git commit -m "docs: composition layer tools + counts (118->126)"
```

---

## Self-Review Notes (addressed)

- **Spec coverage:** all 8 tools (Tasks 3-6 pure + Tasks 8-9 wiring), `get_song_scale` (Task 7), key/scale auto-read (helpers in Task 8), seed determinism (Tasks 4-6 tests), emit/overwrite (`_emit_to_slot`), transformer empty-clip error (`_transform_clip`), docs/counts (Task 10). Covered.
- **Parameter-name collision** between scale-`intervals` and harmonize-`intervals` is called out explicitly in Task 6 with the corrected `harmonize(notes, scale_root, scale_intervals, intervals=None, degrees=None)` signature; the server tool (Task 9) passes them positionally, consistent.
- **Live-only pieces** (`get_song_scale`, all clip writes) are isolated to Tasks 7-10; the pure module (Tasks 1-6) is fully offline-tested first.
- **Unverified payload shapes** (`get_clip_info` empty-slot, `get_clip_notes` list-vs-dict) are flagged with implementer notes to confirm against the actual handlers rather than assumed silently.
