# ableton-mcp-max — Progress

**Current focus:** Phase 4 (Devices & Racks) — code complete on branch `phase-4-devices-racks`, offline suite 65/65 green. 7 new tools (get_device_info, delete_device, set_device_on, get_rack_macros, set_rack_macro, get_rack_chains, set_chain_property). Device move + preset selection DEFERRED to Phase 4b (no clean Live 11 LOM path). Awaiting live verification.
**Next action:** Reinstall remote script + quit/reopen Live + restart Claude Code; live-verify Phase 4 tools (re-read set state first; restore all changed values); then PR + squash-merge.

## Phases
| Phase | Title | Status | Completed |
|-------|-------|--------|-----------|
| 0 | Foundation (fork + parity + install) | Live-verified | 2026-05-24 |
| 1 | Device & Parameter Control | Live-verified | 2026-05-24 |
| 2 | Mixer (volume/pan/mute/solo/arm/sends/master/returns/xfade) | Live-verified | 2026-05-24 |
| 2b | Routing (input/output/monitor) | Live-verified | 2026-05-24 |
| 3 | Clip & MIDI Editing | Live-verified | 2026-05-24 |
| 3.1 | Extended note API migration (+ modify_clip_notes) | Live-verified | 2026-05-25 |
| 4 | Devices & Racks (info/delete/on-off/macros/chains) | Code complete, awaiting live | |
| 4b | Device move + preset selection (deferred) | Not started | |
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

## Phase 3.1 — extended note API migration (live-verified 2026-05-25)
- Migrated add/replace/remove/get note ops to Live 11 extended API
  (add_new_notes / remove_notes_extended / get_notes_extended) + `import Live` in remote script.
  **The legacy-note modal NO LONGER APPEARS on any write** (root issue resolved).
- get_clip_notes now returns note_id + probability + velocity_deviation + release_velocity.
  Live confirmed: explicit probability=0.5/release_velocity=80 on add round-trip through get;
  omitted fields default to 1.0 / 0.0 / 64.0 (server-side clip_utils.normalize_note).
- **Extended arg order CONFIRMED** = (from_pitch, pitch_span, from_time, time_span) — pitch FIRST,
  opposite the legacy get_notes. Verified via pitch-window + time-window reads.
- NEW modify_clip_notes (apply_note_modifications): live-confirmed in-place edit by note_id
  (changed only provided fields, note_id preserved, other notes untouched — no remove+re-add);
  bogus note_id rejected with "note_id(s) not found in clip: [...]".
- clip_utils: +normalize_note (defaults/clamps) +NOTE_MOD_FIELDS; offline suite 43/43.

## Phase 4 tools (Devices & Racks) — code complete, awaiting live verification
- [x] device_utils.resolve_device_index / resolve_macro / normalize_chain_property /
      validate_chain_property / coerce_chain_value / coerce_on_value
      (offline unit tests: 22/22; total suite 65/65)
- [ ] get_device_info (class/type, is_active, can_have_chains/drum_pads, is_on,
      macro_count/chain_count for racks; track_type-aware via _resolve_track)
- [ ] delete_device (track.delete_device(index); reports new device_count) — LIVE on scratch device only
- [ ] set_device_on (writes "Device On" param[0]; rejects devices without it)
- [ ] get_rack_macros (filters device.parameters named "Macro N")
- [ ] set_rack_macro (server resolves macro# / "Macro N" → param index; clamped set; rack-guarded)
- [ ] get_rack_chains (device.chains: name, mute/solo, mixer volume/panning, contained devices)
- [ ] set_chain_property (mute/solo bool; volume/panning clamped via chain.mixer_device; rack-guarded)
- **Deferred to Phase 4b:** device move (no LOM reorder API) + preset selection (browser re-load).
- **Add device** already covered by existing load_instrument_or_effect (browser load) — not re-impl.
- LOM items to confirm live: macro naming/count on real Instrument Rack; chain.mixer_device
  reachability on audio vs MIDI chains (try/except guarded); delete_device re-indexing;
  drum-rack (can_have_drum_pads) chain shape degrades gracefully.

## Device parameter reachability notes
- Wavetable: 93 automatable params exposed. Quantized params (Device On, Osc On,
  Filter Type/LP-HP/Slope, Sub Transpose, Loop Modes, LFO Shape/Sync/Retrigger)
  expose value_items and are settable by integer index. Continuous params settable
  by float; out-of-range values clamp to min/max. Settable by name (case-insensitive)
  or index. No menu-only/unreachable controls observed at the device top level.
