# Phase 11 — Capture & Recording (Plan)

**Date:** 2026-05-27
**Status:** Live-verified 2026-05-27; ready to PR

Design: `docs/superpowers/specs/2026-05-27-phase-11-capture-recording-design.md`.

## Steps
1. **transport_utils.py** — add `CAPTURE_DESTINATION_NAMES`, `CAPTURE_MODE_NAMES`,
   `resolve_capture_destination`, `resolve_capture_mode`, `coerce_record_length`.
   [done]
2. **tests/test_transport_utils.py** — +8 tests (resolvers default/names/bad, record
   length passthrough/positive/non-positive/non-numeric). Offline suite 202 → 210. [done]
3. **server.py** — import the 3 helpers; add 5 `@mcp.tool()` (`capture_midi`,
   `capture_and_insert_scene`, `trigger_session_record`, `stop_all_clips`, `tap_tempo`);
   extend `get_transport` docstring. `Optional` added to typing import for
   `stop_all_clips(track_index=None)`. [done]
4. **remote_script/__init__.py** — 5 names into the mutation list; 5 dispatch branches in
   `main_thread_task`; 5 handler methods (`_capture_midi`/`_capture_and_insert_scene`
   resolve names via `getattr(Live.Song.Capture*)`; `_trigger_session_record` optional
   float; `_stop_all_clips` song-vs-track with range guard; `_tap_tempo`); 3 reads into the
   `_get_transport` getattr loop. [done]

## Offline gate [done]
- `uv run --with pytest pytest -q` → 210 passed.
- `uv run python -c "import ableton_mcp_max.server"` → OK.
- `uv run python -m py_compile remote_script/AbletonMCP/__init__.py` → OK.

## Deploy + live verify [pending — needs Live + Claude Code restart]
1. `bash scripts/install_remote_script.sh`; quit+reopen Live (load handlers); restart
   Claude Code (load new MCP tools — arrive deferred, load via ToolSearch).
2. Verify against the open set (restore changes; record in PROGRESS.md):
   - `get_transport` → new can_capture_midi / is_counting_in / session_record_status keys.
   - `tap_tempo` → tempo changes (read via get_transport).
   - `stop_all_clips` song-level (fire a clip, stop-all) then track-scoped (`track_index`).
   - `trigger_session_record(record_length=4)` on an armed track → records, then stop; clean.
   - `capture_midi` / `capture_and_insert_scene` with user playing/holding MIDI (check
     `can_capture_midi` first); delete captured clip/scene after.
   - Negatives: bad destination/mode name (server ValueError), record_length<=0,
     stop_all_clips track_index out of range (handler-side).

## Ship [pending]
- branch `phase-11-capture-recording` → PR → `gh pr merge --squash --delete-branch` →
  `git remote prune origin` (gh login `ringo380`).
