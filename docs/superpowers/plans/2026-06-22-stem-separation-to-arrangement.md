# Stem Separation to Arrangement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `separate_stems_to_arrangement` MCP tool that splits a mixed audio file into stems (Demucs CLI), detects its tempo + key (librosa), applies them to the open Live set, and lays each stem onto its own audio track at bar 1 of the Arrangement.

**Architecture:** Pure, import-light helpers in a new `stem_utils.py` (command building + output-path resolution + analysis-JSON parsing + key→scale mapping) are unit-tested offline. Heavy deps stay out of the server `uv` venv: Demucs is shelled out as a CLI on PATH, and tempo/key analysis runs `scripts/analyze_audio.py` under brew Python as a subprocess. A new `server.py` tool orchestrates the subprocess steps then drives existing Ableton handlers (`create_audio_track`, `load_audio_clip`, `set_clip_property`, `set_clip_name`, `set_track_name`, `duplicate_clip_to_arrangement`, `delete_clip`, `set_tempo`, `set_song_scale`). No Remote Script changes.

**Tech Stack:** Python 3.10+ (server, `uv`), FastMCP, Demucs CLI, librosa (brew Python only), pytest.

## Global Constraints

- `requires-python = ">=3.10"` for the server package.
- Do NOT add `demucs`, `torch`, or `librosa` to `pyproject.toml` dependencies — they must NOT enter the server `uv` venv. Demucs is invoked as a CLI; librosa runs only inside `scripts/analyze_audio.py` under brew Python (`/opt/homebrew/bin/python3`).
- `*_utils.py` modules are imported by `server.py` only and MUST stay pure (no `import librosa`, no `import torch`, no Ableton calls). The Remote Script cannot import them.
- No Remote Script (`remote_script/...`) edits — reuse existing handlers only.
- Written-content dash rule: only the standard hyphen `-`. No em/en dashes anywhere in code, comments, docs, or commits.
- No AI attribution in commits (this repo is public / a shipped plugin).
- Offline test gate: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q`. Server import check: `uv run python -c "import ableton_mcp_max.server"`.
- Stem layout order (top to bottom): `drums, bass, other, vocals` (4-stem); `drums, bass, other, vocals, guitar, piano` (6-stem); `vocals, no_vocals` (two-stem).
- Live verification is manual; record results in `PROGRESS.md`.

---

### Task 1: `stem_utils.py` pure helpers

**Files:**
- Create: `ableton_mcp_max/stem_utils.py`
- Test: `tests/test_stem_utils.py`

**Interfaces:**
- Consumes: nothing (pure module, stdlib only).
- Produces (later tasks rely on these exact names/signatures):
  - `MODELS: dict` — model spec table.
  - `validate_model(model: str) -> dict` returns `{"demucs_model": str, "two_stems": str|None, "stems": list[str]}` where `stems` is in layout order and matches the demucs output filenames (without `.wav`). Raises `ValueError` on unknown model.
  - `build_demucs_cmd(audio_path: str, model: str, out_dir: str, device: str) -> list[str]`
  - `expected_stem_paths(out_dir: str, model: str, track_basename: str) -> list[tuple[str, str]]` returns `[(stem_name, abs_wav_path), ...]` in layout order.
  - `parse_analysis(json_str: str) -> tuple[float|None, str|None, str|None]` returns `(tempo, key, scale)` ready for `set_tempo`/`set_song_scale`.
  - `key_to_scale_args(pitch_class: str, mode: str) -> tuple[str, str]` returns `(key, scale)`.
  - `resolve_device(device: str, machine: str) -> str` maps `"auto"` to `"mps"`/`"cpu"`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_stem_utils.py
import json
import pytest
from ableton_mcp_max import stem_utils as su


def test_validate_model_default_4stem():
    spec = su.validate_model("htdemucs")
    assert spec["demucs_model"] == "htdemucs"
    assert spec["two_stems"] is None
    assert spec["stems"] == ["drums", "bass", "other", "vocals"]


def test_validate_model_6stem_order():
    spec = su.validate_model("htdemucs_6s")
    assert spec["demucs_model"] == "htdemucs_6s"
    assert spec["stems"] == ["drums", "bass", "other", "vocals", "guitar", "piano"]


def test_validate_model_two_stems():
    spec = su.validate_model("two_stems")
    assert spec["demucs_model"] == "htdemucs"
    assert spec["two_stems"] == "vocals"
    assert spec["stems"] == ["vocals", "no_vocals"]


def test_validate_model_aliases_and_case():
    assert su.validate_model("HTDemucs")["demucs_model"] == "htdemucs"
    assert su.validate_model("4")["stems"] == ["drums", "bass", "other", "vocals"]
    assert su.validate_model("6")["demucs_model"] == "htdemucs_6s"


def test_validate_model_unknown_raises():
    with pytest.raises(ValueError):
        su.validate_model("spleeter")


def test_build_demucs_cmd_4stem():
    cmd = su.build_demucs_cmd("/x/song.wav", "htdemucs", "/tmp/out", "cpu")
    assert cmd[0] == "demucs"
    assert "-n" in cmd and "htdemucs" in cmd
    assert "-o" in cmd and "/tmp/out" in cmd
    assert "-d" in cmd and "cpu" in cmd
    assert "--two-stems" not in " ".join(cmd)
    assert cmd[-1] == "/x/song.wav"


def test_build_demucs_cmd_two_stems_flag():
    cmd = su.build_demucs_cmd("/x/song.wav", "two_stems", "/tmp/out", "mps")
    joined = " ".join(cmd)
    assert "--two-stems=vocals" in joined
    assert "-n htdemucs" in joined


def test_expected_stem_paths_layout_and_location():
    paths = su.expected_stem_paths("/tmp/out", "htdemucs", "song")
    names = [n for n, _ in paths]
    assert names == ["drums", "bass", "other", "vocals"]
    assert paths[0][1] == "/tmp/out/htdemucs/song/drums.wav"


def test_expected_stem_paths_two_stems():
    paths = su.expected_stem_paths("/tmp/out", "two_stems", "song")
    assert [n for n, _ in paths] == ["vocals", "no_vocals"]
    assert paths[1][1] == "/tmp/out/htdemucs/song/no_vocals.wav"


def test_key_to_scale_args():
    assert su.key_to_scale_args("C#", "minor") == ("C#", "minor")
    assert su.key_to_scale_args("A", "major") == ("A", "major")


def test_parse_analysis_full():
    blob = json.dumps({"tempo": 128.4, "key_pitch_class": "F#", "mode": "minor"})
    tempo, key, scale = su.parse_analysis(blob)
    assert tempo == pytest.approx(128.4)
    assert (key, scale) == ("F#", "minor")


def test_parse_analysis_missing_fields_returns_none():
    tempo, key, scale = su.parse_analysis(json.dumps({"tempo": None}))
    assert tempo is None and key is None and scale is None


def test_parse_analysis_bad_json_returns_none_tuple():
    assert su.parse_analysis("not json") == (None, None, None)


def test_resolve_device_auto():
    assert su.resolve_device("auto", "arm64") == "mps"
    assert su.resolve_device("auto", "x86_64") == "cpu"
    assert su.resolve_device("cpu", "arm64") == "cpu"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_stem_utils.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'ableton_mcp_max.stem_utils'`.

- [ ] **Step 3: Write minimal implementation**

```python
# ableton_mcp_max/stem_utils.py
"""Pure helpers for stem separation (Demucs CLI) -> Arrangement layout.

Import-light by contract: stdlib only. No librosa, no torch, no Ableton.
Imported by server.py only (the Remote Script runs in Live's own Python).
"""

import json

# Layout order is also the demucs output-filename set for each model.
MODELS = {
    "htdemucs": {
        "demucs_model": "htdemucs",
        "two_stems": None,
        "stems": ["drums", "bass", "other", "vocals"],
    },
    "htdemucs_6s": {
        "demucs_model": "htdemucs_6s",
        "two_stems": None,
        "stems": ["drums", "bass", "other", "vocals", "guitar", "piano"],
    },
    "two_stems": {
        "demucs_model": "htdemucs",
        "two_stems": "vocals",
        "stems": ["vocals", "no_vocals"],
    },
}

_ALIASES = {
    "htdemucs": "htdemucs",
    "4": "htdemucs",
    "4stem": "htdemucs",
    "htdemucs_6s": "htdemucs_6s",
    "6": "htdemucs_6s",
    "6stem": "htdemucs_6s",
    "6s": "htdemucs_6s",
    "two_stems": "two_stems",
    "2": "two_stems",
    "2stem": "two_stems",
    "vocals": "two_stems",
}


def validate_model(model):
    """Return a copy of the model spec for `model` (case/alias-insensitive)."""
    key = _ALIASES.get(str(model).strip().lower())
    if key is None:
        raise ValueError(
            "Unknown model %r. Choose one of: htdemucs (4-stem), "
            "htdemucs_6s (6-stem), two_stems." % (model,))
    spec = MODELS[key]
    return {
        "demucs_model": spec["demucs_model"],
        "two_stems": spec["two_stems"],
        "stems": list(spec["stems"]),
    }


def build_demucs_cmd(audio_path, model, out_dir, device):
    """Build the demucs CLI argv. Demucs writes <out_dir>/<model>/<name>/*.wav."""
    spec = validate_model(model)
    cmd = ["demucs", "-n", spec["demucs_model"], "-o", out_dir, "-d", device]
    if spec["two_stems"]:
        cmd.append("--two-stems=%s" % spec["two_stems"])
    cmd.append(audio_path)
    return cmd


def expected_stem_paths(out_dir, model, track_basename):
    """[(stem_name, abs_wav_path)] in layout order, as demucs writes them."""
    spec = validate_model(model)
    base = "%s/%s/%s" % (out_dir, spec["demucs_model"], track_basename)
    return [(name, "%s/%s.wav" % (base, name)) for name in spec["stems"]]


def key_to_scale_args(pitch_class, mode):
    """Map a detected pitch class + mode to (key, scale) for set_song_scale."""
    scale = "minor" if str(mode).strip().lower() == "minor" else "major"
    return (str(pitch_class).strip(), scale)


def parse_analysis(json_str):
    """Parse analyze_audio.py output into (tempo, key, scale).

    Tolerant: any parse error or missing field yields None for that value.
    """
    try:
        data = json.loads(json_str)
    except (ValueError, TypeError):
        return (None, None, None)
    tempo = data.get("tempo")
    tempo = float(tempo) if isinstance(tempo, (int, float)) else None
    pc = data.get("key_pitch_class")
    mode = data.get("mode")
    if pc and mode:
        key, scale = key_to_scale_args(pc, mode)
    else:
        key, scale = (None, None)
    return (tempo, key, scale)


def resolve_device(device, machine):
    """auto -> mps on Apple Silicon (arm64), else cpu. Explicit values pass through."""
    if device != "auto":
        return device
    return "mps" if str(machine).lower() in ("arm64", "aarch64") else "cpu"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_stem_utils.py -q`
Expected: PASS (all 14 tests).

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/stem_utils.py tests/test_stem_utils.py
git commit -m "feat(stems): pure stem_utils helpers (model spec, demucs cmd, analysis parse)"
```

---

### Task 2: `scripts/analyze_audio.py` librosa analysis script

**Files:**
- Create: `scripts/analyze_audio.py`
- Test: `tests/test_analyze_audio.py`

**Interfaces:**
- Consumes: nothing from prior tasks (standalone script run under brew Python).
- Produces: a CLI contract used by Task 3 — `python3 scripts/analyze_audio.py <audio_path>` prints ONE JSON line to stdout: `{"tempo": float, "key_pitch_class": str, "mode": "major"|"minor"}`. On failure prints `{"error": "..."}` and exits non-zero. The JSON shape is what `stem_utils.parse_analysis` consumes.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_analyze_audio.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_analyze_audio.py -q`
Expected: FAIL (script missing -> non-zero return / FileNotFoundError), or SKIP if librosa is absent on this machine. On the dev machine librosa 0.11.0 is present, so expect FAIL.

- [ ] **Step 3: Write the script**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_analyze_audio.py -q`
Expected: PASS (or SKIP where librosa is unavailable).

- [ ] **Step 5: Commit**

```bash
git add scripts/analyze_audio.py tests/test_analyze_audio.py
git commit -m "feat(stems): analyze_audio.py tempo+key detection (brew python, librosa)"
```

---

### Task 3: `separate_stems_to_arrangement` tool + orchestration helpers

**Files:**
- Modify: `ableton_mcp_max/server.py` (add imports, helpers, and the new `@mcp.tool()`; place the tool near `load_audio_clip` around line 5653)
- Test: manual (Live) + server-import check. Pure logic already covered in Task 1.

**Interfaces:**
- Consumes: `ableton_mcp_max.stem_utils` (Task 1) functions; `scripts/analyze_audio.py` CLI contract (Task 2); existing `server.py` internals `_ok`, `_err`, `_ensure_local`, `_read_audio_meta`, `_resolve_sample_uri`, `get_ableton_connection`, `logger`; existing Remote Script commands `create_audio_track`, `set_highlighted_clip_slot`, `load_browser_item`, `set_clip_property`, `set_clip_name`, `set_track_name`, `duplicate_clip_to_arrangement`, `delete_clip`, `set_tempo`, `set_song_scale`, `get_session_info`, `restart_live`.
- Produces: the `separate_stems_to_arrangement` MCP tool (consumed by Task 4's command).

- [ ] **Step 1: Add module imports near the top of `server.py`**

Add to the existing import block (with `import os`, `subprocess`, `tempfile`, `platform`; add any not already present):

```python
import os
import platform
import subprocess
import tempfile

from ableton_mcp_max import stem_utils
```

Note: `server.py` already imports several `*_utils` modules; match that import style. Check whether `subprocess`/`tempfile`/`platform` are already imported before adding duplicates.

- [ ] **Step 2: Add the two subprocess runner helpers (private, host-side)**

Place these just above where the new tool will go. They are thin wrappers; the testable logic (arg building, parsing) lives in `stem_utils`.

```python
_BREW_PY = "/opt/homebrew/bin/python3"
_ANALYZE_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "scripts", "analyze_audio.py")


def _run_demucs(audio_path, model, out_dir, device, timeout=1200):
    """Run the Demucs CLI. Returns (ok, message). Raises nothing."""
    cmd = stem_utils.build_demucs_cmd(audio_path, model, out_dir, device)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return (False, "demucs CLI not found on PATH. Install it: "
                       "pip3 install --break-system-packages demucs")
    except subprocess.TimeoutExpired:
        return (False, "demucs timed out after %ds" % timeout)
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()[-5:]
        return (False, "demucs failed (exit %d): %s"
                % (proc.returncode, " | ".join(tail)))
    return (True, "ok")


def _run_analysis(audio_path, timeout=120):
    """Run analyze_audio.py under brew python. Returns (tempo, key, scale).

    Degrades gracefully: any failure (no brew python, librosa missing, decode
    error) yields (None, None, None) so the caller keeps the default tempo.
    """
    if not os.path.exists(_BREW_PY):
        return (None, None, None)
    try:
        proc = subprocess.run(
            [_BREW_PY, _ANALYZE_SCRIPT, audio_path],
            capture_output=True, text=True, timeout=timeout)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return (None, None, None)
    if proc.returncode != 0 or not proc.stdout.strip():
        return (None, None, None)
    return stem_utils.parse_analysis(proc.stdout.strip().splitlines()[-1])
```

- [ ] **Step 3: Add the per-stem layout helper (private, Ableton-side)**

```python
def _lay_stem_on_track(ableton, track_index, stem_name, sample_path):
    """Create-already-done track: load stem into slot 0, warp off + name it,
    duplicate to arrangement at bar 1, delete the session staging clip.

    Returns dict {name, track_index, path, loaded}.
    """
    local = _ensure_local(sample_path)
    uri = _resolve_sample_uri(local, "samples")
    ableton.send_command("set_highlighted_clip_slot",
                         {"track_index": track_index, "scene_index": 0})
    res = ableton.send_command("load_browser_item", {
        "track_index": track_index, "item_uri": uri, "track_type": "regular"})
    loaded = bool(res.get("loaded", False))
    if not loaded:
        return {"name": stem_name, "track_index": track_index,
                "path": local, "loaded": False}
    # Warp OFF + name on the SESSION clip; the arrangement copy inherits both.
    ableton.send_command("set_clip_property", {
        "track_index": track_index, "clip_index": 0,
        "property": "warping", "value": 0})
    ableton.send_command("set_clip_name", {
        "track_index": track_index, "clip_index": 0, "name": stem_name})
    ableton.send_command("set_track_name", {
        "track_index": track_index, "name": stem_name})
    ableton.send_command("duplicate_clip_to_arrangement", {
        "track_index": track_index, "source_slot_index": 0,
        "destination_time": 0.0})
    ableton.send_command("delete_clip", {
        "track_index": track_index, "clip_index": 0})
    return {"name": stem_name, "track_index": track_index,
            "path": local, "loaded": True}
```

Verify the exact command names + param keys against the Remote Script dispatch in `remote_script/AbletonMCP/__init__.py` before relying on them (e.g. `set_highlighted_clip_slot` uses `scene_index`; `duplicate_clip_to_arrangement` uses `source_slot_index`/`destination_time`; `set_clip_property` uses `property`/`value`). Match what the existing tool wrappers send (see `load_audio_clip`, `duplicate_clip_to_arrangement`, `set_clip_property` in `server.py`).

- [ ] **Step 4: Add the `separate_stems_to_arrangement` MCP tool**

```python
@mcp.tool()
def separate_stems_to_arrangement(
    ctx: Context,
    audio_path: str,
    model: str = "htdemucs",
    fresh: bool = False,
    detect_tempo: bool = True,
    detect_key: bool = True,
    device: str = "auto",
    output_dir: str = None,
) -> str:
    """Split an audio file into stems and lay each onto its own Arrangement track.

    Uses the Demucs CLI to separate `audio_path` into stems, optionally detects
    the source tempo + key (librosa, via scripts/analyze_audio.py) and applies
    them to the open set, then creates one audio track per stem and places each
    stem at bar 1 of the Arrangement timeline (Warp OFF, so full-song stems stay
    phase-locked). Session view is used only as transient staging; the end state
    has empty session slots.

    Prerequisites: the `demucs` CLI on PATH and (for tempo/key) librosa in brew
    Python. See the README "Stem separation" prerequisites; a clear error is
    returned when demucs is missing and analysis degrades gracefully without
    librosa.

    Parameters:
    - audio_path: absolute path to the mixed audio file.
    - model: "htdemucs" (4-stem, default), "htdemucs_6s" (6-stem), or "two_stems".
    - fresh: when True, bounce Live to a blank set FIRST (discards the open set).
      The CALLER must confirm with the user before passing fresh=True.
    - detect_tempo / detect_key: analyze the source and set tempo / song scale.
    - device: "auto" (mps on Apple Silicon, else cpu), "cpu", or "mps".
    - output_dir: where Demucs writes stems (default: a temp dir).

    Returns JSON {ok, data:{audio, model, device, tempo, key, scale,
    tempo_detected, key_detected, fresh, stems:[{name, track_index, path,
    loaded}]}}.
    """
    try:
        try:
            spec = stem_utils.validate_model(model)
        except ValueError as e:
            return _err(str(e))

        local_src = _ensure_local(audio_path)
        if not os.path.isfile(local_src):
            return _err("Audio file not found: %s" % audio_path)

        device = stem_utils.resolve_device(device, platform.machine())
        out_dir = output_dir or tempfile.mkdtemp(prefix="stems_")

        ok, msg = _run_demucs(local_src, model, out_dir, device)
        if not ok:
            return _err(msg)

        basename = os.path.splitext(os.path.basename(local_src))[0]
        stem_paths = stem_utils.expected_stem_paths(out_dir, model, basename)
        missing = [p for _, p in stem_paths if not os.path.isfile(p)]
        if missing:
            return _err("Demucs produced no output for: %s" % ", ".join(missing))

        tempo, key, scale = (None, None, None)
        if detect_tempo or detect_key:
            tempo, key, scale = _run_analysis(local_src)

        ableton = get_ableton_connection()

        if fresh:
            try:
                ableton.send_command("restart_live", {})
                ableton = get_ableton_connection()
            except Exception as e:
                return _err("fresh=True could not reach a blank set (%s). Save / "
                            "name the open set by hand first, then retry." % e)

        if detect_tempo and tempo:
            ableton.send_command("set_tempo", {"tempo": tempo})
        if detect_key and key:
            root, scale_name = comp.resolve_song_scale(key, scale or "major")
            ableton.send_command(
                "set_song_scale", {"root_note": root, "scale_name": scale_name})

        info = ableton.send_command("get_session_info") or {}
        next_index = int(info.get("track_count", 0))

        stems_out = []
        for stem_name, path in stem_paths:
            ableton.send_command("create_audio_track", {"index": -1})
            stems_out.append(
                _lay_stem_on_track(ableton, next_index, stem_name, path))
            next_index += 1

        return _ok({
            "audio": local_src,
            "model": spec["demucs_model"],
            "device": device,
            "tempo": tempo,
            "key": key,
            "scale": scale,
            "tempo_detected": bool(detect_tempo and tempo),
            "key_detected": bool(detect_key and key),
            "fresh": fresh,
            "stems": stems_out,
        })
    except Exception as e:
        logger.error("Error in separate_stems_to_arrangement: %s", e)
        return _err("Error in separate_stems_to_arrangement: %s" % e)
```

Note: confirm `comp.resolve_song_scale` is the in-scope reference used by `set_song_scale` (it is, per `server.py:3470`). If `comp` is not in scope at the tool's location, call `ableton.send_command("set_song_scale", {"root_note": key, "scale_name": scale})` only after mapping, or reuse the same helper `set_song_scale` uses. Verify before finalizing.

- [ ] **Step 5: Verify get_session_info returns track_count**

Run: `grep -nE "track_count" ableton_mcp_max/server.py remote_script/AbletonMCP/__init__.py | head`
Expected: `get_session_info`/`_get_session_info` includes a `track_count` key. If the key name differs (e.g. `tracks`), adjust `next_index` accordingly. Document the confirmed key here before proceeding.

- [ ] **Step 6: Server import + syntax check**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python -c "import ableton_mcp_max.server"`
Expected: no output, exit 0 (imports cleanly).

- [ ] **Step 7: Full offline test gate**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q`
Expected: PASS (existing suite + Task 1/2 tests; analyze test may SKIP).

- [ ] **Step 8: Commit**

```bash
git add ableton_mcp_max/server.py
git commit -m "feat(stems): separate_stems_to_arrangement tool (demucs + analysis + arrangement layout)"
```

- [ ] **Step 9: Manual Live verification (record in PROGRESS.md)**

Requires a Claude Code restart (new MCP tool loads at session start) and Live running with the AbletonDev/cached server connected. After restart, load the tool via `ToolSearch select:mcp__AbletonDev__separate_stems_to_arrangement`, then run it on a short test audio file. Confirm: N stem tracks appended, each with one clip at bar 1 of the Arrangement, warp OFF, session slots empty, project tempo + scale updated to the detected values. Record the result (pass/fail, observed tempo/key) in `PROGRESS.md`.

---

### Task 4: `/ableton:stems` slash command (front door + fresh prompt)

**Files:**
- Create: `commands/stems.md`

**Interfaces:**
- Consumes: the `separate_stems_to_arrangement` MCP tool (Task 3).
- Produces: a user-facing command; no code depends on it.

- [ ] **Step 1: Inspect an existing command for the house format**

Run: `ls commands/ && sed -n '1,40p' commands/restart.md`
Expected: see the frontmatter + body convention (description, argument usage). Match it.

- [ ] **Step 2: Write the command**

```markdown
---
description: Separate an audio file into stems and lay each onto its own Arrangement track in Ableton Live.
argument-hint: <path-to-audio-file> [fresh]
---

# Stem split to Arrangement

Separate the audio file at `$ARGUMENTS` into stems with Demucs, detect its tempo
and key, set those on the open Live set, and place each stem on its own audio
track at bar 1 of the Arrangement (Warp OFF).

## Steps

1. Resolve the audio path from `$ARGUMENTS` (first token). If no path is given,
   ask the user for one.
2. Determine fresh mode: if the user passed `fresh` (or asked for a brand-new
   set), you MUST confirm BEFORE doing anything in Ableton:
   - Warn that fresh mode bounces Live to a blank set and DISCARDS the currently
     open set's unsaved changes.
   - Ask the user to confirm and to make sure Live is ready.
   - Only after explicit confirmation, call the tool with `fresh=true`.
   Otherwise call with `fresh=false` (stems are appended to the open set).
3. Call `mcp__AbletonMCPMax__separate_stems_to_arrangement` (or the AbletonDev
   equivalent during development) with the resolved `audio_path`, the chosen
   `model` (default htdemucs), and `fresh`.
4. Report back: the detected tempo + key, the model used, and the list of stem
   tracks created. If the result shows any stem with `loaded:false` or an error,
   surface it (e.g. demucs not installed -> point to the README prerequisites).

## Notes

- Demucs separation can take a few minutes for a full song; that runs before any
  Ableton call, so it will not time out the Live connection.
- Prerequisites (demucs CLI, librosa) are documented in the README under
  "Stem separation".
```

- [ ] **Step 3: Commit**

```bash
git add commands/stems.md
git commit -m "feat(stems): /ableton:stems slash command front door"
```

---

### Task 5: Documentation + tool index regen

**Files:**
- Modify: `README.md` (add a "Stem separation" prerequisites section)
- Modify: generated docs/index counts via the publish-flow scripts

**Interfaces:**
- Consumes: nothing.
- Produces: nothing code depends on.

- [ ] **Step 1: Add a Prerequisites section to README.md**

Add a section (place it near other setup/prerequisite content; find it with `grep -nE "^##|Prerequisite|Install" README.md | head`):

```markdown
## Stem separation prerequisites

The `separate_stems_to_arrangement` tool (and the `/ableton:stems` command) shell
out to external command-line tools that are NOT bundled with the MCP server:

- Demucs (source separation), on your PATH:
  - `pip3 install --break-system-packages demucs`
  - This installs the `demucs` CLI into your Homebrew Python and onto PATH.
- librosa (tempo + key detection), in Homebrew Python:
  - `pip3 install --break-system-packages librosa`
  - macOS note: the analysis step runs under `/opt/homebrew/bin/python3`, so
    librosa must be installed there (not `/usr/bin/python3`).

If `demucs` is missing, the tool returns a clear error. If librosa is missing,
stem layout still runs but tempo / key detection is skipped.
```

- [ ] **Step 2: Regenerate the tool index / docs counts**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python scripts/build_tool_index.py && PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python scripts/gen_docs_site.py`
Expected: `docs/tools/`, `docs/tools/index.md`, `commands/tool-index.md` regenerated with the new tool (count goes from 146 to 147). Then hand-edit the 5 hardcoded count spots in `docs/index.md` (description, tagline, two `stats__num`, the "exposes the N `@mcp.tool()`" line) per CLAUDE.md.

- [ ] **Step 3: Verify the new tool appears in the index**

Run: `grep -n "separate_stems_to_arrangement" docs/tools/index.md commands/tool-index.md`
Expected: the tool is listed in both.

- [ ] **Step 4: Commit**

```bash
git add README.md docs/ commands/tool-index.md
git commit -m "docs(stems): prerequisites + regenerated tool index (147 tools)"
```

---

## Self-Review

**Spec coverage:**
- Component split (stem_utils / analyze_audio / demucs CLI / tool / command) -> Tasks 1, 2, 3, 4. Covered.
- Tool signature + flow (separate, analyze, set tempo/scale, layout, warp off, delete staging) -> Task 3. Covered.
- Stem order + naming, no color -> Task 1 (`MODELS`) + Task 3 (`_lay_stem_on_track`). Covered.
- Fresh mode + up-front prompt -> Task 3 (tool gate) + Task 4 (command confirmation). Covered.
- Error handling (demucs missing, librosa missing graceful, bad file, partial layout) -> Task 3 helpers + tool. Covered.
- Prerequisites docs + brew-python caveat -> Task 5. Covered.
- Testing (stem_utils unit, analyze gated, server import, manual live) -> Tasks 1, 2, 3 steps. Covered.
- No new pyproject deps, no Remote Script edits -> Global Constraints; tool reuses existing commands. Covered.

**Placeholder scan:** No TBD/TODO; all code steps show complete code; verification steps (get_session_info key, command names, comp scope) are explicit confirm-then-adjust instructions, not vague placeholders.

**Type consistency:** `validate_model` returns `{"demucs_model","two_stems","stems"}` used consistently in `build_demucs_cmd`, `expected_stem_paths`, and the tool. `parse_analysis` returns `(tempo, key, scale)` consumed identically in `_run_analysis` and the tool. `_lay_stem_on_track` returns `{name, track_index, path, loaded}` matching the tool's `stems` output. Consistent.
