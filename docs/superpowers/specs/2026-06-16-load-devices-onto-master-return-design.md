# Load effects onto master/return tracks

**Created:** 2026-06-16
**Status:** Design approved (feasibility-gated by live verification)

## Summary

Let `load_instrument_or_effect` and `load_preset` load an audio effect onto a
**return** or **master** track via a `track_type` argument, matching the
convention used elsewhere. This is gap "C" from the master/return initiative,
pulled forward at the user's request and landed on the same branch as the
device-parameter access work (`feat/master-return-device-params`).

## Motivation

The mixing/mastering automation goal needs the agent to place a limiter/EQ on
the master bus and effects on returns. Today the load tools are regular-track
only. Investigation shows the load path already supports the mechanism:
`_load_browser_item` selects the target track (`song.view.selected_track = track`)
then calls `app.browser.load_item(item)`, and `_set_selected_track` already
selects return/master tracks. The handler simply hardcodes
`self._song.tracks[track_index]`.

## Feasibility gate

The LOM doc for `Browser.load_item(item)` says only "Loads the provided browser
item" — it loads onto the current selection/hotswap target and does not document
any master/return restriction. Live's UI allows dragging audio effects onto
returns and the master. The remaining unknown is whether `load_item` honors a
return/master selection programmatically. **This is settled by live verification
in this work; if `load_item` refuses a return/master target, STOP and reassess —
do NOT add a silent holder-track + copy workaround** (the LOM has no
device-copy-between-tracks API anyway).

## Scope

**In scope:**
- `load_instrument_or_effect` accepts `track_type` ('regular'|'return'|'master').
- `load_preset` accepts `track_type`.
- `_load_browser_item` resolves the target track via `_resolve_track`.

**Out of scope:**
- `load_drum_kit` — drum kits are instruments; return/master are audio-only.
  Stays regular-only (no `track_type`).
- Instrument-vs-effect validation — loading an instrument onto an audio-only
  track is user error; let Live handle it. Documented, not guarded (a guard
  would require browser-item type detection — YAGNI).

## Design

### Change points

**1. Remote Script — `remote_script/AbletonMCP/__init__.py`:**
- `_load_browser_item(self, track_index, item_uri, track_type="regular")` —
  replace the hardcoded bounds check + `track = self._song.tracks[track_index]`
  with `track = self._resolve_track(track_index, track_type)`. Add
  `"track_type": track_type` to the returned dict.
- Dispatch site (`elif command_type == "load_browser_item":`) — read
  `track_type = params.get("track_type", "regular")` and pass it.
- `load_browser_item` is already in the mutation membership list — no change.

**2. Server — `ableton_mcp_max/server.py`:**
- `load_instrument_or_effect(ctx, track_index, uri, track_type="regular")` —
  forward `track_type` in the `load_browser_item` payload. Docstring documents
  `track_type` and notes only audio effects are valid on return/master.
- `load_preset(ctx, track_index, path, name=None, track_type="regular")` —
  forward `track_type` in the `load_browser_item` payload. Same docstring note.
- `load_drum_kit` unchanged.

**3. Docs:** regenerate the tool index (signature change only; no count change).

### Behavior & interface

- `track_type` default `"regular"` — fully backward-compatible.
- Master ignores `track_index` (pass `0`).
- Loading an audio effect onto a return/master APPENDS (effects append; this is
  Live's normal behavior).

### Error handling

- `_resolve_track` already raises `ValueError` (unknown type) / `IndexError`
  (out-of-range return index).
- If `load_item` fails or no device appears on a return/master, that surfaces in
  live verification — treat as the feasibility gate, not a code bug to paper over.

## Testing

**Offline (pytest):**
- Server-side payload tests: `load_instrument_or_effect` and `load_preset`
  forward `track_type` into the `load_browser_item` command (mock the
  connection). `load_preset` test must stub the `get_browser_presets` pre-fetch
  so URI resolution runs, then assert the load payload carries `track_type`.
- Default `track_type="regular"` preserves the existing payload shape.
- `py_compile` the Remote Script; import the server.

**Live verify (this Live session, after reinstall + bounce already done in the
sibling work):**
- Load an audio effect (e.g. EQ Eight) onto **Return A** via
  `load_instrument_or_effect(track_index=<return idx>, uri=..., track_type="return")`;
  confirm via `get_device_info`/`get_track_info` that the device appears on that
  return. Delete it after (`delete_device` with `track_type="return"`).
- Load an audio effect onto the **Master** via `track_type="master"`; confirm it
  appears; then this device also unblocks the gap #0 master device-parameter
  verification (read/write/restore a param), after which delete it.
- Confirm a regular-track load still works with no `track_type`.
- Record results in PROGRESS.md.

## Files to modify

- `remote_script/AbletonMCP/__init__.py` — `_load_browser_item` + dispatch.
- `ableton_mcp_max/server.py` — `load_instrument_or_effect`, `load_preset`.
- `tests/` — server-side payload tests.
- Generated docs under `docs/tools/` (+ `commands/tool-index.md` if changed).
- `PROGRESS.md` — live-verification record.
