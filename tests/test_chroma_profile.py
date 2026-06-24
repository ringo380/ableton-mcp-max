import json
import math
import os
import struct
import subprocess
import wave

import pytest

_BREW_PY = "/opt/homebrew/bin/python3"
_SCRIPT = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                       "scripts", "chroma_profile.py")


def _has_librosa():
    if not os.path.exists(_BREW_PY):
        return False
    r = subprocess.run([_BREW_PY, "-c", "import librosa"],
                       capture_output=True)
    return r.returncode == 0


def _write_tone(path, freq, seconds=2.0, sr=22050):
    with wave.open(path, "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        frames = bytearray()
        for i in range(int(seconds * sr)):
            v = int(0.6 * 32767 * math.sin(2 * math.pi * freq * i / sr))
            frames += struct.pack("<h", v)
        w.writeframes(bytes(frames))


@pytest.mark.skipif(not _has_librosa(), reason="brew librosa unavailable")
def test_chroma_profile_detects_a440(tmp_path):
    wav = str(tmp_path / "a440.wav")
    _write_tone(wav, 440.0)  # A4 -> pitch class A = index 9
    payload = json.dumps([{"path": wav, "transpose": 0}])
    r = subprocess.run([_BREW_PY, _SCRIPT], input=payload,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["analyzed"] == 1 and out["skipped"] == 0
    assert len(out["profile"]) == 12
    assert out["profile"].index(max(out["profile"])) == 9  # A


@pytest.mark.skipif(not _has_librosa(), reason="brew librosa unavailable")
def test_chroma_profile_skips_bad_file(tmp_path):
    bad = str(tmp_path / "not_audio.wav")
    with open(bad, "w") as f:
        f.write("nonsense")
    payload = json.dumps([{"path": bad, "transpose": 0}])
    r = subprocess.run([_BREW_PY, _SCRIPT], input=payload,
                       capture_output=True, text=True, timeout=120)
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["analyzed"] == 0 and out["skipped"] == 1
    assert out["profile"] == [0.0] * 12
