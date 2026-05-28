# Phase 10 — Implementation Plan

**Date:** 2026-05-27
**Status:** Code complete; offline gate green (202 passed); awaiting live verification

## Tasks
- [x] Group A: transport_utils helpers + 5 song-level setter tools + get_transport reads.
- [x] Group B: clip_utils launch props (alias/support/coercion) + clip handler reads.
- [x] Group C: view_utils + 6 tools (5 setters + get_view_selection) + get_track_info reads.
- [x] Tests: +19 (transport 11, clip 3 funcs, view 7) → suite 202.
- [x] Offline gate: pytest 202, `import ableton_mcp_max.server`, py_compile handler.
- [ ] Live verify (needs install_remote_script + Live bounce + Claude Code restart).
- [ ] PROGRESS.md findings + PR + merge.

## New tools (10) + extended reads
Group A: set_groove_amount, set_swing_amount, set_clip_trigger_quantization,
set_midi_recording_quantization, set_nudge.
Group C: set_selected_track, set_selected_scene, set_detail_clip,
set_highlighted_clip_slot, set_track_fold, get_view_selection.
Group B: extends set_clip_property / get_clip_info (no new tool).
Reads extended: get_transport (+7), get_track_info (+3), get_clip_info (+4).

## Restart protocol (both halves changed)
1. `bash scripts/install_remote_script.sh`
2. Bounce Live (kill -TERM the Live PID; `open -a "Ableton Live 11 Suite"`; wait ~15s).
3. User restarts Claude Code (loads new MCP tools as deferred → `ToolSearch select:...`).

## Live verification checklist
- A: groove/swing set + read via get_transport; clip_trigger_quant by int & name;
  midi_recording_quant; nudge up/down; count_in_duration reads. Restore.
- B: on a session clip set launch_mode/launch_quantization/legato/velocity_amount;
  verify get_clip_info; confirm accepted on a MIDI clip. Restore.
- C: set_selected_track/scene, set_detail_clip, set_highlighted_clip_slot;
  get_view_selection. set_track_fold on a group track (or note clean rejection on a
  non-foldable track). Restore selection.
- Negatives: bad track_type, OOR indices, empty detail-clip slot, fold on
  non-foldable, bad quant name → clean server/handler errors, no Live mutation.
- Resolve the enum-confirmation TODO (record actual int meanings in PROGRESS.md).

## Delivery
Branch `feat/phase10-feel-launch-view` → PR → `gh pr merge --squash --delete-branch`
→ `git remote prune origin` (gh login `ringo380`).
