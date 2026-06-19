# Sample Sourcing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 4 new MCP tools (`search_samples`, `load_audio_clip`, `load_sample_to_drum_pad`, `populate_drum_rack`) and a pure `sample_utils.py` module so the server can discover audio samples in Live's browser/library and load them as audio clips, drum-rack one-shots, and full kits.

**Architecture:** A new pure module `sample_utils.py` holds classification, name-matching, iCloud-placeholder-path derivation, and post-load kind refinement. `server.py` gains a filesystem-walking `search_samples` (resolves User Library + Core Library sample roots, walks them, classifies + ranks each hit), an `_ensure_local` iCloud-materialization helper, and three loader tools that reuse the existing preset-patch / `load_browser_item` infrastructure. The two loaders that touch unverified Live behavior (`load_audio_clip`, `load_sample_to_drum_pad`) are gated behind a **live feasibility spike** (Task 1) that picks the concrete load path before they are built.

**Tech Stack:** Python 3.12+, FastMCP, stdlib `os`/`glob`/`subprocess`/`time`/`wave`/`aifc`, existing server seams (`_user_library_dir`, `_app_core`, `_read_audio_meta`, `_write_user_preset`, `_load_user_preset`, `_read_rack_template`, `get_ableton_connection`, `_ok`, `_err`), existing `load_browser_item` wire command, the AbletonDev MCP tools for live verification.

## Global Constraints

- All logic in `sample_utils.py` is importable without Live running. `classify_sample`, `name_match`, and `refine_kind_by_length` are pure (no I/O); `icloud_placeholder_path` touches the filesystem only (no Live/socket dependency) and is tested with real temp dirs.
- Remote Script: **zero changes planned.** Task 1 (spike) may discover the drum-pad fallback needs a new RS load path; if and only if it does, that is scoped as an extra task at spike time and triggers the dual-restart + RS-install protocol (see project CLAUDE.md). The default assumption for Tasks 2-8 is server-side only, no Live restart.
- iCloud materialization uses `brctl` at the absolute path `/usr/bin/brctl`. The User Library is iCloud-backed at `~/Library/Mobile Documents/com~apple~CloudDocs/Production/User Library` (resolved at runtime via `_user_library_dir()`, never hardcoded).
- A dataless iCloud file `Foo.wav` is stored on disk as a sibling stub `.Foo.wav.icloud` (leading dot, original name, `.icloud` suffix). Downloading materializes the real path and removes the stub.
- Sample classifications are exactly the four strings: `"loop"`, `"one_shot"`, `"kit"`, `"instrument"`.
- Run tests with: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/ -q`
- Syntax-check server imports with: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python -c "import ableton_mcp_max.server"`
- Never reformat existing code; `ruff` / `black` are not used in this repo.
- All new `@mcp.tool()` functions go in `server.py` grouped together immediately after `create_simpler_instrument` (the existing sample-content tool, ~line 4388) so they sit beside the helpers they reuse (`_read_audio_meta`, `_user_library_dir`, `_write_user_preset`).
- New category name (for `gen_docs_site.py`): slug `"samples"`, title `"Samples"`.
- Version bump 0.12.0 -> 0.13.0 in THREE places: `pyproject.toml`, `.claude-plugin/plugin.json`, then `uv lock` (regenerates `uv.lock`).
- Current offline suite: 656 passed. Target after this plan: ~690 passed.
- Live verification uses the **AbletonDev** MCP tools (`mcp__AbletonDev__*` = working tree), not the cached `plugin:ableton` tools. See CLAUDE.md "Restart protocol".

---

### Task 1: Live feasibility spike — resolve the two gated loaders + the factory sample root

**Files:**
- Modify: `PROGRESS.md` (append a "Sample sourcing spike findings" block)

**This task writes NO production code and has no pytest.** It is a live investigation against the open Live set using the AbletonDev MCP tools. Its deliverable is a written findings block that Tasks 5/6 depend on. Do not start Task 5 or 6 until this is recorded.

**Preconditions:**
- Ableton Live 11 or 12 is running with the AbletonMCP control surface loaded (port 9877). Confirm with the AbletonDev tools responding.
- The cached `plugin:ableton` MCP server is disabled for this session so AbletonDev owns the connection (see CLAUDE.md). If both are live, only fire commands through AbletonDev.

- [ ] **Step 1: Confirm a working scratch track + find a sample's browser item**

Create an empty audio track and an empty MIDI track to experiment on (so no existing patch is overwritten):
- `mcp__AbletonDev__create_audio_track` (append; note the returned index, call it `AUDIO_IDX`).
- `mcp__AbletonDev__create_midi_track` (append; note `MIDI_IDX`).

List sample browser content to get a real sample item + its `uri`:
- `mcp__AbletonDev__get_browser_items_at_path` with `path="samples"` (if that errors, try `get_browser_tree` with `category_type="all"` and read the `available_categories` it returns to learn the correct top-level name).
- Record: the exact top-level browser path that lists samples, and one sample item's `name` + `uri` + whether it reports `is_loadable`.

- [ ] **Step 2: Spike `load_audio_clip` feasibility (PRIMARY path)**

Question: can `load_browser_item` drop a sample onto an audio track and produce an audio clip?

Vehicle: `load_instrument_or_effect` already calls `load_browser_item` with an arbitrary `uri`. Use it as the probe (it is the existing wrapper around the wire command):
- Call `mcp__AbletonDev__load_instrument_or_effect` with `track_index=AUDIO_IDX`, `uri=<the sample uri from Step 1>`, `track_type="regular"`.
- Then inspect the track: `mcp__AbletonDev__get_clip_info` on `track_index=AUDIO_IDX, clip_index=0`, and `mcp__AbletonDev__get_device_info` on the same track.

Record which of these happened:
- (A) An **audio clip** appeared in a clip slot -> PRIMARY path works; `load_audio_clip` selects the slot then loads the item.
- (B) A **Simpler/instrument device** was created instead (sample loaded as an instrument) -> audio-clip-via-browser is not supported; FALLBACK = build `load_audio_clip` on `create_simpler_instrument` in a loop-playback configuration and report honestly.
- (C) Nothing loaded / error -> note the error; fall back to (B).

- [ ] **Step 3: Spike `load_sample_to_drum_pad` feasibility (PRIMARY path)**

Question: can a sample target a specific Drum Rack pad?

- Load a Drum Rack onto `MIDI_IDX`: `mcp__AbletonDev__load_instrument_or_effect` with a Drum Rack `uri` (find it via `get_browser_items_at_path path="drums"`), or `mcp__AbletonDev__load_drum_kit`.
- Inspect pad chains: `mcp__AbletonDev__get_rack_chains` on `MIDI_IDX` — record whether pads surface as chains and how a pad maps to a MIDI note (e.g. note 36 = C1 kick pad).
- Probe targeting: try `mcp__AbletonDev__load_instrument_or_effect` with the sample `uri` on `MIDI_IDX` again and re-inspect `get_rack_chains` / `get_device_info` to see whether the sample landed on a pad, replaced the rack, or was rejected.

Record which path to build:
- (A) Selecting a pad chain + `load_browser_item` routes the sample to that pad -> PRIMARY path; the tool selects the pad chain (note how) then loads.
- (B) No pad-targeting via the browser -> FALLBACK = preset-patch a Drum Rack `.adg` injecting the sample at the pad's note, reusing `_read_rack_template` / `_write_user_preset` / `_load_user_preset` (the rack `.adg` backdoor). Note whether this needs a new RS command (only if loading the patched `.adg` requires a path the RS doesn't already handle — `load_browser_item` on a User Library `.adg` already works, so most likely NO new RS code).

- [ ] **Step 4: Confirm the factory sample root for `search_samples`**

`search_samples` will filesystem-walk sample directories. The User Library root is `_user_library_dir()`; confirm the factory sample location:
- Determine the running Live's Core Library: in a shell, `ls "/Applications/Ableton"*"Live"*".app/Contents/App-Resources/Core Library/Samples"` and record whether a `Samples/` subtree exists there.
- Record the absolute factory samples root (e.g. `<Core Library>/Samples`) and whether User Library samples live under `<User Library>/Samples`.

- [ ] **Step 5: Clean up scratch tracks**

- `mcp__AbletonDev__delete_track` on `AUDIO_IDX` and `MIDI_IDX` (delete the higher index first so the lower index does not shift). Confirm with `get_session_info`.

- [ ] **Step 6: Record findings in PROGRESS.md and commit**

Append a block to `PROGRESS.md` titled `## Sample sourcing spike findings (2026-06-19)` containing, in plain prose:
- The top-level browser path that lists samples.
- `load_audio_clip`: PRIMARY (A) or FALLBACK (B) + one sentence why.
- `load_sample_to_drum_pad`: PRIMARY (A) or FALLBACK (B) + whether a new RS command is needed.
- The absolute factory samples root and the User Library samples root.

```bash
git add PROGRESS.md
git commit -m "docs(samples): record sample-sourcing feasibility spike findings"
```

**Decision gate:** Tasks 5 and 6 below give concrete code for BOTH the primary and fallback paths. The implementer picks the variant the spike selected. If Step 3 found a new RS command is required, insert a Task 6.5 ("RS sample-to-pad load command") before wiring the fallback and follow the dual-restart protocol.

---

### Task 2: `sample_utils.py` — classification, name matching, iCloud path, kind refinement

**Files:**
- Create: `ableton_mcp_max/sample_utils.py`
- Create: `tests/test_sample_utils.py`

**Interfaces:**
- Produces:
  - `classify_sample(name: str, path: str) -> str` — one of `"loop"|"one_shot"|"kit"|"instrument"`
  - `name_match(query: str, name: str, folder: str) -> tuple` — `(matched: bool, score: int)`
  - `icloud_placeholder_path(sample_path: str) -> str | None` — sibling `.icloud` stub path, or None
  - `refine_kind_by_length(kind: str, frames: int, sample_rate: int, tempo: float) -> str` — upgrades a long `one_shot` to `loop`

- [ ] **Step 1: Write the failing tests for `classify_sample`**

```python
# tests/test_sample_utils.py
from ableton_mcp_max.sample_utils import (
    classify_sample, name_match, icloud_placeholder_path, refine_kind_by_length,
)


def test_classify_kit_adg_under_drums():
    assert classify_sample("Acoustic Kit.adg", "drums/Kits/Acoustic Kit.adg") == "kit"

def test_classify_instrument_adv():
    assert classify_sample("Dark Pad.adv", "instruments/Wavetable/Dark Pad.adv") == "instrument"

def test_classify_one_shot_by_folder_token():
    assert classify_sample("Hit 03.wav", "Samples/One Shots/Hit 03.wav") == "one_shot"

def test_classify_one_shot_by_name_token():
    assert classify_sample("Kick Deep.wav", "Samples/Drums/Kick Deep.wav") == "one_shot"
    assert classify_sample("Snare Tight.wav", "x/Snare Tight.wav") == "one_shot"
    assert classify_sample("Closed Hat.wav", "x/Closed Hat.wav") == "one_shot"
    assert classify_sample("Clap.wav", "x/Clap.wav") == "one_shot"
    assert classify_sample("Vox Stab.wav", "x/Vox Stab.wav") == "one_shot"

def test_classify_loop_by_folder_token():
    assert classify_sample("Groove.wav", "Samples/Loops/Groove.wav") == "loop"

def test_classify_loop_by_bpm_in_name():
    assert classify_sample("Drums 120 bpm.wav", "x/Drums 120 bpm.wav") == "loop"
    assert classify_sample("Beat 90bpm.wav", "x/Beat 90bpm.wav") == "loop"
    assert classify_sample("Top_128.wav", "x/Top_128.wav") == "loop"

def test_classify_loop_by_loop_token():
    assert classify_sample("Perc Loop.wav", "x/Perc Loop.wav") == "loop"

def test_classify_kit_beats_one_shot_priority():
    # a .adg under drums is a kit even if the name says "Kick"
    assert classify_sample("Kick Rack.adg", "drums/Kits/Kick Rack.adg") == "kit"

def test_classify_fallback_by_extension():
    # plain audio file, no tokens -> loop is too strong a guess; default to one_shot
    assert classify_sample("Untitled.wav", "x/Untitled.wav") == "one_shot"
    # non-audio, non-preset extension still returns a valid kind
    assert classify_sample("Notes.txt", "x/Notes.txt") in {"loop", "one_shot", "kit", "instrument"}
```

- [ ] **Step 2: Run to verify failure**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_sample_utils.py -q 2>&1 | head -15
```
Expected: ModuleNotFoundError (module does not exist yet).

- [ ] **Step 3: Create `ableton_mcp_max/sample_utils.py` with `classify_sample`**

```python
"""Pure sample-sourcing helpers. No Live or socket dependency.

classify_sample / name_match / refine_kind_by_length are pure (no I/O).
icloud_placeholder_path touches the filesystem only (no Live).
"""

import os
import re

# Single-hit drum/percussion words that mark a one-shot when they appear as a
# whole word in the file name.
_ONE_SHOT_WORDS = (
    "kick", "snare", "hat", "hihat", "clap", "stab", "hit", "tom", "rim",
    "crash", "ride", "perc", "shaker", "cowbell", "fx", "vox",
)
# Folder/name tokens.
_ONE_SHOT_TOKENS = ("one shot", "one shots", "oneshot", "hits/", "hits ")
_LOOP_TOKENS = ("loop", "loops")
# A BPM in the name: "120 bpm", "90bpm", or a trailing "_128".
_BPM_RE = re.compile(r"\b\d{2,3}\s?bpm\b", re.IGNORECASE)
_TRAILING_NUM_RE = re.compile(r"_(\d{2,3})(?:\.\w+)?$")

_AUDIO_EXTS = (".wav", ".aif", ".aiff", ".aifc", ".flac", ".mp3", ".ogg")


def _has_word(text, words):
    low = text.lower()
    for w in words:
        if re.search(r"\b%s\b" % re.escape(w), low):
            return True
    return False


def classify_sample(name, path):
    """Return "loop" | "one_shot" | "kit" | "instrument" from name + path.

    Priority (first match wins):
      1. .adg under a Drums/Kit folder            -> kit
      2. instrument preset (.adv)                 -> instrument
      3. one-shot tokens / single-hit drum words  -> one_shot
      4. loop tokens / a BPM in the name          -> loop
      5. fallback by extension (audio -> one_shot)
    """
    ext = os.path.splitext(name)[1].lower()
    low_path = path.lower().replace("\\", "/")
    low_name = name.lower()

    # 1. kit
    if ext == ".adg" and ("/drums/" in low_path or "/kit" in low_path
                          or low_path.startswith("drums/") or "kit" in low_path):
        return "kit"
    # 2. instrument
    if ext == ".adv":
        return "instrument"
    # 3. one_shot
    if any(tok in low_path for tok in _ONE_SHOT_TOKENS) or _has_word(low_name, _ONE_SHOT_WORDS):
        return "one_shot"
    # 4. loop
    if (any(tok in low_path for tok in _LOOP_TOKENS)
            or _BPM_RE.search(low_name) or _TRAILING_NUM_RE.search(low_name)):
        return "loop"
    # 5. fallback: audio files default to one_shot (conservative — refine after load)
    if ext in _AUDIO_EXTS:
        return "one_shot"
    return "one_shot"
```

- [ ] **Step 4: Run the classify tests**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_sample_utils.py -q
```
Expected: 10 passed.

- [ ] **Step 5: Write failing tests for `name_match`**

Append to `tests/test_sample_utils.py`:

```python
def test_name_match_single_term_hit():
    matched, score = name_match("kick", "Kick Deep 01.wav", "Samples/Drums")
    assert matched is True
    assert score >= 1

def test_name_match_or_semantics():
    # any term hitting => matched
    matched, _ = name_match("kick snare", "Snare Tight.wav", "x")
    assert matched is True

def test_name_match_folder_hit():
    matched, _ = name_match("drums", "Untitled.wav", "Samples/Drums/Kicks")
    assert matched is True

def test_name_match_no_hit():
    matched, score = name_match("piano", "Kick.wav", "Samples/Drums")
    assert matched is False
    assert score == 0

def test_name_match_whole_word_bonus_ranks_higher():
    _, exact = name_match("kick", "Kick.wav", "x")
    _, partial = name_match("kick", "Kickstarter Pad.wav", "x")
    assert exact > partial

def test_name_match_case_insensitive():
    matched, _ = name_match("KICK", "kick deep.wav", "x")
    assert matched is True
```

- [ ] **Step 6: Run to verify failure, then implement `name_match`**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_sample_utils.py::test_name_match_single_term_hit -q
```
Expected: ImportError (`name_match` not defined).

Append to `ableton_mcp_max/sample_utils.py`:

```python
def name_match(query, name, folder):
    """Return (matched, score) for a space-separated OR query against name+folder.

    matched is True if ANY query term appears in the name or folder
    (case-insensitive substring). score = term hits + a whole-word bonus per
    term that matches the name as a whole word (so exact-ish names rank above
    incidental substring hits). An empty query matches everything with score 0.
    """
    terms = [t for t in query.lower().split() if t]
    if not terms:
        return True, 0
    low_name = name.lower()
    low_folder = folder.lower()
    score = 0
    matched = False
    for t in terms:
        in_name = t in low_name
        in_folder = t in low_folder
        if in_name or in_folder:
            matched = True
            score += 1
            if re.search(r"\b%s\b" % re.escape(t), low_name):
                score += 1
    return matched, score
```

- [ ] **Step 7: Run name_match tests**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_sample_utils.py -q
```
Expected: 16 passed.

- [ ] **Step 8: Write failing tests for `icloud_placeholder_path` and `refine_kind_by_length`**

Append to `tests/test_sample_utils.py`:

```python
def test_icloud_placeholder_real_file_returns_none(tmp_path):
    real = tmp_path / "Kick.wav"
    real.write_bytes(b"RIFF....")
    assert icloud_placeholder_path(str(real)) is None

def test_icloud_placeholder_stub_present(tmp_path):
    # dataless: only the .Kick.wav.icloud stub exists, no real file
    stub = tmp_path / ".Kick.wav.icloud"
    stub.write_bytes(b"")
    result = icloud_placeholder_path(str(tmp_path / "Kick.wav"))
    assert result == str(stub)

def test_icloud_placeholder_neither_returns_none(tmp_path):
    # no real file and no stub -> not a known placeholder
    assert icloud_placeholder_path(str(tmp_path / "Ghost.wav")) is None

def test_refine_one_shot_to_loop_when_long():
    # 4 seconds at 120 bpm = 8 beats -> loop
    assert refine_kind_by_length("one_shot", frames=4 * 48000, sample_rate=48000, tempo=120.0) == "loop"

def test_refine_keeps_short_one_shot():
    # 0.25 s at 120 bpm = 0.5 beats -> stays one_shot
    assert refine_kind_by_length("one_shot", frames=12000, sample_rate=48000, tempo=120.0) == "one_shot"

def test_refine_boundary_just_over_two_beats():
    # exactly > 2 beats upgrades; 2 beats at 120 bpm = 1.0 s = 48000 frames
    assert refine_kind_by_length("one_shot", frames=48001, sample_rate=48000, tempo=120.0) == "loop"
    assert refine_kind_by_length("one_shot", frames=48000, sample_rate=48000, tempo=120.0) == "one_shot"

def test_refine_non_one_shot_unchanged():
    assert refine_kind_by_length("kit", frames=4 * 48000, sample_rate=48000, tempo=120.0) == "kit"

def test_refine_zero_sample_rate_unchanged():
    assert refine_kind_by_length("one_shot", frames=48000, sample_rate=0, tempo=120.0) == "one_shot"
```

- [ ] **Step 9: Run to verify failure, then implement both functions**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_sample_utils.py::test_icloud_placeholder_stub_present -q
```
Expected: ImportError.

Append to `ableton_mcp_max/sample_utils.py`:

```python
def icloud_placeholder_path(sample_path):
    """Return the sibling '.<name>.icloud' stub path, or None.

    Returns None when the real file already exists (not a placeholder) or when
    no stub exists (not a known iCloud dataless file). Returns the stub path
    only when the real file is absent AND the stub is present — i.e. a genuine
    undownloaded placeholder. Pure filesystem reads; no Live dependency.
    """
    if os.path.exists(sample_path):
        return None
    d = os.path.dirname(sample_path)
    base = os.path.basename(sample_path)
    stub = os.path.join(d, "." + base + ".icloud")
    return stub if os.path.exists(stub) else None


# A one-shot longer than this many beats is really a loop.
_LOOP_BEAT_THRESHOLD = 2.0


def refine_kind_by_length(kind, frames, sample_rate, tempo):
    """Upgrade a long 'one_shot' to 'loop' once true length is known.

    Only acts on kind == 'one_shot'. Returns kind unchanged for anything else,
    or when sample_rate/tempo are non-positive (can't compute beats).
    """
    if kind != "one_shot":
        return kind
    if not sample_rate or sample_rate <= 0 or not tempo or tempo <= 0:
        return kind
    duration_s = frames / float(sample_rate)
    beats = duration_s * tempo / 60.0
    return "loop" if beats > _LOOP_BEAT_THRESHOLD else kind
```

- [ ] **Step 10: Run all sample_utils tests**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_sample_utils.py -q
```
Expected: 24 passed.

- [ ] **Step 11: Commit**

```bash
git add ableton_mcp_max/sample_utils.py tests/test_sample_utils.py
git commit -m "feat(samples): add sample_utils (classify, name_match, icloud path, kind refine)"
```

---

### Task 3: `_ensure_local` iCloud-materialization helper

**Files:**
- Modify: `ableton_mcp_max/server.py` (add `_ensure_local` immediately before `_read_audio_meta`, ~line 4302)
- Create: `tests/test_ensure_local.py`

**Interfaces:**
- Consumes: `icloud_placeholder_path` from `sample_utils`, stdlib `subprocess`, `time`, `os`
- Produces: `_ensure_local(sample_path: str, timeout: int = 30) -> str` — returns the resolved local path; raises `RuntimeError` with a user-facing message on timeout/failure

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ensure_local.py
import os
import pytest
import ableton_mcp_max.server as server


def test_ensure_local_already_local(tmp_path):
    real = tmp_path / "Kick.wav"
    real.write_bytes(b"RIFF")
    assert server._ensure_local(str(real)) == str(real)


def test_ensure_local_downloads_placeholder(tmp_path, monkeypatch):
    target = tmp_path / "Kick.wav"
    stub = tmp_path / ".Kick.wav.icloud"
    stub.write_bytes(b"")  # dataless placeholder present, real file absent

    # Simulate brctl: when called, materialize the real file + remove the stub.
    def fake_run(args, **kw):
        target.write_bytes(b"RIFF")
        if stub.exists():
            stub.unlink()
        class _R:
            returncode = 0
        return _R()

    monkeypatch.setattr(server.subprocess, "run", fake_run)
    monkeypatch.setattr(server.time, "sleep", lambda s: None)
    assert server._ensure_local(str(target), timeout=5) == str(target)


def test_ensure_local_timeout_raises(tmp_path, monkeypatch):
    target = tmp_path / "Kick.wav"
    stub = tmp_path / ".Kick.wav.icloud"
    stub.write_bytes(b"")

    # brctl does nothing; the real file never appears -> timeout.
    def fake_run(args, **kw):
        class _R:
            returncode = 0
        return _R()

    monkeypatch.setattr(server.subprocess, "run", fake_run)
    monkeypatch.setattr(server.time, "sleep", lambda s: None)
    with pytest.raises(RuntimeError) as ei:
        server._ensure_local(str(target), timeout=1)
    assert "placeholder" in str(ei.value).lower()


def test_ensure_local_missing_no_stub_raises(tmp_path):
    # Neither a real file nor a stub: a plain missing path.
    with pytest.raises(RuntimeError):
        server._ensure_local(str(tmp_path / "Ghost.wav"), timeout=1)
```

- [ ] **Step 2: Run to verify failure**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_ensure_local.py -q
```
Expected: AttributeError (`_ensure_local` not defined) — and likely `server.subprocess`/`server.time` attribute errors, confirming those modules must be importable on the server module.

- [ ] **Step 3: Ensure `subprocess` and `time` are imported in server.py**

Check the top-of-file imports in `ableton_mcp_max/server.py`. If `import subprocess` or `import time` is missing, add it alongside the existing stdlib imports (do not duplicate an existing one):

```bash
grep -nE "^import (subprocess|time|os|glob)$" ableton_mcp_max/server.py
```
If `subprocess` or `time` is absent from that list, add the missing line(s) in the stdlib import block near the other `import os` / `import glob` lines.

- [ ] **Step 4: Implement `_ensure_local` before `_read_audio_meta`**

Insert immediately before `def _read_audio_meta(path):` (~line 4302):

```python
def _ensure_local(sample_path, timeout=30):
    """Materialize an iCloud-dataless sample so its bytes are on disk.

    1. If the file already exists locally, return its path.
    2. Else if a '.<name>.icloud' placeholder stub exists, run `brctl download`
       and poll (synchronously) up to `timeout` seconds for the real file.
    3. On timeout, or if the path is simply missing, raise RuntimeError with
       user-facing guidance.

    Synchronous blocking poll by design — this runs server-side, not in the
    Remote Script. Must be called by every loader BEFORE any header read
    (_read_audio_meta opens the file and would fail on a placeholder).
    """
    sample_path = os.path.expanduser(str(sample_path))
    if os.path.exists(sample_path):
        return sample_path

    stub = icloud_placeholder_path(sample_path)
    if stub is None:
        raise RuntimeError(
            "Sample not found and no iCloud placeholder present: %s" % sample_path)

    try:
        subprocess.run(["/usr/bin/brctl", "download", sample_path],
                       timeout=timeout, check=False)
    except Exception as e:
        logger.warning("brctl download failed for %s: %s", sample_path, e)

    deadline = time.monotonic() + max(1, timeout)
    while time.monotonic() < deadline:
        if os.path.exists(sample_path):
            return sample_path
        time.sleep(0.5)

    raise RuntimeError(
        "Sample is still an undownloaded iCloud placeholder after %ss: %s. "
        "Download it in Finder (or right-click -> Download Now) and retry."
        % (timeout, sample_path))
```

- [ ] **Step 5: Add the `sample_utils` import to server.py**

Add near the other `from ableton_mcp_max.* import` lines (e.g. after the `remediation_utils` import block):

```python
from ableton_mcp_max.sample_utils import (
    classify_sample,
    name_match,
    icloud_placeholder_path,
    refine_kind_by_length,
)
```

- [ ] **Step 6: Run tests + server import**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_ensure_local.py -q
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python -c "import ableton_mcp_max.server; print('ok')"
```
Expected: 4 passed, "ok".

- [ ] **Step 7: Commit**

```bash
git add ableton_mcp_max/server.py tests/test_ensure_local.py
git commit -m "feat(samples): add _ensure_local iCloud-materialization helper"
```

---

### Task 4: `search_samples` tool

**Files:**
- Modify: `ableton_mcp_max/server.py` (add `_sample_search_roots` + `search_samples` after `create_simpler_instrument`)
- Create: `tests/test_search_samples.py`

**Interfaces:**
- Consumes: `_user_library_dir`, `_app_core`, `classify_sample`, `name_match`, `icloud_placeholder_path`, `_ok`, `_err`
- Produces:
  - `_sample_search_roots(sources: list) -> list[tuple]` — list of `(root_dir, source_label)`; monkeypatched in tests
  - `search_samples(ctx, query, kinds, limit, sources) -> str`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_search_samples.py
import json
import os
import ableton_mcp_max.server as server


def _make_tree(root):
    """Build a small fake sample library under root."""
    files = {
        "Samples/Drums/Kicks/Kick Deep 01.wav": b"RIFF",
        "Samples/Drums/Snares/Snare Tight.wav": b"RIFF",
        "Samples/Loops/Drum Loop 120 bpm.wav": b"RIFF",
        "Presets/Instruments/Wavetable/Dark Pad.adv": b"x",
        "Drums/Kits/Acoustic Kit.adg": b"x",
        "readme.txt": b"x",  # non-sample, must be ignored
    }
    for rel, data in files.items():
        p = os.path.join(root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(data)


def test_search_samples_finds_by_name(tmp_path, monkeypatch):
    root = str(tmp_path / "user")
    _make_tree(root)
    monkeypatch.setattr(server, "_sample_search_roots", lambda sources: [(root, "user")])

    out = json.loads(server.search_samples(ctx=None, query="kick"))
    assert out["ok"] is True
    d = out["data"]
    names = [i["name"] for i in d["items"]]
    assert any("Kick Deep" in n for n in names)
    # snare/loop/adv should not match "kick"
    assert not any("Snare" in n for n in names)


def test_search_samples_classifies(tmp_path, monkeypatch):
    root = str(tmp_path / "user")
    _make_tree(root)
    monkeypatch.setattr(server, "_sample_search_roots", lambda sources: [(root, "user")])

    out = json.loads(server.search_samples(ctx=None, query="", limit=100))
    d = out["data"]
    by_name = {i["name"]: i for i in d["items"]}
    assert by_name["Kick Deep 01.wav"]["kind"] == "one_shot"
    assert by_name["Drum Loop 120 bpm.wav"]["kind"] == "loop"
    assert by_name["Dark Pad.adv"]["kind"] == "instrument"
    assert by_name["Acoustic Kit.adg"]["kind"] == "kit"
    # the .txt is not an enumerated sample
    assert "readme.txt" not in by_name


def test_search_samples_kind_filter(tmp_path, monkeypatch):
    root = str(tmp_path / "user")
    _make_tree(root)
    monkeypatch.setattr(server, "_sample_search_roots", lambda sources: [(root, "user")])

    out = json.loads(server.search_samples(ctx=None, query="", kinds=["loop"], limit=100))
    d = out["data"]
    assert all(i["kind"] == "loop" for i in d["items"])
    assert len(d["items"]) >= 1


def test_search_samples_limit_and_truncation(tmp_path, monkeypatch):
    root = str(tmp_path / "user")
    _make_tree(root)
    monkeypatch.setattr(server, "_sample_search_roots", lambda sources: [(root, "user")])

    out = json.loads(server.search_samples(ctx=None, query="", limit=2))
    d = out["data"]
    assert d["returned"] == 2
    assert d["count"] >= 2
    assert d["truncated"] is True


def test_search_samples_flags_icloud_placeholder(tmp_path, monkeypatch):
    root = str(tmp_path / "user")
    d = os.path.join(root, "Samples", "Drums")
    os.makedirs(d, exist_ok=True)
    # only the stub exists (dataless): .Kick.wav.icloud, no real Kick.wav
    with open(os.path.join(d, ".Kick.wav.icloud"), "wb") as f:
        f.write(b"")
    monkeypatch.setattr(server, "_sample_search_roots", lambda sources: [(root, "user")])

    out = json.loads(server.search_samples(ctx=None, query="kick", limit=100))
    items = out["data"]["items"]
    kick = next(i for i in items if i["name"] == "Kick.wav")
    assert kick["is_icloud_placeholder"] is True
    assert kick["path"].endswith("/Samples/Drums/Kick.wav")
```

- [ ] **Step 2: Run to verify failure**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_search_samples.py -q
```
Expected: AttributeError (`search_samples` not defined).

- [ ] **Step 3: Implement `_sample_search_roots` + `search_samples` after `create_simpler_instrument`**

Insert after the `create_simpler_instrument` function (after its closing, ~line 4388). Use the factory samples root confirmed by the Task 1 spike for `_app_core()`:

```python
# Audio sample file extensions enumerated by search_samples. Preset extensions
# (.adv/.adg) are also enumerated so kits/instruments surface.
_SAMPLE_EXTS = (".wav", ".aif", ".aiff", ".aifc", ".flac", ".mp3", ".ogg",
                ".adv", ".adg")


def _sample_search_roots(sources):
    """Resolve (root_dir, source_label) pairs to walk for the given sources.

    'user'   -> the configured User Library (iCloud-backed).
    'factory'-> the running Live's Core Library Samples tree (per Task 1 spike).
    Missing roots are skipped. Seam: monkeypatched in tests.
    """
    roots = []
    if "user" in sources:
        lib = _user_library_dir()
        if lib and os.path.isdir(lib):
            roots.append((lib, "user"))
    if "factory" in sources:
        core = _app_core()
        if core:
            fac = os.path.join(core, "Samples")
            if os.path.isdir(fac):
                roots.append((fac, "factory"))
    return roots


@mcp.tool()
def search_samples(
    ctx: Context,
    query: str,
    kinds: list = None,
    limit: int = 40,
    sources: list = None,
) -> str:
    """Search Live's sample library by name and return classified, ranked hits.

    Filesystem-walks the User Library and/or factory Core Library sample trees,
    matching `query` (space-separated terms, OR) against each file's name and
    folder, classifying each hit (loop / one_shot / kit / instrument), and
    returning the top `limit` by match score. READ-only: it never downloads —
    it only FLAGS files that are undownloaded iCloud placeholders so a later
    load knows to materialize them.

    Parameters:
    - query: space-separated search terms (OR). Empty string matches everything.
    - kinds: restrict to these classifications (default all four:
      ["loop","one_shot","kit","instrument"]).
    - limit: max results to return (default 40).
    - sources: which trees to walk: ["factory","user"] (default both).

    Returns JSON {ok, data:{count, returned, truncated, items:[{name, path,
    uri, kind, source, folder, is_icloud_placeholder}]}}. `count` is total
    matches; `items` holds at most `limit`, highest score first. `uri` is None
    (loaders take `sample_path`, not a browser URI).
    """
    try:
        kinds = kinds or ["loop", "one_shot", "kit", "instrument"]
        sources = sources or ["factory", "user"]
        kind_set = set(kinds)

        hits = []
        for root, source in _sample_search_roots(sources):
            for dirpath, _dirs, filenames in os.walk(root):
                for fn in filenames:
                    # iCloud stubs are hidden ".<name>.icloud" files; recover the
                    # real sample name + path from the stub so placeholders surface.
                    is_stub = fn.startswith(".") and fn.endswith(".icloud")
                    if is_stub:
                        real_name = fn[1:-len(".icloud")]
                    else:
                        real_name = fn
                    ext = os.path.splitext(real_name)[1].lower()
                    if ext not in _SAMPLE_EXTS:
                        continue
                    real_path = os.path.join(dirpath, real_name)
                    rel_folder = os.path.relpath(dirpath, root)
                    matched, score = name_match(query, real_name, rel_folder)
                    if not matched:
                        continue
                    kind = classify_sample(real_name, os.path.join(rel_folder, real_name))
                    if kind not in kind_set:
                        continue
                    hits.append({
                        "name": real_name,
                        "path": real_path,
                        "uri": None,
                        "kind": kind,
                        "source": source,
                        "folder": rel_folder,
                        "is_icloud_placeholder": icloud_placeholder_path(real_path) is not None,
                        "_score": score,
                    })

        hits.sort(key=lambda h: h["_score"], reverse=True)
        total = len(hits)
        shown = hits[:limit] if limit and limit > 0 else hits
        for h in shown:
            h.pop("_score", None)
        for h in hits[len(shown):]:
            h.pop("_score", None)
        return _ok({
            "count": total,
            "returned": len(shown),
            "truncated": len(shown) < total,
            "items": shown,
        })
    except Exception as e:
        logger.error("Error searching samples: %s", e)
        return _err("Error searching samples: %s" % e)
```

- [ ] **Step 4: Run tests + server import + full suite**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_search_samples.py -q
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python -c "import ableton_mcp_max.server; print('ok')"
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/ -q
```
Expected: 5 passed (new), "ok", ~685 total.

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/server.py tests/test_search_samples.py
git commit -m "feat(samples): add search_samples tool (filesystem walk + classify + rank)"
```

---

### Task 5: `load_audio_clip` tool (spike-gated)

**Files:**
- Modify: `ableton_mcp_max/server.py` (add `load_audio_clip` after `search_samples`)
- Create: `tests/test_load_audio_clip.py`

**Interfaces:**
- Consumes: `_ensure_local`, `_read_audio_meta`, `refine_kind_by_length`, `classify_sample`, `get_ableton_connection`, `_ok`, `_err` — plus (FALLBACK only) `build_simpler_adv`, `_read_default_adv`, `_write_user_preset`, `_load_user_preset`, `validate_preset_name`
- Produces: `load_audio_clip(ctx, track_index, clip_index, sample_path, track_type="regular") -> str`

**Spike decision:** Implement the variant Task 1 selected.
- **PRIMARY (spike result A):** `load_browser_item` drops the sample onto the audio slot.
- **FALLBACK (spike result B):** load the sample into a Simpler in loop-playback config and report honestly.

- [ ] **Step 1: Write the failing tests (variant-agnostic on the public contract)**

```python
# tests/test_load_audio_clip.py
import json
import os
import ableton_mcp_max.server as server


def test_load_audio_clip_materializes_then_loads(tmp_path, monkeypatch):
    sample = tmp_path / "Loop 120 bpm.wav"
    sample.write_bytes(b"RIFF")

    calls = {"ensure": [], "load": []}
    monkeypatch.setattr(server, "_ensure_local",
                        lambda p, timeout=30: (calls["ensure"].append(p) or str(sample)))
    # header read returns a 2-second loop @ 48k
    monkeypatch.setattr(server, "_read_audio_meta",
                        lambda p: (1000, 2 * 48000, 48000))

    class _FakeConn:
        def send_command(self, cmd, params=None):
            calls["load"].append((cmd, params))
            if cmd in ("load_browser_item",):
                return {"loaded": True}
            if cmd == "get_transport":
                return {"tempo": 120.0}
            return {"loaded": True}

    monkeypatch.setattr(server, "get_ableton_connection", lambda: _FakeConn())

    out = json.loads(server.load_audio_clip(
        ctx=None, track_index=3, clip_index=0, sample_path=str(sample)))
    assert out["ok"] is True
    # materialization ran before any load
    assert calls["ensure"], "expected _ensure_local to be called"
    d = out["data"]
    assert d["track_index"] == 3
    assert d["sample"].endswith("Loop 120 bpm.wav")


def test_load_audio_clip_placeholder_error(tmp_path, monkeypatch):
    def boom(p, timeout=30):
        raise RuntimeError("undownloaded iCloud placeholder after 30s")
    monkeypatch.setattr(server, "_ensure_local", boom)
    out = json.loads(server.load_audio_clip(
        ctx=None, track_index=0, clip_index=0, sample_path="/x/Ghost.wav"))
    assert out["ok"] is False
    assert "placeholder" in out["error"].lower()
```

- [ ] **Step 2: Run to verify failure**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_load_audio_clip.py -q
```
Expected: AttributeError.

- [ ] **Step 3a: Implement the PRIMARY variant (spike result A)** — after `search_samples`

```python
@mcp.tool()
def load_audio_clip(
    ctx: Context,
    track_index: int,
    clip_index: int,
    sample_path: str,
    track_type: str = "regular",
) -> str:
    """Load an audio sample (typically a loop) into an audio clip slot.

    Materializes the file from iCloud first if needed, then loads it onto the
    target audio track + clip slot. Reads the file header to report the clip's
    refined kind (a long one-shot is reported as a loop).

    Parameters:
    - track_index: index of the audio track.
    - clip_index: clip slot index on that track.
    - sample_path: absolute path to the sample (as returned by search_samples).
    - track_type: "regular" (default). Audio clips are a regular-track concept.

    Returns JSON {ok, data:{track_index, clip_index, sample, frames,
    sample_rate, kind, loaded}}.
    """
    try:
        local = _ensure_local(sample_path)
        size, frames, rate = _read_audio_meta(local)
        ableton = get_ableton_connection()
        tempo = 120.0
        try:
            tempo = float(ableton.send_command("get_transport").get("tempo", 120.0))
        except Exception:
            pass
        # Select the target slot, then load the sample item onto it.
        ableton.send_command("set_highlighted_clip_slot",
                             {"track_index": track_index, "scene_index": clip_index})
        result = ableton.send_command("load_browser_item", {
            "track_index": track_index,
            "item_uri": "samples:%s" % local,   # spike confirms the uri grammar
            "track_type": track_type,
        })
        loaded = bool(result.get("loaded", False))
        if not loaded:
            return _err("Failed to load audio clip from %s (load_browser_item "
                        "did not confirm)." % os.path.basename(local))
        kind = refine_kind_by_length(
            classify_sample(os.path.basename(local), local), frames, rate, tempo)
        return _ok({
            "track_index": track_index,
            "clip_index": clip_index,
            "sample": local,
            "frames": frames,
            "sample_rate": rate,
            "kind": kind,
            "loaded": True,
        })
    except RuntimeError as e:
        return _err("Error: %s" % e)
    except Exception as e:
        logger.error("Error loading audio clip: %s", e)
        return _err("Error loading audio clip: %s" % e)
```

**NOTE for the implementer:** the exact `item_uri` grammar / whether `set_highlighted_clip_slot` is the right selection call is what the Task 1 spike pins down. Replace `"samples:%s" % local` and the selection call with the verified mechanism from the spike findings. If `load_browser_item` cannot take a raw path (spike result A still requires a real browser URI), have the spike record the URI-resolution step and add it here.

- [ ] **Step 3b: ALTERNATIVELY implement the FALLBACK variant (spike result B)**

If the spike found audio clips are not browser-loadable, build on `create_simpler_instrument`'s proven path instead — load the loop into a Simpler set to loop playback, on the target track:

```python
@mcp.tool()
def load_audio_clip(
    ctx: Context,
    track_index: int,
    clip_index: int,
    sample_path: str,
    track_type: str = "regular",
) -> str:
    """Load an audio sample as a looping Simpler instrument on a track.

    NOTE: Live's API does not let MCP drop a raw sample onto an audio clip slot
    (verified in the sample-sourcing spike), so this loads the sample into a
    Simpler configured for loop playback and reports that honestly. The clip_index
    is accepted for API symmetry but the sample plays via the instrument, not a
    clip in that slot.

    Returns JSON {ok, data:{track_index, sample, frames, sample_rate, kind,
    loaded, mode:"simpler_loop", note}}.
    """
    try:
        local = _ensure_local(sample_path)
        safe = validate_preset_name(os.path.splitext(os.path.basename(local))[0])
        size, frames, rate = _read_audio_meta(local)
        if frames <= 0:
            return _err("Error: could not read a frame count for %r. Convert to "
                        "WAV/AIFF first." % os.path.basename(local))
        xml = build_simpler_adv(
            _read_default_adv("Simpler.adv"), sample_path=local,
            file_size=size, frames=frames, sample_rate=rate, name=safe,
            root_key=60, relative_path=os.path.basename(local),
            relative_path_type=0,
        )
        dest, browser_path = _write_user_preset(xml, safe, "Simpler")
        loaded, note = _load_user_preset(track_index, browser_path, safe)
        ableton = get_ableton_connection()
        tempo = 120.0
        try:
            tempo = float(ableton.send_command("get_transport").get("tempo", 120.0))
        except Exception:
            pass
        kind = refine_kind_by_length(
            classify_sample(os.path.basename(local), local), frames, rate, tempo)
        return _ok({
            "track_index": track_index,
            "sample": local,
            "frames": frames,
            "sample_rate": rate,
            "kind": kind,
            "loaded": loaded,
            "mode": "simpler_loop",
            "note": note,
        })
    except RuntimeError as e:
        return _err("Error: %s" % e)
    except (ValueError, FileNotFoundError) as e:
        return _err("Error: %s" % e)
    except Exception as e:
        logger.error("Error loading audio clip: %s", e)
        return _err("Error loading audio clip: %s" % e)
```

If you implement variant 3b, update the two tests in Step 1: the FALLBACK returns `data["mode"] == "simpler_loop"` and does not require `set_highlighted_clip_slot`/`load_browser_item`; adjust the `_FakeConn` to handle `get_browser_presets`/`load_browser_item` for `_load_user_preset` and add `build_simpler_adv`/`_read_default_adv`/`_write_user_preset`/`_load_user_preset` monkeypatches as needed. Keep the placeholder-error test unchanged.

- [ ] **Step 4: Run tests + server import + full suite**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_load_audio_clip.py -q
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python -c "import ableton_mcp_max.server; print('ok')"
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/ -q
```
Expected: 2 passed (new), "ok", ~687 total.

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/server.py tests/test_load_audio_clip.py
git commit -m "feat(samples): add load_audio_clip tool"
```

---

### Task 6: `load_sample_to_drum_pad` tool (spike-gated)

**Files:**
- Modify: `ableton_mcp_max/server.py` (add `load_sample_to_drum_pad` after `load_audio_clip`)
- Create: `tests/test_load_sample_to_drum_pad.py`

**Interfaces:**
- Consumes: `_ensure_local`, `_read_audio_meta`, `get_ableton_connection`, `_ok`, `_err` — plus (FALLBACK) the rack `.adg` patch infra (`_read_rack_template`, `_write_user_preset`, `_load_user_preset`) and a new `rack_preset_utils` helper if the spike requires injecting a sample at a pad note.
- Produces: `load_sample_to_drum_pad(ctx, track_index, pad_note, sample_path) -> str`

**Spike decision:** Implement the variant Task 1 selected (A = select pad chain + `load_browser_item`; B = preset-patch the Drum Rack `.adg`). If the spike found a NEW RS command is required for B, that is Task 6.5 (insert before this), built per the dual-restart protocol.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_load_sample_to_drum_pad.py
import json
import ableton_mcp_max.server as server


def test_load_sample_to_drum_pad_happy(tmp_path, monkeypatch):
    sample = tmp_path / "Kick.wav"
    sample.write_bytes(b"RIFF")
    monkeypatch.setattr(server, "_ensure_local", lambda p, timeout=30: str(sample))
    monkeypatch.setattr(server, "_read_audio_meta", lambda p: (100, 24000, 48000))

    calls = []

    class _FakeConn:
        def send_command(self, cmd, params=None):
            calls.append((cmd, params))
            if cmd == "get_rack_chains":
                return {"chains": [{"index": 0, "name": "Kick", "note": 36}]}
            return {"loaded": True}

    monkeypatch.setattr(server, "get_ableton_connection", lambda: _FakeConn())

    out = json.loads(server.load_sample_to_drum_pad(
        ctx=None, track_index=2, pad_note=36, sample_path=str(sample)))
    assert out["ok"] is True
    d = out["data"]
    assert d["track_index"] == 2
    assert d["pad_note"] == 36
    assert d["sample"].endswith("Kick.wav")


def test_load_sample_to_drum_pad_placeholder_error(monkeypatch):
    def boom(p, timeout=30):
        raise RuntimeError("undownloaded iCloud placeholder after 30s")
    monkeypatch.setattr(server, "_ensure_local", boom)
    out = json.loads(server.load_sample_to_drum_pad(
        ctx=None, track_index=0, pad_note=36, sample_path="/x/Ghost.wav"))
    assert out["ok"] is False
    assert "placeholder" in out["error"].lower()
```

- [ ] **Step 2: Run to verify failure**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_load_sample_to_drum_pad.py -q
```
Expected: AttributeError.

- [ ] **Step 3: Implement the spike-selected variant** — after `load_audio_clip`

PRIMARY (spike result A) skeleton — adjust the chain-selection + load calls to the exact mechanism the spike recorded:

```python
@mcp.tool()
def load_sample_to_drum_pad(
    ctx: Context,
    track_index: int,
    pad_note: int,
    sample_path: str,
) -> str:
    """Load a one-shot sample onto a single Drum Rack pad.

    Materializes the file from iCloud first if needed, locates the Drum Rack on
    the track and the pad chain for `pad_note` (MIDI note of the pad, e.g. 36 =
    C1), and loads the sample onto that pad.

    Parameters:
    - track_index: index of the track holding the Drum Rack.
    - pad_note: MIDI note number of the target pad.
    - sample_path: absolute path to the one-shot (as returned by search_samples).

    Returns JSON {ok, data:{track_index, pad_note, sample, loaded}}.
    """
    try:
        local = _ensure_local(sample_path)
        ableton = get_ableton_connection()
        chains = ableton.send_command("get_rack_chains", {"track_index": track_index})
        pads = chains.get("chains", []) if isinstance(chains, dict) else []
        pad = next((c for c in pads if c.get("note") == pad_note), None)
        if pad is None and not pads:
            return _err("No Drum Rack chains found on track %s. Load a Drum Rack "
                        "first." % track_index)
        # Select the pad chain + load (exact calls per Task 1 spike findings).
        result = ableton.send_command("load_browser_item", {
            "track_index": track_index,
            "item_uri": "samples:%s" % local,
            "pad_note": pad_note,
        })
        loaded = bool(result.get("loaded", False))
        if not loaded:
            return _err("Failed to load %s onto pad %s of track %s."
                        % (os.path.basename(local), pad_note, track_index))
        return _ok({
            "track_index": track_index,
            "pad_note": pad_note,
            "sample": local,
            "loaded": True,
        })
    except RuntimeError as e:
        return _err("Error: %s" % e)
    except Exception as e:
        logger.error("Error loading sample to drum pad: %s", e)
        return _err("Error loading sample to drum pad: %s" % e)
```

**NOTE for the implementer:** replace the `load_browser_item` params (`item_uri` grammar, `pad_note` routing) with the verified mechanism from the spike. If the spike selected FALLBACK B (preset-patch), implement instead by: reading the track's current Drum Rack `.adg` (or a factory Drum Rack template via `_read_rack_template`), injecting a `<MultiSamplePart>` referencing `local` into the pad chain at `pad_note` (add a pure helper `inject_drum_pad_sample(xml, pad_note, sample_path, frames, sample_rate)` in `rack_preset_utils.py` with its own offline test mirroring the existing rack-XML tests + a `@pytest.mark.skipif` real-`.adg` round-trip), writing via `_write_user_preset(..., category="Drums", ext="adg")`, and loading via `_load_user_preset`. Keep the public return shape identical so the tests above pass unchanged.

- [ ] **Step 4: Run tests + server import + full suite**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_load_sample_to_drum_pad.py -q
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python -c "import ableton_mcp_max.server; print('ok')"
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/ -q
```
Expected: 2 passed (new; more if a `rack_preset_utils` helper test was added), "ok", ~689 total.

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/server.py tests/test_load_sample_to_drum_pad.py
git commit -m "feat(samples): add load_sample_to_drum_pad tool"
```

---

### Task 7: `populate_drum_rack` tool

**Files:**
- Modify: `ableton_mcp_max/server.py` (add `populate_drum_rack` after `load_sample_to_drum_pad`)
- Create: `tests/test_populate_drum_rack.py`

**Interfaces:**
- Consumes: `load_sample_to_drum_pad` (called as a plain Python function, not via MCP), `_ok`, `_err`
- Produces: `populate_drum_rack(ctx, track_index, mapping) -> str`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_populate_drum_rack.py
import json
import ableton_mcp_max.server as server


def test_populate_drum_rack_loads_all(monkeypatch):
    # Stub the single-pad loader to succeed and record calls.
    seen = []
    def fake_pad(ctx, track_index, pad_note, sample_path):
        seen.append((track_index, pad_note, sample_path))
        return json.dumps({"ok": True, "data": {"track_index": track_index,
                          "pad_note": pad_note, "sample": sample_path, "loaded": True}})
    monkeypatch.setattr(server, "load_sample_to_drum_pad", fake_pad)

    mapping = [
        {"pad_note": 36, "sample_path": "/s/Kick.wav"},
        {"pad_note": 38, "sample_path": "/s/Snare.wav"},
    ]
    out = json.loads(server.populate_drum_rack(ctx=None, track_index=1, mapping=mapping))
    assert out["ok"] is True
    d = out["data"]
    assert d["loaded_count"] == 2
    assert len(d["results"]) == 2
    assert all(r["status"] == "loaded" for r in d["results"])
    assert len(seen) == 2


def test_populate_drum_rack_partial_failure(monkeypatch):
    def fake_pad(ctx, track_index, pad_note, sample_path):
        if pad_note == 40:
            return json.dumps({"ok": False, "error": "undownloaded iCloud placeholder"})
        return json.dumps({"ok": True, "data": {"loaded": True}})
    monkeypatch.setattr(server, "load_sample_to_drum_pad", fake_pad)

    mapping = [
        {"pad_note": 36, "sample_path": "/s/Kick.wav"},
        {"pad_note": 40, "sample_path": "/s/Clap.wav"},  # fails
    ]
    out = json.loads(server.populate_drum_rack(ctx=None, track_index=1, mapping=mapping))
    assert out["ok"] is True   # the call itself succeeds; per-entry failures are reported
    d = out["data"]
    assert d["loaded_count"] == 1
    statuses = {r["pad_note"]: r["status"] for r in d["results"]}
    assert statuses[36] == "loaded"
    assert statuses[40] == "error"
    err_entry = next(r for r in d["results"] if r["pad_note"] == 40)
    assert "error" in err_entry


def test_populate_drum_rack_bad_mapping_entry():
    out = json.loads(server.populate_drum_rack(
        ctx=None, track_index=1, mapping=[{"sample_path": "/s/x.wav"}]))  # missing pad_note
    assert out["ok"] is False
```

- [ ] **Step 2: Run to verify failure**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_populate_drum_rack.py -q
```
Expected: AttributeError.

- [ ] **Step 3: Implement `populate_drum_rack`** — after `load_sample_to_drum_pad`

```python
@mcp.tool()
def populate_drum_rack(
    ctx: Context,
    track_index: int,
    mapping: list,
) -> str:
    """Load many one-shot samples onto many Drum Rack pads in one call.

    Loops load_sample_to_drum_pad over `mapping`. Does NOT abort on the first
    failure — each entry's result is reported so partial failures are visible.

    Parameters:
    - track_index: index of the track holding the Drum Rack.
    - mapping: list of {pad_note, sample_path}.

    Returns JSON {ok, data:{track_index, loaded_count, results:[{pad_note,
    sample_path, status:"loaded"|"error", error?}]}}.
    """
    try:
        if not isinstance(mapping, list) or not mapping:
            return _err("mapping must be a non-empty list of {pad_note, sample_path}.")
        results = []
        loaded_count = 0
        for entry in mapping:
            if not isinstance(entry, dict) or "pad_note" not in entry \
                    or "sample_path" not in entry:
                return _err("Each mapping entry needs 'pad_note' and 'sample_path'; "
                            "got %r." % (entry,))
            pad_note = entry["pad_note"]
            sample_path = entry["sample_path"]
            raw = load_sample_to_drum_pad(
                ctx, track_index=track_index, pad_note=pad_note,
                sample_path=sample_path)
            res = json.loads(raw)
            if res.get("ok"):
                loaded_count += 1
                results.append({"pad_note": pad_note, "sample_path": sample_path,
                                "status": "loaded"})
            else:
                results.append({"pad_note": pad_note, "sample_path": sample_path,
                                "status": "error",
                                "error": res.get("error", "unknown error")})
        return _ok({
            "track_index": track_index,
            "loaded_count": loaded_count,
            "results": results,
        })
    except Exception as e:
        logger.error("Error populating drum rack: %s", e)
        return _err("Error populating drum rack: %s" % e)
```

- [ ] **Step 4: Run tests + server import + full suite**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_populate_drum_rack.py -q
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python -c "import ableton_mcp_max.server; print('ok')"
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/ -q
```
Expected: 3 passed (new), "ok", ~692 total.

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/server.py tests/test_populate_drum_rack.py
git commit -m "feat(samples): add populate_drum_rack tool"
```

---

### Task 8: Docs regen, category registration, version bump

**Files:**
- Modify: `scripts/gen_docs_site.py` (add the "samples" category)
- Modify: `pyproject.toml`, `.claude-plugin/plugin.json` (version 0.12.0 -> 0.13.0)
- Modify: `uv.lock` (via `uv lock`)
- Modify: `docs/index.md` (hero counts), regenerated `docs/tools/*`, `commands/tool-index.md`

- [ ] **Step 1: Register the "samples" category in `gen_docs_site.py`**

In `scripts/gen_docs_site.py`, append a new tuple to the `CATEGORIES` list AFTER the `"remediation"` entry (the list ends with `]` at ~line 110). Every tool name must appear exactly once across the map (asserted by the script), so this adds the 4 new tools:

```python
    ("samples", "Samples", "Discover audio samples in Live's User Library and factory packs and load them as audio clips, single drum-rack pads, or full drum kits: search by name with automatic loop/one-shot/kit/instrument classification, and load with transparent iCloud materialization.", [
        "search_samples",
        "load_audio_clip",
        "load_sample_to_drum_pad",
        "populate_drum_rack",
    ]),
```

- [ ] **Step 2: Regenerate the docs site + tool index**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python scripts/gen_docs_site.py
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python scripts/build_tool_index.py
```
Expected output mentions "136 tools across 20 categories". If the script raises an AssertionError ("tool not in category map" or "Duplicate tool"), a tool name is misspelled in the category tuple vs the `@mcp.tool()` def — fix the tuple to match.

- [ ] **Step 3: Update the hardcoded hero counts in `docs/index.md`**

The landing page hardcodes tool + category counts in 5 spots (per project CLAUDE.md). Update each from the old values to **136** tools / **20** categories:

```bash
grep -nE "132|19 categor|nineteen|exposes the" docs/index.md
```
Edit each occurrence: the description line, the tagline, the two `stats__num` numbers, and the "exposes the N `@mcp.tool()`" line. Change `132` -> `136` and `19` -> `20` where they refer to tool/category totals (do not touch unrelated numbers).

- [ ] **Step 4: Bump the version in three places**

In `pyproject.toml`: change `version = "0.12.0"` to `version = "0.13.0"`.
In `.claude-plugin/plugin.json`: change `"version": "0.12.0"` to `"version": "0.13.0"`.
Then sync the lockfile:

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv lock
grep -nE "0\.1[23]\.0" pyproject.toml .claude-plugin/plugin.json | head
```
Expected: both files show 0.13.0.

- [ ] **Step 5: Final full suite + server import**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/ -q
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python -c "import ableton_mcp_max.server; print('ok')"
```
Expected: ~692 passed, "ok".

- [ ] **Step 6: Commit**

```bash
git add scripts/gen_docs_site.py pyproject.toml .claude-plugin/plugin.json uv.lock docs/ commands/tool-index.md
git commit -m "chore(samples): docs regen + version bump 0.12.0 -> 0.13.0 (136 tools, Samples category)"
```

---

### Task 9: Live verification

**Files:**
- Modify: `PROGRESS.md` (append live-verify results)

After Tasks 1-8, restart Claude Code (server.py changed — MCP loads at session start; see CLAUDE.md) so the AbletonDev tools expose the 4 new tools as deferred tools (load via `ToolSearch select:mcp__AbletonDev__search_samples,...`). If Task 6.5 added an RS command, also reinstall the Remote Script and bounce Live first.

- [ ] **Step 1: Verify `search_samples`**

Call `mcp__AbletonDev__search_samples` with `query="kick"` (both sources). Confirm: results return, each has `kind`/`source`/`path`, and at least one User Library hit. Try `kinds=["loop"]` and confirm only loops come back. Note any `is_icloud_placeholder: true` hits.

- [ ] **Step 2: Verify `load_audio_clip`**

Create a scratch audio track (`create_audio_track`). Pick a loop from Step 1 and call `load_audio_clip` onto it. Confirm via `get_clip_info` / `get_device_info` that the result matches the implemented variant (audio clip present, or Simpler-loop per the fallback). Delete the scratch track.

- [ ] **Step 3: Verify `load_sample_to_drum_pad` + `populate_drum_rack`**

Create a scratch MIDI track, load a Drum Rack, then `load_sample_to_drum_pad` a one-shot onto pad note 36; confirm via `get_rack_chains`. Then `populate_drum_rack` with 2-3 mappings and confirm `loaded_count`. If a hit was an iCloud placeholder, confirm materialization worked (no placeholder error). Delete the scratch track.

- [ ] **Step 4: Record results + commit**

Append a "Sample sourcing live-verify (2026-06-19)" block to `PROGRESS.md` with pass/fail per tool and any gotchas. Restore the set (delete scratch tracks). Then:

```bash
git add PROGRESS.md
git commit -m "docs(samples): record sample-sourcing live-verify results"
```

---

## Self-Review

**Spec coverage** (checked against `docs/superpowers/specs/2026-06-19-sample-sourcing-design.md`):
- 4 tools — `search_samples` (Task 4), `load_audio_clip` (Task 5), `load_sample_to_drum_pad` (Task 6), `populate_drum_rack` (Task 7). ✓
- `sample_utils.py` with all 4 functions — Task 2. ✓
- `_ensure_local` materialization — Task 3. ✓
- Feasibility gates as first task — Task 1 spike. ✓
- `refine_kind_by_length` wired into the loader — Task 5 Step 3 (both variants call it). ✓
- iCloud placeholder flagging in search (no download) — Task 4 (uses `icloud_placeholder_path`, never `_ensure_local`). ✓
- Reader-limit convention (count/returned/truncated) — Task 4. ✓
- Testing approach (offline utils, temp-dir search, mocked `_ensure_local`) — Tasks 2-7. ✓
- Version 0.12.0 -> 0.13.0, 132 -> 136 tools, 19 -> 20 categories, Samples category — Task 8. ✓
- Out-of-scope items (preview, audio-similarity, warp) — not built; correctly absent. ✓
- Live verification recorded in PROGRESS.md — Task 9. ✓

**Placeholder scan:** The gated loaders (Tasks 5/6) intentionally carry BOTH primary and fallback concrete implementations because the spike result is not knowable at plan-writing time — this is a feasibility gate, not a placeholder. Every other task has full code. No "TODO"/"add error handling"/"similar to Task N" stubs.

**Type consistency:** `classify_sample(name, path)`, `name_match(query, name, folder) -> (bool, int)`, `icloud_placeholder_path(path) -> str|None`, `refine_kind_by_length(kind, frames, sample_rate, tempo)`, `_ensure_local(path, timeout=30) -> str`, `_sample_search_roots(sources) -> [(root, label)]` — used identically across Tasks 2-7. `load_sample_to_drum_pad(ctx, track_index, pad_note, sample_path)` signature matches its call in `populate_drum_rack`. Return shapes (`{ok, data:{...}}`) consistent throughout.
