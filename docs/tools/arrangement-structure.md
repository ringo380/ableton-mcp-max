---
layout: default
title: Arrangement Structure
parent: Tools
nav_order: 12
---

# Arrangement Structure
{: .no_toc }

Read the structural layout of the arrangement (section map from cue points or clip inference) and build multi-section arrangements from section definitions.

<details open markdown="block">
  <summary>Tools on this page</summary>
  {: .text-delta }
1. TOC
{:toc}
</details>

---

## get_arrangement_structure

```python
get_arrangement_structure()
```

Derive the song's section structure from the Arrangement timeline.

Sections are identified in two ways:
- If cue points (locators) exist: sections = spans between consecutive
  locators (last locator to arrangement end = final section). Section
  names come from the locator names (note: Live auto-assigns sequential
  names "1", "2", etc. - original section names are not preserved in
  locators). source = "cues".
- If no cue points: sections are inferred from clip start/stop
  change-points across all tracks. Named "Section 1", "Section 2", etc.
  with a density_label ("sparse"/"medium"/"dense"). source = "inferred".

Each section includes per-section facts: active_tracks (track indices
with at least one clip overlapping the span), clip_count, coverage
(average per-track clip-beats / span-beats, 0.0-1.0), and energy
(active_tracks * coverage, min-max normalized 0.0-1.0 across sections).

Returns:
{
  time_signature: [num, den],
  song_end_bar: float,         # bar of the arrangement end (1-indexed)
  source: "cues" | "inferred",
  section_count: int,
  sections: [
    {name, start_bar, length_bars, start_time, end_time,
     active_tracks, clip_count, coverage, energy}
  ]
}

Note: bar fields use Ableton's 1-indexed convention (bar 1 = beat 0).

## build_arrangement

```python
build_arrangement(
    sections: List[dict],
    write_locators: bool = True,
    replace: bool = False,
    start_bar: int = 1,
)
```

Assemble an Arrangement from Session clips using an explicit section map.

Computes section start beats from bar lengths and the live time signature,
then tiles Session clips into each section via duplicate_clip_to_arrangement.
Optionally writes cue points (locators) at each section start so section
positions are visible in Live and round-trip through get_arrangement_structure.
Note: Live's LOM does not support setting CuePoint names - written locators
receive Live's auto-sequential names ("1", "2", etc.), not the section names
passed here.

Parameters:
- sections: list of section dicts:
    {
      "name": "Intro",           # required, non-empty string
      "length_bars": 8,          # required, positive number
      "clips": [                 # optional; omit for a silent section
        {
          "track_index": 0,      # non-negative int
          "source_slot_index": 0,# non-negative int (Session slot)
          "repeat": "fill"       # "fill" (tile to fill) or int (exact count)
        }
      ]
    }
- write_locators: write a cue point at each section start (default true).
  Positions are correct; names are Live's auto-sequential labels, not the
  section names.
- replace: before placing, delete all existing arrangement clips on every
  track referenced in the section map (idempotent re-builds). Default false.
- start_bar: 1-indexed bar where the first section begins (default 1).

Returns a summary of placed clips and locators. Always follow with a
get_arrangement_structure call to verify (write-lag: returned counts may
not reflect Live's final state).

