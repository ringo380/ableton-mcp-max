# ableton-mcp-max — Arrangement Intelligence (Design)

**Created:** 2026-06-18
**Status:** Designed (not yet implemented)

Roadmap item #2 of the "autonomous track production + closed analyze->act loop"
initiative (#0 master/return access + #1 composition layer shipped in v0.10.0; #3
closed-loop remediation and #4 `/ableton:produce` skill remain after this).

## Goal

A two-way **section-map** layer over the Arrangement timeline:

- **Read:** derive the song's section structure (Intro/Verse/Chorus/...) from the
  set, with per-section facts (active tracks, clip count, coverage, energy).
- **Write:** assemble an arrangement from Session clips given an explicit section
  map - place + tile clips per section at computed bar positions, optionally write
  named locators so the structure is visible and round-trips.

This sits above the Phase 8 arrangement primitives (`get_arrangement_clips`,
`duplicate_clip_to_arrangement`, `delete_arrangement_clip`, `create_cue_point`,
`get_cue_points`) - it composes them, it does not replace them.

## Non-goals (YAGNI / deferred)

- **No structure templates / auto-assignment.** The build direction takes an
  explicit section map; "pop template auto-fills clips by heuristic" is a possible
  later convenience layer, not this spec.
- **No semantic section labelling on inference.** With no locators, inference can
  detect *where* sections change (clip-layout boundaries) but cannot know "this is
  a chorus." Inferred sections are named `Section N` + a density label.
- **No structure issue-flagging** ("no intro", "chorus too short", "monotonous").
  That is #3's job; the read here produces facts, not warnings.
- **No note-level density.** Per-section energy is derived from clip coverage +
  active-track count (cheap, from `get_arrangement_clips` geometry), not by reading
  every arrangement clip's notes.
- No new Remote Script command - both tools compose existing reads/writes; the
  Live-side dispatch surface is unchanged.

## The core abstraction — the section map

The shared data structure both directions speak. A list of sections, each:

```
{
  name,            # locator name (cues) or "Section N" (inferred)
  start_bar,       # 1-indexed, Live UI convention (bar 1 = beat 0)
  length_bars,
  start_time,      # beats (computed from the live time signature)
  end_time,        # beats
  # --- read direction only (facts) ---
  active_tracks,   # track indices with a clip overlapping this span
  clip_count,
  coverage,        # clip-beats / span-beats, capped at 1.0
  energy           # active_tracks x coverage, normalized 0..1 across the set
}
```

Bars are 1-indexed to match Live's UI (consistent with the composition layer using
Ableton labels). Beats are computed from the set's live time signature, read via
the existing `get_transport` (which already returns `signature_numerator` /
`signature_denominator`). Beats-per-bar = `numerator * (4 / denominator)`.

The **write** direction consumes the geometry half (`name`, `length_bars`, and per
-section clip assignments); the **read** direction produces geometry **plus** facts.

## Tool 2 (read) — `get_arrangement_structure`

```
get_arrangement_structure() -> str
```

Server-side composition - **no new Remote Script command**. Reuses:
- `get_transport` -> time signature,
- `get_cue_points` -> locators,
- a `get_arrangement_clips(track_index)` loop over all tracks -> clips per track.

Song end is derived from the clips + cues (see "Song end" below), not from
`get_transport`.

Then in `arrangement_structure_utils`:

- **Cues present** -> `sections_from_cues`: sections are the spans between
  consecutive cue points, plus the span from the last cue to song end. Section name
  = locator name. `source: "cues"`.
- **No cues** -> `infer_sections`: collect the distinct clip start/stop change
  -points across all tracks; consecutive change-points bound a section. Name them
  `Section 1..N` with a density label (`sparse` / `medium` / `dense`) derived from
  that span's coverage. `source: "inferred"`.
- **Per-section facts** (`section_facts` + `normalize_energy`): `active_tracks`
  (tracks with a clip overlapping the span), `clip_count`, `coverage`
  (sum of overlapping clip-beats within the span / span-beats, capped at 1.0), and
  `energy` (`active_tracks * coverage`, then min-max normalized 0..1 across all
  sections so sections are comparable within the set).

Returns:
```
{
  time_signature: [num, den],
  song_end_bar,
  source: "cues" | "inferred",
  section_count,
  sections: [ {name, start_bar, length_bars, start_time, end_time,
               active_tracks, clip_count, coverage, energy}, ... ]
}
```

**Song end:** the arrangement extends to the max `end_time` across all tracks'
arrangement clips (and the last cue, if later). Used to bound the final section.
An empty arrangement (no clips, no cues) returns `section_count: 0, sections: []`.

## Tool 3 (write) — `build_arrangement`

```
build_arrangement(sections, write_locators=True, replace=False, start_bar=1) -> str
```

`sections` is the explicit section map:
```
sections = [
  {
    name: "Intro",
    length_bars: 8,
    clips: [
      {track_index: 0, source_slot_index: 0, repeat: "fill"},   # tile to fill
      {track_index: 1, source_slot_index: 0, repeat: 2}          # exactly 2x
    ]
  },
  {name: "Verse", length_bars: 16, clips: [...]},
  ...
]
```

Flow (server.py orchestration):

1. `validate_section_map(sections)` - reject malformed input (missing/empty name,
   non-positive `length_bars`, bad indices, unknown `repeat`) **before any
   mutation**.
2. Read time signature via `get_transport`.
3. `compute_section_starts` - cumulative start beat per section from `length_bars`
   + time signature, offset by `start_bar`.
4. `replace=True` -> first clear existing arrangement clips on every track named in
   any section's `clips` (loop `get_arrangement_clips` + `delete_arrangement_clip`
   high-index-first so re-indexing doesn't shift pending deletes). Idempotent
   re-builds.
5. For each section, for each clip entry: look up the Session clip length
   (`get_clip_info` on the source slot), `tiling_plan(section_beats, clip_length,
   repeat)` -> placement offsets, then `duplicate_clip_to_arrangement(track_index,
   source_slot_index, section_start + offset)` for each offset.
6. `write_locators=True` -> after placement, loop the existing server-side cue
   orchestration (`create_cue_point` at each section start). Because build writes
   named locators, a built arrangement round-trips back through
   `get_arrangement_structure` via the cues-primary path.

Returns the placed-clip summary + the cues written:
```
{
  built: true,
  time_signature: [num, den],
  sections: [ {name, start_bar, length_bars, placed_clips: [{track_index, time,
               count}], locator_written: bool}, ... ],
  total_clips_placed
}
```
Recommends a follow-up `get_arrangement_structure` read (per the project's
write-lag gotcha - never trust the returned confirmation as authoritative).

**Tiling semantics** (`tiling_plan`):
- `repeat: "fill"` -> `floor(section_beats / clip_length)` copies at
  `0, clip_length, 2*clip_length, ...` (no partial trailing copy; a clip longer
  than the section places **one** copy).
- `repeat: <int N>` -> exactly N copies at successive `clip_length` offsets,
  regardless of section length (may overrun the section - documented, not guarded;
  caller's choice).
- Degenerate guard: clip_length <= 0 -> validation error.

## Pure module — `arrangement_structure_utils.py`

Imported by **server.py only** (the Remote Script runs in Live's own interpreter
and cannot import it). All bar/beat math, inference, and tiling logic - the bulk of
the test surface.

- `bars_to_beats(bars, num, den)` -> float beats.
- `compute_section_starts(sections, start_beat, num, den)` -> list of cumulative
  start beats (and section-beat lengths) per section.
- `sections_from_cues(cue_list, song_end)` -> spans from `[{time, name}, ...]`.
- `infer_sections(clips_by_track, song_end)` -> spans + `Section N` names + density
  labels from clip change-points.
- `section_facts(span, clips_by_track)` -> `{active_tracks, clip_count, coverage}`
  for one span; `normalize_energy(sections)` -> fills `energy` across the set.
- `tiling_plan(section_beats, clip_length, repeat)` -> list of placement offsets.
- `validate_section_map(sections)` -> raises `ValueError` with a clear message on
  malformed input.

Live-count range guards (track count, slot count, arrangement-clip count) stay in
the handler / existing tools, consistent with the rest of the codebase.

## Testing

**Offline (`tests/test_arrangement_structure_utils.py`):**
- `bars_to_beats` / `compute_section_starts`: 4/4, 6/8, 3/4; cumulative offsets;
  `start_bar` offset.
- `sections_from_cues`: ordered cues, last-cue-to-end span, single cue, cue at 0.
- `infer_sections`: synthetic multi-track clip layouts -> expected boundaries;
  overlapping clips; gaps; empty arrangement.
- `section_facts` / `normalize_energy`: coverage capping, active-track counting,
  min-max normalization (incl. all-equal -> uniform energy, single section).
- `tiling_plan`: exact fit, partial fill (no trailing copy), clip longer than
  section (one copy), integer repeat, overrun, degenerate clip_length raises.
- `validate_section_map`: missing name, non-positive length_bars, bad repeat, bad
  index types - each a clean `ValueError`.

Target ~30-40 new tests. Full suite (currently 566) stays green; `server.py`
imports clean; RS `py_compile` clean (unchanged, but run it).

**Live smoke (vs Live 12 Suite, scratch tracks, recorded in PROGRESS.md):**
- Generate 1-2 Session clips on scratch MIDI tracks (composition tools).
- `build_arrangement` with a 3-section map (e.g. Intro 4 / Main 8 / Outro 4),
  `repeat: "fill"`, `write_locators=True`.
- `get_arrangement_structure` reads back 3 sections via the written locators
  (`source: "cues"`); verify section names, `start_bar`/`length_bars`, tiling
  counts, active_tracks, and energy ordering.
- `replace=True` re-build -> no duplicate clips (old ones cleared first).
- Delete the locators -> `get_arrangement_structure` falls to `source: "inferred"`;
  verify boundaries match the clip layout and `Section N` naming.
- Negative cases: malformed section map (clean `ValueError`, no mutation), build
  referencing an empty Session slot (clean error from the existing
  `duplicate_clip_to_arrangement` guard).
- Self-clean: delete scratch tracks + any created locators; re-read state (the
  project set changes between sessions - do not assume track indices).

## Flagged unknowns — verify live, do not assume

- **Cue grid-quantization on build:** `create_cue_point` notes that Live may snap
  the locator to the current grid, so a section start may land a hair off the
  computed beat. The read path keys sections off the **locator times Live actually
  stored**, so a build->read round-trip stays self-consistent; just confirm the
  stored times are close enough that section names line up with their clips.
- **`get_clip_info` on a Session source slot** returns the clip `length` used for
  tiling - confirm the field name/shape against the live tool before wiring.
- **Song-end derivation:** confirm the max arrangement-clip `end_time` across
  tracks is a reliable arrangement-length proxy (vs any `Song` length property);
  fall back to the last cue / last clip end.
- **`replace` delete ordering:** confirm deleting `arrangement_clips` high-index
  -first avoids the re-indexing shift noted in Phase 8.

## Tool count

126 -> **128** (two new tools; new "Arrangement" category). No new Remote Script
command.
