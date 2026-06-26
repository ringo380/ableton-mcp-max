---
name: ableton-arrangement
description: Building song structure and energy in the Ableton arrangement - sections, scenes, cue points, transitions, and timeline automation. Use when arranging a track, building sections (intro/drop/breakdown), adding automation, or shaping energy over time.
---

# Ableton arrangement

Goal: a full-length arrangement with deliberate energy and clean transitions.

## Tools
- Structure: `build_arrangement`, `get_arrangement_structure`, `get_arrangement_clips`,
  `duplicate_clip_to_arrangement`, `delete_arrangement_clip`, `set_arrangement_loop`.
- Scenes/cues: `create_scene` / `duplicate_scene` / `capture_and_insert_scene`,
  `create_cue_point` / `jump_to_cue`.
- Automation: `set_arrangement_automation` (timeline envelopes), `get_automation` /
  `set_automation` (clip envelopes, regular tracks).

## Principles
- Map sections to a target energy curve from the brief (intro -> build -> drop ->
  breakdown -> outro). Use cue points as section markers.
- Transitions sell the arrangement: automate filter sweeps, risers, and mute/unmute at
  section boundaries.
- Build with session clips, then commit to the arrangement.

## Gotchas
- Arrangement automation writes via the value-probe backdoor; on Live 12 envelopes need
  point Ids or a corrupt load - the tool handles this, but reload to confirm round-trip.
- Clip-envelope reads are sampled only (no breakpoint enumeration); sample slightly inside
  a step (the exact left edge returns the pre-step value).

## Checklist
- [ ] Sections match the brief's energy intent; cue points placed.
- [ ] Transitions automated at boundaries.
- [ ] Logged the structure to decisions.md.
