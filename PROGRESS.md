# ableton-mcp-max — Progress

**Current focus:** Phase 3 (Clip & MIDI Editing) implemented on branch `phase-3-clip-midi`; offline tests green. Awaiting live verification.
**Next action:** Reinstall remote script + quit/reopen Live + restart Claude Code, then live-verify the 9 Phase 3 tools (esp. get_notes/remove_notes arg order, RecordingQuantization grid ints, warp_mode ints, duplicate_clip_to). Record results below, then PR + squash-merge.

## Phases
| Phase | Title | Status | Completed |
|-------|-------|--------|-----------|
| 0 | Foundation (fork + parity + install) | Live-verified | 2026-05-24 |
| 1 | Device & Parameter Control | Live-verified | 2026-05-24 |
| 2 | Mixer (volume/pan/mute/solo/arm/sends/master/returns/xfade) | Live-verified | 2026-05-24 |
| 2b | Routing (input/output/monitor) | Live-verified | 2026-05-24 |
| 3 | Clip & MIDI Editing | Implemented (offline) | |
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
- [ ] get_clip_info (read; audio-only fields probed via try/except)
- [ ] get_clip_notes (MIDI-only; get_notes arg order from_time,from_pitch,time_span,pitch_span; time_span<0→clip.length)
- [ ] replace_clip_notes (MIDI-only; remove_notes(0,0,length,128) then set_notes)
- [ ] remove_clip_notes (MIDI-only; window remove)
- [ ] set_clip_property (generic; audio-only props rejected on MIDI both server + remote)
- [ ] set_clip_loop (ordered dual-edge write; looping=-1 leaves unchanged)
- [ ] quantize_clip (MIDI-only; grid=RecordingQuantization int — VALUES NEED LIVE CONFIRM)
- [ ] duplicate_clip (clip_slot.duplicate_clip_to; default target=clip_index+1; empty-target guard)
- [ ] delete_clip (clip_slot.delete_clip)
- **Verify-live flags:** get_notes/remove_notes arg order; RecordingQuantization enum + grid int values
  in clip_utils.QUANTIZE_GRID_MAP (incl. whether 1/4 exists); warp_mode int→mode mapping; gain 0–1↔dB;
  duplicate_clip_to signature.

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

## Device parameter reachability notes
- Wavetable: 93 automatable params exposed. Quantized params (Device On, Osc On,
  Filter Type/LP-HP/Slope, Sub Transpose, Loop Modes, LFO Shape/Sync/Retrigger)
  expose value_items and are settable by integer index. Continuous params settable
  by float; out-of-range values clamp to min/max. Settable by name (case-insensitive)
  or index. No menu-only/unreachable controls observed at the device top level.
