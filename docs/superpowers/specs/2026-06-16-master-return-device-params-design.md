# Master/return device-parameter access

**Created:** 2026-06-16
**Status:** Design approved

## Summary

Make `get_device_parameters` and `set_device_parameter` reach devices on
**return** and **master** tracks, matching the `track_type` convention already
used by `get_device_info`, `set_device_on`, `delete_device`, and
`set_chain_property`.

Today both tools are regular-track-only: they hardcode
`self._song.tracks[track_index]` in the Remote Script, so a master limiter, a
master EQ band, or a return reverb's parameters cannot be read or written. This
is the foundational gap blocking mastering automation and the planned
analyze -> suggest -> act remediation loop.

This is sub-project #0 of a larger initiative (autonomous track production +
closed-loop analysis/remediation). It is deliberately the smallest, lowest-risk
piece: a proven-feasible plumbing change, fully backward-compatible.

## Motivation

`track.devices[i].parameters` works identically for regular, return, and master
tracks in the LOM, so this is a tool-design gap, not a LOM limitation. The
Remote Script already has the resolution helpers needed
(`_resolve_track(track_index, track_type)` and
`_resolve_device(track_index, device_index, track_type)`); the two
device-parameter handlers simply do not use them.

## Scope

**In scope (Scope A):**
- `get_device_parameters` accepts `track_type`.
- `set_device_parameter` accepts `track_type`.

**Out of scope (separate, later specs):**
- (B) Master/return automation envelopes (`get_automation` / `set_automation`
  targeting master/return mixer volume + device params).
- (C) Loading devices onto master/return (`load_instrument_or_effect` etc.) -
  has real LOM feasibility risk (may require a holder-track + copy workaround);
  feasibility-gated into its own spec.

## Design

### Change points (3 files)

**1. Remote Script - `remote_script/AbletonMCP/__init__.py`** (the only
behavioral change; requires reinstall + Live bounce to load):

- `_get_device_parameters(self, track_index, device_index, track_type="regular")`
  - Replace the hardcoded `track = self._song.tracks[track_index]` +
    inline bounds check with the existing
    `track, device = self._resolve_device(track_index, device_index, track_type)`.
  - Add `"track_type": track_type` to the returned dict (as `_get_device_info`
    already does).
- `_set_device_parameter(self, track_index, device_index, parameter_index, value, track_type="regular")`
  - Same swap to `_resolve_device`.
  - Keep the existing `is_enabled` guard ("Parameter '%s' is not settable
    (disabled)") and the min/max clamp unchanged - they now apply to
    master/return devices too.
- Dispatch sites:
  - `get_device_parameters` (inline read branch, ~line 729): read
    `track_type = params.get("track_type", "regular")` and pass to the handler.
  - `set_device_parameter` (mutation branch / `main_thread_task`, ~line 279):
    read `track_type` and pass to the handler. The command already routes
    through `main_thread_task`; only the param is added.

**2. Server - `ableton_mcp_max/server.py`:**

- `get_device_parameters(ctx, track_index, device_index, track_type="regular")`
  - Forward `track_type` in the command payload.
  - Docstring: drop the "REGULAR tracks only" warning; document
    `track_type: 'regular' (default), 'return', or 'master'`.
- `set_device_parameter(ctx, track_index, device_index, parameter, value, track_type="regular")`
  - Forward `track_type` in the command payload.
  - **The internal pre-fetch** `get_device_parameters` call (used to resolve a
    parameter name -> index via `resolve_parameter_index`) **must also pass
    `track_type`**, or name resolution reads the wrong track's device.
  - Docstring: drop the "REGULAR tracks only" warning; document `track_type`.

**3. Docs:**

- Regenerate the tool index (`scripts/build_tool_index.py` /
  `scripts/gen_docs_site.py`) so the updated signatures appear.
- No new tools -> no hand-edited counts change (the `docs/index.md` hero
  counts stay the same).

### Behavior & interface

- `track_type` is the standard string enum `'regular' | 'return' | 'master'`,
  default `"regular"`.
- **Fully backward-compatible:** existing calls without `track_type` behave
  exactly as before.
- Master ignores `track_index` (single track); pass `0` by convention, matching
  the other `track_type`-aware tools.
- Returns stay through `_ok` / `_err`. No uniform-envelope changes.

### Error handling

- `_resolve_track` already raises `ValueError` for an unknown `track_type` and
  `IndexError` for an out-of-range return index - reused as-is.
- Embedded-Python gotcha: some params on master/return devices may report
  `is_enabled=False`; the existing "not settable (disabled)" guard in
  `_set_device_parameter` already covers this and now applies to master/return.

## Testing

**Offline (pytest + py_compile + server import):**
- Resolution logic lives in the Remote Script and cannot be imported in pytest,
  so unit coverage is server-side: assert both tools place `track_type` into the
  command payload (mock the connection), including the **pre-fetch** call inside
  `set_device_parameter`.
- Confirm default `track_type="regular"` preserves the existing payload shape.
- `uv run python -m py_compile remote_script/AbletonMCP/__init__.py` and
  `uv run python -c "import ableton_mcp_max.server"` stay clean; Remote Script
  stays Py2/3.7-safe.

**Live verify (requires `bash scripts/install_remote_script.sh` + Live bounce):**
- Read params of a device on **Return A** (e.g. the factory reverb), write one
  parameter, read back via a **separate** call (per the song/property write-lag
  note), restore the original value.
- Repeat for a device on the **master** track.
- Record results in PROGRESS.md.

## Files to modify

- `remote_script/AbletonMCP/__init__.py` - handlers + dispatch (behavioral).
- `ableton_mcp_max/server.py` - two tools + docstrings.
- Generated docs under `docs/tools/` + `commands/tool-index.md` (regen).
- `tests/` - server-side payload tests for `track_type` pass-through.
- `PROGRESS.md` - live-verification record.

## Restart protocol for this change

Both halves change, so: edit both -> `bash scripts/install_remote_script.sh`
-> one Live bounce (quit + reopen, or `restart_live`) -> one Claude Code restart
(server.py edit). New behavior is on existing tools, so no deferred-tool reload.
