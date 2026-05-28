# Phase 9 — Track Lifecycle & Undo/Redo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add MCP tools to create/delete/duplicate regular and return tracks and to undo/redo, closing the standing "no way to remove scratch tracks" gap.

**Architecture:** Three-layer split per the project convention — a server-only pure helper (`track_utils.py`, unit-tested) validates/coerces args; `server.py` exposes 7 `@mcp.tool()` functions that `send_command(...)`; the Remote Script (`remote_script/AbletonMCP/__init__.py`) handles each as a main-thread **mutation** calling the confirmed Live 11 LOM methods. The Remote Script cannot import the helper (separate interpreter), so all validation happens server-side.

**Tech Stack:** Python, FastMCP (`@mcp.tool()`), Live 11 LOM (`Song.create_audio_track/create_return_track/delete_track/delete_return_track/duplicate_track/undo/redo`, `Song.can_undo/can_redo`), pytest (offline pure-logic only), `uv`.

**Reference spec:** `docs/superpowers/specs/2026-05-27-phase-9-track-lifecycle-design.md`

**Offline gate (no Live):** `uv run --with pytest pytest -q`, `uv run python -c "import ableton_mcp_max.server"`, `uv run python -m py_compile remote_script/AbletonMCP/__init__.py`. Do NOT reformat existing files.

---

## File Structure

- **Create:** `ableton_mcp_max/track_utils.py` — pure arg coercion (`coerce_create_index`, `coerce_track_index`).
- **Create:** `tests/test_track_utils.py` — unit tests for the helper.
- **Modify:** `ableton_mcp_max/server.py` — add 7 `@mcp.tool()` functions (after the existing track tools, ~line 786 region). Verify `create_midi_track` unchanged.
- **Modify:** `remote_script/AbletonMCP/__init__.py` — add the 7 command names to the mutation `elif` list (~line 248), add 7 dispatch branches in `main_thread_task` (~line 283), and add 7 handler methods near `_create_midi_track` (~line 1214).

---

## Task 1: `track_utils.py` pure helper

**Files:**
- Create: `ableton_mcp_max/track_utils.py`
- Test: `tests/test_track_utils.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_track_utils.py`:

```python
import pytest
from ableton_mcp_max.track_utils import (
    coerce_create_index,
    coerce_track_index,
)


# coerce_create_index -----------------------------------------------------

def test_create_index_none_means_append():
    assert coerce_create_index(None) == -1


def test_create_index_minus_one_ok():
    assert coerce_create_index(-1) == -1


def test_create_index_zero_ok():
    assert coerce_create_index(0) == 0


def test_create_index_positive_ok():
    assert coerce_create_index(5) == 5


def test_create_index_float_coerces():
    assert coerce_create_index(3.0) == 3
    assert isinstance(coerce_create_index(3.0), int)


def test_create_index_below_minus_one_raises():
    with pytest.raises(ValueError):
        coerce_create_index(-2)


def test_create_index_non_numeric_raises():
    with pytest.raises(ValueError):
        coerce_create_index("nope")


# coerce_track_index ------------------------------------------------------

def test_track_index_valid():
    assert coerce_track_index(4) == 4


def test_track_index_zero_ok():
    assert coerce_track_index(0) == 0


def test_track_index_negative_raises():
    with pytest.raises(ValueError):
        coerce_track_index(-1)


def test_track_index_non_numeric_raises():
    with pytest.raises(ValueError):
        coerce_track_index("nope")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --with pytest pytest tests/test_track_utils.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'ableton_mcp_max.track_utils'`

- [ ] **Step 3: Write minimal implementation**

Create `ableton_mcp_max/track_utils.py`:

```python
"""Pure helpers for track lifecycle (create/delete/duplicate).

No Live dependencies — server-side only, like the other *_utils modules. The
Remote Script runs in Live's own interpreter and cannot import this; the server
coerces/validates here and sends already-resolved ints to the handler.
"""


def coerce_create_index(value):
    """Coerce a create-track index. None or -1 mean 'append at end'; any value
    >= 0 is an insert position. Raises ValueError for < -1 or non-integers."""
    if value is None:
        return -1
    try:
        out = int(value)
    except (TypeError, ValueError):
        raise ValueError("Index must be an integer or None; got '%s'" % (value,))
    if out < -1:
        raise ValueError("Index must be >= -1 (-1 = end); got %s" % (out,))
    return out


def coerce_track_index(value):
    """Coerce a delete/duplicate track index to a non-negative int.
    Raises ValueError otherwise."""
    try:
        out = int(value)
    except (TypeError, ValueError):
        raise ValueError("Index must be an integer; got '%s'" % (value,))
    if out < 0:
        raise ValueError("Index must be >= 0; got %s" % (out,))
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --with pytest pytest tests/test_track_utils.py -q`
Expected: PASS (11 passed)

- [ ] **Step 5: Run full offline suite (no regressions)**

Run: `uv run --with pytest pytest -q`
Expected: PASS — 172 prior + 11 new = 183 passed.

- [ ] **Step 6: Commit**

```bash
git add ableton_mcp_max/track_utils.py tests/test_track_utils.py
git commit -m "feat(phase9): track_utils index coercion helpers"
```

---

## Task 2: Remote Script handlers + dispatch wiring

The Remote Script has no unit tests (runs in Live's interpreter). Verification is
`py_compile` + live. Wire all 7 commands in one task so the dispatch list, the
`main_thread_task` branches, and the handler methods stay consistent.

**Files:**
- Modify: `remote_script/AbletonMCP/__init__.py` (mutation list ~248, `main_thread_task` ~283, handlers near `_create_midi_track` ~1214)

- [ ] **Step 1: Add the 7 command names to the mutation `elif` list**

In the `elif command_type in [...]:` block (~line 248), append these to the list (before the closing `]`):

```python
                                 "create_audio_track", "create_return_track",
                                 "delete_track", "delete_return_track",
                                 "duplicate_track", "undo", "redo"]:
```

(Replace the existing final `"delete_arrangement_clip"]:` line so the new names sit inside the same list — i.e. change `"delete_arrangement_clip"]:` to `"delete_arrangement_clip",` then add the lines above ending in `]:`.)

- [ ] **Step 2: Add 7 dispatch branches in `main_thread_task`**

Immediately after the existing `elif command_type == "delete_arrangement_clip":` branch in `main_thread_task`, add:

```python
                        elif command_type == "create_audio_track":
                            index = params.get("index", -1)
                            result = self._create_audio_track(index)
                        elif command_type == "create_return_track":
                            result = self._create_return_track()
                        elif command_type == "delete_track":
                            index = params.get("index", 0)
                            result = self._delete_track(index)
                        elif command_type == "delete_return_track":
                            index = params.get("index", 0)
                            result = self._delete_return_track(index)
                        elif command_type == "duplicate_track":
                            index = params.get("index", 0)
                            result = self._duplicate_track(index)
                        elif command_type == "undo":
                            result = self._undo()
                        elif command_type == "redo":
                            result = self._redo()
```

- [ ] **Step 3: Add the 7 handler methods**

Directly after the `_create_midi_track` method (ends ~line 1232, before `_set_track_name`), insert:

```python
    def _create_audio_track(self, index):
        """Create a new audio track at index (-1 = end)."""
        try:
            self._song.create_audio_track(index)
            new_index = len(self._song.tracks) - 1 if index == -1 else index
            new_track = self._song.tracks[new_index]
            return {"index": new_index, "name": new_track.name}
        except Exception as e:
            self.log_message("Error creating audio track: " + str(e))
            raise Exception("Could not create audio track (Live limit reached?): " + str(e))

    def _create_return_track(self):
        """Create a new return track at the end."""
        try:
            self._song.create_return_track()
            new_index = len(self._song.return_tracks) - 1
            new_track = self._song.return_tracks[new_index]
            return {"index": new_index, "name": new_track.name}
        except Exception as e:
            self.log_message("Error creating return track: " + str(e))
            raise Exception("Could not create return track (Live limit reached?): " + str(e))

    def _delete_track(self, index):
        """Delete the regular track at index; return remaining count."""
        if index < 0 or index >= len(self._song.tracks):
            raise Exception("Track index out of range (0..%d)" % (len(self._song.tracks) - 1,))
        self._song.delete_track(index)
        return {"deleted": True, "remaining_count": len(self._song.tracks)}

    def _delete_return_track(self, index):
        """Delete the return track at index; return remaining count."""
        if index < 0 or index >= len(self._song.return_tracks):
            raise Exception("Return track index out of range (0..%d)" % (len(self._song.return_tracks) - 1,))
        self._song.delete_return_track(index)
        return {"deleted": True, "remaining_count": len(self._song.return_tracks)}

    def _duplicate_track(self, index):
        """Duplicate the regular track at index; Live selects the new track."""
        if index < 0 or index >= len(self._song.tracks):
            raise Exception("Track index out of range (0..%d)" % (len(self._song.tracks) - 1,))
        self._song.duplicate_track(index)
        new_track = self._song.view.selected_track
        new_index = list(self._song.tracks).index(new_track)
        return {"new_index": new_index, "name": new_track.name}

    def _undo(self):
        """Undo the last action in Live's global undo stack (no-op if empty)."""
        if not self._song.can_undo:
            return {"undone": False, "reason": "nothing to undo",
                    "can_undo": False, "can_redo": self._song.can_redo}
        self._song.undo()
        return {"undone": True, "can_undo": self._song.can_undo,
                "can_redo": self._song.can_redo}

    def _redo(self):
        """Redo the last undone action (no-op if nothing to redo)."""
        if not self._song.can_redo:
            return {"redone": False, "reason": "nothing to redo",
                    "can_undo": self._song.can_undo, "can_redo": False}
        self._song.redo()
        return {"redone": True, "can_undo": self._song.can_undo,
                "can_redo": self._song.can_redo}
```

- [ ] **Step 4: Compile-check the Remote Script**

Run: `uv run python -m py_compile remote_script/AbletonMCP/__init__.py`
Expected: no output (exit 0). If `SyntaxError`, fix the edited region.

- [ ] **Step 5: Commit**

```bash
git add remote_script/AbletonMCP/__init__.py
git commit -m "feat(phase9): remote script track lifecycle + undo/redo handlers"
```

---

## Task 3: server.py MCP tools

**Files:**
- Modify: `ableton_mcp_max/server.py` (add after `set_track_name`, ~line 800; uses `json` already imported and `track_utils`)

- [ ] **Step 1: Add the `track_utils` import**

The project uses named imports (e.g. `from ableton_mcp_max.param_utils import resolve_parameter_index` at server.py:10). Add alongside them:

```python
from ableton_mcp_max.track_utils import coerce_create_index, coerce_track_index
```

- [ ] **Step 2: Add the 7 tools**

After the `set_track_name` tool (~line 800), insert:

```python
@mcp.tool()
def create_audio_track(ctx: Context, index: int = -1) -> str:
    """
    Create a new audio track.

    Parameters:
    - index: Insert position (-1 = end of list)
    """
    try:
        resolved = coerce_create_index(index)
        ableton = get_ableton_connection()
        result = ableton.send_command("create_audio_track", {"index": resolved})
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error creating audio track: {str(e)}")
        return f"Error creating audio track: {str(e)}"


@mcp.tool()
def create_return_track(ctx: Context) -> str:
    """
    Create a new return track (added at the end of the return-track list).
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("create_return_track", {})
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error creating return track: {str(e)}")
        return f"Error creating return track: {str(e)}"


@mcp.tool()
def delete_track(ctx: Context, index: int) -> str:
    """
    Delete the regular (audio/MIDI) track at the given index. Remaining tracks
    re-index; re-read get_session_info afterward.

    Parameters:
    - index: The index of the track to delete
    """
    try:
        resolved = coerce_track_index(index)
        ableton = get_ableton_connection()
        result = ableton.send_command("delete_track", {"index": resolved})
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error deleting track: {str(e)}")
        return f"Error deleting track: {str(e)}"


@mcp.tool()
def delete_return_track(ctx: Context, index: int) -> str:
    """
    Delete the return track at the given index. Remaining return tracks
    re-index; re-read get_session_info afterward.

    Parameters:
    - index: The index of the return track to delete
    """
    try:
        resolved = coerce_track_index(index)
        ableton = get_ableton_connection()
        result = ableton.send_command("delete_return_track", {"index": resolved})
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error deleting return track: {str(e)}")
        return f"Error deleting return track: {str(e)}"


@mcp.tool()
def duplicate_track(ctx: Context, index: int) -> str:
    """
    Duplicate the regular track at the given index. Live inserts the copy and
    selects it; the returned new_index is the copy's position.

    Parameters:
    - index: The index of the track to duplicate
    """
    try:
        resolved = coerce_track_index(index)
        ableton = get_ableton_connection()
        result = ableton.send_command("duplicate_track", {"index": resolved})
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error duplicating track: {str(e)}")
        return f"Error duplicating track: {str(e)}"


@mcp.tool()
def undo(ctx: Context) -> str:
    """
    Undo the last action. WARNING: this walks Live's GLOBAL undo stack — it can
    undo actions the user performed by hand, not just MCP changes. No-op (clean
    result) if there is nothing to undo.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("undo", {})
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error performing undo: {str(e)}")
        return f"Error performing undo: {str(e)}"


@mcp.tool()
def redo(ctx: Context) -> str:
    """
    Redo the last undone action. Operates on Live's global undo stack. No-op
    (clean result) if there is nothing to redo.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("redo", {})
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error performing redo: {str(e)}")
        return f"Error performing redo: {str(e)}"
```

- [ ] **Step 3: Verify the server imports cleanly**

Run: `uv run python -c "import ableton_mcp_max.server"`
Expected: no output (exit 0). Fixes any import/syntax error before proceeding.

- [ ] **Step 4: Re-run the full offline suite (no regressions)**

Run: `uv run --with pytest pytest -q`
Expected: PASS — 183 passed (unchanged; server tools aren't unit-tested).

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/server.py
git commit -m "feat(phase9): create/delete/duplicate track + undo/redo MCP tools"
```

---

## Task 4: Offline gate + create_midi_track parity check

**Files:** none modified (verification only)

- [ ] **Step 1: Confirm create_midi_track already supports index (no change needed)**

Run: `grep -n "def create_midi_track" ableton_mcp_max/server.py`
Expected: shows `def create_midi_track(ctx: Context, index: int = -1)`. If the signature already has `index`, the spec's "verify parity" item is satisfied — make NO change. If it somehow lacks `index`, add `index: int = -1` and pass `{"index": index}` to match `create_audio_track`.

- [ ] **Step 2: Run the complete offline gate**

Run each:
```bash
uv run --with pytest pytest -q
uv run python -c "import ableton_mcp_max.server"
uv run python -m py_compile remote_script/AbletonMCP/__init__.py
```
Expected: 183 passed; both compile/import commands exit 0 with no output.

- [ ] **Step 3: Commit (only if Step 1 required a change; otherwise skip)**

```bash
git add ableton_mcp_max/server.py
git commit -m "feat(phase9): create_midi_track index parity"
```

---

## Task 5: Live verification (manual, requires user)

Per CLAUDE.md restart protocol: both halves changed → ONE reinstall + ONE dual-restart.

- [ ] **Step 1: Install the Remote Script and bounce Live**

```bash
bash scripts/install_remote_script.sh
```
Then quit + reopen Live (Claude may `kill -TERM` the Live PID after confirming no save sheet, then `open -a "Ableton Live 11 Suite"`; wait ~10–15s). Relaunch reopens a BLANK default set — re-read state, don't assume prior tracks.

- [ ] **Step 2: Restart Claude Code (user action — cannot self-restart)**

After restart, load the new deferred tools:
`ToolSearch select:mcp__AbletonMCPMax__create_audio_track,mcp__AbletonMCPMax__create_return_track,mcp__AbletonMCPMax__delete_track,mcp__AbletonMCPMax__delete_return_track,mcp__AbletonMCPMax__duplicate_track,mcp__AbletonMCPMax__undo,mcp__AbletonMCPMax__redo`

- [ ] **Step 3: Exercise each tool against the open set**

1. `get_session_info` → note baseline regular + return track counts.
2. `create_audio_track()` → expect `{index, name}`; re-`get_session_info` → count++.
3. `create_return_track()` → expect `{index, name}`; return count++.
4. `duplicate_track(index=<an existing regular index>)` → expect `{new_index, name}`; count++.
5. `delete_track(index=<the duplicate's new_index>)` → expect `{deleted:true, remaining_count}`; count--.
6. `delete_return_track(index=<created return index>)` → return count--.
7. Undo/redo round-trip: `create_audio_track()` → `undo` (`{undone:true,...}`) → `get_session_info` count back to prior → `redo` (`{redone:true,...}`) → count restored.
8. Negatives: `delete_track(index=999)` → clean "out of range (0..N)"; on a fresh blank set with nothing to undo, `undo` → `{undone:false, reason:"nothing to undo"}`.

- [ ] **Step 4: Clean up scratch tracks via the new tool**

Use `delete_track` / `delete_return_track` to remove every track created during the test (dogfoods the self-cleanup win). Confirm `get_session_info` matches the baseline counts.

- [ ] **Step 5: Record results in PROGRESS.md**

Add a "Phase 9 tools (Track Lifecycle & Undo/Redo)" section with the live findings and update the phase table. Commit:
```bash
git add PROGRESS.md
git commit -m "docs(phase9): live-verification results"
```
