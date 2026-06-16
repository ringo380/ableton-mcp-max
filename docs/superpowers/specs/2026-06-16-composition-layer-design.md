# Composition layer: server-side MIDI generators & transformers

**Created:** 2026-06-16
**Status:** Design approved

## Summary

Add a **composition layer** to ableton-mcp-max: pure server-side MIDI-generation
and clip-transformation primitives that emit notes through the existing note path
(`create_clip` / `add_notes_to_clip` / `replace_clip_notes`, normalized by
`clip_utils.normalize_note`). Eight new tools - four **generators** that fill a
target clip slot with musical material, and four **transformers** that rewrite an
existing clip's notes.

All music-theory logic lives in one new pure module, `composition_utils.py`
(imported by `server.py` only). The only Remote Script change is a single new
read command, `get_song_scale`, that powers the "match the set's key/scale
automatically" path. Everything else is server-side and offline-testable.

This is sub-project **#1** of the larger initiative (autonomous track production +
closed analyze -> act loop): #0 master/return device access (merged, PR #24),
**#1 composition layer (this spec)**, #2 arrangement intelligence, #3 closed-loop
remediation, #4 `/ableton:produce` orchestration skill. Per the user's direction,
#1 ships before the next release (so #0 + gap C stay unreleased on `main` until #1
lands, then one release bundles all three).

## Motivation

Today the server can edit notes a clip already has, but has no primitive for
*creating* musical material - chords, basslines, melodies, drum patterns - or for
musically transforming a clip (humanize, snap-to-scale, arpeggiate, harmonize).
These are the building blocks the arrangement-intelligence (#2) and
closed-loop-remediation (#3) layers will orchestrate. Generation is pure
computation (no Live round-trip needed to compute the notes), so it fits the
project's `*_utils.py` + offline-pytest model cleanly.

LOM feasibility is confirmed: `Song.scale_name` and `Song.root_note` are
read/write and `Song.scale_intervals` *reports the active scale as a list of
semitone offsets* (e.g. Major -> `[0,2,4,5,7,9,11]`) in both Live 11 and 12. So
generators can read the set's actual key/scale - including user/custom scales -
without hardcoding scale tables.

## Scope

**In scope - 8 new tools (new "Composition" category, 118 -> 126):**

Generators (write into a target session slot; create the MIDI clip if empty):
- `generate_chord_progression`
- `generate_bassline`
- `generate_melody`
- `generate_drum_pattern`

Transformers (read an existing clip, transform, write back):
- `humanize_clip`
- `quantize_clip_to_scale`
- `arpeggiate_clip` (includes a `strum` mode)
- `harmonize_clip`

Plus one Remote Script read command: `get_song_scale`.

**Out of scope (YAGNI / later follow-ups):**
- Time signatures other than 4/4 (assume 4/4; tools are `bars`-based).
- Groove/swing application (already covered by `set_groove_amount` /
  `set_swing_amount`).
- Writing generators to **arrangement** clips (session slots only for #1).
- Auto-loading an instrument onto the track (the user picks the sound).
- A separate `strum_clip` tool (folded into `arpeggiate_clip` as a mode).

## Architecture

### New module: `ableton_mcp_max/composition_utils.py`

Pure functions, no Live dependency, imported by `server.py` only (the Remote
Script runs in Live's own interpreter and cannot import it - all resolve/build
math happens here; the server sends already-built note dicts to the existing
write handlers).

Contents:

- **Key/scale model.**
  - `parse_key(key:str) -> int` - `"C"`,`"C#"`,`"Db"`,`...`,`"B"` -> root 0-11
    (sharps and flats both accepted; case-insensitive).
  - Named-scale interval table -> `dict[str, list[int]]`: `major`,
    `natural_minor`, `harmonic_minor`, `melodic_minor`, `dorian`, `phrygian`,
    `lydian`, `mixolydian`, `locrian`, `major_pentatonic`, `minor_pentatonic`,
    `blues`, `whole_tone`, `chromatic`.
  - `resolve_key_scale(key, scale, song_scale) -> (root:int, intervals:list[int])`
    - explicit params win; if both omitted, use the set's `root_note` +
    `scale_intervals` from `get_song_scale` directly; if that read is missing or
    fails, fall back to a documented default (`C` `natural_minor`) and never
    crash.
  - `scale_pitches(root, intervals, lo, hi) -> list[int]`,
    `degree_to_pitch(root, intervals, degree, octave) -> int`,
    `snap_to_scale(pitch, root, intervals) -> int` (nearest scale tone).

- **Chord model.**
  - Roman numeral -> diatonic degree + quality inferred from the scale
    (e.g. in major `ii` is minor, `V` major, `vii` diminished), with explicit
    suffix overrides (`IV7`, `V7`, `ii7`, etc.).
  - Literal chord symbols (`"Cmaj7"`, `"Am7"`, `"F"`) parsed independently of key.
  - `build_chord(symbol_or_numeral, root, intervals, octave) -> list[int]`
    (root-position triad or 7th).

- **Generators (pure; return `list[note dict]`).** Each note dict uses the
  `normalize_note` field set (`pitch`, `start_time`, `duration`, `velocity`, ...).
  - `build_chord_progression(progression, root, intervals, bars, octave, durations)`
  - `build_bassline(progression|None, style, root, intervals, bars, octave, rng)`
  - `build_melody(root, intervals, bars, contour, density, octave, rng)`
  - `build_drum_pattern(style, bars, fills, rng)`

- **Transformers (pure; `list[note dict] -> list[note dict]`).**
  - `humanize(notes, timing, velocity, rng)`
  - `quantize_to_scale(notes, root, intervals)`
  - `arpeggiate(notes, mode, rate, gate, rng)` (`mode` in
    `up`/`down`/`updown`/`random`/`strum`)
  - `harmonize(notes, root, intervals, intervals_or_degrees)`

- **Seeded RNG.** A `make_rng(seed) -> random.Random` helper: `seed=None` ->
  system-seeded (fresh each call); an int seed -> reproducible. Same seed + same
  params -> byte-identical note list (this is what offline tests assert). Server
  is normal CPython, so `random.Random` is available (the Workflow-sandbox
  `Math.random`/`Date.now` restriction does not apply here).

### Remote Script: one new read command

`get_song_scale` -> `{"scale_name": str, "root_note": int, "scale_intervals":
[int,...]}`, read inline off `self._song` (no main-thread schedule, same shape as
`get_application_version`). Py2/3.7-safe; each property read guarded with
`try/except` (the embedded interpreter re-raises non-AttributeError for
unsupported endpoints, so never `hasattr`). On any failure the command returns the
fields it could read (or an empty/null marker) and the server falls back to the
documented default scale.

This is the **only** Remote Script change, and the only piece requiring a Live
bounce to live-verify.

## Tool surface

All tools return the uniform `_ok({...})` / `_err(...)` envelope. Generators'
`data` summarizes `{notes_added, key, scale, bars, ...}`.

### Generators (write into `track_index`, `clip_slot_index`)

```
generate_chord_progression(track_index, clip_slot_index, progression,
    key=None, scale=None, bars=4, octave=3, durations=None, replace=False)
generate_bassline(track_index, clip_slot_index, progression=None, style="root",
    key=None, scale=None, bars=4, octave=1, seed=None, replace=False)
generate_melody(track_index, clip_slot_index, key=None, scale=None, bars=4,
    contour="arch", density=0.5, octave=4, seed=None, replace=False)
generate_drum_pattern(track_index, clip_slot_index, style="four_on_floor",
    bars=4, fills=False, seed=None, replace=False)
```

- `progression` is a list of roman numerals (`["I","vi","IV","V"]`) and/or chord
  symbols (`["Cmaj7","Am7"]`).
- `style` (bassline): `root`, `octaves`, `walking` (needs `progression`), `arp`.
- `style` (drums): `four_on_floor`, `basic_rock`, `breakbeat`, `hihat_8ths`,
  `boom_bap`. GM drum map (kick 36, snare 38, closed hat 42, open hat 46, ...).
- `contour` (melody): `up`, `down`, `arch`, `valley`, `random`.

### Transformers (read/write `track_index`, `clip_slot_index`)

```
humanize_clip(track_index, clip_slot_index, timing=0.02, velocity=8, seed=None)
quantize_clip_to_scale(track_index, clip_slot_index, key=None, scale=None)
arpeggiate_clip(track_index, clip_slot_index, mode="up", rate=0.25, gate=0.9,
    seed=None)
harmonize_clip(track_index, clip_slot_index, intervals=None, degrees=None,
    key=None, scale=None)
```

- `humanize_clip`: jitter onset by +/-`timing` beats and velocity by +/-`velocity`,
  clamped to valid ranges.
- `quantize_clip_to_scale`: snap every pitch to the nearest in-scale tone.
- `arpeggiate_clip`: expand chords (simultaneous notes) into sequential notes at
  `rate` (beats) with `gate` duration ratio; `mode="strum"` instead staggers the
  onsets tightly while preserving the chord's sustain.
- `harmonize_clip`: add a harmony voice per note - either fixed `intervals`
  (e.g. `[4,7]`) snapped into scale, or scale `degrees` (kept diatonic). Exactly
  one of `intervals`/`degrees` is provided.

## Emit / overwrite mechanics

- **Generators.** Resolve key/scale -> build notes in `composition_utils` -> if
  the slot is empty, `create_clip(length=bars*4)` then `add_notes_to_clip`; if the
  slot is occupied and `replace=False`, return
  `_err("slot occupied; pass replace=true")`; if `replace=True`, rewrite via
  `replace_clip_notes`. No new write-side Remote Script command - reuses the
  existing `create_clip` / `add_notes_to_clip` / `replace_clip_notes` handlers.
  Clip length assumes 4/4 (`bars * 4` beats); note times are in beats.
- **Transformers.** `get_clip_notes` -> transform -> `replace_clip_notes`. An
  empty or absent clip returns `_err`. Regeneration rewrites the whole note set,
  so incoming `note_id`s are dropped (consistent with `replace_clip_notes`).

## Testing plan

- **Offline pytest (the bulk):**
  - `test_composition_scales.py` - key parsing (sharps/flats/case), interval
    tables, `snap_to_scale`, `resolve_key_scale` precedence + fallback.
  - `test_composition_chords.py` - roman/symbol -> exact pitch sets, diatonic
    quality inference, 7th suffixes.
  - `test_composition_generators.py` - seeded determinism (exact note lists),
    pitch-in-scale invariants, all onsets within `bars*4` beats, note counts,
    drum pitches in GM map.
  - `test_composition_transformers.py` - humanize bounds + seed reproducibility,
    quantize lands in scale, arpeggio ordering/timing, harmonize diatonicity,
    empty-clip error path.
- **Remote Script:** `py_compile` the handler; `get_song_scale` live-verified
  after RS reinstall + Live bounce (read the set's scale; confirm
  `scale_intervals` matches the chosen scale).
- **Live-verify pass:** create a scratch MIDI track, generate each pattern into a
  slot, `get_clip_notes` round-trip, run a transformer, restore (delete the
  scratch track). Record results in PROGRESS.md.
- **Gate:** `uv run --with pytest pytest -q` +
  `uv run python -c "import ableton_mcp_max.server"` + `py_compile` on the RS. Do
  not reformat existing files.

## Docs / release

- Regenerate docs (`scripts/gen_docs_site.py`, `scripts/build_tool_index.py`);
  update the hand-maintained tool/category counts in `docs/index.md` (118 -> 126,
  +1 category). Tool count rises by 8.
- After #1 lands and is live-verified, cut one release bundling #0 + gap C + #1:
  bump `pyproject.toml` + `.claude-plugin/plugin.json` + `uv lock`, `gh release
  create`, bump the marketplace `ableton` ref + `node scripts/build-readme.js` +
  push.

## Risks / open notes

- `Song.scale_intervals` is documented in the LOM but should be confirmed live on
  both Live 11 and 12 during the `get_song_scale` verify (graceful fallback covers
  a missing endpoint regardless).
- "Musical quality" is subjective; offline tests assert *correctness* invariants
  (in-scale, in-range, in-time, deterministic), not aesthetic quality. Live-verify
  is the ear check.
- Generated material is intentionally simple/template-driven; richer styles are a
  follow-up, not part of #1.
