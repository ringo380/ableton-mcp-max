# Stem Separation to Arrangement — Design

**Created**: 2026-06-22
**Status**: In Progress

## Overview

Add an MCP tool that takes a single mixed audio file, separates it into its
component stems using a command-line source-separation tool (Demucs), detects
the original file's tempo and musical key, sets those on the open Live set, and
lays each stem out on its own audio track stacked at bar 1 of the **Arrangement**
view.

This is the "unmix a song into Ableton" workflow: point at a track, get a Live
set with drums / bass / other / vocals each on their own timeline track, at the
song's real tempo and key.

## Goals

- One mixed audio file in → N audio tracks in the Arrangement, one stem each.
- Detect tempo + key from the original audio and apply them to the set before
  laying out stems.
- Reuse existing, proven MCP handlers for every Ableton-side operation (no new
  Remote Script code).
- Keep the heavy ML dependencies (torch via Demucs, librosa) **out** of the MCP
  server's `uv` venv by shelling out to external CLIs / brew Python.

## Non-Goals

- Authoring `.als` files from scratch (ruled out — large, brittle).
- Session/Live-view layout. This is Arrangement-only. (Session clip slots are
  used only as transient staging; the end state has empty session slots.)
- Per-stem effects, mixing, or gain staging — out of scope; the user takes it
  from here.

## Decisions (from brainstorming)

- **Set target**: Option A — populate the currently open set (append audio
  tracks). A `fresh=True` flag bounces Live to a blank set first. Truly-new
  `.als` authoring rejected.
- **Separation tool**: Demucs CLI, with a `model` parameter defaulting to
  `htdemucs` (4-stem). Options: `htdemucs_6s` (6-stem: adds guitar, piano) and
  a two-stem mode (`--two-stems=vocals` → vocals + accompaniment).
- **Placement**: Arrangement timeline only, all stems at bar 1, stacked.
- **Warp**: OFF on every arrangement clip. Full-song stems are not loops; with
  the project tempo set to the detected BPM, warp-off keeps every stem
  sample-accurate and phase-locked (they came from one file).
- **Tempo + key**: detect from the original audio with librosa *before* layout,
  then `set_tempo` + `set_song_scale`.
- **Stem order** (top to bottom): `drums, bass, other, vocals`
  (+ `guitar, piano` for 6-stem).
- **No LOM direct-to-arrangement load exists**: stems are staged into a session
  clip slot, then `duplicate_clip_to_arrangement` to bar 1, then the session
  staging clip is deleted. Transient session touch, clean end state. Accepted.

## Architecture

Follows the repo convention: resolve/normalize/validate on the server in a pure
helper module; the tool orchestrates; the Remote Script is untouched.

### 1. `ableton_mcp_max/stem_utils.py` (new, pure, unit-tested)

Import-light — no torch, no librosa. Pure functions only:

- `validate_model(model) -> dict` — canonical Demucs model name, expected stem
  filenames, and per-stem track display name + color + layout order.
- `build_demucs_cmd(audio_path, model, out_dir, device) -> list[str]` — argv for
  the Demucs subprocess (including `--two-stems=vocals` when the two-stem model
  is requested).
- `expected_stem_paths(out_dir, model, track_basename) -> list[(name, path)]` —
  where Demucs writes each `.wav`
  (`<out_dir>/<demucs_model>/<track_basename>/<stem>.wav`), in layout order.
- `parse_analysis(json_str) -> (tempo: float|None, key: str|None, scale: str|None)`
  — parse the analyze-audio JSON (raw `{tempo, key_pitch_class, mode}`) and map
  it to `set_song_scale`-ready `(tempo, key, scale)` via `key_to_scale_args`.
- `key_to_scale_args(pitch_class, mode) -> (key: str, scale: str)` — map
  librosa's detected pitch class (e.g. `"C#"`) + `mode` (`"major"`/`"minor"`) to
  `set_song_scale` arguments. This is the pure, offline-tested seam — so the
  analysis script stays a thin librosa wrapper and the mapping is covered by the
  test gate even when librosa is absent.

### 2. `scripts/analyze_audio.py` (new, external subprocess)

Run via **brew Python** (`/opt/homebrew/bin/python3`), not the server venv.
Loads the file with librosa, estimates tempo (`librosa.beat.beat_track`) and key
(chroma + Krumhansl-Schmuckler profile, per `~/.claude/notes/audio-analysis.md`),
and prints a single JSON object of **raw** detection:
`{"tempo": float, "key_pitch_class": str, "mode": "major"|"minor"}`. The
pitch-class/mode to `set_song_scale` mapping is left to `stem_utils` so it stays
a pure, offline-tested seam. Keeps librosa/numba/scipy out of the MCP server venv.

### 3. Demucs (external CLI)

Invoked as a subprocess found on `PATH` (`/opt/homebrew/bin/demucs`). No new
Python dependency. A clear, actionable error is returned if it is not installed.

### 4. `separate_stems_to_arrangement(...)` tool in `server.py`

```python
@mcp.tool()
def separate_stems_to_arrangement(
    ctx,
    audio_path: str,
    model: str = "htdemucs",        # htdemucs (4) | htdemucs_6s (6) | two_stems
    fresh: bool = False,            # bounce to a blank set first (gated; see Fresh Mode)
    detect_tempo: bool = True,
    detect_key: bool = True,
    device: str = "auto",           # auto -> mps on Apple Silicon, else cpu
    output_dir: str = None,         # default: a temp working dir
) -> str
```

**Flow (host-side):**

1. `_ensure_local(audio_path)` — materialize from iCloud if needed; validate it
   is a decodable audio file. Fail early otherwise.
2. Resolve `device` (`auto` → `mps` on Apple Silicon for speed, else `cpu`).
3. **Separate**: subprocess Demucs → stems under `output_dir`. Runs before any
   socket call, so a multi-minute separation never risks an Ableton-socket
   timeout.
4. **Analyze** (if `detect_tempo`/`detect_key`): subprocess `analyze_audio.py`
   via brew Python → `{tempo, key, scale}`.
5. **Apply musical context**: `set_tempo(tempo)`, then `set_song_scale(key,
   scale)`. Verified via a follow-up read (song-property writes lag their own
   read-back — never trust the returned dict).
6. **Lay out stems** — for each stem, in layout order:
   - `create_audio_track` (named + colored per `stem_utils`),
   - `load_audio_clip` into that track's session slot 0 (staging),
   - `duplicate_clip_to_arrangement(track, slot=0, time=0.0)`,
   - set Warp OFF on the new arrangement clip,
   - delete the session staging clip.
7. Return `{ok, data:{audio, model, device, tempo, key, scale,
   stems:[{name, track_index, path, loaded}], fresh, tempo_detected,
   key_detected}}`.

### 5. `/ableton:stems <file>` slash command (new, front door)

Thin orchestration wrapper providing the up-front prompt that an MCP tool cannot
do itself:

- Explains that `fresh` mode discards the currently open set; asks the user to
  confirm and to have Live ready.
- Non-fresh: just appends stem tracks to whatever set is open.
- Calls `separate_stems_to_arrangement` with the resolved arguments.

## Fresh Mode (`fresh=True`)

- The tool **never silently discards work.** With `fresh=True`, its first step
  bounces Live to a blank set via the existing `restart_live` path (which
  already handles the dirty-set save/discard policy).
- Contract: the calling agent/command MUST have confirmed with the user before
  passing `fresh=True`.
- If a clean blank set cannot be reached (e.g. an untitled dirty set needs a
  Save-As path dialog `restart_live` cannot fill), the tool returns `{ok:false}`
  with a message telling the user to save/name the set by hand first. No data
  loss, no half-populated set.

## Error Handling

Each failure returns a clean `{ok:false}` with an actionable message and leaves
no half-finished state:

- Demucs not on `PATH` → instruct the user to install it (link to docs
  Prerequisites).
- Brew Python / librosa missing → **degrade gracefully**: skip tempo/key, keep
  the default project tempo, still lay out stems, and report
  `tempo_detected:false` / `key_detected:false` rather than failing the run.
- `audio_path` missing or not a decodable audio file → fail before Demucs.
- Demucs subprocess non-zero exit / no stem files produced → fail with the
  stderr tail.
- An Ableton socket step fails mid-layout → report which stems made it in
  (partial result); do not claim success.
- `fresh=True` cannot reach a clean blank set → `{ok:false}`, no destructive
  action.

## Documentation

Add a **Prerequisites / setup** section (README + generated docs site) covering:

- Installing the Demucs CLI: `pip3 install --break-system-packages demucs`
  (lands in brew Python's site-packages; the `demucs` CLI ends up on `PATH`).
- Installing librosa for analysis (already present at librosa 0.11.0 on this
  machine; document it for other setups).
- The macOS brew-Python caveat (`/opt/homebrew/bin/python3`, not
  `/usr/bin/python3`) so the analyze step finds librosa.
- Note that the tool returns a clear error when either is missing.

Regen the tool index / docs site per the publish flow
(`scripts/build_tool_index.py`, `scripts/gen_docs_site.py`, and the hardcoded
counts in `docs/index.md`) on ship.

## Testing

Offline gate: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q`.

- `tests/test_stem_utils.py` — pure unit tests: model validation/normalization,
  Demucs argv construction (incl. two-stem), expected stem-path resolution,
  analysis-JSON → `(tempo, key, scale)` parsing, key → `set_song_scale` arg
  mapping, track name/color/order mapping. No Ableton, no torch/librosa import.
- A tiny self-check for `scripts/analyze_audio.py` on a short synthetic signal,
  gated with `@pytest.mark.skipif` when librosa is not importable.
- Server import syntax-check: `uv run python -c "import ableton_mcp_max.server"`.
- **Live verification is manual** (project convention), recorded in PROGRESS.md
  after a real run: separate a test track, confirm tempo + key set, all stems
  stacked in the Arrangement at bar 1, warp off on each.

## Files to Modify / Create

- `ableton_mcp_max/stem_utils.py` — new pure helper module.
- `scripts/analyze_audio.py` — new external analysis script (brew Python).
- `ableton_mcp_max/server.py` — new `separate_stems_to_arrangement` tool.
- `commands/stems.md` — new `/ableton:stems` slash command.
- `tests/test_stem_utils.py` — new unit tests.
- `README.md` + docs site — Prerequisites section + regenerated tool index.
- `PROGRESS.md` — record on ship.

## Verification

- Offline gate green (pytest + server import).
- Manual Live run: 4 stems stacked in Arrangement at bar 1, project tempo + key
  match the source, warp off, session slots empty.
