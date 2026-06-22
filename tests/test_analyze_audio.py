import json
import os
import subprocess
import sys
import wave
import struct
import math
import pytest

BREW_PY = "/opt/homebrew/bin/python3"
SCRIPT = os.path.join(os.path.dirname(__file__), "..", "scripts", "analyze_audio.py")


def _librosa_available():
    if not os.path.exists(BREW_PY):
        return False
    r = subprocess.run([BREW_PY, "-c", "import librosa"], capture_output=True)
    return r.returncode == 0


def _write_sine_wav(path, freq=440.0, seconds=2.0, rate=22050):
    with wave.open(path, "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = b"".join(
            struct.pack("<h", int(0.3 * 32767 * math.sin(2 * math.pi * freq * n / rate)))
            for n in range(int(seconds * rate)))
        w.writeframes(frames)


@pytest.mark.skipif(not _librosa_available(), reason="librosa not in brew python")
def test_analyze_audio_emits_expected_json(tmp_path):
    wav = str(tmp_path / "tone.wav")
    _write_sine_wav(wav)
    out = subprocess.run([BREW_PY, SCRIPT, wav], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    data = json.loads(out.stdout.strip().splitlines()[-1])
    assert isinstance(data["tempo"], (int, float))
    assert data["key_pitch_class"] in [
        "C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    assert data["mode"] in ("major", "minor")
