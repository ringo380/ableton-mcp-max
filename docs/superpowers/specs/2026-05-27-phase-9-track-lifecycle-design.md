# Phase 9 — Track Lifecycle & Undo/Redo — Design

**Created**: 2026-05-27
**Status**: Approved (design); awaiting implementation plan

## Overview

Closes the project's most-cited workflow gap: there is no way to delete a track via
MCP, so scratch tracks created during live tests accumulate and must be removed by the
user with Cmd+Z. Phase 9 adds track create/delete/duplicate for both regular and return
tracks, plus global undo/redo. Every tool maps 1:1 to a confirmed Live 11 LOM call.

LOM feasibility confirmed against `https://nsuspray.github.io/Live_API_Doc/11.0.0.xml`:
- `Song.create_audio_track(index=None)` → Track (`-1` = append at end; missing = after last selected)
- `Song.create_midi_track(index=None)` → Track (**already shipped** — index arg present)
- `Song.create_return_track()` → Track (end only, no index)
- `Song.delete_track(index)` → None (raises if index absent)
- `Song.delete_return_track(index)` → None (raises if index absent)
- `Song.duplicate_track(index)` → None (duplicates + **selects** the new track)
- `Song.undo()` / `Song.redo()` → None; `Song.can_undo` / `Song.can_redo` read properties

## Scope

In scope:
- 7 net-new tools (below) + parity verification of the existing `create_midi_track`.

Decided during brainstorming:
- **Separate tools per track type** (1:1 with the LOM), not unified `create_track`/`delete_track`
  with a `track_type` arg.
- **`create_midi_track` extension already satisfied** — it already accepts `index=-1` and the
  handler is fully wired; this phase only verifies parity, no code change expected.
- **`undo`/`redo` guarded with a `can_undo`/`can_redo` precheck** — no MCP-action counter.

Out of scope (explicitly deferred):
- Song-property bonuses (`clip_trigger_quantization`, `midi_recording_quantization`,
  `swing_amount`, `groove_amount`, `capture_midi`, `tap_tempo`, `nudge_up/down`).
- Track grouping/folding, freeze/flatten/consolidate (no confirmed LOM write path).
- Scoping undo to MCP-issued actions only (Live coalesces/splits undo steps unpredictably;
  brittle — explicitly rejected).

## Tools

| Tool | LOM call | Args | Returns |
|------|----------|------|---------|
| `create_audio_track` | `Song.create_audio_track(index)` | `index=-1` (-1 = end) | `{index, name}` |
| `create_return_track` | `Song.create_return_track()` | none | `{index, name}` |
| `delete_track` | `Song.delete_track(index)` | `index` | `{deleted, remaining_count}` |
| `delete_return_track` | `Song.delete_return_track(index)` | `index` | `{deleted, remaining_count}` |
| `duplicate_track` | `Song.duplicate_track(index)` | `index` | `{new_index, name}` |
| `undo` | `Song.undo()` | none | `{undone, can_undo, can_redo}` |
| `redo` | `Song.redo()` | none | `{redone, can_undo, can_redo}` |
| `create_midi_track` | *(already shipped)* | `index=-1` | verify index parity only |

`create_audio_track` is referenced in a server.py list (~line 158) but has **no server tool
and no remote handler** — it is net-new work, not a partial.

## Components

### `track_utils.py` (server-only pure helper, unit-tested)
Follows the established pattern: resolve/validate/clamp on the server, send already-clean
ints to the Remote Script handler (the handler runs in Live's own Python and cannot import
these helpers).

- `coerce_create_index(value)` → int. Accepts `None`/`-1` (append) or `>= 0`; rejects `< -1`
  and non-integers with a clear `ValueError`.
- `coerce_track_index(value)` → int `>= 0` for delete/duplicate; rejects negatives/non-ints.

Offline unit tests added to the suite (currently 172 passing).

### `server.py` tools
Seven `@mcp.tool()` functions, each: coerce args via `track_utils`, `send_command(...)`,
return a short human-readable string built from the handler's result dict (matching the
existing tool style). `create_midi_track` is left unchanged pending parity verification.

### Remote Script (`remote_script/AbletonMCP/__init__.py`)
All 7 are **mutations** → each added to BOTH the `elif command_type in [...]` dispatch list
AND a branch in `main_thread_task` (LOM track create/delete and undo/redo must run on the
main thread).

- **Creates** return the new `Track` directly from the LOM call, so `name` reads cleanly
  in-task. Index = `len(self._song.tracks) - 1` for append, else the passed index; return
  tracks use `self._song.return_tracks`. Wrap in try/except to catch Live's *limitation
  error* and re-raise as a clean "Live track limit reached" message.
- **Deletes** call the LOM by index, then return `len(...)` of the remaining collection as
  `remaining_count`.
- **`duplicate_track`** returns `None` from the LOM but selects the new track → read
  `self._song.view.selected_track` to derive `new_index` (its position in `song.tracks`)
  and `name`.
- **`undo`/`redo`** precheck `self._song.can_undo` / `can_redo`. If false, return
  `{undone: false, reason: "nothing to undo"}` (or `redone`) with **no** LOM call. If true,
  call it, then return fresh `can_undo`/`can_redo`.

## Data flow

1. Claude calls e.g. `delete_track(index=5)`.
2. server.py `coerce_track_index(5)` → `5`; `send_command("delete_track", {"index": 5})`.
3. Remote Script: command in mutation list → scheduled on main thread → `main_thread_task`
   branch validates `0 <= index < len(tracks)`, calls `self._song.delete_track(5)`, returns
   `{"deleted": true, "remaining_count": len(self._song.tracks)}`.
4. server.py formats `"Deleted track 5; 7 tracks remaining"`.

## Error handling

- Index out of range (delete/duplicate): pre-read the current count in the handler and reject
  cleanly with the existing "out of range (0..N)" style — no Live mutation. (Belt-and-braces:
  also catch the LOM's own raise.)
- Track-count limitation on create: catch Live's limitation/RuntimeError → clean message.
- `delete`/`duplicate` on non-existent index: clean rejection, no mutation.
- `undo`/`redo` on empty stack: precheck returns `{undone: false, reason: "nothing to undo"}`.

## Known caveats (carried from prior phases)

- **Index churn:** delete/duplicate re-index the collection (same as `delete_scene` /
  `delete_arrangement_clip`). Return the fresh count; advise re-reading `get_session_info`.
- **`undo` is global:** docstring must state it walks Live's entire undo stack (including
  user hand-edits). The `can_undo` precheck only prevents erroring on an empty stack — it
  does NOT scope undo to MCP-issued actions.
- **Self-cleanup win:** `delete_track` finally lets live tests remove scratch tracks rather
  than leaving them for user Cmd+Z (resolves a standing note in CLAUDE.md / PROGRESS.md).
- **Return-value lag:** track creates return the Track object directly, so in-task name reads
  are reliable (unlike song-property writes). `duplicate_track`'s `selected_track` read is
  in-task and expected reliable, but live verification will confirm.

## Testing

- **Offline:** `track_utils` unit tests; `uv run python -c "import ableton_mcp_max.server"`;
  `uv run python -m py_compile remote_script/AbletonMCP/__init__.py`.
- **Live (after `install_remote_script.sh` + quit/reopen Live + restart Claude Code):**
  - create audio + return track → verify count++ and returned name
  - duplicate a track → new selected track index + name
  - delete regular + return track → count--
  - undo/redo round-trip on a create (create → undo removes it → redo restores)
  - negatives: bad index on delete/duplicate; undo on an empty stack
  - clean up any scratch tracks via the new `delete_track` (dogfood the self-cleanup win)
- Record results in PROGRESS.md.

## Restart protocol

Both halves change → ONE `bash scripts/install_remote_script.sh` + ONE quit/reopen Live +
ONE Claude Code restart. New tools arrive as deferred tools → load via
`ToolSearch select:mcp__AbletonMCPMax__<name>`.
