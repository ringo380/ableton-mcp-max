# Phase 8: Arrangement Authoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 6 MCP tools to author the Ableton Arrangement timeline — create/delete/rename cue points and read/place/delete arrangement clips.

**Architecture:** The established two halves over localhost:9877 — `ableton_mcp_max/server.py` (`@mcp.tool()`s that coerce/validate and send resolved values) ↔ `remote_script/AbletonMCP/__init__.py` (handlers that apply against live `Song`/`Track`/`Clip`/`CuePoint`). A new pure `ableton_mcp_max/arrangement_utils.py` (server-only, unit-tested) holds time/index coercion. Cue create/delete use the playhead move→`set_or_delete_cue()`→restore pattern (the only LOM path).

**Tech Stack:** Python (server: modern CPython via `uv`; Remote Script: Live's embedded 3.7-era interpreter — `%`-formatting only, no f-strings). pytest for offline tests.

**Spec:** `docs/superpowers/specs/2026-05-26-phase-8-arrangement-authoring-design.md`

---

## File Structure

- **Create** `ableton_mcp_max/arrangement_utils.py` — pure coercion/validation: `coerce_time`, `coerce_index`, `cue_exists_at`. Server-only.
- **Create** `tests/test_arrangement_utils.py` — offline unit tests for the above.
- **Modify** `remote_script/AbletonMCP/__init__.py` — add 6 handler methods (`_create_cue_point`, `_delete_cue_point`, `_set_cue_point_name`, `_get_arrangement_clips`, `_duplicate_clip_to_arrangement`, `_delete_arrangement_clip`); wire `get_arrangement_clips` as an inline read; add the 5 mutations to the modifying-command list + `main_thread_task` branches.
- **Modify** `ableton_mcp_max/server.py` — import from `arrangement_utils`; add 6 `@mcp.tool()`s after `load_preset` (before `_resolve_auto_target`).
- **Modify** `PROGRESS.md` — Phase 8 row + tool section + live results.

Restart protocol (per CLAUDE.md): land all edits → `bash scripts/install_remote_script.sh` + Live bounce (Claude self-serves) for the Remote Script; **Claude Code restart (user)** for server.py + the new util module. New tools arrive deferred → load via `ToolSearch select:mcp__AbletonMCPMax__<name>`.

---

## Task 1: `arrangement_utils.py` (pure helpers, TDD)

**Files:**
- Create: `ableton_mcp_max/arrangement_utils.py`
- Test: `tests/test_arrangement_utils.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_arrangement_utils.py`:

```python
import pytest
from ableton_mcp_max.arrangement_utils import (
    coerce_time,
    coerce_index,
    cue_exists_at,
)


# coerce_time -------------------------------------------------------------

def test_coerce_time_float():
    assert coerce_time(8.5) == 8.5


def test_coerce_time_int_to_float():
    assert coerce_time(4) == 4.0
    assert isinstance(coerce_time(4), float)


def test_coerce_time_zero_ok():
    assert coerce_time(0) == 0.0


def test_coerce_time_negative_raises():
    with pytest.raises(ValueError):
        coerce_time(-1)


def test_coerce_time_non_numeric_raises():
    with pytest.raises(ValueError):
        coerce_time("nope")


# coerce_index ------------------------------------------------------------

def test_coerce_index_valid():
    assert coerce_index(3) == 3


def test_coerce_index_zero_ok():
    assert coerce_index(0) == 0


def test_coerce_index_string_digit():
    assert coerce_index("5") == 5


def test_coerce_index_negative_raises():
    with pytest.raises(ValueError):
        coerce_index(-2)


def test_coerce_index_non_numeric_raises():
    with pytest.raises(ValueError):
        coerce_index("x")


# cue_exists_at -----------------------------------------------------------

def test_cue_exists_exact():
    assert cue_exists_at([0.0, 16.0, 32.0], 16.0) == (True, 1)


def test_cue_exists_within_epsilon():
    assert cue_exists_at([0.0, 16.0], 16.0000001) == (True, 1)


def test_cue_exists_no_match():
    assert cue_exists_at([0.0, 16.0], 8.0) == (False, None)


def test_cue_exists_empty_list():
    assert cue_exists_at([], 0.0) == (False, None)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --with pytest pytest tests/test_arrangement_utils.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'ableton_mcp_max.arrangement_utils'`

- [ ] **Step 3: Write the implementation**

Create `ableton_mcp_max/arrangement_utils.py`:

```python
"""Pure helpers for arrangement authoring (cue points + arrangement clips).

No Live dependencies — server-side only, like the other *_utils modules. The
Remote Script runs in Live's own interpreter and cannot import this; the server
coerces/validates here and sends already-resolved values to the handler.
"""


def coerce_time(value):
    """Coerce an arrangement time to a non-negative float (in beats).
    Raises ValueError if negative or non-numeric."""
    try:
        out = float(value)
    except (TypeError, ValueError):
        raise ValueError("Time must be a number (beats); got '%s'" % (value,))
    if out < 0:
        raise ValueError("Time must be >= 0; got %s" % (out,))
    return out


def coerce_index(value):
    """Coerce an index to a non-negative int. Raises ValueError otherwise."""
    try:
        out = int(value)
    except (TypeError, ValueError):
        raise ValueError("Index must be an integer; got '%s'" % (value,))
    if out < 0:
        raise ValueError("Index must be >= 0; got %s" % (out,))
    return out


def cue_exists_at(cue_times, time, epsilon=1e-6):
    """Return (exists, index) for whether a cue sits at `time` within epsilon.

    `cue_times` is an ordered list of floats (cue point times in beats); index
    is None when no cue matches.
    """
    for i, t in enumerate(cue_times):
        if abs(float(t) - float(time)) <= epsilon:
            return (True, i)
    return (False, None)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --with pytest pytest tests/test_arrangement_utils.py -q`
Expected: PASS (14 passed)

- [ ] **Step 5: Run the full suite (no regressions)**

Run: `uv run --with pytest pytest -q`
Expected: PASS (158 prior + 14 new = 172 passed)

- [ ] **Step 6: Commit**

```bash
git add ableton_mcp_max/arrangement_utils.py tests/test_arrangement_utils.py
git commit -m "feat: arrangement_utils pure helpers (coerce_time/index, cue_exists_at)"
```

---

## Task 2: Remote-script handlers + dispatch wiring

**Files:**
- Modify: `remote_script/AbletonMCP/__init__.py` (read dispatch ~line 629; mutation list ~lines 255-271; `main_thread_task` branches ~line 279+; handler methods appended near `_get_cue_points` ~line 2316)

> The Remote Script runs in Live's embedded interpreter: use `%`-formatting, no f-strings. These handlers cannot be unit-tested offline; verification is `py_compile` here + live smoke in Task 5.

- [ ] **Step 1: Add the inline read-dispatch arm for `get_arrangement_clips`**

In the read-dispatch block, immediately after the `get_cue_points` arm (currently at line 629-630):

```python
            elif command_type == "get_cue_points":
                response["result"] = self._get_cue_points()
            elif command_type == "get_arrangement_clips":
                response["result"] = self._get_arrangement_clips(
                    params.get("track_index", 0))
```

- [ ] **Step 2: Add the 5 mutations to the modifying-command list**

In the `elif command_type in [...]` list (ends at line 271 with `"register_listener", "unregister_listener"]`), add the new mutation command names. Change:

```python
                                 "register_listener", "unregister_listener"]:
```
to:
```python
                                 "register_listener", "unregister_listener",
                                 "create_cue_point", "delete_cue_point",
                                 "set_cue_point_name",
                                 "duplicate_clip_to_arrangement",
                                 "delete_arrangement_clip"]:
```

- [ ] **Step 3: Add the `main_thread_task` branches**

Inside `main_thread_task`, after the last existing branch (the listener branches) and before the queue-put, add:

```python
                        elif command_type == "create_cue_point":
                            time = params.get("time", 0.0)
                            result = self._create_cue_point(time)
                        elif command_type == "delete_cue_point":
                            index = params.get("index", 0)
                            result = self._delete_cue_point(index)
                        elif command_type == "set_cue_point_name":
                            index = params.get("index", 0)
                            name = params.get("name", "")
                            result = self._set_cue_point_name(index, name)
                        elif command_type == "duplicate_clip_to_arrangement":
                            track_index = params.get("track_index", 0)
                            source_slot_index = params.get("source_slot_index", 0)
                            destination_time = params.get("destination_time", 0.0)
                            result = self._duplicate_clip_to_arrangement(
                                track_index, source_slot_index, destination_time)
                        elif command_type == "delete_arrangement_clip":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            result = self._delete_arrangement_clip(
                                track_index, clip_index)
```

> To find the exact insertion point: search for the existing `unregister_listener` branch inside `main_thread_task` (the dispatch mirror of the modifying list) and add these after it, matching indentation.

- [ ] **Step 4: Append the 6 handler methods**

Add after `_jump_to_cue` / `_back_to_arrangement` (near line 2355), matching the surrounding indentation (4-space method indent inside the class):

```python
    def _create_cue_point(self, time):
        """Create a cue point (locator) at `time` beats. set_or_delete_cue()
        toggles at current_song_time, so move the playhead there, toggle, and
        restore. Pre-check existing cues to avoid toggling an existing marker
        OFF."""
        try:
            t = float(time)
            cues = self._song.cue_points
            for i in range(len(cues)):
                if abs(cues[i].time - t) <= 1e-6:
                    return {"created": False, "reason": "exists",
                            "index": i, "time": cues[i].time}
            saved = self._song.current_song_time
            self._song.current_song_time = t
            self._song.set_or_delete_cue()
            self._song.current_song_time = saved
            # Echo the actual (possibly grid-snapped) cue; tolerate snapping.
            cues = self._song.cue_points
            for i in range(len(cues)):
                if abs(cues[i].time - t) <= 0.5:
                    return {"created": True, "index": i, "time": cues[i].time}
            return {"created": True, "index": -1, "time": t}
        except Exception as e:
            self.log_message("Error creating cue point: " + str(e))
            raise

    def _delete_cue_point(self, index):
        """Delete the cue at `index` by toggling set_or_delete_cue at its time."""
        try:
            cues = self._song.cue_points
            n = len(cues)
            if index < 0 or index >= n:
                if n == 0:
                    raise IndexError("No cue points to delete")
                raise IndexError("Cue index out of range (0..%d)" % (n - 1))
            target_time = cues[index].time
            saved = self._song.current_song_time
            self._song.current_song_time = float(target_time)
            self._song.set_or_delete_cue()
            self._song.current_song_time = saved
            return {"deleted": True, "index": index, "time": target_time}
        except Exception as e:
            self.log_message("Error deleting cue point: " + str(e))
            raise

    def _set_cue_point_name(self, index, name):
        """Rename the cue at `index`."""
        try:
            cues = self._song.cue_points
            n = len(cues)
            if index < 0 or index >= n:
                if n == 0:
                    raise IndexError("No cue points")
                raise IndexError("Cue index out of range (0..%d)" % (n - 1))
            cues[index].name = name
            return {"index": index, "name": cues[index].name}
        except Exception as e:
            self.log_message("Error setting cue point name: " + str(e))
            raise

    def _get_arrangement_clips(self, track_index):
        """List the clips placed on a track's Arrangement timeline."""
        try:
            tracks = self._song.tracks
            if track_index < 0 or track_index >= len(tracks):
                raise IndexError(
                    "Track index out of range (0..%d)" % (len(tracks) - 1))
            track = tracks[track_index]
            clips = track.arrangement_clips
            out = []
            for i in range(len(clips)):
                c = clips[i]
                out.append({
                    "index": i,
                    "name": c.name,
                    "start_time": c.start_time,
                    "end_time": c.end_time,
                    "length": c.length,
                    "is_midi_clip": c.is_midi_clip,
                })
            return {"track_index": track_index, "count": len(out), "clips": out}
        except Exception as e:
            self.log_message("Error getting arrangement clips: " + str(e))
            raise

    def _duplicate_clip_to_arrangement(self, track_index, source_slot_index,
                                       destination_time):
        """Place a same-track Session-slot clip onto the Arrangement timeline."""
        try:
            tracks = self._song.tracks
            if track_index < 0 or track_index >= len(tracks):
                raise IndexError(
                    "Track index out of range (0..%d)" % (len(tracks) - 1))
            track = tracks[track_index]
            slots = track.clip_slots
            if source_slot_index < 0 or source_slot_index >= len(slots):
                raise IndexError(
                    "Slot index out of range (0..%d)" % (len(slots) - 1))
            slot = slots[source_slot_index]
            if not slot.has_clip:
                raise ValueError(
                    "No clip in session slot %d on track %d"
                    % (source_slot_index, track_index))
            new_clip = track.duplicate_clip_to_arrangement(
                slot.clip, float(destination_time))
            info = None
            if new_clip is not None:
                info = {
                    "name": new_clip.name,
                    "start_time": new_clip.start_time,
                    "end_time": new_clip.end_time,
                }
            return {
                "track_index": track_index,
                "source_slot_index": source_slot_index,
                "destination_time": float(destination_time),
                "placed": True,
                "new_clip": info,
            }
        except Exception as e:
            self.log_message("Error duplicating clip to arrangement: " + str(e))
            raise

    def _delete_arrangement_clip(self, track_index, clip_index):
        """Delete a clip from a track's Arrangement timeline."""
        try:
            tracks = self._song.tracks
            if track_index < 0 or track_index >= len(tracks):
                raise IndexError(
                    "Track index out of range (0..%d)" % (len(tracks) - 1))
            track = tracks[track_index]
            clips = track.arrangement_clips
            n = len(clips)
            if clip_index < 0 or clip_index >= n:
                if n == 0:
                    raise IndexError(
                        "No arrangement clips on track %d" % track_index)
                raise IndexError(
                    "Arrangement clip index out of range (0..%d)" % (n - 1))
            name = clips[clip_index].name
            track.delete_clip(clips[clip_index])
            return {"track_index": track_index, "clip_index": clip_index,
                    "deleted": True, "name": name}
        except Exception as e:
            self.log_message("Error deleting arrangement clip: " + str(e))
            raise
```

- [ ] **Step 5: Syntax-check the Remote Script**

Run: `uv run python -m py_compile remote_script/AbletonMCP/__init__.py`
Expected: no output (exit 0). If it errors, fix the reported line.

- [ ] **Step 6: Commit**

```bash
git add remote_script/AbletonMCP/__init__.py
git commit -m "feat: remote-script handlers for cue points + arrangement clips"
```

---

## Task 3: server.py tools

**Files:**
- Modify: `ableton_mcp_max/server.py` (import block near the other `*_utils` imports ~line 51-58; tools added after `load_preset`, before `def _resolve_auto_target` ~line 1935)

- [ ] **Step 1: Add the import**

After the `from ableton_mcp_max.preset_utils import (...)` block, add:

```python
from ableton_mcp_max.arrangement_utils import (
    coerce_time,
    coerce_index,
)
```

- [ ] **Step 2: Add the 6 tools**

Immediately before `def _resolve_auto_target(` (after the `load_preset` tool), insert:

```python
@mcp.tool()
def create_cue_point(ctx: Context, time: float) -> str:
    """
    Create a cue point (locator) on the Arrangement at the given time.

    No-ops (returns created=false) if a cue already exists at that time, so it
    never accidentally removes an existing marker. Live may snap the cue to the
    current grid — verify the actual time with get_cue_points.

    Parameters:
    - time: Position in beats (>= 0).
    """
    try:
        value = coerce_time(time)
        ableton = get_ableton_connection()
        result = ableton.send_command("create_cue_point", {"time": value})
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error creating cue point: {str(e)}")
        return f"Error creating cue point: {str(e)}"

@mcp.tool()
def delete_cue_point(ctx: Context, index: int) -> str:
    """
    Delete a cue point (locator) by its index (as listed by get_cue_points).

    Parameters:
    - index: Index into the ordered cue-point list (>= 0).
    """
    try:
        idx = coerce_index(index)
        ableton = get_ableton_connection()
        result = ableton.send_command("delete_cue_point", {"index": idx})
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error deleting cue point: {str(e)}")
        return f"Error deleting cue point: {str(e)}"

@mcp.tool()
def set_cue_point_name(ctx: Context, index: int, name: str) -> str:
    """
    Rename a cue point (locator) by its index (as listed by get_cue_points).

    Parameters:
    - index: Index into the ordered cue-point list (>= 0).
    - name: New name for the locator.
    """
    try:
        idx = coerce_index(index)
        ableton = get_ableton_connection()
        result = ableton.send_command("set_cue_point_name", {
            "index": idx,
            "name": name,
        })
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error renaming cue point: {str(e)}")
        return f"Error renaming cue point: {str(e)}"

@mcp.tool()
def get_arrangement_clips(ctx: Context, track_index: int) -> str:
    """
    List the clips on a track's Arrangement timeline.

    Parameters:
    - track_index: Index of the track.

    Returns JSON {track_index, count, clips:[{index, name, start_time,
    end_time, length, is_midi_clip}, ...]}.
    """
    try:
        idx = coerce_index(track_index)
        ableton = get_ableton_connection()
        result = ableton.send_command("get_arrangement_clips", {
            "track_index": idx,
        })
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting arrangement clips: {str(e)}")
        return f"Error getting arrangement clips: {str(e)}"

@mcp.tool()
def duplicate_clip_to_arrangement(ctx: Context, track_index: int,
                                  source_slot_index: int,
                                  destination_time: float) -> str:
    """
    Place a Session-slot clip onto the same track's Arrangement timeline.

    The source clip is taken from a Session clip slot on the SAME track and
    duplicated onto that track's Arrangement at destination_time.

    Parameters:
    - track_index: Index of the track.
    - source_slot_index: Session clip-slot index on that track (must hold a clip).
    - destination_time: Arrangement position in beats (>= 0).
    """
    try:
        t_idx = coerce_index(track_index)
        s_idx = coerce_index(source_slot_index)
        dest = coerce_time(destination_time)
        ableton = get_ableton_connection()
        result = ableton.send_command("duplicate_clip_to_arrangement", {
            "track_index": t_idx,
            "source_slot_index": s_idx,
            "destination_time": dest,
        })
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error duplicating clip to arrangement: {str(e)}")
        return f"Error duplicating clip to arrangement: {str(e)}"

@mcp.tool()
def delete_arrangement_clip(ctx: Context, track_index: int,
                            clip_index: int) -> str:
    """
    Delete a clip from a track's Arrangement timeline.

    Parameters:
    - track_index: Index of the track.
    - clip_index: Index into get_arrangement_clips' list (>= 0). Deleting
      re-indexes the remaining clips — re-read after.
    """
    try:
        t_idx = coerce_index(track_index)
        c_idx = coerce_index(clip_index)
        ableton = get_ableton_connection()
        result = ableton.send_command("delete_arrangement_clip", {
            "track_index": t_idx,
            "clip_index": c_idx,
        })
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error deleting arrangement clip: {str(e)}")
        return f"Error deleting arrangement clip: {str(e)}"

```

- [ ] **Step 3: Syntax-check the server module imports**

Run: `uv run python -c "import ableton_mcp_max.server; print('server import OK')"`
Expected: `server import OK`

- [ ] **Step 4: Full offline suite (no regressions)**

Run: `uv run --with pytest pytest -q`
Expected: PASS (172 passed)

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/server.py
git commit -m "feat: Phase 8 arrangement tools (cue CRUD + arrangement clips)"
```

---

## Task 4: Install Remote Script + bounce Live (Claude self-serves)

**Files:** none (deployment only)

- [ ] **Step 1: Reinstall the Remote Script**

Run: `bash scripts/install_remote_script.sh`
Expected: copies `remote_script/AbletonMCP` into Live's User Library; prints success.

- [ ] **Step 2: Bounce Live to load the new handlers**

Confirm no unsaved-changes sheet is blocking, then `kill -TERM <Live MacOS pid>` and `open -a "Ableton Live 11 Suite"`. Wait ~10-15s for the set + Control Surface to load. (Per CLAUDE.md: relaunch reopens a BLANK default set — fine for testing arrangement authoring on a scratch track.)

- [ ] **Step 3: Confirm reconnect**

Run: `lsof -nP -iTCP:9877 -sTCP:LISTEN`
Expected: a `Live` LISTEN line on 127.0.0.1:9877.

> The new SERVER tools are NOT callable until the user restarts Claude Code (MCP loads at session start). Stop here and hand off to Task 5.

---

## Task 5: Restart Claude Code (user) + live verification

**Files:**
- Modify: `PROGRESS.md`

- [ ] **Step 1: User restarts Claude Code**

Ask the user to restart Claude Code, then load the tools:
`ToolSearch select:mcp__AbletonMCPMax__create_cue_point,mcp__AbletonMCPMax__delete_cue_point,mcp__AbletonMCPMax__set_cue_point_name,mcp__AbletonMCPMax__get_arrangement_clips,mcp__AbletonMCPMax__duplicate_clip_to_arrangement,mcp__AbletonMCPMax__delete_arrangement_clip`
(plus `get_cue_points`, `get_transport`, `create_clip`, `create_midi_track`, `get_session_info` for the harness).

- [ ] **Step 2: Cue point create + idempotence**

- `get_cue_points` → baseline list.
- `create_cue_point(time=16)` → `created:true`; `get_cue_points` shows a locator near 16 (note any grid snap).
- `create_cue_point(time=16)` again → `created:false, reason:"exists"` (no accidental delete).

- [ ] **Step 3: Cue rename + delete**

- `set_cue_point_name(index=<new>, name="VERIFY8")` → `get_cue_points` reflects the rename.
- `delete_cue_point(index=<new>)` → `get_cue_points` count back to baseline; `get_transport` shows the playhead is not left displaced / playing.
- Negative: `delete_cue_point(index=999)` → clean "out of range" error, no mutation.

- [ ] **Step 4: Arrangement clip read + place + delete**

- On a scratch MIDI track (create_midi_track if needed; re-read its index via get_session_info — do NOT assume track 0), `create_clip(track, slot=0, length=4)` to seed a Session clip.
- `get_arrangement_clips(track)` → `count:0` baseline.
- `duplicate_clip_to_arrangement(track, source_slot_index=0, destination_time=0)` → `placed:true`, echoes new_clip start/end.
- `get_arrangement_clips(track)` → `count:1`, `start_time≈0`.
- `delete_arrangement_clip(track, clip_index=0)` → `deleted:true`; `get_arrangement_clips` → `count:0`.
- Negative: `duplicate_clip_to_arrangement(track, source_slot_index=8, destination_time=0)` from an empty slot → clean "No clip in session slot" error; `delete_arrangement_clip(track, 999)` → clean "out of range" error.

- [ ] **Step 5: Confirm the flagged unknowns (record findings)**

- Did `create_cue_point` place exactly at 16 or grid-snap? Record actual `.time`.
- Did `duplicate_clip_to_arrangement` return a non-None clip (so new_clip echoes)? Is `destination_time` in beats?
- After `delete_arrangement_clip(0)`, did the remaining clips re-index?
- Did toggling cues leave the playhead/transport unchanged (separate `get_transport`)?

- [ ] **Step 6: Restore + record results**

- Delete any cues/clips created during testing; leave the set as found. Note any leftover scratch track (no delete_track tool — user can Cmd+Z).
- Update `PROGRESS.md`: add Phase 8 to the phases table (Live-verified + date), add a "Phase 8 tools (Arrangement Authoring)" section listing the 6 tools + `arrangement_utils` + offline test count (172) + live findings.

- [ ] **Step 7: Commit**

```bash
git add PROGRESS.md
git commit -m "docs: Phase 8 live verification results"
```

---

## Task 6: PR

**Files:** none

- [ ] **Step 1: Verify gh account**

Run: `gh api user --jq .login`
Expected: `ringo380`. (Do not proceed otherwise.)

- [ ] **Step 2: Push + open PR**

```bash
git push -u origin feat/phase8-arrangement-authoring
gh pr create --base main --head feat/phase8-arrangement-authoring \
  --title "feat: Phase 8 arrangement authoring (cue CRUD + arrangement clips)" \
  --body-file <(printf '%s\n' "<summary of the 6 tools, arrangement_utils, offline 172, live results; NO AI attribution>")
```

- [ ] **Step 3: After review/approval — merge**

```bash
gh pr merge <N> --squash --delete-branch
git remote prune origin
```

---

## Self-Review Notes

- **Spec coverage:** all 6 spec tools have tasks (cue create/delete/rename → Task 2/3 steps; get/duplicate/delete arrangement clips → Task 2/3 steps). `arrangement_utils` (coerce_time, coerce_index, cue_exists_at) → Task 1. Offline + live testing → Tasks 1, 5. ✓
- **Type consistency:** handler method names (`_create_cue_point`, `_delete_cue_point`, `_set_cue_point_name`, `_get_arrangement_clips`, `_duplicate_clip_to_arrangement`, `_delete_arrangement_clip`) match their dispatch branches and the `send_command` command strings used by the server tools. Param keys (`time`, `index`, `name`, `track_index`, `source_slot_index`, `destination_time`, `clip_index`) match between server tool payloads and handler `params.get(...)`. ✓
- **Placeholder scan:** only the PR body in Task 6 Step 2 is a fill-in (intentional — composed at PR time from real results). All code steps contain complete code. ✓
- **Note:** `cue_exists_at` is unit-tested but not imported by server.py (the authoritative existence check happens handler-side against live `cue_points`); it's retained as a tested pure helper, consistent with the utils-module convention.
