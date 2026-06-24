"""Pure, stdlib-only key detection (Krumhansl-Schmuckler pitch-class
correlation). Imported by server.py only. No Live, no I/O, no numpy."""

PITCH_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

KS_MAJOR = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
KS_MINOR = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]


def correlation(a, b):
    """Pearson correlation; 0.0 if either input is constant."""
    n = len(a)
    ma = sum(a) / n
    mb = sum(b) / n
    num = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    da = sum((a[i] - ma) ** 2 for i in range(n)) ** 0.5
    db = sum((b[i] - mb) ** 2 for i in range(n)) ** 0.5
    return num / (da * db) if da and db else 0.0


def key_name(root_pc, mode):
    return "%s %s" % (PITCH_NAMES[root_pc % 12], mode)


def relative_key(root_pc, mode):
    if mode == "major":
        return ((root_pc + 9) % 12, "minor")
    return ((root_pc + 3) % 12, "major")


def detect_key(hist, top_n=5):
    """Correlate `hist` (12-bin pitch-class histogram) against all 24 rotated
    KS profiles. Returns ranked candidates with gap-normalized confidence."""
    cands = []
    for tonic in range(12):
        rot = hist[tonic:] + hist[:tonic]
        for mode, profile in (("major", KS_MAJOR), ("minor", KS_MINOR)):
            cands.append({
                "key": key_name(tonic, mode),
                "mode": mode,
                "root_pc": tonic,
                "score": correlation(rot, profile),
            })
    cands.sort(key=lambda c: c["score"], reverse=True)
    scores = [c["score"] for c in cands]
    top, lo = scores[0], scores[-1]
    mean = sum(scores) / len(scores)
    denom = (top - lo) or 1.0
    conf = max(0.0, min(1.0, (top - mean) / denom))
    for c in cands:
        c["confidence"] = round(conf, 4) if c is cands[0] else round(
            max(0.0, min(1.0, (c["score"] - mean) / denom)), 4)
        c["score"] = round(c["score"], 4)
    return cands[:min(top_n, 24)]


def histogram_from_notes(notes, transpose=0):
    """Build a 12-bin pitch-class histogram from MIDI notes.

    Each note: {"pitch": int, "duration": float, "velocity": float}
    Bin = (pitch + transpose) % 12
    Weight = duration * (velocity / 127.0)
    """
    hist = [0.0] * 12
    for n in notes:
        pc = (int(n["pitch"]) + transpose) % 12
        hist[pc] += float(n.get("duration", 0.0)) * (float(n.get("velocity", 0.0)) / 127.0)
    return hist


def histogram_from_chroma(profile, transpose=0):
    """Rotate a 12-bin chroma profile by transpose.

    out[(i + transpose) % 12] += profile[i]
    """
    out = [0.0] * 12
    for i in range(12):
        out[(i + transpose) % 12] += float(profile[i])
    return out


def _l1(hist):
    """L1-normalize a histogram; return None if sum <= 0 (empty)."""
    s = sum(hist)
    if s <= 0:
        return None
    return [x / s for x in hist]


def combine(midi_hist, audio_hist, audio_weight=0.5):
    """Blend two histograms with L1 normalization.

    Each input is L1-normalized independently. An all-zero source is treated as
    empty and is ignored (the other passes through normalized). Both empty
    returns [0.0] * 12. Otherwise: (1 - audio_weight) * midi + audio_weight * audio.
    """
    m = _l1(midi_hist)
    a = _l1(audio_hist)
    if m is None and a is None:
        return [0.0] * 12
    if a is None:
        return m
    if m is None:
        return a
    w = max(0.0, min(1.0, audio_weight))
    return [(1.0 - w) * m[i] + w * a[i] for i in range(12)]
