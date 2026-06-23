# detect_key — content-based key detection design

**Created**: 2026-06-23
**Status**: Design (approved)

## Overview

A new MCP tool, `detect_key`, that examines the combined track contents of the
currently open Ableton Live set and reports the most likely musical key,
inferred purely from content (MIDI notes + audio) and **independent of the key
or scale configured in Live**. It returns a ranked set of candidate keys with
confidence scores plus the evidence used, and compares its detected key to
Live's current scale setting.

Read-only: the tool reads clips, notes, sample files, and (optionally) live
audio. It performs no writes, so there are no write-lag, undo, or hot-swap
concerns.

## Goals

- Detect the most likely key from **MIDI clips and audio clips** across the set.
- Ignore Live's configured key/scale when detecting (report it only for
  comparison).
- Return ranked candidates + evidence (histogram, per-source breakdown,
  detected-vs-Live comparison).
- Keep all detection logic in a pure, unit-tested server-side module, matching
  the existing `*_utils.py` architecture.

## Non-goals (YAGNI)

- Per-section / per-region key detection (whole-set only for v1).
- Modulation / key-change tracking over time.
- Modes beyond major/minor (no dorian/mixolydian classification in v1).
- Tempo/chord/structure analysis (out of scope; `analyze_set` territory).

## Approach

**Krumhansl-Schmuckler pitch-class correlation.** Build a single 12-bin
pitch-class histogram from all content, then correlate it against the 24 rotated
major/minor Krumhansl-Kessler key profiles. Rank keys by correlation. MIDI feeds
the histogram directly; audio feeds it via a librosa chroma matrix collapsed to
12 bins.

Rejected alternatives:
- Diatonic scale-fit scoring — worse at relative/parallel disambiguation,
  ignores tonal weighting.
- External key-detection library (essentia / libKeyFinder) — heavy dependency,
  audio-only, can't unify MIDI + audio in one histogram.

## Architecture

Three pieces, following the established split (pure logic on the server; reads
inline in the Remote Script; the tool orchestrates):

1. **`ableton_mcp_max/key_detection_utils.py`** — new pure module, imported by
   `server.py` only, fully unit-tested. No Live, no I/O.
2. **`detect_key`** — new `@mcp.tool()` in `server.py` that gathers content and
   calls the pure module.
3. **Remote Script** — one new bulk read command `get_clip_contents` in
   `_process_command` (inline read, no `main_thread_task` mutation branch),
   surfacing each clip's metadata including the audio `file_path`.

### Pure module: `key_detection_utils.py`

Constants:
- `KS_MAJOR`, `KS_MINOR` — the 12-element Krumhansl-Kessler profile weights.
- `PITCH_NAMES` — pitch-class index → name (`["C","C#",...,"B"]`), reusing
  Live's enharmonic convention already used in `composition_utils`.

Functions:
- `histogram_from_notes(notes, transpose=0) -> list[float]` (len 12)
  Sums each note into its pitch-class bin, weighted by `duration * velocity`
  (velocity normalized 0..1). `transpose` (the clip's `pitch_coarse`, in
  semitones) is added to each pitch before the `% 12`.
- `histogram_from_chroma(chroma, transpose=0) -> list[float]` (len 12)
  Sums a `12 x N` chroma matrix across frames into a 12-bin vector and rotates
  by `transpose` semitones.
- `combine(midi_hist, audio_hist, audio_weight=0.5) -> list[float]`
  L1-normalizes each non-empty source, then blends:
  `(1 - audio_weight) * midi_norm + audio_weight * audio_norm`. If one source is
  empty, returns the other unchanged (normalized).
- `detect_key(hist) -> list[dict]`
  Correlates `hist` against all 24 rotated profiles (12 major + 12 minor).
  Returns a list sorted by score descending: `{key, mode, root_pc, score,
  confidence}`. `confidence` is the gap-normalized score of the top candidate
  relative to the field (e.g. `(top - mean) / (top - min)` clamped to 0..1), so
  a flat/ambiguous histogram reads as low confidence.
- `key_name(root_pc, mode) -> str` — e.g. `"A minor"`.
- `relative_key(root_pc, mode) -> (root_pc, mode)` — for the relative
  major/minor note in output.

Correlation uses Pearson correlation between the normalized histogram and each
profile (standard for KS). Pure Python (no numpy dependency required for the
12-element vectors).

### Remote Script: `get_clip_contents`

A single inline read (added to the `elif command_type ==` chain in
`_process_command`, **not** the `main_thread_task` mutation list — it is a pure
read). Returns:

```
{
  "clips": [
    {"track_index": int, "clip_index": int, "location": "session"|"arrangement",
     "is_midi": bool, "length": float, "pitch_coarse": int,
     "file_path": str|null}
  ]
}
```

- Iterates every track's `clip_slots` (session) and `arrangement_clips`
  (arrangement).
- `pitch_coarse` read via try/except (MIDI clips may raise; default 0).
- `file_path` read via try/except on audio clips (`Clip.file_path` exists in
  Live 11+); `null` for MIDI or on failure.
- Keep Py2/3.7-safe (no f-strings) per the embedded-interpreter constraint.

One socket round-trip replaces N per-clip metadata reads. MIDI note bodies are
still read per-clip via the existing `get_clip_notes` (the extended note API).

### Tool: `detect_key`

Signature (server-side):

```python
@mcp.tool()
def detect_key(ctx, source: str = "auto", audio_weight: float = 0.5,
               top_n: int = 5) -> str
```

- `source`: `"auto"` (MIDI + offline audio files; default), `"midi"`
  (MIDI only), `"audio"` (audio files only), `"tap"` (audio via the live M4L
  audio tap instead of files).
- `audio_weight`: blend weight for the audio histogram (0..1).
- `top_n`: number of ranked candidates to return.

Flow:
1. Call `get_clip_contents` (one RS read) → clip list.
2. **MIDI** (unless `source="audio"`/`"tap"`): for each MIDI clip, read notes
   via existing `get_clip_notes`, accumulate via `histogram_from_notes` using
   the clip's `pitch_coarse`. Track note/clip counts.
3. **Audio offline** (`source` in `auto`/`audio`): for each audio clip with a
   `file_path`, `_ensure_local(file_path)` (handles iCloud placeholders),
   `librosa.load` + `librosa.feature.chroma_cqt`, accumulate via
   `histogram_from_chroma` using `pitch_coarse`. Count skipped/unreadable.
4. **Audio tap** (`source="tap"`): capture playback through the existing M4L
   audio tap, compute chroma from the captured buffer, accumulate. (Reuses the
   tap-deploy/capture path; only covers what is playing.)
5. `combine(midi_hist, audio_hist, audio_weight)` → `detect_key` → take `top_n`.
6. Read `get_song_scale` for the Live setting; compute `matches_live`.
7. Return JSON.

### Output shape

```json
{
  "ok": true,
  "detected_key": "A minor",
  "confidence": 0.78,
  "candidates": [
    {"key": "A minor", "score": 0.91, "confidence": 0.78},
    {"key": "C major", "score": 0.88, "confidence": 0.71},
    {"key": "E minor", "score": 0.62, "confidence": 0.40}
  ],
  "relative_key": "C major",
  "pitch_class_histogram": [ ... 12 floats, normalized ... ],
  "sources": {
    "midi": {"clips": 7, "notes": 412},
    "audio": {"clips": 3, "analyzed": 2, "skipped": 1, "mode": "offline"},
    "audio_weight": 0.5
  },
  "live_scale": {"root_note": "C", "scale_name": "Minor"},
  "matches_live": false
}
```

## Error handling

- **Empty set / no usable content** → `{"ok": false, "error": "..."}` with a
  clear message (no clips, or all clips empty/unreadable).
- **librosa unavailable** (import fails) → degrade to MIDI-only, set
  `sources.audio.mode = "unavailable"` and note it; never crash.
- **`source="audio"`/`"tap"` but no audio obtainable** → `ok:false` with reason.
- **Per-clip failures** (missing file, unsupported format, iCloud download
  timeout, note-read error) → skip that clip, increment a skipped counter,
  continue. Never fatal.
- **Tap mode with nothing playing / tap not deployed** → surface honestly in
  `sources.audio` and fall back per `source` semantics.

## Testing

Pure module — full offline unit tests (the offline gate is the source of truth;
no Live needed):
- C-major-scale note list → C major ranks first; A-natural-minor note set → A
  minor ranks first.
- Transpose handling: same notes with `transpose=2` shifts the detected root up
  a tone.
- `histogram_from_chroma` on a known synthetic chroma vector.
- `combine` weighting: `audio_weight=0` ignores audio; `=1` ignores MIDI;
  empty-source passthrough.
- `detect_key` confidence: a flat histogram yields low confidence; a strong
  single-key histogram yields high confidence.
- Name/relative-key helpers.

Real-file librosa round-trip test guarded by `@pytest.mark.skipif` (skip if
librosa or a fixture sample is unavailable).

Offline gate: `uv run --with pytest pytest -q`, `uv run python -c "import
ableton_mcp_max.server"`, `uv run python -m py_compile
remote_script/AbletonMCP/__init__.py`.

Live verification (manual, recorded in PROGRESS.md): a known-key set →
`detect_key` returns that key as the top candidate for `source="midi"`,
`"audio"`, and `"auto"`; `matches_live` reflects Live's setting honestly.

## Files to modify

- `ableton_mcp_max/key_detection_utils.py` — new pure module (KS profiles,
  histogram builders, correlation, naming).
- `ableton_mcp_max/server.py` — new `detect_key` `@mcp.tool()`; register
  `get_clip_contents` in the command allow-list; import the new module.
- `remote_script/AbletonMCP/__init__.py` — new `get_clip_contents` inline read
  handler.
- `tests/test_key_detection_utils.py` — new unit tests.
- Docs/version bumps on ship (per CLAUDE.md publish flow): tool count in
  `README.md`, `docs/index.md`, regen tool index, `pyproject.toml` +
  `.claude-plugin/plugin.json` + `uv.lock`.

## Open considerations (decided)

- **Default `audio_weight = 0.5`** — equal blend after per-source
  normalization; tunable per call.
- **Bulk `get_clip_contents` read** over per-clip metadata calls — one socket
  round-trip.
- **Relative-major/minor ambiguity** is inherent to pitch-class profiles; the
  ranked candidates expose it rather than hiding it.
