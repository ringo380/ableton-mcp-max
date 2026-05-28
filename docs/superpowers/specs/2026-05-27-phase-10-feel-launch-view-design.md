# Phase 10 — Global Feel/Quant, Clip Launch Settings, View/Selection & Folding (Design)

**Date:** 2026-05-27
**Status:** Code complete; awaiting live verification

## Motivation
A gap audit against the Live 11 LOM (`11.0.0.xml`) after Phase 9 surfaced several
confirmed-feasible, still-uncovered capabilities. Three groups were selected for
Phase 10. Two candidates were dropped as infeasible in Live 11:
- **Warp-marker editing** — `Clip.warp_markers` is read-only; there are no
  `add_warp_marker` / `remove_warp_marker` / `move_warp_marker` methods.
- **Follow actions** — `follow_action*` is absent from the 11.0.0 LOM.

(Capture/recording — `capture_midi`, `capture_and_insert_scene`,
`trigger_session_record`, `stop_all_clips`, `tap_tempo` — is feasible but was
deferred by the user; revisit in a later phase.)

## Group A — Global feel / quantization (song-level)
New tools (all mutating; song-property-write-lag applies — confirm via a follow-up
`get_transport`, never the returned dict, per the Phase 5 gotcha):
- `set_groove_amount(amount)` — `Song.groove_amount`, 0.0–1.0 clamp.
- `set_swing_amount(amount)` — `Song.swing_amount`, 0.0–1.0 clamp.
- `set_clip_trigger_quantization(value)` — `Song.clip_trigger_quantization`
  (`Live.Song.Quantization` int). Accepts int (0–13) or name.
- `set_midi_recording_quantization(value)` — `Song.midi_recording_quantization`
  (`Live.Song.RecordingQuantization` int). Accepts int or name; reuses the
  live-confirmed `clip_utils.QUANTIZE_GRID_MAP` (same enum).
- `set_nudge(direction, active)` — `Song.nudge_up` / `Song.nudge_down` (bools).

Reads added to `get_transport`: groove_amount, swing_amount,
clip_trigger_quantization, midi_recording_quantization, count_in_duration
(READ-ONLY per LOM), nudge_up, nudge_down — each probed with try/except.

`transport_utils` helpers: `coerce_unit_float`, `resolve_clip_trigger_quantization`
(name map `CLIP_TRIGGER_QUANTIZATION_MAP`, int pass-through),
`resolve_midi_recording_quantization` (reuses QUANTIZE_GRID_MAP),
`normalize_nudge_direction`.

## Group B — Clip launch settings
No new tool; flows through existing `set_clip_property` / `get_clip_info`.
Added canonical clip props (valid on BOTH midi and audio — general `Clip` props):
`launch_mode` (int 0=Trigger,1=Gate,2=Toggle,3=Repeat), `launch_quantization`
(int enum), `legato` (bool), `velocity_amount` (float). `clip_utils` updated:
`_ALIASES`, `_COMMON` (both kinds), `_BOOL_PROPS` (+legato), `_INT_PROPS`
(+launch_mode/launch_quantization). The handler's audio-only gate is unchanged
(still only warp/gain/pitch), so launch props apply to MIDI clips.

## Group C — View / selection & track folding
New `view_utils.py` (`normalize_track_type`, `coerce_index`). New tools:
- `set_selected_track(track_index, track_type="regular")` — `Song.View.selected_track`.
- `set_selected_scene(scene_index)` — `Song.View.selected_scene`.
- `set_detail_clip(track_index, clip_slot_index)` — `Song.View.detail_clip`
  (slot must hold a clip).
- `set_highlighted_clip_slot(track_index, scene_index)` — `Song.View.highlighted_clip_slot`.
- `get_view_selection()` — read-only; selected track index/name, selected scene
  index, detail_clip name, highlighted-slot has_clip.
- `set_track_fold(track_index, folded)` — `Track.fold_state` (guarded by
  `Track.is_foldable`; clean rejection on non-group tracks).
Reads added to `get_track_info`: `is_foldable`, `is_grouped`, `fold_state` (probed).

## Enum-confirmation TODO (resolve during live verification)
- `Live.Song.Quantization` ordering for `clip_trigger_quantization`.
- `Live.Clip.LaunchQuantization` ordering; `launch_mode` int meanings (0–3).
- `fold_state` int vs bool (handler writes 1/0).
The int path always works; name maps are provisional until live-confirmed (Phase 3
quantize-grid lesson: the original map was off-by-one).

## Files
- `ableton_mcp_max/transport_utils.py`, `clip_utils.py`, `view_utils.py` (new),
  `server.py`.
- `remote_script/AbletonMCP/__init__.py` — dispatch + handlers; extended
  `_get_transport`, `_get_clip_info`, `_get_track_info`.
- `tests/test_transport_utils.py`, `test_clip_utils.py`, `test_view_utils.py` (new).
