---
description: Best-practice workflow and tool sequence for establishing a NEW track in Ableton Live via the ableton MCP.
allowed-tools: ["Bash"]
---

# /ableton:new-track

Load this when the user wants to add a brand-new track (instrument or audio) and build it out. Follow this order; it encodes the non-obvious gotchas so the first attempt is the right one.

> If MCP tools aren't loaded yet, fetch them: `ToolSearch select:mcp__AbletonMCPMax__create_midi_track,mcp__AbletonMCPMax__set_track_name,mcp__AbletonMCPMax__load_instrument_or_effect,mcp__AbletonMCPMax__create_clip,mcp__AbletonMCPMax__add_notes_to_clip`

## 0. Read current state first

The open Live set changes between sessions — **never assume track 0** or any prior layout. Call `get_session_info` to see current track/scene counts, then decide where the new track goes.

## 1. Create the track

- MIDI (for instruments/synths/drums): `create_midi_track(index=-1)` — `-1` appends at the end; pass a specific index to insert.
- Audio (for recording/samples): `create_audio_track(index=-1)`.

Track creation is undoable but `undo` is **global** (it also undoes the user's hand-edits) — prefer `delete_track` to clean up a scratch track rather than `undo`.

## 2. Name it

`set_track_name(track_index, name)`. Do this right after creation while you know the index.

## 3. Load an instrument (MIDI tracks)

`load_instrument_or_effect(track_index, uri)`.

- **Critical: loading HOT-SWAPS / REPLACES** any instrument already on the track. On a fresh empty track this is fine; never load onto a track holding a patch you care about.
- To discover URIs, browse with `get_browser_tree` / `get_browser_items_at_path` (returns only DIRECT children — recurse to reach factory presets, which are all nested and carry `.adv`/`.adg` extensions). Or use `load_drum_kit` for a Drum Rack + samples.

## 4. Create a clip

`create_clip(track_index, clip_index, length=4.0)` — `clip_index` is the clip-slot (scene) row; `length` is in beats. Make sure a scene exists at that row (`create_scene` if needed).

## 5. Add MIDI notes — use the extended API only

`add_notes_to_clip(track_index, clip_index, notes)` where each note is a dict:
`{"pitch": 60, "start_time": 0.0, "duration": 1.0, "velocity": 100, "mute": false}`
(optional Live 11 fields: `probability`, `velocity_deviation`, `release_velocity`).

- **Never reach for legacy set_notes/remove_notes** — they pop a blocking modal in Live that stalls the Remote Script and times out the socket (the edit may apply but you get an error). The MCP only exposes the safe extended-API tools (`add_notes_to_clip`, `replace_clip_notes`, `modify_clip_notes`, `remove_clip_notes`) — use those.
- To rewrite a whole clip, `replace_clip_notes`. To tweak existing notes in place, `modify_clip_notes` by `note_id` (don't remove + re-add).

## 6. Verify

Read back what you wrote — `get_clip_notes(track_index, clip_index)` and `get_track_info(track_index)`. Don't trust a tool's own success string for state that Live applies asynchronously (see `/ableton:best-practices` on write-lag). Then `fire_clip` to audition if the user wants to hear it.

## Cleanup (scratch tracks)

`delete_track(track_index)` removes a regular track you added for testing — no need to ask the user to Cmd+Z.
