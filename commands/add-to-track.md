---
description: Best-practice workflow for modifying an EXISTING track in Ableton Live via the ableton MCP — re-read state, respect device-tool asymmetry, verify writes.
allowed-tools: ["Bash"]
---

# /ableton:add-to-track

Load this when the user wants to change something on a track that already exists — add clips/notes, load a device, tweak params, adjust the mixer, write automation. The recurring failure mode here is acting on stale assumptions, so the workflow front-loads reads.

> Load tools if deferred: `ToolSearch select:mcp__AbletonMCPMax__get_session_info,mcp__AbletonMCPMax__get_track_info,mcp__AbletonMCPMax__get_device_info`

## 1. Re-read state before touching anything

The Live set changes between sessions and even mid-session as the user works. **Do not assume a track index from earlier in the conversation.**

- `get_session_info` → current track/return/scene counts.
- `get_track_info(track_index)` → name, devices, clips, arm/mute/solo, routing for the target track.
- `get_device_info(track_index, ...)` / `get_rack_macros` / `get_rack_chains` to see what's already loaded.

Confirm you have the right track by name, not just index.

## 2. Know the device-tool asymmetry

- `get_device_parameters` / `set_device_parameter` are **regular-track-only** (no `track_type` arg) — you cannot read/write params on devices that live on return or master tracks (e.g. the A-Reverb / B-Delay on returns are out of reach for param edits).
- These DO accept a `track_type` and work on returns/master: `get_device_info`, `get_rack_macros`, `set_rack_macro`, `set_chain_property`, `set_device_on`, `delete_device`.
- Return/master/group tracks have **no `.arm`** and group tracks have no monitoring — don't assume every track exposes the same fields.

## 3. Make the change

- Notes: extended API only (`add_notes_to_clip` / `replace_clip_notes` / `modify_clip_notes` / `remove_clip_notes`) — never legacy set_notes (blocking modal → socket timeout).
- Devices: `load_instrument_or_effect` HOT-SWAPS the instrument slot — appending an effect is fine, but be deliberate about replacing instruments.
- Mixer: `set_mixer_property` (volume/pan/sends). Automation: `create_automation_envelope` / `set_automation` (note: `insert_step` writes FLAT segments; `duration=0` is a no-op — the server auto-tiles value-only points into a staircase; there are no linear ramps in the LOM).

## 4. Verify with a SEPARATE follow-up read

Song-level property writes **lag their own read-back** — a tool that sets `self._song.X` and returns it in the same task often returns the PRE-write value. The mutation is reliable; the returned confirmation dict is not. Always verify with a fresh, separate call:
- transport/record/loop/tempo changes → re-read via `get_transport`.
- structural changes → re-read via `get_session_info`.

After `undo` / `redo`, structural reads can be stale for **one** call — read structural state TWICE (the first `get_session_info` may show the pre-undo counts).

## 5. Undo caveat

`undo` is **global** — it undoes the user's manual edits too, not just MCP actions. Prefer targeted reversal (`delete_track`, `delete_device`, `delete_clip`, restore the old value) over `undo` unless the user explicitly wants a global step-back.

## Restoring values

If you changed a value just to test, restore the original you read in step 1. Record anything notable for the user.
