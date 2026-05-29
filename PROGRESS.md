# ableton-mcp-max — Progress

**Current focus:** Preset-patch rack tools (task #5) COMPLETE + LIVE-VERIFIED. Phase A (v0.2.0:
inspect_rack_preset, clone_rack, rename_rack_macros, set_rack_zones) shipped; Phase B macro→param
mapping experiment cracked the `<KeyMidi>` encoding and `add_rack_macro_mappings` is built +
live-verified on branch `feat/rack-macro-mappings` (offline 307/307; server imports; remote script
unchanged). Phases 0–11 + Phase A all live-verified and merged. See "Preset-patch backdoor" section.
**Next action (resume here):** ship `feat/rack-macro-mappings` as v0.3.0 (bump plugin.json, PR→squash
merge, release, bump marketplace ableton ref + build-readme). gh login must be ringo380. Future: rack
macro-mapping v2 (custom/inverted ranges; nested rack-in-rack params).

## Phases
| Phase | Title | Status | Completed |
|-------|-------|--------|-----------|
| 0 | Foundation (fork + parity + install) | Live-verified | 2026-05-24 |
| 1 | Device & Parameter Control | Live-verified | 2026-05-24 |
| 2 | Mixer (volume/pan/mute/solo/arm/sends/master/returns/xfade) | Live-verified | 2026-05-24 |
| 2b | Routing (input/output/monitor) | Live-verified | 2026-05-24 |
| 3 | Clip & MIDI Editing | Live-verified | 2026-05-24 |
| 3.1 | Extended note API migration (+ modify_clip_notes) | Live-verified | 2026-05-25 |
| 4 | Devices & Racks (info/delete/on-off/macros/chains) | Live-verified | 2026-05-25 |
| 4b | Preset selection (device-move dropped: no LOM API) | Live-verified | 2026-05-26 |
| 5 | Scenes, Transport, Arrangement | Live-verified | 2026-05-25 |
| 6 | Automation Envelopes | Live-verified | 2026-05-25 |
| 7 | Change Listeners (polling buffer) | Live-verified | 2026-05-25 |
| 8 | Arrangement Authoring (cue CRUD + arrangement clips) | Live-verified | 2026-05-26 |
| 9 | Track Lifecycle (create/delete/duplicate) & Undo/Redo | Live-verified | 2026-05-27 |
| 10 | Global Feel/Quant, Clip Launch Settings, View/Selection & Folding | Live-verified | 2026-05-27 |
| 11 | Capture & Recording (capture_midi/scene, session record, stop-all, tap-tempo) | Live-verified | 2026-05-27 |

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
- [x] get_device_info (live: Wavetable -> can_have_chains false, 93 params, is_on true;
      "Basic Analog Bass" rack -> can_have_chains true, chain_count 1, is_on true. macro_count
      now 16 after fix.)
- [x] delete_device (live: deleted "Basic Analog Bass" from track 0 -> device_count 0, track empty; re-indexes)
- [x] set_device_on (live: track 0 Wavetable off->on confirmed both ways incl. "on" string coercion; restored)
- [x] get_rack_macros (live after fix: 16 macros incl. renamed Filter Cutoff/Drive/etc., positional macro_number)
- [x] set_rack_macro (live after fix: by number 5->Drive=60, by custom name "Filter Cutoff"=100;
      macro 99 rejected with full "1=Filter Cutoff..16=Macro 16" list)
- [x] get_rack_chains (live: 1 chain "Analog" with 6 inner devices Analog/Comp/VinylDist/Delay/Delay/Reverb;
      mute/solo/volume/panning surfaced)
- [x] set_chain_property mute/solo (live: chain "Analog" mute false->true->false confirmed; restored)
- [x] set_chain_property volume/panning guard (live after fix: chain "Analog" volume rejected with clean
      "not settable (disabled by Live for this chain)"). Whether any rack chain exposes an *enabled*
      volume/panning still TBD (re-probe on a multi-chain rack later).
- **Deferred to Phase 4b:** device move (no LOM reorder API) + preset selection (browser re-load).
- **Add device** already covered by existing load_instrument_or_effect (browser load) — not re-impl.

### Live findings (2026-05-25)
- **MACRO LAYOUT (important):** a rack's parameters are `Device On`(0), then the macros
  (1..N), then `Chain Selector`(last). Macros may be RENAMED (e.g. "Basic Analog Bass" macros
  1-8 = Filter Cutoff/Filter Reso/Filter Envelope/Space/Drive/Comp/Delay/Volume; 9-16 default
  "Macro 9".."Macro 16"). Original name-prefix filter missed the renamed ones. FIXED: _rack_macros
  now enumerates by POSITION (everything between Device On and Chain Selector) and tags each with
  a 1-based macro_number; resolve_macro resolves a number positionally + a name by custom label.
- **CHAIN MIXER:** chain.mixer_device.volume/panning can be `is_enabled == False` (seen on the
  single-chain Analog rack chain) -> Live raises "Value cannot be set, the parameter is disabled".
  Handler now pre-checks is_enabled and raises a clear message. mute/solo always work.
- **load_instrument_or_effect HOT-SWAPS:** loading onto a track that already has an instrument
  REPLACES it (track 1 Lead's Wavetable was replaced by the test rack). Restore via Live undo.
- TBD: drum-rack (can_have_drum_pads) chain shape; multi-chain rack with enabled chain volume.

## Phase 4b tools (Preset Selection) — LIVE-VERIFIED 2026-05-26
Scope settled this session: **device move/reorder DROPPED as infeasible** — Live 11's LOM exposes
no device copy/paste/reorder API (`Track` has only `delete_device`; no `move_device`/clipboard).
The only technically-possible route was a fragile osascript Cmd+C/Cmd+V keystroke hack (Live must be
frontmost, UI-focus + timing dependent, breaks the socket/LOM architecture) — explicitly rejected.
Revisit if/when the project targets Live 12.
- [x] preset_utils.py (server-only pure helper): `match_preset` (direct-children match: exact →
      case-insensitive → unique substring; ValueError listing available names), `match_recursive_preset`
      (matches a query against name OR relative_path across the whole subtree; capped available list),
      `split_preset_path` (full path → (parent, leaf); ValueError on single-segment).
      Offline tests +18 → total suite 158/158.
- [x] remote_script: new READ command `get_browser_presets(path, max_depth=6)` — reuses
      get_browser_items_at_path's root-category + path-walk, then recursively collects loadable
      leaves ({name, relative_path, uri}). Read-only (direct dispatch, NOT in mutation list /
      main_thread_task). Returns same {error, available_categories} envelope on path miss.
- [x] server.py tools: `list_device_presets(path, max_depth=6, limit=100)` → get_browser_presets,
      returns {count, returned, truncated, presets} (capped to `limit` — factory devices expose
      hundreds; raw dump overran the MCP token limit at 419 presets). `load_preset(track_index, path,
      name=None)` → get_browser_presets(folder) → `match_recursive_preset` → load_browser_item.
      HOT-SWAPS like load_instrument_or_effect. (2 tools cover all 3 requested capabilities —
      load-by-name and load-.adv/.adg are the same browser-item/load_browser_item op.)
- Plan: `~/.claude/plans/let-s-work-on-phase-expressive-catmull.md`.
- **Code review (medium, 2026-05-26):** found list/load path-semantics mismatch — `list_device_presets`
  lists presets recursively (all 419 Wavetable presets nested in subfolders) but `load_preset`
  originally resolved only against DIRECT children via get_browser_items_at_path, so the documented
  list→load-by-name workflow could not load ANY factory Wavetable preset (live-reproduced:
  "No loadable presets at this path."). **Fixed**: load_preset now resolves recursively via
  get_browser_presets + match_recursive_preset (matches name or relative_path). Also capped
  list_device_presets output (76KB → bounded).
- **Live verification (2026-05-26, scratch MIDI track), PRE-FIX server.py:**
  list_device_presets('instruments/Wavetable') → 419 presets (all nested, relative_path like
  'Ambient & Evolving/Dark Swarm.adg'); load_preset by name against the category path FAILED
  ("No loadable presets at this path" — the bug). Workarounds confirmed working live: folder-path +
  name, and full-path form (split_preset_path); hot-swap confirmed (get_device_info →
  InstrumentGroupDevice rack); negative match → clean error listing available names; delete_device →
  device_count 0 (restore). NOTE: a scratch MIDI track was left in the open project (no delete_track
  tool) — remove via Live undo.
- **POST-FIX LIVE-VERIFIED (2026-05-26, after Claude Code restart, scratch MIDI track):** the exact
  pre-fix failure now works — load_preset(track, 'instruments/Wavetable', name='Dark Swarm.adg') →
  loaded 'Ambient & Evolving/Dark Swarm.adg'; relative_path substring ('Bass/Talking') → uniquely
  resolved 'Bass/Talking 808 Bass.adg'; hot-swap confirmed (get_device_info → InstrumentGroupDevice);
  list cap: limit=3 → {count:419, returned:3, truncated:true}+hint, default limit=100 → returned:100
  WITHOUT overrunning the MCP token limit (pre-fix 419-dump errored at 76KB). delete_device restore OK.
  Offline suite 158/158.

## Device parameter reachability notes
- Wavetable: 93 automatable params exposed. Quantized params (Device On, Osc On,
  Filter Type/LP-HP/Slope, Sub Transpose, Loop Modes, LFO Shape/Sync/Retrigger)
  expose value_items and are settable by integer index. Continuous params settable
  by float; out-of-range values clamp to min/max. Settable by name (case-insensitive)
  or index. No menu-only/unreachable controls observed at the device top level.

## Phase 5 tools (Scenes, Transport, Arrangement) — ALL live-verified 2026-05-25
- [x] scene_utils.normalize_scene_property / coerce_scene_value;
      transport_utils.parse_time_signature / resolve_cue_direction / coerce_song_time /
      coerce_jump_beats / coerce_loop_fields / coerce_punch_fields
      (offline suite 93/93). Reuse device_utils.coerce_on_value for bool toggles.
- **Scenes (7):**
  - [x] get_scenes (live: 9 scenes; per-scene tempo/time-sig surface -1 sentinel when not overridden)
  - [x] fire_scene (live: launched scene 0, is_playing→true; index 99 rejected "out of range (0..8)")
  - [x] create_scene (live: -1 appended, count 9→10)
  - [x] delete_scene (live: count 10→9; range-guarded)
  - [x] duplicate_scene (live: count 9→10, copy after source)
  - [x] set_scene_name (live: scene 2 ""→"VERIFY"→"" restored)
  - [x] set_scene_property (live: color/tempo/tempo_enabled/time_signature all applied;
        aliases bpm/time_sig/colour fold correctly; bad denom 4/3 + bogus prop rejected server-side)
- **Transport (8):**
  - [x] get_transport (live: full state incl. session_record/song_length/back_to_arranger)
  - [x] continue_playback (live: resumed from position, advanced playhead)
  - [x] set_metronome (live: off→on→off; reads back fresh)
  - [x] set_arrangement_record (live: record_mode on→off — NOTE arming starts playback)
  - [x] set_session_record (live: on→off — NOTE arming starts playback)
  - [x] set_punch (live: in/out true→false; both-None guard server-side)
  - [x] set_song_position (live: jumped to 8 then 64; negative -1 rejected server-side)
  - [x] jump_by (live: +/- beats, -4 from 8→4)
- **Arrangement (5):**
  - [x] get_cue_points (live: 2 locators locator1@32, locator2@64)
  - [x] set_arrangement_loop (live: enabled/start/length applied, only-provided fields;
        all-None guard server-side; restored to original off/8/16)
  - [x] jump_to_cue (live: prev 64→32, next/forward 32→64; "sideways" rejected)
  - [x] back_to_arrangement (live: back_to_arranger override true→false re-engages arrangement)
  - [x] re_enable_automation (live: returns re_enabled true, no error — LOM call present in build)

### Phase 5 live findings (2026-05-25)
- **Verify-or-drop flags ALL resolved:** re_enable_automation() exists & works; back_to_arranger=0
  clears the override; jump_to_next_cue()/jump_to_prev_cue() both work (used instead of cue.jump()).
- **Return-value lag (cosmetic):** song-level property WRITES (record_mode, session_record, punch_in/out,
  current_song_time, loop, back_to_arranger) succeed but the handler's same-task read-back returns the
  PRE-write value — a follow-up get_transport always shows the correct value. metronome reads fresh.
  The mutation itself is reliable; only the returned confirmation dict can be stale. Not worth a fix
  (Live applies the property change asynchronously even within schedule_message).
- **Arming record auto-starts playback:** set_arrangement_record(on) and set_session_record(on) begin
  playback immediately. Tests must stop + restore promptly. song_length stayed 232.0 → nothing recorded
  (no armed tracks).
- **Per-scene time_signature cannot be reset to the -1 "inherit" sentinel** (numerator must be >=1):
  once set it's a permanent override. Live API limitation — set_scene_property can change it but not clear it.
- **Live snaps scene color to its palette:** set color 16711680 stored as 16728642 (nearest entry).

## Phase 6 tools (Automation Envelopes) — ALL live-verified 2026-05-25
- [x] automation_utils.normalize_clip_location / normalize_target_type /
      normalize_mixer_target / coerce_resolution / coerce_time / coerce_duration /
      coerce_value / normalize_breakpoints (offline suite 114/114; 21 new)
- [x] get_automation (live: sampled read; has_envelope false→true; windowed
      from_time/time_span read confirmed; device + mixer targets)
- [x] set_automation (live: single point + batch points list; auto-tile fix below)
- [x] clear_automation (live: range clear + full-envelope clear)
- [x] create_automation_envelope (live: created true then false — idempotent)
- [x] clear_all_automation (live: wiped Macro 1 + Track Volume envelopes → has_envelope false)
- Targets verified: device param by NAME ("Macro 1" on an Instrument Rack — confirms
  macros automate through the device path), mixer "volume" → "Track Volume",
  mixer "send" send_index=0 → "A-Reverb".

### Phase 6 live findings (2026-05-25)
- **insert_step needs duration > 0 — duration=0 is a NO-OP.** Live's
  AutomationEnvelope.insert_step(time, duration, value) writes a FLAT segment
  [time, time+duration); a zero-width step creates the envelope but holds no value
  (read back 0). There are NO linear ramps in the LOM — flat tiles are the only
  write primitive (a multi-point list draws a staircase, not a ramp).
- **FIX (live-found, in `_set_automation`): auto-tile zero/negative durations.** Points
  are sorted by time; a point with duration<=0 fills to the NEXT point's time (last
  point fills to clip.length; 1/32-beat fallback if that gap is <=0). So
  `set_automation(time=0, value=64)` now holds 64 across the whole clip, and a bare
  `points` list (no durations) draws the obvious staircase. Verified: value-only point
  held 64 over [0,4]; staircase 20/80/127 tiled at [0,1.5)/[1.5,3)/[3,4).
- **value_at_time left-edge boundary:** sampling at the EXACT start of a step returns
  the PRE-step value (e.g. t=0.0 reads 0 even when a step starts at 0). Samples inside
  the step are correct. Cosmetic; sample slightly inside a region to see its value.
- **Arrangement path:** `track.arrangement_clips` EXISTS and indexes (a bad index
  returns our clean "Arrangement clip index out of range", not AttributeError). The
  resolver is proven; full read/write on an arrangement clip not exercised (the test
  set had none) — re-verify when an arrangement clip is present.
- Negatives all clean server-side (no Live mutation): bad clip_location, mixer "send"
  without send_index, empty points list.
- **No legacy modal / main-thread stall** on any automation write (unlike the old
  legacy-note API) — envelope writes go through schedule_message cleanly.

## Phase 7 tools (Change Listeners — polling buffer) — CODE COMPLETE, awaiting live verify
Approach: Live's observer API is push-based; this MCP is request/response. Remote Script attaches
real Live listeners whose no-arg callbacks read the new value and append a change event to a
bounded per-listener deque (LISTENER_BUFFER_MAX=512; overflow evicts oldest + bumps `dropped`).
Claude drains on demand. Zero protocol changes. (Plan:
`~/.claude/plans/let-s-plan-out-phase-nifty-widget.md`.)
- [x] listener_utils.py (server-only pure helper): normalize_scope, normalize_listener_property
      (alias folding), build_descriptor (canonical {target_kind, listener_method, remove_method,
      readback, mixer_sub, selectors}; reuses mixer_utils track-type asymmetry), coerce_max_events,
      needs_device_resolution. Offline tests 26 new → total suite 140/140.
- [x] server.py: register_listener, poll_changes, unregister_listener, list_listeners (device-param
      identifier resolved via get_device_parameters + param_utils, like _resolve_auto_target).
- [x] remote_script: registry dict + threading.Lock + monotonic seq/id in __init__; register/
      unregister are MUTATIONS (in the elif list + main_thread_task — Live add_/remove_*_listener
      must run on main thread); poll/list are DIRECT reads (buffer-only, skip main thread); navigation
      `_listener_target_object` per target_kind (song/song_view/track/track_mixer/clip/clip_slot/
      device_param); `_make_listener_cb` factory + `_listener_emit` under lock; detach-all in disconnect.
- Scopes wired: transport (is_playing, current_song_time [high-volume], tempo, metronome,
  record_mode, session_record, loop), mixer (volume/pan/mute/solo/arm — arm regular-only),
  clip (playing_status, name, notes, has_clip, selected_scene via song.view), device (param value).

### Phase 7 live-verification results (2026-05-25 — ALL PASS)
- [x] Transport: is_playing fired true (start) → false (stop); tempo fired 128 then 120 on set_tempo.
      seq monotonic across listeners, dropped=0.
- [x] Mixer: volume on track 0 (regular) fired 0.85→0.7 on set_mixer_property (restored 0.85).
      arm on RETURN track 0 rejected at register time: "Property 'arm' not supported on return
      tracks. Supported: crossfade_assign, mute, pan, send, solo, volume" (no Live mutation).
- [x] Clip: playing_status on track0/slot0 fired true then false on fire_clip (clip is 0.44 beats so
      it retriggered → two events). Stopped clip after.
- [x] Device: loaded Analog onto empty MIDI track 1; register scope=device property=value
      parameter="Volume" resolved to param[3]; set_device_parameter 0.7→0.5 fired value=0.5.
      Scratch device deleted after (track 1 empty again).
- [x] High-volume / dropped: current_song_time during playback hit the bounded deque ceiling —
      pending capped at 512 with dropped climbing (393→774 across two polls). max_events=3 returned
      exactly the 3 oldest (remaining 509). Confirms LISTENER_BUFFER_MAX=512 + oldest-eviction.
- [x] list_listeners showed all 6 with target+pending+dropped; unregister_listener (no id) removed
      all 6; subsequent list_listeners count 0 and poll_changes empty (no further accrual).
- [x] Negatives: bad scope ("Unknown scope 'bogus_scope'. Valid: transport, mixer, clip, device"),
      bad transport property ("Unknown transport property ... Valid: current_song_time, is_playing,
      loop, metronome, record_mode, session_record, tempo"), mixer w/o track_index ("mixer listener
      for 'volume' requires track_index") — all rejected server-side.

### Phase 7 live findings (2026-05-25)
- **listener_id is a simple monotonic "L<n>"** assigned per register; persists until unregister.
- **`pending` caps at LISTENER_BUFFER_MAX (512); `dropped` is cumulative** since last drain of that
  listener — high-volume targets (current_song_time) overflow fast, so poll often or expect drops.
- **poll seq is a global monotonic counter** shared across listeners (not per-listener), so event
  ordering is total across the whole registry.
- **arm validation happens at REGISTER time** for return/master (reuses mixer_utils asymmetry), not
  at poll — a rejected register never attaches a Live listener.

## Phase 8 tools (Arrangement Authoring) — ALL live-verified 2026-05-26
Extends Phase 5 from cue reads/navigation into cue + arrangement-clip editing. Pure helper
`arrangement_utils.py` (coerce_time, coerce_index, cue_exists_at; offline tests +14 → suite 172/172).
- **Cue points (2 — rename DROPPED):**
  - [x] create_cue_point(time) — server orchestrates get_transport → set_song_position(time) →
        create_cue_at_playhead → restore playhead. Live: created cue@16 alongside existing
        locator1@32 + locator2@64 (none disturbed), playhead restored to 8; re-call → created:false
        reason:exists (idempotent, never deletes).
  - [x] delete_cue_point(index) — server looks up cues[index].time → set_song_position → toggle off →
        restore. Live: removed cue@16, other two survived, playhead restored; index 999 → clean
        server-side "out of range (0..1)".
  - **set_cue_point_name DROPPED:** `CuePoint.name` is READ-ONLY in the Live 11 LOM ("can't set
        attribute"). Locator names are UI-only; no API write path.
- **Arrangement clips (3):**
  - [x] get_arrangement_clips(track_index) — Live: count:0 baseline; lists index/name/start_time/
        end_time/length/is_midi_clip.
  - [x] duplicate_clip_to_arrangement(track_index, source_slot_index, destination_time) — Live:
        placed a session clip at beats 0 then 8, returns new_clip{name,start,end} (destination_time
        confirmed in BEATS); empty source slot → clean "No clip in session slot N on track M".
  - [x] delete_arrangement_clip(track_index, clip_index) — Live: deleted + remaining clips re-index
        (clip@8 became index 0); index 999 → clean "out of range".
- Spec: `docs/superpowers/specs/2026-05-26-phase-8-arrangement-authoring-design.md`;
  Plan: `docs/superpowers/plans/2026-05-26-phase-8-arrangement-authoring.md`.

### Phase 8 live findings (2026-05-26) — design changes driven by live behavior
- **In-task `current_song_time` writes are async (Phase 5 gotcha, confirmed harder here):** the
  original one-handler move→toggle→restore for cues FAILED — `set_or_delete_cue()` fired at the
  STALE playhead position, deleting the wrong cue (test: create_cue_point(16) with playhead at 64
  deleted locator2@64 and created nothing). Fix: split into separate socket commands; the playhead
  settles BETWEEN commands. Handlers `_create_cue_at_playhead`/`_delete_cue_at_playhead` now operate
  only at the already-settled playhead; the server does the positioning + restore.
- **`set_or_delete_cue()` takes NO time arg** — it toggles at the playhead; there is no create-at-
  arbitrary-time call. Pre-check cue_points to decide create vs. (avoid) delete.
- **CuePoint.name read-only** → rename infeasible (dropped). New cues get Live's auto-name ("1","2").
- **cue_points list is insertion-ordered, not time-sorted** (index 2 can be at an earlier time than
  index 0) — index is stable for delete; don't assume chronological order.
- **duplicate_clip_to_arrangement returns the new Clip** and re-reads of arrangement_clips within the
  same task reflect it (unlike song-position). delete_clip(clip) re-indexes the list.

## Phase 9 tools (Track Lifecycle & Undo/Redo) — ALL live-verified 2026-05-27
Closes the standing "no delete_track" gap (scratch tracks no longer need user Cmd+Z). Pure helper
`track_utils.py` (coerce_create_index: None/-1 → append, else >=0; coerce_track_index: >=0;
offline tests +11 → suite 183/183). All 7 LOM calls confirmed in 11.0.0.xml. Separate tools per
track type (1:1 with LOM), per design.
- **Creates (3):**
  - [x] create_audio_track(index=-1) — live: appended at index 7 → "8-Audio", track_count 7→8.
  - [x] create_return_track() — live: appended at return index 2 → "C-Return", return_count 2→3.
  - [x] create_midi_track — PARITY ONLY (Phase 0 tool already had index=-1; no change this phase).
- **duplicate_track(index) (1):** live: duplicate_track(7) → new_index 8 "9-Audio", count 8→9.
  Confirms new_index derived from `song.view.selected_track` (LOM duplicate_track returns None).
- **Deletes (2):**
  - [x] delete_track(index) — live: deleted 8 then 7, remaining_count 9→8→7, collection re-indexes.
  - [x] delete_return_track(index) — live: deleted return 2, remaining_count 3→2.
- **Undo/redo (2):**
  - [x] undo() / redo() — live: create → undo {undone:true, can_redo:true} → redo {redone:true,
        can_redo:false}. Both guarded by can_undo/can_redo precheck (clean no-op when empty).
- **Negatives:** delete_track(999) → handler-side "Track index out of range (0..6)"; duplicate_track(-5)
  → server-side coercion "Index must be >= 0; got -5" (no socket call). All scratch tracks cleaned up
  via the new delete tools → set restored to baseline 7 regular / 2 returns.
- Spec: `docs/superpowers/specs/2026-05-27-phase-9-track-lifecycle-design.md`;
  Plan: `docs/superpowers/plans/2026-05-27-phase-9-track-lifecycle.md`.

### Phase 9 live findings (2026-05-27)
- **Track-structural undo readback is STALE (new, important):** immediately after `undo()` of a
  track create, a follow-up `get_session_info` returned a TRANSIENT wrong count (9 regular / 3 returns
  — the pre-delete peak) instead of the settled value; a second read showed the correct count. This is
  the song-property-write-lag class (Phase 5) now confirmed for track-collection structure after undo.
  The undo/redo MECHANISM itself is reliable (undone/redone flags + can_undo/can_redo correct, redo
  reinstated the track and settled to the right state). **Verify structural state with a second read
  after undo/redo; don't trust the first post-undo count.**
- **undo is GLOBAL** (documented in the tool): it walks Live's whole undo stack including user
  hand-edits; the can_undo precheck only prevents erroring on an empty stack, it does not scope to MCP.
- **duplicate_track selects the new track**, so `song.view.selected_track` is a reliable in-task source
  for new_index/name (LOM duplicate_track itself returns None).

## Phase 10 tools (Global Feel/Quant, Clip Launch, View/Selection & Folding) — ALL live-verified 2026-05-27
Gap-audit phase. Two candidates dropped as infeasible in Live 11: **warp-marker editing**
(`Clip.warp_markers` read-only; no add/remove/move_warp_marker methods) and **follow actions**
(`follow_action*` absent from 11.0.0 LOM). Capture/recording (capture_midi/capture_and_insert_scene/
trigger_session_record/stop_all_clips/tap_tempo) is feasible but DEFERRED by user. Offline suite +19 → 202.
- **Group A — global feel/quant (`transport_utils.py`, 5 tools):**
  - [x] set_groove_amount(amount) — live: 1.0→0.5→1.0 confirmed via get_transport. 0–1 clamp.
  - [x] set_swing_amount(amount) — live: 0.0→0.5→0.0 confirmed. 0–1 clamp.
  - [x] set_clip_trigger_quantization(value) — live: name "1/4"→7 confirmed; default read=4 (1_bar).
        Confirms CLIP_TRIGGER_QUANTIZATION_MAP matches standard Live.Song.Quantization ordering.
        Bad name → clean server-side error listing all options + "(or an int 0-13)".
  - [x] set_midi_recording_quantization(value) — live: name "1/8"→2 confirmed (matches QUANTIZE_GRID_MAP).
  - [x] set_nudge(direction, active) — live: up true→false confirmed via get_transport nudge_up flag.
  - [x] get_transport extended (+7 reads): groove_amount, swing_amount, clip_trigger_quantization,
        midi_recording_quantization, count_in_duration (READ-ONLY, read 0), nudge_up, nudge_down — all present.
- **Group B — clip launch settings (extends set_clip_property/get_clip_info, NO new tool):**
  - [x] launch_mode/launch_quantization/legato/velocity_amount — live on a scratch MIDI clip (track 6):
        launch_mode=3, launch_quantization=2, legato=true, velamount alias→velocity_amount=0.5; all
        read back via get_clip_info. NOT rejected as audio-only (confirms valid on MIDI). Also read on
        an audio clip (track 0). Scratch clip deleted after.
- **Group C — view/selection & folding (`view_utils.py`, 6 tools):**
  - [x] set_selected_track — live: regular track 0, AND return 0 ("A-Reverb") confirmed; restored to track 6.
  - [x] set_selected_scene — live: scene 1 set (later re-coupled to 0 by highlighted-slot, see findings).
  - [x] set_detail_clip — live: track 0/slot 0 → detail_clip "FHP_DARK SYNTH3_C"; empty slot (track 6) →
        clean "No clip in slot 0 on track 6".
  - [x] set_highlighted_clip_slot — live: track 0/scene 0 → has_clip true.
  - [x] set_track_fold — FULLY verified (2026-05-27): negative (non-group → clean "not a group track")
        AND positive on hand-made group track "3-Group" (idx 2): bool true/false + int 1/0 round-trip,
        fold visually confirmed collapsed in Live. (Group tracks need ⌘G by hand — no LOM create API.)
  - [x] get_view_selection() — live: selected track index/name, scene index, detail_clip name,
        highlighted-slot has_clip all returned.
  - [x] get_track_info extended (+3 reads): is_foldable/is_grouped present on all tracks read;
        fold_state omitted on non-foldable tracks (getattr raised → defensive skip).
- Spec: `docs/superpowers/specs/2026-05-27-phase-10-feel-launch-view-design.md`;
  Plan: `docs/superpowers/plans/2026-05-27-phase-10-feel-launch-view.md`.

### Phase 10 live findings (2026-05-27)
- **Quantization enums CONFIRMED:** clip_trigger_quantization default reads 4 = `1_bar`; name "1/4"→7.
  This matches the standard Live.Song.Quantization ordering encoded in CLIP_TRIGGER_QUANTIZATION_MAP
  (none=0, 8/4/2_bars=1/2/3, 1_bar=4, 1/2=5, ... 1/4=7, ... 1/32=13). midi_recording_quantization "1/8"→2
  matches the already-confirmed clip_utils.QUANTIZE_GRID_MAP. **launch_mode/launch_quantization ints
  round-trip** (set 3/2, read 3/2); exact UI labels not visually confirmed but the int path is reliable.
- **detail_clip read couples to the highlighted slot:** in a batch, calling set_highlighted_clip_slot
  AFTER set_detail_clip transiently cleared detail_clip (read null); setting detail_clip alone reads back
  correctly. Highlighting a slot also re-selects its track+scene (so a prior set_selected_scene gets
  overridden). Set these LAST / individually if you need the read to stick. Setters themselves are reliable.
- **fold_state CLOSED (2026-05-27):** verified on a hand-made group track ("3-Group", idx 2) — bool
  true/false AND int 1/0 both round-trip; fold visually confirmed in Live; non-foldable grouped child
  (idx 3) rejected cleanly. Group tracks can't be created via LOM (no API) — make via ⌘G by hand.
  CAVEAT: `get_track_info` crashes on group tracks (reads `.arm`, which group tracks lack) — separate
  pre-existing bug, see header. fold_state verification used the setter's own echo + visual check, not
  get_track_info.
- **Song-property-write lag (Phase 5) did NOT bite Group A here** — get_transport read back the new
  groove/swing/quant/nudge values correctly on the first follow-up read. Still prefer the separate read.

## Phase 11 tools (Capture & Recording) — ALL live-verified 2026-05-27
Closes the capture/recording set deferred during the Phase 10 gap-audit. All 5 LOM calls confirmed in
11.0.0.xml (Song methods). Pure helper additions in `transport_utils.py` (offline suite +8 → 210).
- **5 tools (all song-level mutations):**
  - [x] capture_midi(destination="auto") — live: with NO material → safe no-op (captured:true, nothing
        created); all 3 destinations (auto/session/arrangement) resolve via getattr + execute. POSITIVE
        test: user played MIDI into an armed scratch track → can_capture_midi flipped true →
        capture_midi("session") created an 8.0-beat MIDI clip in the armed track's slot. Scratch track deleted.
  - [x] capture_and_insert_scene(mode="all") — live: fired track-0 audio clip (playing) → captured a new
        NON-empty scene inserted at index 1 (after selected scene 0); scene_count 9→10. Captured scene deleted.
  - [x] trigger_session_record(record_length=4) — live: on an armed scratch MIDI track → auto-started
        playback AND created a clip of EXACTLY 4.0 beats (fixed-length recording finished, clip looping).
        Scratch track deleted. record_length=0 rejected server-side ("must be > 0").
  - [x] stop_all_clips(track_index=None, quantized=True) — live: song-level (fire clip → stop-all,
        quantized=false → clip stopped, song keeps playing) AND track-scoped (track_index=0 → scope:track).
        Negatives: track_index=99 → handler "Track index out of range (0..7)"; track_index=-5 → server-side
        "Index must be >= 0" (no socket call).
  - [x] tap_tempo() — live: executes cleanly (tapped:true, tempo echoed). A SINGLE tap does NOT change
        tempo (Live needs successive taps to compute an interval) — call repeatedly in time to set tempo.
- **get_transport +3 reads:** can_capture_midi, is_counting_in, session_record_status — all present (live:
  can_capture_midi false at rest, flipped true after playing MIDI; session_record_status int 0).
- **Enum handling:** CaptureDestination/CaptureMode int values are UNDOCUMENTED in the LOM, so the server
  validates the NAME (transport_utils.resolve_capture_destination/resolve_capture_mode — return the name,
  not an int) and the Remote Script resolves it via getattr(Live.Song.CaptureDestination, name). Deliberate
  deviation from the usual "send ints" convention; keeps the enum source-of-truth in Live.
- **transport_utils helpers:** resolve_capture_destination (None→auto), resolve_capture_mode (None→all),
  coerce_record_length (None→omit; else float >0). stop_all_clips reuses coerce_on_value +
  track_utils.coerce_track_index.
- Spec: `docs/superpowers/specs/2026-05-27-phase-11-capture-recording-design.md`;
  Plan: `docs/superpowers/plans/2026-05-27-phase-11-capture-recording.md`.
- **Live-test reminders:** confirm effects via SEPARATE follow-up reads (song-property-write lag);
  capture tools do nothing on an empty blank set (need playing material); clean up captured clips/scenes
  + restore the set; stop session-record promptly (auto-starts playback).

## Preset-patch backdoor (initiative — separate from numbered Phases)
Reach Ableton controls absent from the LOM `device.parameters` API by patching gzipped
preset XML (.adv/.adg), writing to the User Library, and loading via the browser.
Shared pure core: `ableton_mcp_max/preset_patch.py` (set_attr/set_manual/scope/get_attr + validators).

- **Wavetable + Simpler** (committed `30570cd`): `list_wavetable_tables`, `create_wavetable_preset`
  (osc table / unison mode / voices — none automatable), `create_simpler_instrument` (sample ref
  injected into empty `<SampleParts/>`). `wavetable_preset_utils.py` / `simpler_preset_utils.py`.

- **Rack macro-mapping & zones — Phase A: LIVE-VERIFIED 2026-05-29** (branch `feat/preset-patch-backdoor`).
  Pure XML in `rack_preset_utils.py` (depth-aware branch scanner finds chain-level zones that are
  DIRECT children of a branch, ignoring nested sampler multisample KeyRanges); 4 tools in server.py.
  Spec: `docs/superpowers/specs/2026-05-29-rack-preset-macro-mapping-design.md`;
  Plan: `docs/superpowers/plans/2026-05-29-rack-preset-macro-mapping.md`. Offline 293/293.
  - [x] inspect_rack_preset — live: "808 Drifter" → instrument, 8 visible macros, all 16 read
        (named + color + default; unnamed color -1), 1 chain w/ key/vel/selector zones.
  - [x] clone_rack — live: 808 Drifter → User Library `Instruments/Instrument Rack/MCP RackTest.adg`
        (category/folder derived from rack_type); browser_path returned.
  - [x] rename_rack_macros — live: macro 1→"MCP One" color 5, macro 2→"MCP Two & Co" default 100;
        `&` XML-escape round-trips; unlisted macros preserved.
  - [x] set_rack_zones — live: chain 0 key→[24,96], velocity→[1,100]; file round-trips via inspect.
  - [x] load_preset (existing tool) — live: loaded MCP RackTest onto scratch MIDI track 3 first try
        (User Library already indexed). LOM `get_rack_macros` confirmed device "MCP RackTest" with
        "MCP One" / "MCP Two & Co"; full device chain intact. Scratch track + test preset cleaned up.
  - **Rack-type detection is POSITION-based** (earliest device tag = top-level rack's device): factory
    "drum kits" (e.g. Acuff Kit) are actually INSTRUMENT racks wrapping a nested Drum Rack (master-bus
    macros like "Master EQ"/"Master Comp") → correctly detected as `instrument`. A bare top-level
    DrumGroupDevice (only from saving a raw Drum Rack) detects as `drum`; its DrumBranchPreset pads
    carry direct-child key/vel zones (probe-confirmed), so `has_key_velocity=True` is correct.
  - **Phase B (macro→parameter MAPPINGS): save-diff experiment DONE 2026-05-29 → GO (cleanly patchable).**
    Encoding cracked: a mapping is a self-contained `<KeyMidi>` block injected into the TARGET PARAMETER
    (after its `<LomId>`), with `Channel=16` (macro sentinel), `IsNote=false`, `ControllerMapMode=0`,
    `Lower/UpperRangeNote=-1`, and **`NoteOrController` = the 0-based macro index** (Macro 1→0). NO ids
    (all AutomationTarget/ModulationTarget stay 0; factory non-zero ids are MacroSnapshots/preset-refs,
    unrelated). Confirmed: test Macro1→Gain gave NoteOrController=0; factory "Basic Bass Amp" — all 16
    mapped params carry Channel=16 KeyMidi w/ NoteOrController=macro index; many params can share a macro.
    Default full-range mapping needs NO range edit (param's MidiControllerRange unchanged). Custom/inverted
    ranges = deferred v2 (storage unconfirmed). See spec Section 3 "FINDINGS".
  - **`add_rack_macro_mappings` (Phase B v1): LIVE-VERIFIED 2026-05-29.** Tool + `patch_macro_mappings`
    in `rack_preset_utils.py` (depth-aware `_child_elements` scanner navigates branch→DevicePresets→
    AbletonDevicePreset→Device→device-element→param; injects KeyMidi after `<LomId>`; idempotent replace;
    many-to-one; bad chain/device/param rejected with available-tag listing). Plan:
    `docs/superpowers/plans/2026-05-29-rack-macro-mappings.md`. Offline 307/307.
    Live: cloned "Basic Bass Amp"→MCP MapVerify, mapped Macro 16→chain0/device0(Gate)/Attack via the util,
    loaded onto a scratch track → Live PARSED it cleanly AND `get_rack_macros` showed macro 16 auto-renamed
    "Attack" (Live auto-labels a single-mapped unnamed macro with its target = proof the mapping bound).
    Scratch track + preset cleaned up. Addresses params that are DIRECT children of a (non-rack) device;
    nested rack-in-rack params + custom ranges = future. Shipped as plugin v0.3.0.
