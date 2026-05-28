# Phase 11 — Capture & Recording (Design)

**Date:** 2026-05-27
**Status:** Live-verified 2026-05-27 (all 5 tools + 3 reads)

## Motivation
Capture/recording was the one feature set flagged feasible during the Phase 10 gap
audit but deferred by the user. This phase closes it. All five LOM calls are confirmed
present in Live 11 (`11.0.0.xml`, Song methods):

| Tool | LOM signature |
|------|---------------|
| `capture_midi` | `Song.capture_midi([Destination=CaptureDestination.auto])` |
| `capture_and_insert_scene` | `Song.capture_and_insert_scene([CaptureMode=CaptureMode.all])` |
| `trigger_session_record` | `Song.trigger_session_record([record_length=inf])` |
| `stop_all_clips` | `Song.stop_all_clips([Quantized=True])` and `Track.stop_all_clips([Quantized=True])` |
| `tap_tempo` | `Song.tap_tempo()` |

Read properties confirmed: `Song.can_capture_midi`, `Song.is_counting_in`,
`Song.session_record_status`.

## Tools (5, all song-level mutations)
- `capture_midi(destination="auto")` — destination "auto" | "session" | "arrangement".
- `capture_and_insert_scene(mode="all")` — mode "all" (only Live.Song.CaptureMode value).
- `trigger_session_record(record_length=None)` — optional fixed length in beats (>0);
  omit for Live's open-ended default. Arming auto-starts playback (Phase 5 finding).
- `stop_all_clips(track_index=None, quantized=True)` — omit `track_index` ⇒
  `Song.stop_all_clips` (whole set); provide ⇒ `Track.stop_all_clips` (one track).
- `tap_tempo()` — one tap.

Reads added to `get_transport` (try/except probed, like Phase 10): `can_capture_midi`,
`is_counting_in`, `session_record_status`.

## Enum handling (deliberate deviation from "send ints")
`CaptureDestination` (auto/session/arrangement) and `CaptureMode` (all) integer values
are NOT documented in the LOM. Rather than hardcode guessed ints, the server validates
the NAME (`transport_utils.resolve_capture_destination` / `resolve_capture_mode`, no int)
and sends the lowercase name; the Remote Script resolves it via
`getattr(Live.Song.CaptureDestination, name)` (the script already does `import Live`).
This keeps the enum source-of-truth in Live itself.

## transport_utils helpers (server-only, unit-tested)
- `resolve_capture_destination(value)` — None→"auto"; validates name; ValueError lists valid.
- `resolve_capture_mode(value)` — None→"all"; validates name.
- `coerce_record_length(value)` — None→None (omit); else float >0, else ValueError.
- `stop_all_clips` reuses `device_utils.coerce_on_value` (quantized) and
  `track_utils.coerce_track_index` (optional track_index).

## Live-behavior risks (verify, not blockers)
- Song-property-write lag (Phase 5/9) — confirm effects via SEPARATE follow-up reads
  (`get_transport`, `get_session_info`, `get_scenes`), never the returned dict.
- `capture_midi` needs recently-played audible MIDI material; `capture_and_insert_scene`
  needs currently-playing clips — check `can_capture_midi` first; neither does anything on
  an empty blank set.
- Arming session record auto-starts playback — stop + restore promptly.
- Capture creates clips/scenes — clean up (delete_scene / delete_clip / undo) after tests.

## Files
- `ableton_mcp_max/transport_utils.py` — 3 new helpers + name tuples.
- `ableton_mcp_max/server.py` — 5 `@mcp.tool()` defs; get_transport docstring.
- `remote_script/AbletonMCP/__init__.py` — mutation list +5; 5 dispatch branches;
  5 handlers; 3 reads in `_get_transport`.
- `tests/test_transport_utils.py` — +8 tests (offline suite 202 → 210).
