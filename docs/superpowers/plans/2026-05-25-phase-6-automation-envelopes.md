# Phase 6 — Automation Envelopes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add MCP tools to read (sampled) and write parameter automation in Ableton session and arrangement clips — for device parameters, rack macros, and mixer volume/pan/sends.

**Architecture:** Same two halves over localhost:9877 as all prior phases. A new pure helper `automation_utils.py` (server-side, unit-tested) normalizes targets and breakpoints; the server resolves device-parameter names→indices via the existing `get_device_parameters` round-trip and sends already-resolved identifiers. The Remote Script handler fetches the live `Clip` / `DeviceParameter` / `AutomationEnvelope` objects: `get_automation` runs inline; `set_automation`, `clear_automation`, `create_automation_envelope`, `clear_all_automation` are main-thread mutations.

**Tech Stack:** Python 3.10+ (server, via `uv`), Python 3.7-era embedded interpreter (Remote Script, inside Live — no f-strings / `|` unions / `match`; `%`-formatting only), MCP `FastMCP`, `pytest` for the offline helper.

**Branch:** `feat/phase6-automation-envelopes` (off `main` @ 93b3fd4). Squash-merge to `main` via PR after live verification.

**Design reference:** `docs/superpowers/specs/2026-05-25-phase-6-automation-envelopes-design.md`

---

## ⚠️ Restart / reinstall batching (read before starting)

Per project protocol (`CLAUDE.md`): batch BOTH halves, then do ONE reinstall + ONE dual-restart.

- Tasks 2–5 edit the Remote Script. **Do NOT reinstall after each** — commit the code, but run `bash scripts/install_remote_script.sh` + bounce Live **once**, after Task 5.
- Task 6 edits `server.py`. After Task 6, restart Claude Code **once** to load the 5 new (deferred) tools.
- So the single heavy checkpoint is **between Task 6 and Task 7**: reinstall Remote Script → quit+reopen Live → restart Claude Code → load tools via `ToolSearch select:mcp__AbletonMCPMax__get_automation,...`.

---

## LOM reference (from spec; verify live where flagged)

| Object | Method | Notes |
|--------|--------|-------|
| `Clip` | `automation_envelope(param)` | → `AutomationEnvelope` or `None` |
| `Clip` | `create_automation_envelope(param)` | → `AutomationEnvelope` |
| `Clip` | `clear_envelope(param)` | remove one parameter's envelope |
| `Clip` | `clear_all_envelopes()` | remove all envelopes in the clip |
| `AutomationEnvelope` | `value_at_time(time)` | sample (only read primitive) |
| `AutomationEnvelope` | `insert_step(time, duration, value)` | `duration=0` = single breakpoint |
| `AutomationEnvelope` | `clear_range(time, duration)` | |
| `Track` | `clip_slots[i].clip` | session clip |
| `Track` | `arrangement_clips[i]` | arrangement clip (**verify exists in Live 11**) |

`DeviceParameter` sources: `track.devices[d].parameters[p]` (incl. macros on a rack); `track.mixer_device.volume` / `.panning` / `.sends[i]`.

---

## File Structure

| File | Responsibility |
|------|----------------|
| `ableton_mcp_max/automation_utils.py` | **Pure** helpers: normalize clip_location / target_type / mixer target; coerce resolution/time/duration/value; normalize+validate breakpoint lists. No Live deps. |
| `tests/test_automation_utils.py` | Offline unit tests for `automation_utils`. |
| `remote_script/AbletonMCP/__init__.py` | `_resolve_clip_loc`, `_resolve_auto_param`, `_resolve_envelope` resolvers; `get_automation` read dispatch+handler; 4 mutation handlers + dispatch + mutation-list entries. |
| `ableton_mcp_max/server.py` | 5 new `@mcp.tool()`s after `load_drum_kit`; import `automation_utils`. |
| `PROGRESS.md` | Mark Phase 6; tool checkboxes; live results. |

---

## Tool contract (target args are shared)

```
# shared clip + parameter targeting:
track_index:int, clip_index:int, clip_location:str="session"  # "session"|"arrangement"
target_type:str="device"                                       # "device"|"mixer"
  device: device_index:int=0, parameter:int|str               # name or index (macros incl.)
  mixer:  mixer_property:str, send_index:int=-1                # volume|pan|send

get_automation(...target..., from_time=0.0, time_span=-1.0, resolution=16)
  → {clip_location, track_index, clip_index, target, has_envelope, samples:[{time,value}]}

set_automation(...target..., points=None, time=None, value=None, duration=0.0)
  → {..., target, points_written}

clear_automation(...target..., from_time=None, time_span=None)
  → {..., target, cleared:"range"|"envelope"}

create_automation_envelope(...target...)
  → {..., target, created:bool}

clear_all_automation(track_index, clip_index, clip_location="session")
  → {clip_location, track_index, clip_index, cleared_all:true}
```

---

### Task 0: Create the branch

- [ ] **Step 1: Branch off main**

```bash
cd ~/git/ableton-mcp-max
git checkout main && git pull --ff-only
git checkout -b feat/phase6-automation-envelopes
```

---

### Task 1: Pure helper `automation_utils` (TDD)

**Files:**
- Create: `ableton_mcp_max/automation_utils.py`
- Test: `tests/test_automation_utils.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_automation_utils.py
import pytest
from ableton_mcp_max.automation_utils import (
    normalize_clip_location,
    normalize_target_type,
    normalize_mixer_target,
    coerce_resolution,
    coerce_time,
    coerce_duration,
    coerce_value,
    normalize_breakpoints,
)

# --- clip_location ---
def test_clip_location_default_session():
    assert normalize_clip_location("session") == "session"

def test_clip_location_case_insensitive():
    assert normalize_clip_location("Arrangement") == "arrangement"

def test_clip_location_bad_raises():
    with pytest.raises(ValueError):
        normalize_clip_location("timeline")

# --- target_type ---
def test_target_type_device():
    assert normalize_target_type("device") == "device"

def test_target_type_mixer_case():
    assert normalize_target_type("MIXER") == "mixer"

def test_target_type_bad_raises():
    with pytest.raises(ValueError):
        normalize_target_type("macro")

# --- mixer target ---
def test_mixer_target_volume():
    assert normalize_mixer_target("volume", -1) == ("volume", -1)

def test_mixer_target_pan_alias():
    assert normalize_mixer_target("panning", -1) == ("pan", -1)

def test_mixer_target_send_requires_index():
    with pytest.raises(ValueError):
        normalize_mixer_target("send", -1)

def test_mixer_target_send_ok():
    assert normalize_mixer_target("send", 0) == ("send", 0)

# --- resolution clamp ---
def test_resolution_clamps_to_one():
    assert coerce_resolution(0) == 1
    assert coerce_resolution(-5) == 1

def test_resolution_passthrough():
    assert coerce_resolution(32) == 32

# --- time / duration / value ---
def test_time_negative_raises():
    with pytest.raises(ValueError):
        coerce_time(-0.5)

def test_duration_negative_raises():
    with pytest.raises(ValueError):
        coerce_duration(-1.0)

def test_value_coerces_float():
    assert coerce_value(1) == 1.0

# --- breakpoints ---
def test_breakpoints_single_form():
    bps = normalize_breakpoints(None, 2.0, 0.5, 0.0)
    assert bps == [{"time": 2.0, "value": 0.5, "duration": 0.0}]

def test_breakpoints_list_form():
    bps = normalize_breakpoints(
        [{"time": 0.0, "value": 0.0}, {"time": 4.0, "value": 1.0, "duration": 1.0}],
        None, None, 0.0)
    assert bps == [
        {"time": 0.0, "value": 0.0, "duration": 0.0},
        {"time": 4.0, "value": 1.0, "duration": 1.0},
    ]

def test_breakpoints_empty_raises():
    with pytest.raises(ValueError):
        normalize_breakpoints([], None, None, 0.0)

def test_breakpoints_none_raises():
    with pytest.raises(ValueError):
        normalize_breakpoints(None, None, None, 0.0)

def test_breakpoints_missing_value_raises():
    with pytest.raises(ValueError):
        normalize_breakpoints([{"time": 1.0}], None, None, 0.0)

def test_breakpoints_negative_time_raises():
    with pytest.raises(ValueError):
        normalize_breakpoints([{"time": -1.0, "value": 0.5}], None, None, 0.0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/git/ableton-mcp-max && uv run --with pytest pytest tests/test_automation_utils.py -v`
Expected: FAIL — `ModuleNotFoundError: ableton_mcp_max.automation_utils`.

- [ ] **Step 3: Implement the helper**

```python
# ableton_mcp_max/automation_utils.py
"""Pure helpers for automation-envelope handling. No Live dependencies.

The server uses these to normalize targets and validate breakpoints before
sending already-resolved values to the Remote Script (which runs in Live's own
interpreter and cannot import this module)."""

from ableton_mcp_max.mixer_utils import normalize_property

_CLIP_LOCATIONS = ("session", "arrangement")
_TARGET_TYPES = ("device", "mixer")
# Mixer properties that can host automation (canonical names from mixer_utils).
_MIXER_AUTOMATABLE = ("volume", "pan", "send")


def normalize_clip_location(loc):
    """Fold clip location to 'session'|'arrangement' (case-insensitive)."""
    lowered = str(loc).strip().lower()
    if lowered in _CLIP_LOCATIONS:
        return lowered
    raise ValueError(
        "Unknown clip_location '%s'. Valid: session, arrangement" % loc
    )


def normalize_target_type(t):
    """Fold target type to 'device'|'mixer' (case-insensitive)."""
    lowered = str(t).strip().lower()
    if lowered in _TARGET_TYPES:
        return lowered
    raise ValueError(
        "Unknown target_type '%s'. Valid: device, mixer" % t
    )


def normalize_mixer_target(mixer_property, send_index):
    """Normalize a mixer automation target. Returns (canonical, send_index).
    Only volume/pan/send are automatable; 'send' requires send_index >= 0."""
    canonical = normalize_property(mixer_property)  # reuse mixer aliases
    if canonical not in _MIXER_AUTOMATABLE:
        raise ValueError(
            "Mixer property '%s' is not automatable. Valid: volume, pan, send"
            % mixer_property
        )
    if canonical == "send" and (send_index is None or send_index < 0):
        raise ValueError("mixer_property 'send' requires send_index >= 0")
    return canonical, (send_index if canonical == "send" else -1)


def coerce_resolution(n):
    """Sample count for a read; clamp to >= 1."""
    n = int(n)
    return n if n >= 1 else 1


def coerce_time(t):
    """Coerce a non-negative time (beats)."""
    v = float(t)
    if v < 0:
        raise ValueError("time must be >= 0")
    return v


def coerce_duration(d):
    """Coerce a non-negative duration (beats); 0 = single breakpoint."""
    v = float(d)
    if v < 0:
        raise ValueError("duration must be >= 0")
    return v


def coerce_value(v):
    """Coerce an envelope value to float (clamping happens in Live)."""
    return float(v)


def normalize_breakpoints(points, time, value, default_duration):
    """Build a validated list of breakpoints from EITHER a `points` list OR the
    single (time, value, duration) form. Each entry -> {time, value, duration}.
    Raises ValueError on an empty result, a missing time/value, or a negative
    time/duration."""
    if points is None:
        if time is None or value is None:
            raise ValueError(
                "set_automation requires either `points` or both `time` and `value`"
            )
        return [{
            "time": coerce_time(time),
            "value": coerce_value(value),
            "duration": coerce_duration(default_duration),
        }]
    if not isinstance(points, (list, tuple)) or len(points) == 0:
        raise ValueError("`points` must be a non-empty list of breakpoints")
    out = []
    for i, p in enumerate(points):
        if "time" not in p or "value" not in p:
            raise ValueError(
                "breakpoint %d missing 'time' or 'value': %r" % (i, p)
            )
        out.append({
            "time": coerce_time(p["time"]),
            "value": coerce_value(p["value"]),
            "duration": coerce_duration(p.get("duration", default_duration)),
        })
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ~/git/ableton-mcp-max && uv run --with pytest pytest tests/test_automation_utils.py -v`
Expected: all pass (23 tests).

- [ ] **Step 5: Run the full offline suite (no regressions)**

Run: `cd ~/git/ableton-mcp-max && uv run --with pytest pytest -q`
Expected: 93 prior + 23 new = 116 passing.

- [ ] **Step 6: Commit**

```bash
cd ~/git/ableton-mcp-max
git add ableton_mcp_max/automation_utils.py tests/test_automation_utils.py
git commit -m "feat: add pure automation_utils helper with tests"
```

---

### Task 2: Remote Script — shared resolvers + `get_automation` read handler

Edits `remote_script/AbletonMCP/__init__.py`. **Do not reinstall yet** (batched to Task 5).

**Files:**
- Modify: `remote_script/AbletonMCP/__init__.py` (read dispatch near line 559 after `get_cue_points`; new handler methods after `_resolve_clip` ~line 1301)

- [ ] **Step 1: Add the read dispatch branch** (immediately after the `get_cue_points` elif, ~line 560, before the final `else`)

```python
            elif command_type == "get_automation":
                response["result"] = self._get_automation(
                    params.get("track_index", 0),
                    params.get("clip_index", 0),
                    params.get("clip_location", "session"),
                    params.get("target_type", "device"),
                    params.get("device_index", 0),
                    params.get("parameter_index", 0),
                    params.get("mixer_property", ""),
                    params.get("send_index", -1),
                    params.get("from_time", 0.0),
                    params.get("time_span", -1.0),
                    params.get("resolution", 16),
                )
```

- [ ] **Step 2: Add the shared resolvers** (after `_resolve_clip`, ~line 1301)

```python
    def _resolve_clip_loc(self, track_index, clip_index, clip_location):
        """Return the Live clip at (track_index, clip_index) in session or
        arrangement view. Raises on out-of-range / empty session slot."""
        if track_index < 0 or track_index >= len(self._song.tracks):
            raise IndexError("Track index out of range")
        track = self._song.tracks[track_index]
        if clip_location == "arrangement":
            clips = track.arrangement_clips
            if clip_index < 0 or clip_index >= len(clips):
                raise IndexError("Arrangement clip index out of range")
            return clips[clip_index]
        # default: session
        if clip_index < 0 or clip_index >= len(track.clip_slots):
            raise IndexError("Clip index out of range")
        clip_slot = track.clip_slots[clip_index]
        if not clip_slot.has_clip:
            raise Exception("No clip in slot")
        return clip_slot.clip

    def _resolve_auto_param(self, track_index, target_type, device_index,
                            parameter_index, mixer_property, send_index):
        """Return the DeviceParameter to automate (device param/macro or mixer
        volume/pan/send). `parameter_index` and `mixer_property` are already
        resolved/normalized by the server."""
        if track_index < 0 or track_index >= len(self._song.tracks):
            raise IndexError("Track index out of range")
        track = self._song.tracks[track_index]
        if target_type == "mixer":
            md = track.mixer_device
            if mixer_property == "volume":
                return md.volume
            if mixer_property == "pan":
                return md.panning
            if mixer_property == "send":
                if send_index < 0 or send_index >= len(md.sends):
                    raise IndexError("send_index out of range")
                return md.sends[send_index]
            raise ValueError("Unsupported mixer_property: " + str(mixer_property))
        # default: device
        if device_index < 0 or device_index >= len(track.devices):
            raise IndexError("Device index out of range")
        device = track.devices[device_index]
        if parameter_index < 0 or parameter_index >= len(device.parameters):
            raise IndexError("Parameter index out of range")
        return device.parameters[parameter_index]

    def _get_automation(self, track_index, clip_index, clip_location,
                        target_type, device_index, parameter_index,
                        mixer_property, send_index, from_time, time_span,
                        resolution):
        """Sampled read of a parameter's automation envelope in a clip.
        No LOM API enumerates breakpoints, so we sample value_at_time."""
        clip = self._resolve_clip_loc(track_index, clip_index, clip_location)
        param = self._resolve_auto_param(
            track_index, target_type, device_index, parameter_index,
            mixer_property, send_index)
        env = clip.automation_envelope(param)
        result = {
            "clip_location": clip_location,
            "track_index": track_index,
            "clip_index": clip_index,
            "target": {"type": target_type, "name": param.name},
            "has_envelope": env is not None,
            "samples": [],
        }
        if env is None:
            return result
        start = float(from_time)
        span = float(time_span)
        if span < 0:
            span = clip.length
        n = int(resolution)
        if n < 1:
            n = 1
        samples = []
        if n == 1:
            samples.append({"time": start, "value": env.value_at_time(start)})
        else:
            step = span / float(n - 1)
            i = 0
            while i < n:
                t = start + step * i
                samples.append({"time": t, "value": env.value_at_time(t)})
                i = i + 1
        result["samples"] = samples
        return result
```

- [ ] **Step 3: Syntax-check the handler**

Run: `cd ~/git/ableton-mcp-max && uv run python -m py_compile remote_script/AbletonMCP/__init__.py`
Expected: no output (compiles).

- [ ] **Step 4: Commit**

```bash
cd ~/git/ableton-mcp-max
git add remote_script/AbletonMCP/__init__.py
git commit -m "feat: add get_automation read + shared resolvers to Remote Script"
```

---

### Task 3: Remote Script — `set_automation` handler (mutation)

**Files:**
- Modify: `remote_script/AbletonMCP/__init__.py` (mutation list ~line 249; `main_thread_task` branch after `re_enable_automation` ~line 465; new handler method after `_get_automation`)

- [ ] **Step 1: Add the four new commands to the modifying-command list** (extend the list ending `..., "re_enable_automation"]` at ~line 249)

```python
                                 "back_to_arrangement", "re_enable_automation",
                                 "set_automation", "clear_automation",
                                 "create_automation_envelope",
                                 "clear_all_automation"]:
```

- [ ] **Step 2: Add the `set_automation` branch inside `main_thread_task`** (after the `re_enable_automation` branch, ~line 466)

```python
                        elif command_type == "set_automation":
                            result = self._set_automation(
                                params.get("track_index", 0),
                                params.get("clip_index", 0),
                                params.get("clip_location", "session"),
                                params.get("target_type", "device"),
                                params.get("device_index", 0),
                                params.get("parameter_index", 0),
                                params.get("mixer_property", ""),
                                params.get("send_index", -1),
                                params.get("breakpoints", []))
```

- [ ] **Step 3: Add the `_set_automation` handler** (after `_get_automation`)

```python
    def _set_automation(self, track_index, clip_index, clip_location,
                        target_type, device_index, parameter_index,
                        mixer_property, send_index, breakpoints):
        """Insert one or more breakpoints/steps into a parameter's envelope,
        creating the envelope if it does not yet exist. `breakpoints` is a
        server-validated list of {time, value, duration}."""
        clip = self._resolve_clip_loc(track_index, clip_index, clip_location)
        param = self._resolve_auto_param(
            track_index, target_type, device_index, parameter_index,
            mixer_property, send_index)
        env = clip.automation_envelope(param)
        if env is None:
            env = clip.create_automation_envelope(param)
        count = 0
        for bp in breakpoints:
            env.insert_step(
                float(bp["time"]), float(bp["duration"]), float(bp["value"]))
            count = count + 1
        return {
            "clip_location": clip_location,
            "track_index": track_index,
            "clip_index": clip_index,
            "target": {"type": target_type, "name": param.name},
            "points_written": count,
        }
```

- [ ] **Step 4: Syntax-check**

Run: `cd ~/git/ableton-mcp-max && uv run python -m py_compile remote_script/AbletonMCP/__init__.py`
Expected: no output.

- [ ] **Step 5: Commit**

```bash
cd ~/git/ableton-mcp-max
git add remote_script/AbletonMCP/__init__.py
git commit -m "feat: add set_automation handler to Remote Script"
```

---

### Task 4: Remote Script — `clear_automation` handler (mutation)

**Files:**
- Modify: `remote_script/AbletonMCP/__init__.py` (`main_thread_task` branch after `set_automation`; new handler after `_set_automation`)

- [ ] **Step 1: Add the `clear_automation` branch inside `main_thread_task`** (after the `set_automation` branch)

```python
                        elif command_type == "clear_automation":
                            result = self._clear_automation(
                                params.get("track_index", 0),
                                params.get("clip_index", 0),
                                params.get("clip_location", "session"),
                                params.get("target_type", "device"),
                                params.get("device_index", 0),
                                params.get("parameter_index", 0),
                                params.get("mixer_property", ""),
                                params.get("send_index", -1),
                                params.get("from_time", None),
                                params.get("time_span", None))
```

- [ ] **Step 2: Add the `_clear_automation` handler** (after `_set_automation`)

```python
    def _clear_automation(self, track_index, clip_index, clip_location,
                         target_type, device_index, parameter_index,
                         mixer_property, send_index, from_time, time_span):
        """Clear a parameter's automation. With a range -> clear_range; without
        -> clear the whole envelope for that parameter."""
        clip = self._resolve_clip_loc(track_index, clip_index, clip_location)
        param = self._resolve_auto_param(
            track_index, target_type, device_index, parameter_index,
            mixer_property, send_index)
        out = {
            "clip_location": clip_location,
            "track_index": track_index,
            "clip_index": clip_index,
            "target": {"type": target_type, "name": param.name},
        }
        if from_time is not None and time_span is not None:
            env = clip.automation_envelope(param)
            if env is not None:
                env.clear_range(float(from_time), float(time_span))
            out["cleared"] = "range"
        else:
            clip.clear_envelope(param)
            out["cleared"] = "envelope"
        return out
```

- [ ] **Step 3: Syntax-check**

Run: `cd ~/git/ableton-mcp-max && uv run python -m py_compile remote_script/AbletonMCP/__init__.py`
Expected: no output.

- [ ] **Step 4: Commit**

```bash
cd ~/git/ableton-mcp-max
git add remote_script/AbletonMCP/__init__.py
git commit -m "feat: add clear_automation handler to Remote Script"
```

---

### Task 5: Remote Script — `create_automation_envelope` + `clear_all_automation` handlers (mutations)

**Files:**
- Modify: `remote_script/AbletonMCP/__init__.py` (`main_thread_task` branches after `clear_automation`; two new handlers after `_clear_automation`)

- [ ] **Step 1: Add the two branches inside `main_thread_task`** (after the `clear_automation` branch)

```python
                        elif command_type == "create_automation_envelope":
                            result = self._create_automation_envelope(
                                params.get("track_index", 0),
                                params.get("clip_index", 0),
                                params.get("clip_location", "session"),
                                params.get("target_type", "device"),
                                params.get("device_index", 0),
                                params.get("parameter_index", 0),
                                params.get("mixer_property", ""),
                                params.get("send_index", -1))
                        elif command_type == "clear_all_automation":
                            result = self._clear_all_automation(
                                params.get("track_index", 0),
                                params.get("clip_index", 0),
                                params.get("clip_location", "session"))
```

- [ ] **Step 2: Add the two handlers** (after `_clear_automation`)

```python
    def _create_automation_envelope(self, track_index, clip_index,
                                    clip_location, target_type, device_index,
                                    parameter_index, mixer_property, send_index):
        """Explicitly create an empty envelope for a parameter. `created` is
        False if one already existed."""
        clip = self._resolve_clip_loc(track_index, clip_index, clip_location)
        param = self._resolve_auto_param(
            track_index, target_type, device_index, parameter_index,
            mixer_property, send_index)
        existed = clip.automation_envelope(param) is not None
        if not existed:
            clip.create_automation_envelope(param)
        return {
            "clip_location": clip_location,
            "track_index": track_index,
            "clip_index": clip_index,
            "target": {"type": target_type, "name": param.name},
            "created": (not existed),
        }

    def _clear_all_automation(self, track_index, clip_index, clip_location):
        """Remove every automation envelope in the clip."""
        clip = self._resolve_clip_loc(track_index, clip_index, clip_location)
        clip.clear_all_envelopes()
        return {
            "clip_location": clip_location,
            "track_index": track_index,
            "clip_index": clip_index,
            "cleared_all": True,
        }
```

- [ ] **Step 3: Syntax-check**

Run: `cd ~/git/ableton-mcp-max && uv run python -m py_compile remote_script/AbletonMCP/__init__.py`
Expected: no output.

- [ ] **Step 4: Commit**

```bash
cd ~/git/ableton-mcp-max
git add remote_script/AbletonMCP/__init__.py
git commit -m "feat: add create/clear_all automation handlers to Remote Script"
```

- [ ] **Step 5: Reinstall the Remote Script (ONE time, all of Tasks 2–5)**

```bash
bash ~/git/ableton-mcp-max/scripts/install_remote_script.sh
```
Then bounce Live so the new handlers load (Claude may self-serve per CLAUDE.md, or USER ACTION: ⌘Q Live → reopen). Give Live ~10–15s to reload the Control Surface.

---

### Task 6: Server — the 5 automation MCP tools

**Files:**
- Modify: `ableton_mcp_max/server.py` (import after the `transport_utils` block ~line 41; 5 `@mcp.tool()`s appended after `load_drum_kit`, before `# Main execution` ~line 1810)

- [ ] **Step 1: Add the import** (after the `transport_utils` import block, ~line 41)

```python
from ableton_mcp_max.automation_utils import (
    normalize_clip_location,
    normalize_target_type,
    normalize_mixer_target,
    coerce_resolution,
    normalize_breakpoints,
)
```

- [ ] **Step 2: Add a private resolver helper + `get_automation`** (append after `load_drum_kit`, before `# Main execution`)

```python
def _resolve_auto_target(ableton, track_index, target_type, device_index,
                         parameter, mixer_property, send_index):
    """Normalize an automation parameter target. For device targets, resolve a
    parameter name->index via a get_device_parameters round-trip (mirrors
    set_device_parameter). Returns a dict of resolved fields to forward to the
    Remote Script."""
    ttype = normalize_target_type(target_type)
    if ttype == "mixer":
        canonical, sidx = normalize_mixer_target(mixer_property, send_index)
        return {
            "target_type": "mixer",
            "mixer_property": canonical,
            "send_index": sidx,
            "device_index": 0,
            "parameter_index": 0,
        }
    # device: resolve name/index against the live parameter list
    info = ableton.send_command(
        "get_device_parameters",
        {"track_index": track_index, "device_index": device_index},
    )
    plist = info.get("parameters", [])
    idx = resolve_parameter_index(plist, parameter)
    return {
        "target_type": "device",
        "device_index": device_index,
        "parameter_index": idx,
        "mixer_property": "",
        "send_index": -1,
    }


@mcp.tool()
def get_automation(
    ctx: Context,
    track_index: int,
    clip_index: int,
    target_type: str = "device",
    device_index: int = 0,
    parameter: Union[int, str] = 0,
    mixer_property: str = "",
    send_index: int = -1,
    clip_location: str = "session",
    from_time: float = 0.0,
    time_span: float = -1.0,
    resolution: int = 16,
) -> str:
    """
    Read a parameter's automation envelope in a clip as evenly-spaced samples
    (the Live API cannot enumerate breakpoints, only sample value_at_time).

    Parameters:
    - track_index, clip_index: locate the clip
    - clip_location: "session" (default) or "arrangement"
    - target_type: "device" (default) or "mixer"
      - device: device_index + parameter (name or index; rack macros included)
      - mixer: mixer_property in {volume, pan, send} (+ send_index for send)
    - from_time/time_span: sample window in beats (time_span<0 -> whole clip)
    - resolution: number of samples (>=1)
    Returns has_envelope plus a samples=[{time,value}] list.
    """
    try:
        loc = normalize_clip_location(clip_location)
        ableton = get_ableton_connection()
        target = _resolve_auto_target(
            ableton, track_index, target_type, device_index, parameter,
            mixer_property, send_index)
        payload = {
            "track_index": track_index,
            "clip_index": clip_index,
            "clip_location": loc,
            "from_time": from_time,
            "time_span": time_span,
            "resolution": coerce_resolution(resolution),
        }
        payload.update(target)
        result = ableton.send_command("get_automation", payload)
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error reading automation: {str(e)}")
        return f"Error reading automation: {str(e)}"
```

- [ ] **Step 3: Add `set_automation`**

```python
@mcp.tool()
def set_automation(
    ctx: Context,
    track_index: int,
    clip_index: int,
    target_type: str = "device",
    device_index: int = 0,
    parameter: Union[int, str] = 0,
    mixer_property: str = "",
    send_index: int = -1,
    clip_location: str = "session",
    points: List[Dict[str, Any]] = None,
    time: float = None,
    value: float = None,
    duration: float = 0.0,
) -> str:
    """
    Write automation breakpoints into a clip (creating the envelope if absent).

    Provide EITHER a single point (time + value, optional duration) OR a
    `points` list of {time, value, duration?}. duration=0 inserts a single
    breakpoint; duration>0 inserts a flat step of that length. Values are
    clamped to the parameter's range by Live.

    Targeting is identical to get_automation (clip_location, target_type,
    device/mixer fields).
    """
    try:
        loc = normalize_clip_location(clip_location)
        breakpoints = normalize_breakpoints(points, time, value, duration)
        ableton = get_ableton_connection()
        target = _resolve_auto_target(
            ableton, track_index, target_type, device_index, parameter,
            mixer_property, send_index)
        payload = {
            "track_index": track_index,
            "clip_index": clip_index,
            "clip_location": loc,
            "breakpoints": breakpoints,
        }
        payload.update(target)
        result = ableton.send_command("set_automation", payload)
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error setting automation: {str(e)}")
        return f"Error setting automation: {str(e)}"
```

- [ ] **Step 4: Add `clear_automation`**

```python
@mcp.tool()
def clear_automation(
    ctx: Context,
    track_index: int,
    clip_index: int,
    target_type: str = "device",
    device_index: int = 0,
    parameter: Union[int, str] = 0,
    mixer_property: str = "",
    send_index: int = -1,
    clip_location: str = "session",
    from_time: float = None,
    time_span: float = None,
) -> str:
    """
    Clear a parameter's automation in a clip. Pass BOTH from_time and time_span
    to clear only that range; omit both to remove the parameter's whole envelope.

    Targeting is identical to get_automation.
    """
    try:
        loc = normalize_clip_location(clip_location)
        ableton = get_ableton_connection()
        target = _resolve_auto_target(
            ableton, track_index, target_type, device_index, parameter,
            mixer_property, send_index)
        payload = {
            "track_index": track_index,
            "clip_index": clip_index,
            "clip_location": loc,
            "from_time": from_time,
            "time_span": time_span,
        }
        payload.update(target)
        result = ableton.send_command("clear_automation", payload)
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error clearing automation: {str(e)}")
        return f"Error clearing automation: {str(e)}"
```

- [ ] **Step 5: Add `create_automation_envelope`**

```python
@mcp.tool()
def create_automation_envelope(
    ctx: Context,
    track_index: int,
    clip_index: int,
    target_type: str = "device",
    device_index: int = 0,
    parameter: Union[int, str] = 0,
    mixer_property: str = "",
    send_index: int = -1,
    clip_location: str = "session",
) -> str:
    """
    Create an empty automation envelope for a parameter in a clip (no-op if one
    already exists; `created` reports which). Targeting is identical to
    get_automation. Note: set_automation already creates envelopes lazily; use
    this only when you want an empty lane without writing points.
    """
    try:
        loc = normalize_clip_location(clip_location)
        ableton = get_ableton_connection()
        target = _resolve_auto_target(
            ableton, track_index, target_type, device_index, parameter,
            mixer_property, send_index)
        payload = {
            "track_index": track_index,
            "clip_index": clip_index,
            "clip_location": loc,
        }
        payload.update(target)
        result = ableton.send_command("create_automation_envelope", payload)
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error creating automation envelope: {str(e)}")
        return f"Error creating automation envelope: {str(e)}"
```

- [ ] **Step 6: Add `clear_all_automation`**

```python
@mcp.tool()
def clear_all_automation(
    ctx: Context,
    track_index: int,
    clip_index: int,
    clip_location: str = "session",
) -> str:
    """
    Remove every automation envelope in a clip (clip.clear_all_envelopes()).
    """
    try:
        loc = normalize_clip_location(clip_location)
        ableton = get_ableton_connection()
        result = ableton.send_command(
            "clear_all_automation",
            {"track_index": track_index, "clip_index": clip_index,
             "clip_location": loc},
        )
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error clearing all automation: {str(e)}")
        return f"Error clearing all automation: {str(e)}"
```

- [ ] **Step 7: Verify the server still imports**

Run: `cd ~/git/ableton-mcp-max && uv run python -c "import ableton_mcp_max.server"`
Expected: no errors.

- [ ] **Step 8: Commit**

```bash
cd ~/git/ableton-mcp-max
git add ableton_mcp_max/server.py
git commit -m "feat: add 5 automation envelope MCP tools"
```

- [ ] **Step 9: USER ACTION — restart Claude Code** so the 5 new tools load. After restart, load their schemas:
  `ToolSearch select:mcp__AbletonMCPMax__get_automation,mcp__AbletonMCPMax__set_automation,mcp__AbletonMCPMax__clear_automation,mcp__AbletonMCPMax__create_automation_envelope,mcp__AbletonMCPMax__clear_all_automation`

---

### Task 7: Live smoke test + PROGRESS.md + finish branch

Run through the MCP against the open Live set; record PASS/FAIL in `PROGRESS.md`. **Re-read state first** — the open set changes between sessions; do not assume track 0 / specific clips. A Claude-driven Live bounce reopens a BLANK set, so create a scratch MIDI clip + load a device if needed.

- [ ] **Step 1: Establish a target.** `get_session_info` + `get_track_info` to find a track with a device and a clip (or create a scratch MIDI track + clip and load an instrument via `load_instrument_or_effect`).

- [ ] **Step 2: Read with no envelope** — `get_automation` on a fresh param. Expect `has_envelope=false`, `samples=[]`.

- [ ] **Step 3: Write a single breakpoint** — `set_automation track_index=.. clip_index=.. device_index=.. parameter="<name>" time=0 value=<mid>`. Then `get_automation` and confirm `has_envelope=true` and the sample near time 0 ≈ the value.

- [ ] **Step 4: Write a batch curve** — `set_automation ... points=[{time:0,value:0},{time:2,value:1},{time:4,value:0}]`. Re-`get_automation` with `resolution=9` over `[0,4]`; confirm samples rise then fall.

- [ ] **Step 5: Clear a range** — `clear_automation ... from_time=2 time_span=2`; re-read and confirm the later region changed while the start is intact.

- [ ] **Step 6: Full envelope clear** — `clear_automation ...` (no range); re-read → `has_envelope` false (or empty/default samples).

- [ ] **Step 7: create_automation_envelope** — call it on a fresh param; expect `created=true`. Call again; expect `created=false`. Read → `has_envelope=true`.

- [ ] **Step 8: Macro automation** — pick a rack device; `set_automation target_type="device" device_index=<rack> parameter="<macro name or number>" points=[...]`; read back. (Confirms macros automate through the device path.)

- [ ] **Step 9: Mixer volume automation** — `set_automation target_type="mixer" mixer_property="volume" points=[{time:0,value:0.6},{time:4,value:0.9}]`; read back. Then a send: `mixer_property="send" send_index=0`.

- [ ] **Step 10: Arrangement clip** — if the set has an arrangement clip, repeat Step 3 with `clip_location="arrangement"`. **This is the riskiest path** — confirm `arrangement_clips` indexing works; if `arrangement_clips` is missing/raises, note it in PROGRESS.md and flag as a follow-up.

- [ ] **Step 11: clear_all_automation** — on a clip with multiple envelopes, call it; re-read each param → all `has_envelope=false`.

- [ ] **Step 12: Negative cases** — bad `clip_location="timeline"`, `mixer_property="send"` without `send_index`, and empty `points=[]` should each return a clean server-side error with no Live mutation.

- [ ] **Step 13: Restore** — `clear_all_automation` on any scratch clips created; remove scratch tracks/devices if added. Leave the set as found.

- [ ] **Step 14: Update PROGRESS.md** — set the Phase 6 row to Live-verified with date; add a `## Phase 6 tools` section with per-tool checkboxes and live findings (esp. arrangement-clip behavior, `insert_step` auto-create, time units, return-value lag). Update the top "Current focus / Next action" to point at Phase 7 (Change Listeners, stretch) or Phase 4b.

```bash
cd ~/git/ableton-mcp-max
git add PROGRESS.md
git commit -m "docs: mark Phase 6 automation envelopes live-verified"
```

- [ ] **Step 15: Open PR and squash-merge** (after live verification passes)

```bash
cd ~/git/ableton-mcp-max
gh api user --jq .login   # MUST be ringo380
git push -u origin feat/phase6-automation-envelopes
gh pr create --title "Phase 6: Automation Envelopes (5 tools)" --base main \
  --body "Adds get/set/clear automation, create envelope, clear-all across session + arrangement clips for device params, macros, and mixer vol/pan/sends. Offline suite 116/116; live-verified (see PROGRESS.md)."
# after review:
gh pr merge --squash --delete-branch
git remote prune origin
```

---

## Self-Review

**Spec coverage** (against `2026-05-25-phase-6-automation-envelopes-design.md`):
- Sampled read + `has_envelope` → `get_automation` (Task 2/6) ✓
- Device + mixer + macro targets → `_resolve_auto_param` (device path covers macros) + `_resolve_auto_target` (Tasks 2, 6) ✓
- Session + arrangement clips → `_resolve_clip_loc` + `clip_location` arg (Task 2) ✓
- set with single + batch points → `set_automation` + `normalize_breakpoints` (Tasks 1, 3, 6) ✓
- clear range vs full → `clear_automation` (Tasks 4, 6) ✓
- explicit create + clear-all → `create_automation_envelope`, `clear_all_automation` (Tasks 5, 6) ✓
- pure `automation_utils` unit-tested → Task 1 ✓
- live smoke incl. macros, mixer, arrangement, negatives → Task 7 ✓
- flagged unknowns (arrangement_clips, insert_step auto-create, time units, return-value lag) → called out in Task 7 Step 14 + LOM table ✓

**Placeholder scan:** No TBD/TODO. The only runtime `None`/`<name>` placeholders are intentional live-test inputs in Task 7 (depend on the open set) and Python `None` defaults. Code steps all show full code.

**Type/name consistency:** Server forwards `parameter_index` + `mixer_property` + `send_index` + `device_index`; every Remote Script handler reads those exact keys via `_resolve_auto_param(track_index, target_type, device_index, parameter_index, mixer_property, send_index)` — argument order matches all four call sites (Tasks 2–5). `breakpoints` (list of `{time,value,duration}`) is produced by `normalize_breakpoints` (Task 1) and consumed by `_set_automation` (Task 3). Tool/handler/command names align: `get_automation`/`set_automation`/`clear_automation`/`create_automation_envelope`/`clear_all_automation` appear identically in the mutation list, dispatch branches, server `send_command` strings, and `ToolSearch` load line.

**Embedded-Python safety:** Remote Script handlers use `%`-formatting and plain `while`/`for`/`if` — no f-strings or 3.10+ syntax. `value_at_time` sampling uses an explicit `while` loop.
