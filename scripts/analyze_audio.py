#!/usr/bin/env python3
"""Estimate tempo and musical key of an audio file with librosa.

Run under brew Python (has librosa); NOT the server uv venv. Prints one JSON
line: {"tempo": float, "key_pitch_class": str, "mode": "major"|"minor"}.
On error prints {"error": "..."} and exits 1.

Key detection: chroma energy correlated against Krumhansl-Schmuckler major and
minor profiles (per ~/.claude/notes/audio-analysis.md); best-correlating
rotation picks the pitch class, best profile picks the mode.
"""

import json
import sys

PITCHES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# Krumhansl-Schmuckler key profiles.
MAJOR = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
MINOR = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]


def _corr(a, b):
    n = len(a)
    ma = sum(a) / n
    mb = sum(b) / n
    num = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    da = sum((a[i] - ma) ** 2 for i in range(n)) ** 0.5
    db = sum((b[i] - mb) ** 2 for i in range(n)) ** 0.5
    return num / (da * db) if da and db else 0.0


def main(argv):
    if len(argv) < 2:
        print(json.dumps({"error": "usage: analyze_audio.py <audio_path>"}))
        return 1
    try:
        import librosa
        import numpy as np

        y, sr = librosa.load(argv[1], mono=True)
        tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
        tempo = float(np.atleast_1d(tempo)[0])

        chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
        profile = chroma.mean(axis=1).tolist()

        best = (-2.0, "C", "major")
        for i in range(12):
            rot = profile[i:] + profile[:i]
            cmaj = _corr(rot, MAJOR)
            cmin = _corr(rot, MINOR)
            if cmaj > best[0]:
                best = (cmaj, PITCHES[i], "major")
            if cmin > best[0]:
                best = (cmin, PITCHES[i], "minor")

        print(json.dumps({
            "tempo": round(tempo, 2),
            "key_pitch_class": best[1],
            "mode": best[2],
        }))
        return 0
    except Exception as e:  # noqa: BLE001 - report any failure as JSON
        print(json.dumps({"error": str(e)}))
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
