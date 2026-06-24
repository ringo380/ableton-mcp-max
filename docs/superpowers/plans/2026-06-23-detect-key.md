# detect_key Implementation Plan (Plan A: MIDI + offline audio)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only `detect_key` MCP tool that infers the most likely musical key of the open Live set from MIDI notes + offline audio files, independent of Live's configured scale.

**Architecture:** A pure, unit-tested module (`key_detection_utils.py`) holds Krumhansl-Schmuckler key profiles, pitch-class histogram builders, correlation, and naming. Audio chroma is extracted by a brew-Python subprocess (`scripts/chroma_profile.py`) returning a 12-bin profile (the server's `uv` venv has no librosa). A new Remote Script read (`get_clip_contents`) enumerates clips with metadata. The `detect_key` tool orchestrates: gather MIDI notes + audio profile, blend, correlate, return ranked candidates + evidence.

**Tech Stack:** Python 3 (server, pure stdlib for the module), librosa under brew Python (subprocess only), Ableton Remote Script (Py2/3.7-safe), pytest, uv.

## Global Constraints

- Pure `*_utils` modules are imported by **server.py only**; the Remote Script runs in Live's own Python and CANNOT import them. Resolve/normalize on the server; the RS handler only reads.
- `key_detection_utils.py` must be **stdlib-only** (no numpy/librosa) so it loads in the `uv` venv and tests run offline.
- Remote Script code must be **Py2/3.7-safe**: `%`-formatting only, no f-strings, no `match`, no `X | Y` unions. Probe audio-only clip attrs with `try/except` (Live raises `RuntimeError`, not `AttributeError`).
- Audio analysis runs under brew Python at `/opt/homebrew/bin/python3` (`server._BREW_PY`); the script must degrade to a JSON error on any failure and exit nonzero, never raise to the caller.
- Pitch-class convention: C = 0. `PITCH_NAMES = ["C","C#","D","D#","E","F","F#","G","G#","A","A#","B"]` (matches `scripts/analyze_audio.py`).
- Transpose convention (both MIDI and audio): a clip transposed up by `t` semitones maps source bin `i` to sounding pitch class `(i + t) % 12`.
- KS profile values (copy verbatim, from `scripts/analyze_audio.py`):
  - `KS_MAJOR = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]`
  - `KS_MINOR = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]`
- Tool output uses the uniform envelope: success `server._ok(data)`, failure `server._err(msg)`.
- Test command: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q`
- Syntax gates: `uv run python -c "import ableton_mcp_max.server"` and `uv run python -m py_compile remote_script/AbletonMCP/__init__.py`.
- `source="tap"` is out of scope for this plan (Plan B); `detect_key` returns `_err("tap source not yet supported")` for it.

---

### Task 1: Pure module — KS profiles, correlation, detection, naming

**Files:**
- Create: `ableton_mcp_max/key_detection_utils.py`
- Test: `tests/test_key_detection_utils.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `PITCH_NAMES: list[str]` (len 12), `KS_MAJOR`, `KS_MINOR` (len 12 floats)
  - `correlation(a: list[float], b: list[float]) -> float` (Pearson; 0.0 if either is constant)
  - `detect_key(hist: list[float], top_n: int = 5) -> list[dict]` — each dict `{"key": str, "mode": "major"|"minor", "root_pc": int, "score": float, "confidence": float}`, sorted by `score` desc, length `min(top_n, 24)`
  - `key_name(root_pc: int, mode: str) -> str` (e.g. `"A minor"`)
  - `relative_key(root_pc: int, mode: str) -> tuple[int, str]`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_key_detection_utils.py
import ableton_mcp_max.key_detection_utils as kd


def test_pitch_names_and_profiles():
    assert kd.PITCH_NAMES[0] == "C" and kd.PITCH_NAMES[9] == "A"
    assert len(kd.KS_MAJOR) == 12 and len(kd.KS_MINOR) == 12


def test_correlation_constant_is_zero():
    assert kd.correlation([1, 1, 1], [1, 2, 3]) == 0.0


def test_detect_key_c_major_profile_ranks_c_major_first():
    # A histogram shaped like the C-major profile must detect C major.
    top = kd.detect_key(kd.KS_MAJOR, top_n=3)
    assert top[0]["key"] == "C major"
    assert top[0]["root_pc"] == 0 and top[0]["mode"] == "major"
    assert 0.0 <= top[0]["confidence"] <= 1.0


def test_detect_key_a_minor_profile_ranks_a_minor_first():
    # Rotate the minor profile so tonic A (pc 9) sits at bin 9.
    hist = kd.KS_MINOR[-9:] + kd.KS_MINOR[:-9]
    top = kd.detect_key(hist, top_n=5)
    assert top[0]["key"] == "A minor"


def test_detect_key_flat_histogram_low_confidence():
    top = kd.detect_key([1.0] * 12, top_n=5)
    assert top[0]["confidence"] < 0.2


def test_naming_and_relative():
    assert kd.key_name(9, "minor") == "A minor"
    assert kd.relative_key(0, "major") == (9, "minor")
    assert kd.relative_key(9, "minor") == (0, "major")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q tests/test_key_detection_utils.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'ableton_mcp_max.key_detection_utils'`

- [ ] **Step 3: Write minimal implementation**

```python
# ableton_mcp_max/key_detection_utils.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q tests/test_key_detection_utils.py`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/key_detection_utils.py tests/test_key_detection_utils.py
git commit -m "feat(key): KS key profiles, correlation, detect_key, naming"
```

---

### Task 2: Pure module — histogram builders + combine

**Files:**
- Modify: `ableton_mcp_max/key_detection_utils.py`
- Test: `tests/test_key_detection_utils.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces:
  - `histogram_from_notes(notes: list[dict], transpose: int = 0) -> list[float]` — each note `{"pitch": int, "duration": float, "velocity": float}`; bin = `(pitch + transpose) % 12`; weight = `duration * (velocity / 127.0)`
  - `histogram_from_chroma(profile: list[float], transpose: int = 0) -> list[float]` — rotate so `out[(i + transpose) % 12] += profile[i]`
  - `combine(midi_hist: list[float], audio_hist: list[float], audio_weight: float = 0.5) -> list[float]` — L1-normalize each non-empty source, blend `(1 - w) * midi + w * audio`; an all-zero source counts as empty and the other passes through normalized

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_key_detection_utils.py
def test_histogram_from_notes_weights_and_transpose():
    notes = [
        {"pitch": 60, "duration": 1.0, "velocity": 127},  # C
        {"pitch": 64, "duration": 2.0, "velocity": 127},  # E, double weight
    ]
    h = kd.histogram_from_notes(notes)
    assert h[0] == 1.0 and h[4] == 2.0 and sum(h) == 3.0
    ht = kd.histogram_from_notes(notes, transpose=2)  # up a tone: C->D, E->F#
    assert ht[2] == 1.0 and ht[6] == 2.0


def test_histogram_from_chroma_rotates():
    prof = [0.0] * 12
    prof[0] = 1.0  # energy on C
    out = kd.histogram_from_chroma(prof, transpose=3)  # C -> D#
    assert out[3] == 1.0 and sum(out) == 1.0


def test_combine_weights():
    midi = [1.0] + [0.0] * 11        # all on C
    audio = [0.0] * 9 + [1.0, 0, 0]  # all on A (pc 9)
    only_midi = kd.combine(midi, audio, audio_weight=0.0)
    assert only_midi[0] == 1.0 and only_midi[9] == 0.0
    only_audio = kd.combine(midi, audio, audio_weight=1.0)
    assert only_audio[9] == 1.0 and only_audio[0] == 0.0
    blended = kd.combine(midi, audio, audio_weight=0.5)
    assert abs(blended[0] - 0.5) < 1e-9 and abs(blended[9] - 0.5) < 1e-9


def test_combine_empty_source_passthrough():
    midi = [2.0] + [0.0] * 11
    out = kd.combine(midi, [0.0] * 12, audio_weight=0.5)
    assert abs(out[0] - 1.0) < 1e-9  # normalized midi, audio ignored
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q tests/test_key_detection_utils.py -k "histogram or combine"`
Expected: FAIL — `AttributeError: module ... has no attribute 'histogram_from_notes'`

- [ ] **Step 3: Write minimal implementation**

```python
# add to ableton_mcp_max/key_detection_utils.py
def histogram_from_notes(notes, transpose=0):
    hist = [0.0] * 12
    for n in notes:
        pc = (int(n["pitch"]) + transpose) % 12
        hist[pc] += float(n.get("duration", 0.0)) * (float(n.get("velocity", 0.0)) / 127.0)
    return hist


def histogram_from_chroma(profile, transpose=0):
    out = [0.0] * 12
    for i in range(12):
        out[(i + transpose) % 12] += float(profile[i])
    return out


def _l1(hist):
    s = sum(hist)
    if s <= 0:
        return None
    return [x / s for x in hist]


def combine(midi_hist, audio_hist, audio_weight=0.5):
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q tests/test_key_detection_utils.py`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/key_detection_utils.py tests/test_key_detection_utils.py
git commit -m "feat(key): note/chroma histogram builders + normalized combine"
```

---

### Task 3: Audio chroma subprocess (brew Python)

**Files:**
- Create: `scripts/chroma_profile.py`
- Test: `tests/test_chroma_profile.py`

**Interfaces:**
- Consumes: nothing (standalone script run under brew Python).
- Produces: CLI contract — reads a JSON array on **stdin**: `[{"path": str, "transpose": int}, ...]`. Prints ONE JSON line to stdout: `{"profile": [12 floats], "analyzed": int, "skipped": int}`. On total failure prints `{"error": "..."}` and exits 1. Per-file decode failures increment `skipped` and do not abort.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_chroma_profile.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q tests/test_chroma_profile.py`
Expected: FAIL — `FileNotFoundError`/nonzero exit (script does not exist). If brew librosa is absent both tests SKIP — that is acceptable; proceed to Step 3.

- [ ] **Step 3: Write minimal implementation**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q tests/test_chroma_profile.py`
Expected: PASS (2 passed) — or SKIPPED if brew librosa is unavailable on this machine.

- [ ] **Step 5: Commit**

```bash
git add scripts/chroma_profile.py tests/test_chroma_profile.py
git commit -m "feat(key): brew-python chroma_profile subprocess for audio clips"
```

---

### Task 4: Remote Script — `get_clip_contents` bulk read

**Files:**
- Modify: `remote_script/AbletonMCP/__init__.py` (add an `elif` branch in `_process_command` and a `_get_clip_contents` method near `_get_clip_info` at ~line 2254)

**Interfaces:**
- Consumes: nothing.
- Produces: command `get_clip_contents` (no params) → `{"clips": [{"track_index": int, "clip_index": int, "location": "session"|"arrangement", "is_midi": bool, "length": float, "pitch_coarse": int, "file_path": str|None}]}`

- [ ] **Step 1: Add the dispatch branch**

In `_process_command`, alongside the other read commands (e.g. near the `get_clip_info` branch around line 785), add:

```python
            elif command_type == "get_clip_contents":
                response["result"] = self._get_clip_contents()
```

- [ ] **Step 2: Add the handler method**

Add this method next to `_get_clip_info` (Py2/3.7-safe, try/except probes):

```python
    def _get_clip_contents(self):
        """Enumerate every clip (session slots + arrangement) with the metadata
        key detection needs. Pure read; audio-only attrs probed via try/except
        (Live raises RuntimeError -- not AttributeError -- on MIDI clips)."""
        clips = []

        def _emit(clip, track_index, clip_index, location):
            if clip is None:
                return
            entry = {
                "track_index": track_index,
                "clip_index": clip_index,
                "location": location,
                "is_midi": bool(clip.is_midi_clip),
                "length": clip.length,
                "pitch_coarse": 0,
                "file_path": None,
            }
            try:
                entry["pitch_coarse"] = int(clip.pitch_coarse)
            except Exception:
                pass
            try:
                if clip.is_audio_clip:
                    entry["file_path"] = clip.file_path
            except Exception:
                pass
            clips.append(entry)

        for t_index, track in enumerate(self._song.tracks):
            try:
                for s_index, slot in enumerate(track.clip_slots):
                    if slot.has_clip:
                        _emit(slot.clip, t_index, s_index, "session")
            except Exception:
                pass
            try:
                for a_index, clip in enumerate(track.arrangement_clips):
                    _emit(clip, t_index, a_index, "arrangement")
            except Exception:
                pass
        return {"clips": clips}
```

- [ ] **Step 3: Syntax-gate the Remote Script**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python -m py_compile remote_script/AbletonMCP/__init__.py`
Expected: no output (exit 0).

- [ ] **Step 4: Commit**

```bash
git add remote_script/AbletonMCP/__init__.py
git commit -m "feat(key): get_clip_contents remote-script bulk read"
```

> Note: this handler needs Live to exercise; it is verified live in Task 6 (reinstall RS + reopen Live per the restart protocol). Offline gate is py_compile only.

---

### Task 5: `detect_key` tool + `_run_chroma` helper

**Files:**
- Modify: `ableton_mcp_max/server.py` (import the module near the other `*_utils` imports; add `_run_chroma` near `_run_analysis` ~line 5680; add the `@mcp.tool()` near the other clip/analysis tools)
- Test: `tests/test_detect_key_tool.py`

**Interfaces:**
- Consumes: `key_detection_utils` (Task 1, 2), `scripts/chroma_profile.py` (Task 3), command `get_clip_contents` (Task 4), existing `get_clip_notes`, `_song_scale`, `_ensure_local`, `_ok`, `_err`, `_BREW_PY`.
- Produces: MCP tool `detect_key(ctx, source="auto", audio_weight=0.5, top_n=5) -> str`; helper `_run_chroma(items, timeout=180) -> dict | None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_detect_key_tool.py
import json
import ableton_mcp_max.server as server


class _Conn:
    """Fake connection: serves get_clip_contents + per-clip get_clip_notes."""
    def __init__(self, clips, notes_by_clip, song_scale=None):
        self._clips = clips
        self._notes = notes_by_clip
        self._scale = song_scale

    def send_command(self, command_type, params=None, **kw):
        if command_type == "get_clip_contents":
            return {"clips": self._clips}
        if command_type == "get_clip_notes":
            key = (params["track_index"], params["clip_index"])
            return {"notes": self._notes.get(key, [])}
        if command_type == "get_song_scale":
            return self._scale
        raise AssertionError("unexpected command %s" % command_type)


def _c_major_notes():
    # C major triad emphasis -> should detect C major
    pitches = [60, 64, 67, 60, 64, 67, 72, 65, 62]
    return [{"pitch": p, "duration": 1.0, "velocity": 100} for p in pitches]


def test_detect_key_midi_only(monkeypatch):
    clips = [{"track_index": 0, "clip_index": 0, "location": "session",
              "is_midi": True, "length": 4.0, "pitch_coarse": 0,
              "file_path": None}]
    conn = _Conn(clips, {(0, 0): _c_major_notes()},
                 song_scale={"root_note": "C", "scale_name": "Major"})
    monkeypatch.setattr(server, "get_ableton_connection", lambda: conn)
    out = json.loads(server.detect_key(ctx=None, source="midi"))
    assert out["ok"] is True
    data = out["data"]
    assert data["detected_key"] == "C major"
    assert data["candidates"][0]["key"] == "C major"
    assert data["sources"]["midi"]["notes"] == 9
    assert data["matches_live"] is True


def test_detect_key_empty_set(monkeypatch):
    conn = _Conn([], {})
    monkeypatch.setattr(server, "get_ableton_connection", lambda: conn)
    out = json.loads(server.detect_key(ctx=None, source="midi"))
    assert out["ok"] is False


def test_detect_key_tap_not_supported(monkeypatch):
    conn = _Conn([], {})
    monkeypatch.setattr(server, "get_ableton_connection", lambda: conn)
    out = json.loads(server.detect_key(ctx=None, source="tap"))
    assert out["ok"] is False and "tap" in out["error"].lower()


def test_detect_key_auto_blends_audio(monkeypatch):
    # MIDI says C major; audio profile says A (pc 9). With audio_weight=1.0
    # the result must follow the audio toward A minor/C major neighborhood.
    clips = [
        {"track_index": 0, "clip_index": 0, "location": "session",
         "is_midi": True, "length": 4.0, "pitch_coarse": 0, "file_path": None},
        {"track_index": 1, "clip_index": 0, "location": "session",
         "is_midi": False, "length": 4.0, "pitch_coarse": 0,
         "file_path": "/tmp/a.wav"},
    ]
    conn = _Conn(clips, {(0, 0): _c_major_notes()})
    monkeypatch.setattr(server, "get_ableton_connection", lambda: conn)
    monkeypatch.setattr(server, "_ensure_local", lambda p, **k: p)
    a_profile = [0.0] * 12
    a_profile[9] = 1.0
    monkeypatch.setattr(server, "_run_chroma",
                        lambda items, **k: {"profile": a_profile,
                                            "analyzed": 1, "skipped": 0})
    out = json.loads(server.detect_key(ctx=None, source="auto", audio_weight=1.0))
    assert out["ok"] is True
    assert out["data"]["sources"]["audio"]["analyzed"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q tests/test_detect_key_tool.py`
Expected: FAIL — `AttributeError: module 'ableton_mcp_max.server' has no attribute 'detect_key'`

- [ ] **Step 3a: Import the module**

Near the other `*_utils` imports at the top of `server.py`, add:

```python
from ableton_mcp_max import key_detection_utils as kd
```

- [ ] **Step 3b: Add the `_run_chroma` helper**

Add near `_run_analysis` (~line 5680). Reuses `_BREW_PY`; mirrors the graceful-degrade contract:

```python
_CHROMA_SCRIPT = os.path.join(os.path.dirname(__file__), "..", "scripts",
                              "chroma_profile.py")


def _run_chroma(items, timeout=180):
    """Run scripts/chroma_profile.py under brew python on a list of
    {path, transpose} dicts. Returns {profile, analyzed, skipped} or None on any
    failure (so the caller degrades to MIDI-only)."""
    if not items or not os.path.exists(_BREW_PY):
        return None
    try:
        proc = subprocess.run(
            [_BREW_PY, _CHROMA_SCRIPT], input=json.dumps(items),
            capture_output=True, text=True, timeout=timeout)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    try:
        out = json.loads(proc.stdout.strip().splitlines()[-1])
    except Exception:
        return None
    if "error" in out or "profile" not in out:
        return None
    return out
```

- [ ] **Step 3c: Add the `detect_key` tool**

Add near the other clip/analysis tools:

```python
@mcp.tool()
def detect_key(ctx: Context, source: str = "auto",
               audio_weight: float = 0.5, top_n: int = 5) -> str:
    """Detect the most likely musical key from the open set's combined content
    (MIDI notes + offline audio files), independent of Live's configured scale.

    Parameters:
    - source: "auto" (MIDI + audio files; default), "midi", or "audio".
      ("tap" is not yet supported.)
    - audio_weight: 0..1 blend of the audio histogram vs MIDI (default 0.5).
    - top_n: number of ranked candidates to return (default 5).

    Returns {ok, data} where data has detected_key, confidence, candidates,
    relative_key, pitch_class_histogram, sources, live_scale, matches_live.
    """
    if source == "tap":
        return _err("tap source not yet supported")
    if source not in ("auto", "midi", "audio"):
        return _err("source must be one of: auto, midi, audio")
    try:
        ableton = get_ableton_connection()
        contents = ableton.send_command("get_clip_contents", {})
        clips = (contents or {}).get("clips", [])

        midi_hist = [0.0] * 12
        midi_clips = midi_notes = 0
        if source in ("auto", "midi"):
            for c in clips:
                if not c.get("is_midi"):
                    continue
                res = ableton.send_command("get_clip_notes", {
                    "track_index": c["track_index"],
                    "clip_index": c["clip_index"],
                    "from_time": 0.0, "time_span": -1.0,
                    "from_pitch": 0, "pitch_span": 128})
                notes = (res or {}).get("notes", [])
                if not notes:
                    continue
                ch = kd.histogram_from_notes(notes, int(c.get("pitch_coarse", 0)))
                midi_hist = [midi_hist[i] + ch[i] for i in range(12)]
                midi_clips += 1
                midi_notes += len(notes)

        audio_hist = [0.0] * 12
        audio_info = {"clips": 0, "analyzed": 0, "skipped": 0, "mode": "offline"}
        if source in ("auto", "audio"):
            items = []
            for c in clips:
                if c.get("is_midi") or not c.get("file_path"):
                    continue
                audio_info["clips"] += 1
                local = _ensure_local(c["file_path"])
                if not local:
                    audio_info["skipped"] += 1
                    continue
                items.append({"path": local,
                              "transpose": int(c.get("pitch_coarse", 0))})
            chroma = _run_chroma(items) if items else None
            if chroma is None:
                if items:
                    audio_info["mode"] = "unavailable"
                    audio_info["skipped"] += len(items)
            else:
                audio_hist = kd.histogram_from_chroma(chroma["profile"], 0)
                audio_info["analyzed"] = chroma.get("analyzed", 0)
                audio_info["skipped"] += chroma.get("skipped", 0)

        combined = kd.combine(midi_hist, audio_hist, audio_weight)
        if sum(combined) <= 0:
            return _err("no usable MIDI notes or audio content to analyze")

        candidates = kd.detect_key(combined, top_n=top_n)
        best = candidates[0]
        rel_pc, rel_mode = kd.relative_key(best["root_pc"], best["mode"])

        live = _song_scale()
        matches = None
        if live and live.get("root_note") is not None:
            live_name = "%s %s" % (live.get("root_note"),
                                   "major" if str(live.get("scale_name", "")
                                                  ).lower().startswith("maj")
                                   else "minor")
            matches = (live_name.lower() == best["key"].lower())

        total = sum(combined) or 1.0
        data = {
            "detected_key": best["key"],
            "confidence": best["confidence"],
            "candidates": candidates,
            "relative_key": kd.key_name(rel_pc, rel_mode),
            "pitch_class_histogram": [round(x / total, 4) for x in combined],
            "sources": {
                "midi": {"clips": midi_clips, "notes": midi_notes},
                "audio": audio_info,
                "audio_weight": audio_weight,
            },
            "live_scale": live,
            "matches_live": matches,
        }
        return _ok(data)
    except Exception as e:
        logger.error("Error detecting key: %s", e)
        return _err("Error detecting key: %s" % e)
```

- [ ] **Step 4: Run tests + import gate**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q tests/test_detect_key_tool.py && uv run python -c "import ableton_mcp_max.server"`
Expected: PASS (4 passed), import prints nothing.

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/server.py tests/test_detect_key_tool.py
git commit -m "feat(key): detect_key MCP tool + _run_chroma helper"
```

---

### Task 6: Full offline gate, live verification, docs + version bump

**Files:**
- Modify: `README.md` (tool count), `docs/index.md` (5 hardcoded count spots per CLAUDE.md), `pyproject.toml`, `.claude-plugin/plugin.json`, `uv.lock`, `PROGRESS.md`
- Run: `scripts/gen_docs_site.py` + `scripts/build_tool_index.py` (regen tool tables)

- [ ] **Step 1: Full offline gate**

Run:
```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q
uv run python -c "import ableton_mcp_max.server"
uv run python -m py_compile remote_script/AbletonMCP/__init__.py
```
Expected: all pass / no output.

- [ ] **Step 2: Install RS + reopen Live, then live-verify**

```bash
bash scripts/install_remote_script.sh
```
Then bounce Live (use the `restart_live` MCP tool or `/ableton:restart`), and after the user restarts Claude Code (server.py changed → new deferred tool), load the tool:
`ToolSearch select:mcp__AbletonDev__detect_key`

Verify against the open set (record results in PROGRESS.md):
- `detect_key(source="midi")` on a known-key set → that key is `candidates[0]`.
- `detect_key(source="audio")` on a set with audio clips → returns a profile; `sources.audio.analyzed > 0` (or `mode:"unavailable"` if brew librosa is missing — note honestly).
- `detect_key(source="auto")` → combined result; `matches_live` reflects Live's scale.
- `detect_key(source="tap")` → `ok:false`, "tap source not yet supported".

- [ ] **Step 3: Regenerate docs + bump counts**

```bash
uv run python scripts/build_tool_index.py
uv run python scripts/gen_docs_site.py
```
Then by hand: bump the tool count (147 → 148) in `README.md:7` and the 5 hardcoded spots in `docs/index.md` (description, tagline, two `stats__num`, the "exposes the N `@mcp.tool()`" line). Bump version in `pyproject.toml` + `.claude-plugin/plugin.json`, then `uv lock`.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "docs(key): regen tool index + bump tool count/version for detect_key"
```

---

## Self-Review

**Spec coverage:**
- KS correlation + ranked candidates + confidence → Task 1. ✓
- Histogram from notes (with transpose/weight) + chroma + combine/audio_weight → Task 2. ✓
- Audio via brew-Python subprocess returning 12-bin profile → Task 3. ✓
- `get_clip_contents` bulk read with `file_path`/`pitch_coarse` → Task 4. ✓
- `detect_key` tool, `source` in {auto,midi,audio}, tap→error, output shape, `matches_live`, graceful degrade → Task 5. ✓
- Error handling (empty set, brew/librosa unavailable, per-clip skip) → Tasks 3 + 5. ✓
- Testing (pure unit + skipif script test + monkeypatched tool test) → Tasks 1/2/3/5. ✓
- Docs/version bump on ship → Task 6. ✓
- Tap mode (`source="tap"`) → explicitly deferred to Plan B (spec Decomposition). ✓

**Placeholder scan:** none — every code/test step shows full content.

**Type consistency:** `histogram_from_notes`/`histogram_from_chroma`/`combine`/`detect_key`/`key_name`/`relative_key` signatures match across Tasks 1, 2, 5; `_run_chroma` returns `{profile, analyzed, skipped}` consumed verbatim in Task 5; `get_clip_contents` clip dict keys (`is_midi`, `pitch_coarse`, `file_path`, `track_index`, `clip_index`) match between Task 4 and Task 5.
