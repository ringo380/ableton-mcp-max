# ableton-mcp-max — Progress

**Current focus:** Phase 3 (Clip & MIDI Editing) fully live-verified against Live 11 Suite (MIDI + audio clips). All 9 tools confirmed. Ready to PR + squash-merge.
**Next action:** Push branch `phase-3-clip-midi`, open PR, `gh pr merge --squash --delete-branch`, then plan Phase 4 (Devices & Racks).

## Phases
| Phase | Title | Status | Completed |
|-------|-------|--------|-----------|
| 0 | Foundation (fork + parity + install) | Live-verified | 2026-05-24 |
| 1 | Device & Parameter Control | Live-verified | 2026-05-24 |
| 2 | Mixer (volume/pan/mute/solo/arm/sends/master/returns/xfade) | Live-verified | 2026-05-24 |
| 2b | Routing (input/output/monitor) | Live-verified | 2026-05-24 |
| 3 | Clip & MIDI Editing | Live-verified | 2026-05-24 |
| 4 | Devices & Racks | Not started | |
| 5 | Scenes, Transport, Arrangement | Not started | |
| 6 | Automation Envelopes | Not started | |
| 7 | Change Listeners (stretch) | Not started | |

## Phase 0 tools (parity, vendored) — live-verified (get_session_info + get_track_info confirmed; rest vendored unchanged from ahujasid)
- [x] get_session_info, get_track_info, create_midi_track, set_track_name,
      create_clip, add_notes_to_clip, set_clip_name, set_tempo, fire_clip,
      stop_clip, start_playback, stop_playback, load_instrument_or_effect,
      get_browser_tree, get_browser_items_at_path, load_drum_kit

## Phase 1 tools
- [x] param_utils.resolve_parameter_index (offline unit tests: 6/6 pass)
- [x] get_device_parameters (live: Wavetable, 93 params read w/ value_items)
- [x] set_device_parameter (live: by-name continuous + quantized, index clamping 999→48 all OK; values restored)

## Phase 2 tools
- [x] mixer_utils.normalize_property / validate_property (offline unit tests: 9/9 pass)
- [x] get_mixer (live: regular has arm+sends+xfade; return has sends, no arm; master volume/pan only. Returns = A-Reverb, B-Delay)
- [x] set_mixer_property (live: volume/pan clamped, mute toggle, send by index all OK; negative cases — arm-on-return, mute-on-master, send-without-index — rejected server-side with no Live mutation; values restored)

## Phase 2b tools
- [x] routing_utils.normalize/validate/resolve (offline unit tests: 9/9 pass)
- [x] get_routing (live: regular = input/output/monitor; return & master = input+output, NO monitoring_state. Fixed hasattr→try/except: Live raises RuntimeError not AttributeError for monitoring on return/master)
- [x] set_routing (live: monitor 2→1, output_type "Sends Only"→"Master" via object-assignment; negative — bogus/stale display_name — rejected with live "Available:" list; values restored)
- Note: input-routing-on-return/master validation was loosened (Live exposes those endpoints) and is unit-tested; the loosened server validation takes effect next Claude Code restart. The _assign_routing handler path itself is live-proven via output_type.

## Phase 3 tools
- [x] clip_utils.normalize_clip_property / validate_clip_property / coerce_clip_value /
      resolve_quantize_grid (offline unit tests: 24/24 pass; total suite 39/39)
- [x] get_clip_info (live: MIDI clip omits audio-only fields; verified on scratch + real clip)
- [x] get_clip_notes (live: arg order CONFIRMED via time + pitch windows; time_span<0→clip.length)
- [x] replace_clip_notes (live: clears then sets exactly the given notes, no leftovers)
- [x] remove_clip_notes (live: partial window [1,3) removed middle 2, left out-of-window notes)
- [x] set_clip_property (live: signature_numerator 4→3, looping→false, gain rejected on MIDI)
- [x] set_clip_loop (live: window set + looping re-enabled; inverted end<start rejected w/ values)
- [x] quantize_clip (live: enum INTS confirmed grid1=1/4 snap, grid3=1/8t snap; after fix+restart
      grid NAME "1/8"->int 2 snapped 0.6->0.5, i.e. straight eighth not triplet — fully confirmed)
- [x] duplicate_clip (live: copied to default target slot+1; empty-target guard rejects occupied)
- [x] delete_clip (live: scratch slots emptied, slots remain)
- [x] audio-clip properties (live: track 3/4 audio clips expose warping/warp_mode/gain/
      gain_display_string/pitch_coarse/pitch_fine; set gain 0.4->0.6 ("0.00 dB"->"8.00 dB",
      confirms gain is normalized 0-1), pitch_coarse->5, warp_mode 4->3, pitch_fine->25; all
      restored. gain on MIDI clip rejected with clear error.)
- **Note interaction (not a bug):** after set_clip_loop, clip.length reflects the loop length, so
  get_clip_notes default scan (time_span=-1→clip.length) only covers the loop region. Pass explicit
  from_time/time_span to scan beyond the loop.

## Routing reachability notes
- All track types expose input_routing_type/channel + output_routing_type/channel.
- current_monitoring_state: regular tracks only (return/master raise "no monitoring state").
- Endpoints are objects set by assigning from available_* lists (matched by display_name/identifier), never raw strings.

## Deployment state
- MCP server registered as **AbletonMCPMax** for project `abletonwork`
  (`uv run --directory ~/git/ableton-mcp-max ableton-mcp-max`); old `AbletonMCP`
  (uvx ahujasid) removed from that project.
- Remote Script installed at
  `/Applications/Ableton Live 11 Suite.app/Contents/App-Resources/MIDI Remote Scripts/AbletonMCP/`
  (original ahujasid script backed up to `AbletonMCP.bak.*` alongside it).
- Requires: quit+reopen Live (load new handlers), restart Claude Code (load new tools).

## Phase 3 live-verification notes
- **get_clip_notes arg order CONFIRMED** = (from_time, from_pitch, time_span, pitch_span).
  Time window [0,2) returned only early notes; from_pitch=65 returned only pitches >=65.
- **get_clip_info**: MIDI clip omits audio-only fields (warp/gain/pitch) via try/except. Confirmed
  on scratch clip + real "I Remember - Chords" clip.
- **quantize_clip 1/4 CONFIRMED**: grid="1/4" -> enum int 1; note at 2.4 snapped to 2.0 (musically
  correct). Confirms 1/4 exists and QUANTIZE_GRID_MAP ordering (none=0, 1/4=1, ...) is right.
- **replace_clip_notes works** (clip correctly held only the new note afterward) BUT see dialog below.
- **GOTCHA — Live 11 legacy-note-API modal**: any WRITE via legacy set_notes/remove_notes
  (replace_clip_notes, remove_clip_notes, add_notes_to_clip, quantize) pops a modal
  ("A custom MIDI Remote Script uses an older process to modify MIDI notes...") that BLOCKS the
  Remote Script main thread -> our socket times out with "No data received" even though the edit
  succeeds. Reads (get_notes) are unaffected. Short-term: user checks "Do not show again for this
  device" + Proceed. PROPER FIX: migrate note writes to Live 11 extended API
  (set_notes_extended/apply_note_modifications) — also preserves MPE/probability/release-velocity.
  Recommend pulling this forward from a later phase.
  - CONFIRMED the modal fires on EVERY legacy note write (per-write, not one-time) unless
    "Do not show again for this device" is checked. clip.quantize does NOT trigger it (different
    code path). So replace/remove/add-notes all block per call until the box is checked.
- **quantize enum FIX (live-found)**: original QUANTIZE_GRID_MAP was wrong (had a nonexistent 1/4t,
  off-by-one beyond 1/4). Corrected to none=0,1/4=1,1/8=2,1/8t=3,1/8+1/8t=4,1/16=5,1/16t=6,
  1/16+1/16t=7,1/32=8 (confirmed: grid 1->1/4 snap, grid 3->1/8t snap). Fix is in clip_utils.py;
  takes effect after the next Claude Code restart (server-imported module, no hot reload).

## Device parameter reachability notes
- Wavetable: 93 automatable params exposed. Quantized params (Device On, Osc On,
  Filter Type/LP-HP/Slope, Sub Transpose, Loop Modes, LFO Shape/Sync/Retrigger)
  expose value_items and are settable by integer index. Continuous params settable
  by float; out-of-range values clamp to min/max. Settable by name (case-insensitive)
  or index. No menu-only/unreachable controls observed at the device top level.
