---
layout: default
title: Tools
nav_order: 2
has_children: true
---

# Tool Reference

All **182 tools** exposed by the `ableton` MCP, grouped by area. Pick a category:

## [Session & View](./session-view.html)

Read the live set, move the selection, and steer what Live shows on screen.

`get_session_info`, `get_view_selection`, `set_selected_track`, `set_selected_scene`, `set_detail_clip`, `set_highlighted_clip_slot`

## [Tracks](./tracks.html)

Create, name, fold, duplicate, and delete tracks - plus global undo/redo.

`get_track_info`, `set_track_name`, `set_track_fold`, `create_midi_track`, `create_audio_track`, `create_return_track`, `delete_track`, `delete_return_track`, `duplicate_track`, `undo`, `redo`

## [Clips](./clips.html)

Create and manage session clips: properties, loop, quantize, launch, and stop.

`create_clip`, `set_clip_name`, `get_clip_info`, `set_clip_property`, `set_clip_loop`, `quantize_clip`, `duplicate_clip`, `delete_clip`, `fire_clip`, `stop_clip`, `set_clip_trigger_quantization`

## [MIDI Notes](./midi-notes.html)

Read and edit notes inside MIDI clips via the Live 11 extended note API.

`add_notes_to_clip`, `get_clip_notes`, `replace_clip_notes`, `remove_clip_notes`, `modify_clip_notes`

## [Devices & Racks](./devices-racks.html)

Inspect and drive devices, rack macros, and chains; load instruments and effects.

`get_device_parameters`, `set_device_parameter`, `get_device_info`, `delete_device`, `set_device_on`, `get_rack_macros`, `set_rack_macro`, `get_rack_chains`, `set_chain_property`, `load_instrument_or_effect`

## [Plugins (VST/AU)](./plugins.html)

Expose and control third-party VST3/AU plugin parameters via the Configure-slot backdoor: probe a plugin's full parameter list, then Configure a curated param-map pack so its knobs become settable, automatable LOM parameters. For Serum 2, also author the FX racks (read, set params, bypass, insert, remove, reorder) and synthesize a full instrument patch from scratch - oscillators (params, mode, wavetable), filters, envelopes, LFOs, macros, and the mod matrix - by patching the plugin-state blob in the .als and reloading in place.

`probe_plugin_parameters`, `expose_plugin_parameters`, `get_serum_fx`, `set_serum_fx_param`, `insert_serum_fx`, `remove_serum_fx`, `reorder_serum_fx`, `get_serum_patch`, `set_serum_oscillator`, `set_serum_filter`, `set_serum_envelope`, `set_serum_lfo`, `set_serum_macro`, `set_serum_wavetable`, `add_serum_mod_route`, `clear_serum_mod_route`, `create_serum_patch`

## [Mastering (Ozone)](./mastering-ozone.html)

Module-aware control of an iZotope Ozone 12 instance on the master track. Ozone exposes 873 host params but Ableton Configures at most 128 at once, so expose a chosen module's params into the Configure slots (patching the .als and reloading in place), then read/set them per module: EQ bands, Maximizer, Dynamics bands, and any module's params or bypass.

`get_ozone_modules`, `expose_ozone_modules`, `get_ozone_module`, `set_ozone_module_param`, `set_ozone_module_enabled`, `set_ozone_eq_band`, `set_ozone_maximizer`, `set_ozone_dynamics_band`, `get_ozone_state`, `set_ozone_state`

## [Mixer & Routing](./mixer-routing.html)

Volume, pan, sends, and input/output routing for every track type.

`get_mixer`, `set_mixer_property`, `get_routing`, `set_routing`

## [Scenes](./scenes.html)

Create, launch, rename, and capture scenes in the Session view.

`get_scenes`, `fire_scene`, `create_scene`, `delete_scene`, `duplicate_scene`, `set_scene_name`, `set_scene_property`, `capture_and_insert_scene`

## [Transport & Playback](./transport.html)

Tempo, groove, metronome, recording, punch, and the playhead.

`set_tempo`, `start_playback`, `stop_playback`, `continue_playback`, `get_transport`, `set_groove_amount`, `set_swing_amount`, `get_groove_pool`, `assign_groove_to_clip`, `load_groove_to_pool`, `search_grooves`, `set_midi_recording_quantization`, `set_nudge`, `capture_midi`, `trigger_session_record`, `stop_all_clips`, `tap_tempo`, `set_metronome`, `set_arrangement_record`, `set_session_record`, `set_punch`, `set_song_position`, `jump_by`

## [Arrangement & Cues](./arrangement.html)

Cue points, the arrangement loop, and arrangement-timeline clips.

`get_cue_points`, `create_cue_point`, `delete_cue_point`, `jump_to_cue`, `set_arrangement_loop`, `back_to_arrangement`, `get_arrangement_clips`, `duplicate_clip_to_arrangement`, `delete_arrangement_clip`

## [Arrangement Structure](./arrangement-structure.html)

Read the structural layout of the arrangement (section map from cue points or clip inference) and build multi-section arrangements from section definitions.

`get_arrangement_structure`, `build_arrangement`

## [Automation](./automation.html)

Read and write clip automation envelopes for any automatable parameter.

`get_automation`, `set_automation`, `create_automation_envelope`, `clear_automation`, `clear_all_automation`, `re_enable_automation`

## [Browser & Presets](./browser-presets.html)

Walk the browser, load presets and drum kits, and generate presets via the preset-XML backdoor.

`get_browser_tree`, `get_browser_items_at_path`, `load_drum_kit`, `list_device_presets`, `load_preset`, `list_wavetable_tables`, `create_wavetable_preset`, `create_simpler_instrument`, `inspect_rack_preset`, `clone_rack`, `rename_rack_macros`, `set_rack_zones`, `add_rack_macro_mappings`

## [Listeners](./listeners.html)

Subscribe to real-time Live Object Model changes and poll for events.

`register_listener`, `poll_changes`, `unregister_listener`, `list_listeners`

## [Batch & Transactions](./batch.html)

Collapse several mutations into a single atomic Live task / socket round-trip.

`batch`

## [Host Lifecycle](./host.html)

Save the set and gracefully quit/relaunch Ableton Live (no crash-recovery prompt) for an automated bounce after a Remote Script change.

`restart_live`, `save_set`, `save_set_as`

## [Analysis](./analysis.html)

Inspect the open set against best-practice rulesets and surface findings by domain.

`analyze_set`, `check_clipping`, `detect_key`

## [Metering (Audio Tap)](./metering.html)

Per-track and master loudness/true-peak/spectrum/stereo from the MCP Tap Max-for-Live devices, plus cross-track mix analysis.

`get_audio_tap_status`, `list_taps`, `reset_meter`, `read_meter`, `read_track_meter`, `measure_loudness`, `measure_mix`, `deploy_taps`, `remove_taps`

## [Composition](./composition.html)

Generate musical material into clip slots (chords, bass, melody, drums) and transform existing clips (humanize, swing, quantize-to-scale, arpeggiate, harmonize). Key/scale read from the set when not given.

`generate_chord_progression`, `generate_bassline`, `generate_melody`, `generate_drum_pattern`, `humanize_clip`, `swing_clip`, `quantize_clip_to_scale`, `arpeggiate_clip`, `harmonize_clip`, `set_song_scale`, `set_arrangement_automation`

## [Remediation](./remediation.html)

Translate analysis findings into applied mix corrections: shift faders by dB, auto-stage a track to a target LUFS via its MCP Tap, balance all tapped tracks in one coherent pass, and execute a structured correction plan from analyze_set findings.

`adjust_track_gain`, `gain_stage_track`, `balance_mix`, `apply_findings`

## [Samples](./samples.html)

Discover audio samples in Live's User Library and factory packs and load them as audio clips, single drum-rack pads, or full drum kits: search by name with automatic loop/one-shot/kit/instrument classification, and load with transparent iCloud materialization. Also includes stem separation - split a full mix into instrument stems and lay them onto the Arrangement timeline.

`search_samples`, `load_audio_clip`, `load_sample_to_drum_pad`, `populate_drum_rack`, `separate_stems_to_arrangement`

## [Catalog](./catalog.html)

Persistent local index of Serum presets, samples, grooves, and device presets, with similarity search and reuse-vs-create recommendation that can orchestrate the existing create tools.

`search_catalog`, `find_similar`, `catalog_stats`, `reindex_catalog`, `recommend_asset`, `recommend_instrument`, `create_from_plan`

