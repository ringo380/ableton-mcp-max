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


# ---------------------------------------------------------------------------
# Chord model
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Note-generation helpers
# ---------------------------------------------------------------------------

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
    if durations is not None and len(durations) != len(progression):
        raise ValueError("durations length must match progression length")
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
    scale-root per bar. Styles: root, octaves, arp, walking.
    rng is used only by the 'arp'/random styles; root/octaves/walking are deterministic."""
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
            # 4/4 assumed: quarter-note steps through scale tones toward the
            # next chord's root, the downbeat anchored to this chord's root.
            pool = scale_pitches(root, intervals, min(base, nxt), max(base, nxt) + 1) or [base]
            j = 0
            t = t0
            while t < t0 + seg - 1e-9:
                dur = min(1.0, t0 + seg - t)
                p = base if j == 0 else pool[min(j, len(pool) - 1)]
                notes.append(_note(p, t, dur, 90))
                t += 1.0
                j += 1
        else:
            raise ValueError("Unknown bassline style %r" % (style,))
    return notes


GM_DRUMS = {
    "kick": 36, "snare": 38, "closed_hat": 42, "open_hat": 46,
    "clap": 39, "rim": 37, "low_tom": 45, "mid_tom": 47, "hi_tom": 50,
    "crash": 49, "ride": 51,
}

_CONTOUR_TARGETS = {
    # fractional position 0..1 -> desired normalized height -1..1
    "up": lambda f: -1.0 + 2.0 * f,
    "down": lambda f: 1.0 - 2.0 * f,
    "arch": lambda f: 1.0 - abs(2.0 * f - 1.0) * 2.0,    # peak mid, low ends
    "valley": lambda f: abs(2.0 * f - 1.0) * 2.0 - 1.0,  # dip mid, high ends
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
        # Blend current index with the contour target plus +/-1 noise. This is a
        # contour-biased step (pulls toward the target each slot), not a gradual
        # free walk, so a strong contour reaches its extreme within a bar or two.
        idx = max(0, min(len(pitches) - 1, (idx + drift + target_idx) // 2))
        notes.append(_note(pitches[idx], s * step, step, rng.randint(80, 110)))
    return notes


def _drum_bar(style, t0):
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
            # Clear the last beat (3.0 onward, including the 3.5 off-beat hat) to
            # make room for the fill.
            bar = [n for n in bar if n["start_time"] < t0 + 3.0]
            sub = rng.choice([0.25, 0.5])
            k = int(round(1.0 / sub))
            for j in range(k):
                bar.append(_note(GM_DRUMS["snare"], t0 + 3.0 + j * sub, sub,
                                 rng.randint(85, 120)))
        notes.extend(bar)
    return notes


# ---------------------------------------------------------------------------
# Clip transformers
# ---------------------------------------------------------------------------

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
    spacing. mode='strum' instead staggers onsets tightly, keeping sustain.
    Modes: up, down, updown, random, strum.
    Single (non-chord) notes pass through unchanged."""
    groups = {}
    for n in notes:
        groups.setdefault(round(float(n.get("start_time", 0.0)), 6), []).append(n)
    out = []
    for st in sorted(groups):
        chord = groups[st]
        pitches = sorted(set(int(n["pitch"]) for n in chord))
        span = max(float(n.get("duration", rate)) for n in chord)
        vel = float(chord[0].get("velocity", 100))
        if len(pitches) == 1:
            # A lone note is not a chord: pass it through at its own duration
            # rather than re-triggering it. So arpeggiate is safe on a clip that
            # mixes chords and single notes -- only chords get expanded.
            out.append(_note(pitches[0], st, span, vel))
            continue
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

    The scale is passed as scale_root/scale_intervals (not `intervals`, which is
    the harmonize semitone-offset argument) to avoid a name collision."""
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
