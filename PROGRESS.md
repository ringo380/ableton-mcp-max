# ableton-mcp-max — Progress

**Current focus:** Phase 0 + Phase 1 code complete & deployed; pending live verification after a Live + Claude Code restart.
**Next action:** Run the live smoke tests (parity + parameter read/set on Wavetable). Then plan Phase 2 (Mixer & Routing).

## Phases
| Phase | Title | Status | Completed |
|-------|-------|--------|-----------|
| 0 | Foundation (fork + parity + install) | Code done; live verify pending | |
| 1 | Device & Parameter Control | Code done; live verify pending | |
| 2 | Mixer & Routing | Not started | |
| 3 | Clip & MIDI Editing | Not started | |
| 4 | Devices & Racks | Not started | |
| 5 | Scenes, Transport, Arrangement | Not started | |
| 6 | Automation Envelopes | Not started | |
| 7 | Change Listeners (stretch) | Not started | |

## Phase 0 tools (parity, vendored) — live-verify after restart
- [ ] get_session_info, get_track_info, create_midi_track, set_track_name,
      create_clip, add_notes_to_clip, set_clip_name, set_tempo, fire_clip,
      stop_clip, start_playback, stop_playback, load_instrument_or_effect,
      get_browser_tree, get_browser_items_at_path, load_drum_kit

## Phase 1 tools
- [x] param_utils.resolve_parameter_index (offline unit tests: 6/6 pass)
- [ ] get_device_parameters (live verify pending)
- [ ] set_device_parameter (live verify pending)

## Deployment state
- MCP server registered as **AbletonMCPMax** for project `abletonwork`
  (`uv run --directory ~/git/ableton-mcp-max ableton-mcp-max`); old `AbletonMCP`
  (uvx ahujasid) removed from that project.
- Remote Script installed at
  `/Applications/Ableton Live 11 Suite.app/Contents/App-Resources/MIDI Remote Scripts/AbletonMCP/`
  (original ahujasid script backed up to `AbletonMCP.bak.*` alongside it).
- Requires: quit+reopen Live (load new handlers), restart Claude Code (load new tools).

## Device parameter reachability notes
- Wavetable: (fill in from live Task 1.5 — which controls are settable vs. menu-only)
