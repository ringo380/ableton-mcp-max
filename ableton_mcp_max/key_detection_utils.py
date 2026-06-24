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
