# ableton-mcp-max — Phase 8: Arrangement Authoring (Design)

**Created:** 2026-05-26
**Status:** Implemented + live-verified 2026-05-26 (see amendments below)

## Post-implementation amendments (driven by live LOM behavior)

- **`set_cue_point_name` DROPPED.** `CuePoint.name` is read-only in the Live 11
  LOM (assignment raises "can't set attribute"). Shipped tool count is **5, not 6**.
- **`create_cue_point` / `delete_cue_point` redesigned.** The one-handler
  move→toggle→restore below does NOT work: `current_song_time` writes are async
  and don't settle within a single `main_thread_task`, so `set_or_delete_cue()`
  fires at the stale playhead and toggles the wrong cue. They now orchestrate
  **separate** socket commands (read playhead → `set_song_position` → toggle at
  the settled playhead via `_create_cue_at_playhead`/`_delete_cue_at_playhead` →
  restore playhead). The remote handler names below (`_create_cue_point`,
  `_delete_cue_point`, `_set_cue_point_name`) were replaced accordingly.

The rest of the design (arrangement-clip tools, `arrangement_utils`) shipped as
written. Live results recorded in PROGRESS.md.

---

## Goal

Let Claude author the Arrangement timeline: create/delete/rename cue points
(locators), read the clips placed on each track's arrangement, commit a Session
clip onto the timeline at a given time, and delete an arrangement clip. Extends
Phase 5 (which gave cue-point *reads* + navigation and scene/transport control)
into cue-point and arrangement-clip *editing*.

## Architecture

Same two halves over localhost:9877 as all prior phases:
- `ableton_mcp_max/server.py` — new `@mcp.tool()`s. The server resolves/validates
  all names, indices, and times and sends already-resolved values downstream.
- `remote_script/AbletonMCP/__init__.py` — reads run inline in `_process_command`;
  mutations go in BOTH the `elif command_type in [...]` modifying list AND a branch
  in `main_thread_task`. The handler fetches live `Song` / `Track` / `Clip` /
  `CuePoint` objects and applies.
- `ableton_mcp_max/arrangement_utils.py` — new pure, unit-tested helper module
  (imported by server.py only; the Remote Script runs in Live's own interpreter and
  cannot import it). Mirrors the `transport_utils` / `scene_utils` split.

## The LOM primitives (these drive the design)

1. **Cue points are toggled at the playhead.** `Song.set_or_delete_cue()` takes NO
   time argument — it creates a cue at `Song.current_song_time` if none exists
   there, or deletes the one that does. There is no "create cue at arbitrary time"
   call. So create/delete both follow **move-playhead → toggle → restore-playhead**,
   with a pre-check of `Song.cue_points` to know whether the toggle will create or
   delete (and to avoid the footgun of toggling off an existing marker).
   - `Song.cue_points` → ordered list of `CuePoint`; each has `.time` (beats),
     `.name` (get/set → rename), `.jump()`.
   - `CuePoint` has **no delete method** — deletion is only via `set_or_delete_cue()`
     at the cue's time.
2. **Arrangement clips are a per-track list.** `Track.arrangement_clips` (Live 11.0+)
   → list of `Clip`s on that track's timeline. Each `Clip` exposes `name`,
   `start_time`, `end_time`, `length`, `is_midi_clip` / `is_audio_clip`.
3. **Placing a clip on the timeline:** `Track.duplicate_clip_to_arrangement(clip,
   destination_time)` → returns the new arrangement `Clip`. The source clip is taken
   from the **same track's Session slot** (`track.clip_slots[i].clip`).
4. **Deleting an arrangement clip:** `Track.delete_clip(clip)` (distinct from the
   Session-only `ClipSlot.delete_clip()`). Removes the given arrangement clip.

All of these go through `schedule_message` cleanly — none trigger the legacy
note-editing modal.

## Tool set (6)

### Cue points (locators)

#### 1. `create_cue_point` (write — main-thread mutation)
```
create_cue_point(time) -> str
```
- Server: `arrangement_utils.coerce_time(time)` (float ≥ 0).
- Handler: read `cue_points`; if one already exists at `time` (within a small
  epsilon), return `{created: false, reason: "exists", index, time}` WITHOUT
  toggling (never delete by accident). Otherwise save `current_song_time`, set
  `current_song_time = time`, call `set_or_delete_cue()`, restore the playhead, and
  return `{created: true, time}`.
- **Caveat:** Live quantizes cue placement to the current grid; the actual cue time
  may differ slightly from the requested `time`. Verify with a follow-up
  `get_cue_points` (per the project's return-value-lag gotcha).

#### 2. `delete_cue_point` (write — main-thread mutation)
```
delete_cue_point(index) -> str
```
- Server: `coerce_index(index)` (int ≥ 0).
- Handler: range-guard against `len(cue_points)`; capture the target cue's `.time`;
  save playhead, set `current_song_time` to that time, `set_or_delete_cue()` (which
  deletes the cue now under the playhead), restore playhead. Return `{deleted: true,
  index, time}`. Out-of-range → error `"Cue index out of range (0..N-1)"`.

#### 3. `set_cue_point_name` (write — main-thread mutation)
```
set_cue_point_name(index, name) -> str
```
- Handler: range-guard, `cue_points[index].name = name`, return `{index, name}`.

### Arrangement clips

#### 4. `get_arrangement_clips` (read — inline)
```
get_arrangement_clips(track_index) -> str
```
- Handler: range-guard track; iterate `track.arrangement_clips` → `[{index, name,
  start_time, end_time, length, is_midi_clip}, ...]`. Return `{track_index, count,
  clips: [...]}`. Tracks with no arrangement clips → `count: 0, clips: []`.

#### 5. `duplicate_clip_to_arrangement` (write — main-thread mutation)
```
duplicate_clip_to_arrangement(track_index, source_slot_index,
                              destination_time) -> str
```
- Server: `coerce_time(destination_time)` (≥ 0), `coerce_index(source_slot_index)`.
- Handler: range-guard track + slot; require `track.clip_slots[source_slot_index]
  .has_clip` (else error `"No clip in session slot N on track M"`); call
  `track.duplicate_clip_to_arrangement(slot.clip, destination_time)`. Return
  `{track_index, source_slot_index, destination_time, placed: true,
  new_clip: {name, start_time, end_time}}`.

#### 6. `delete_arrangement_clip` (write — main-thread mutation)
```
delete_arrangement_clip(track_index, clip_index) -> str
```
- Handler: range-guard track + `arrangement_clips[clip_index]`; capture name/time
  for the response; `track.delete_clip(arrangement_clips[clip_index])`. Return
  `{track_index, clip_index, deleted: true, name}`. Out-of-range → error.

`get_arrangement_clips` runs inline in `_process_command`; tools 1–3, 5, 6 are
added to the modifying-command list and given `main_thread_task` branches.

## `arrangement_utils.py` (pure, unit-tested)

- `coerce_time(t)` → float; raises `ValueError` on negative or non-numeric.
- `coerce_index(n)` → int; raises on negative or non-numeric.
- `cue_exists_at(cue_times, time, epsilon=1e-6)` → `(bool, index|None)`: whether a
  cue already sits at `time` within `epsilon` (server can pre-validate; the handler
  re-checks against live `cue_points` since the playhead-toggle is authoritative).

Index/range guards that need the *live* object counts (track count, slot count,
arrangement-clip count, cue count) stay in the handler — the server cannot know them
without a round-trip, consistent with how other mutation tools range-guard
server-side only where the count is already known.

## Testing

**Offline (`tests/test_arrangement_utils.py`):**
- `coerce_time`: valid float, int→float, zero ok, negative raises, non-numeric raises.
- `coerce_index`: valid, zero ok, negative raises, non-numeric raises.
- `cue_exists_at`: exact match, within-epsilon match, no match, empty list.

**Live smoke (recorded in PROGRESS.md), on a scratch arrangement:**
- `get_cue_points` baseline → `create_cue_point(time)` → `get_cue_points` shows the
  new locator (note any grid quantization of the time).
- `create_cue_point` at an existing cue's time → `created: false` (no accidental
  delete).
- `set_cue_point_name(index, "VERIFY")` → `get_cue_points` reflects the rename;
  restore original name.
- `delete_cue_point(index)` → `get_cue_points` count drops by one; playhead restored.
- `get_arrangement_clips(track)` baseline (likely empty on a fresh track).
- Put a clip in a Session slot, `duplicate_clip_to_arrangement(track, slot, time)` →
  `get_arrangement_clips` shows it at `start_time≈time`.
- `delete_arrangement_clip(track, 0)` → `get_arrangement_clips` count back to baseline.
- Negative cases: `delete_cue_point` out-of-range, `duplicate_clip_to_arrangement`
  from an empty slot, `delete_arrangement_clip` out-of-range — all clean errors, no
  mutation.
- Restore the set (delete any cues/clips created; the project set changes between
  sessions, so re-read state, don't assume track 0).

## Flagged unknowns — verify live, do not assume

- **Cue-time quantization:** does `set_or_delete_cue()` place the marker exactly at
  `current_song_time`, or snap to the grid? Capture the actual `.time` afterward.
- **Playhead-restore vs. transport state:** confirm moving `current_song_time` to
  toggle a cue and back does not start playback or leave the playhead displaced
  (per Phase 5, song-position writes are reliable but read-back lags — verify with a
  separate `get_transport`).
- **`duplicate_clip_to_arrangement` return:** confirm it returns the new `Clip` (so we
  can echo its `start_time`) and that `destination_time` is in beats.
- **`delete_clip(clip)` on a stale handle:** confirm deleting re-indexes
  `arrangement_clips` (delete index 0, the rest shift down) so callers re-read.
- **Empty `arrangement_clips`** shape on a track that has never had timeline clips.

## Out of scope (Phase 8)

- Arrangement time-signature / tempo markers (no clean Live 11 LOM write path).
- Creating empty clips directly in the arrangement (LOM only duplicates an existing
  Session clip onto the timeline).
- Duplicating an *existing arrangement* clip to a new time (source is Session-slot
  only this phase; revisit if needed).
- Moving/resizing arrangement clips after placement (clip `start_time`/`end_time` are
  read-only on arrangement clips in Live 11).
- Audio-file import to the arrangement.
