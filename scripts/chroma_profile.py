#!/usr/bin/env python3
"""Combined 12-bin chroma profile for a set of audio files.

Run under brew Python (has librosa); NOT the server uv venv. Reads a JSON array
on stdin: [{"path": str, "transpose": int}, ...]. Prints one JSON line:
{"profile": [12 floats], "analyzed": int, "skipped": int}. Per-file decode
failures increment "skipped" and do not abort. On total failure prints
{"error": "..."} and exits 1.

Each file's mean chroma is L1-normalized then rotated by its transpose
(out[(i+transpose)%12] += chroma[i]) before summing, so loud/long clips do not
dominate and clip transpose is honored. Mirrors scripts/analyze_audio.py."""

import json
import sys


def main():
    try:
        items = json.loads(sys.stdin.read() or "[]")
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"error": "bad stdin json: %s" % e}))
        return 1
    try:
        import librosa
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"error": "librosa unavailable: %s" % e}))
        return 1

    profile = [0.0] * 12
    analyzed = 0
    skipped = 0
    for item in items:
        path = item.get("path")
        transpose = int(item.get("transpose", 0))
        try:
            y, sr = librosa.load(path, mono=True)
            chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
            mean = chroma.mean(axis=1).tolist()
            total = sum(mean)
            if total <= 0:
                skipped += 1
                continue
            for i in range(12):
                profile[(i + transpose) % 12] += mean[i] / total
            analyzed += 1
        except Exception:  # noqa: BLE001 - skip undecodable files
            skipped += 1
    print(json.dumps({"profile": profile, "analyzed": analyzed,
                      "skipped": skipped}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
