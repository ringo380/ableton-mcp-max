---
name: ableton-analysis
description: Auditing an Ableton Live set against best-practice rulesets and producing a remediation report - mix balance, loudness, key, health. Use when analyzing/reviewing a set, diagnosing mix issues, detecting key, or checking a project's health.
---

# Ableton analysis

Goal: an evidence-based read of the set and a prioritized remediation list.

## Tools
- `analyze_set` (curated rulesets -> findings), `apply_findings` (act on them).
- Measure: `measure_mix`, `measure_loudness`, `check_clipping`, `detect_key`
  (`source='auto'|'midi'|'audio'`).
- Inspect: `get_session_info`, `get_track_info`, `get_mixer`, `get_arrangement_structure`.

## Principles
- Read state first (`get_session_info` + `get_track_info`) - never assume track 0.
- Lead with measurements (`measure_mix` / `measure_loudness` / `check_clipping`), then
  rulesets, then a sectioned report ordered by severity.
- `detect_key` is content-based; cross-check against `matches_live` and the brief's key.

## Gotchas
- Reads can lag writes and undo/redo - re-read to confirm before reporting.
- Large readers cap with `limit` and report `truncated` - widen the path/limit if cut off.

## Checklist
- [ ] State re-read at start.
- [ ] Findings backed by measurements, ordered by severity.
- [ ] Report appended to decisions.md.
