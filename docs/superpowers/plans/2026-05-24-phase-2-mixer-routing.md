# ableton-mcp-max — Phase 2 Mixer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add mixer control to ableton-mcp-max so Claude can read and set per-track volume, pan, mute, solo, arm, and sends across regular / return / master tracks, plus crossfader assignment. Routing (input/output/monitor) is explicitly deferred to a later Phase 2b.

**Architecture:** Same two halves over localhost:9877 as Phases 0/1. We add **two** consolidated MCP tools (`get_mixer`, `set_mixer_property`) on the server, two matching commands in the Remote Script (`get_mixer` = read, inline; `set_mixer_property` = mutation, scheduled on Live's main thread), and a **pure, unit-tested** helper module `mixer_utils.py` for property-name normalization and track-type/property validation (mirrors the `param_utils` precedent so the Remote Script handler stays trivial and the asymmetry rules are tested offline).

**Tech Stack:** Python 3.10+ (server, via `uv`), Python 3.7-era embedded interpreter (Remote Script, inside Live), MCP `FastMCP`, `pytest` for the offline helper.

**Design decisions (settled with user 2026-05-24):**
- **Consolidated get/set** (not one-tool-per-property): two tools total, name-dispatched, mirroring `set_device_parameter`.
- **Mixer now, routing later**: volume/pan/mute/solo/arm/sends + master + returns + crossfade_assign in Phase 2; input/output routing + monitor state deferred to Phase 2b.

**Branch:** `phase-2-mixer-routing` (off `main` @ 0697bdb). Squash-merge to `main` via PR after live verification.

---

## LOM reference (verified against base code + Live 11)

| Target | Volume | Pan | Mute | Solo | Arm | Sends | Crossfade |
|--------|:------:|:---:|:----:|:----:|:---:|:-----:|:---------:|
| Regular track (`song.tracks[i]`) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ (one per return) | ✓ (`crossfade_assign`) |
| Return track (`song.return_tracks[i]`) | ✓ | ✓ | ✓ | ✓ | ✗ | ✓ | ✓ |
| Master track (`song.master_track`) | ✓ | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ (hosts `crossfader`) |

- `mixer_device.volume` / `mixer_device.panning` are `DeviceParameter`s → use `.value` / `.min` / `.max` (volume 0.0–1.0 where ~0.85 ≈ 0 dB; pan −1.0–1.0).
- `mixer_device.sends` is a list of `DeviceParameter`, indexed parallel to `song.return_tracks`.
- `track.mute` / `.solo` / `.arm` are plain booleans (set with `True`/`False`).
- `mixer_device.crossfade_assign` is quantized: `0 = A`, `1 = None`, `2 = B`.
- Master crossfader value: `song.master_track.mixer_device.crossfader` (out of Phase 2 scope; note only).

---

## File Structure

| File | Responsibility |
|------|----------------|
| `ableton_mcp_max/mixer_utils.py` | **Pure** helpers: normalize a mixer property name; validate (track_type, property) combos; resolve send index. Unit-tested offline. |
| `tests/test_mixer_utils.py` | Offline unit tests for `mixer_utils`. |
| `ableton_mcp_max/server.py` | Add `get_mixer` + `set_mixer_property` `@mcp.tool()`s after `set_device_parameter`. |
| `remote_script/AbletonMCP/__init__.py` | Add `get_mixer` (read) dispatch + handler; add `set_mixer_property` to the main-thread mutation list + handler. |
| `PROGRESS.md` | Mark Phase 2; tool checkboxes; live results. |

---

## Tool contract

```
get_mixer(track_index: int, track_type: str = "regular") -> str   # "regular" | "return" | "master"
  → {track_type, track_index, name, volume{value,min,max}, panning{...},
     mute?, solo?, arm?, crossfade_assign?, sends?: [{index, return_name, value, min, max}]}
  (fields present only where the track type supports them)

set_mixer_property(track_index: int, property: str, value: float,
                   track_type: str = "regular", send_index: int = -1) -> str
  property ∈ {volume, pan, mute, solo, arm, send, crossfade_assign}
  - volume/pan/send: float, clamped to the DeviceParameter's min/max (send requires send_index >= 0)
  - mute/solo/arm: truthy/falsy → bool (value != 0)
  - crossfade_assign: int 0|1|2
  → {track_type, track_index, property, value, [send_index]}
```

`track_index` is ignored for `track_type="master"` (single master) — pass 0.

---

## Phase 2 — Mixer

### Task 2.1: Pure helper `mixer_utils` (TDD)

**Files:**
- Create: `ableton_mcp_max/mixer_utils.py`
- Test: `tests/test_mixer_utils.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_mixer_utils.py
import pytest
from ableton_mcp_max.mixer_utils import normalize_property, validate_property

# --- normalize_property: case/alias folding ---
def test_normalize_canonical():
    assert normalize_property("volume") == "volume"

def test_normalize_case_insensitive():
    assert normalize_property("Volume") == "volume"

def test_normalize_pan_aliases():
    assert normalize_property("pan") == "pan"
    assert normalize_property("panning") == "pan"

def test_normalize_unknown_raises_with_list():
    with pytest.raises(ValueError) as exc:
        normalize_property("nope")
    assert "volume" in str(exc.value)

# --- validate_property: track-type asymmetries ---
def test_regular_supports_all():
    for p in ("volume", "pan", "mute", "solo", "arm", "send", "crossfade_assign"):
        validate_property("regular", p)  # no raise

def test_return_has_no_arm():
    with pytest.raises(ValueError):
        validate_property("return", "arm")

def test_master_has_no_mute_solo_arm_send():
    for p in ("mute", "solo", "arm", "send"):
        with pytest.raises(ValueError):
            validate_property("master", p)

def test_master_allows_volume_pan():
    validate_property("master", "volume")
    validate_property("master", "pan")

def test_unknown_track_type_raises():
    with pytest.raises(ValueError):
        validate_property("bus", "volume")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/git/ableton-mcp-max && uv run --with pytest pytest tests/test_mixer_utils.py -v`
Expected: FAIL — `ModuleNotFoundError: ableton_mcp_max.mixer_utils`.

- [ ] **Step 3: Implement the helper**

```python
# ableton_mcp_max/mixer_utils.py
"""Pure helpers for mixer property handling. No Live dependencies."""

# Canonical property name -> set of aliases (all lowercase).
_ALIASES = {
    "volume": {"volume", "vol"},
    "pan": {"pan", "panning"},
    "mute": {"mute"},
    "solo": {"solo"},
    "arm": {"arm", "record_arm", "rec"},
    "send": {"send"},
    "crossfade_assign": {"crossfade_assign", "crossfade", "xfade"},
}

# Which canonical properties each track type supports.
_SUPPORTED = {
    "regular": {"volume", "pan", "mute", "solo", "arm", "send", "crossfade_assign"},
    "return": {"volume", "pan", "mute", "solo", "send", "crossfade_assign"},
    "master": {"volume", "pan"},
}


def normalize_property(name):
    """Fold an input property name/alias (case-insensitive) to its canonical form.
    Raises ValueError listing the canonical names if unrecognized."""
    lowered = str(name).strip().lower()
    for canonical, aliases in _ALIASES.items():
        if lowered == canonical or lowered in aliases:
            return canonical
    raise ValueError(
        "Unknown mixer property '%s'. Valid: %s"
        % (name, ", ".join(sorted(_ALIASES.keys())))
    )


def validate_property(track_type, canonical_property):
    """Ensure `canonical_property` is supported for `track_type`
    ('regular'|'return'|'master'). Raises ValueError otherwise."""
    if track_type not in _SUPPORTED:
        raise ValueError(
            "Unknown track_type '%s'. Valid: regular, return, master" % track_type
        )
    if canonical_property not in _SUPPORTED[track_type]:
        raise ValueError(
            "Property '%s' not supported on %s tracks. Supported: %s"
            % (canonical_property, track_type,
               ", ".join(sorted(_SUPPORTED[track_type])))
        )
    return canonical_property
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ~/git/ableton-mcp-max && uv run --with pytest pytest tests/test_mixer_utils.py -v`
Expected: all pass (10 tests).

- [ ] **Step 5: Commit**

```bash
cd ~/git/ableton-mcp-max
git add ableton_mcp_max/mixer_utils.py tests/test_mixer_utils.py
git commit -m "feat: add pure mixer property helper with tests"
```

---

### Task 2.2: Remote Script — `_get_mixer` handler (read command)

**Files:**
- Modify: `remote_script/AbletonMCP/__init__.py` (dispatch after the `get_device_parameters` branch ~line 340; handler method near `_get_track_info` ~line 374)

- [ ] **Step 1: Add the dispatch branch** (after the `get_device_parameters` elif, before the final `else`)

```python
            elif command_type == "get_mixer":
                track_index = params.get("track_index", 0)
                track_type = params.get("track_type", "regular")
                response["result"] = self._get_mixer(track_index, track_type)
```

- [ ] **Step 2: Add a track-resolution helper + the `_get_mixer` handler** (near `_get_track_info`)

```python
    def _resolve_track(self, track_index, track_type):
        """Return the Live track object for a (track_index, track_type)."""
        if track_type == "master":
            return self._song.master_track
        if track_type == "return":
            tracks = self._song.return_tracks
        elif track_type == "regular":
            tracks = self._song.tracks
        else:
            raise ValueError("Unknown track_type: " + str(track_type))
        if track_index < 0 or track_index >= len(tracks):
            raise IndexError("Track index out of range for " + track_type)
        return tracks[track_index]

    def _param_dict(self, p):
        return {"value": p.value, "min": p.min, "max": p.max}

    def _get_mixer(self, track_index, track_type):
        """Read mixer state for a regular/return/master track."""
        track = self._resolve_track(track_index, track_type)
        md = track.mixer_device
        result = {
            "track_type": track_type,
            "track_index": track_index,
            "name": track.name,
            "volume": self._param_dict(md.volume),
            "panning": self._param_dict(md.panning),
        }
        # mute/solo/arm: present on regular + return (arm regular-only); not master.
        if track_type in ("regular", "return"):
            result["mute"] = track.mute
            result["solo"] = track.solo
        if track_type == "regular":
            result["arm"] = track.arm
            result["crossfade_assign"] = md.crossfade_assign
        if track_type == "return":
            result["crossfade_assign"] = md.crossfade_assign
        # sends: present on regular + return, parallel to return_tracks.
        if track_type in ("regular", "return"):
            sends = []
            for i, send in enumerate(md.sends):
                return_name = (self._song.return_tracks[i].name
                               if i < len(self._song.return_tracks) else "")
                d = self._param_dict(send)
                d["index"] = i
                d["return_name"] = return_name
                sends.append(d)
            result["sends"] = sends
        return result
```

- [ ] **Step 3: Reinstall the Remote Script and restart Live**

```bash
bash ~/git/ableton-mcp-max/scripts/install_remote_script.sh
```
Then USER ACTION: ⌘Q Live → reopen (Control Surface stays AbletonMCP).

- [ ] **Step 4: Commit**

```bash
cd ~/git/ableton-mcp-max
git add remote_script/AbletonMCP/__init__.py
git commit -m "feat: add get_mixer handler to Remote Script"
```

---

### Task 2.3: Remote Script — `_set_mixer_property` handler (main-thread mutation)

**Files:**
- Modify: `remote_script/AbletonMCP/__init__.py` (modifying-command list ~line 229; `main_thread_task` body after the `set_device_parameter` branch ~line 292; new handler method)

- [ ] **Step 1: Add `set_mixer_property` to the modifying-command list**

Append `"set_mixer_property"` to the `elif command_type in [...]` list (currently ending `..., "set_device_parameter"]`):

```python
            elif command_type in ["create_midi_track", "set_track_name",
                                 "create_clip", "add_notes_to_clip", "set_clip_name",
                                 "set_tempo", "fire_clip", "stop_clip",
                                 "start_playback", "stop_playback", "load_browser_item",
                                 "set_device_parameter", "set_mixer_property"]:
```

- [ ] **Step 2: Add the branch inside `main_thread_task`** (after the `set_device_parameter` branch)

```python
                        elif command_type == "set_mixer_property":
                            track_index = params.get("track_index", 0)
                            track_type = params.get("track_type", "regular")
                            prop = params.get("property", "")
                            value = params.get("value", 0.0)
                            send_index = params.get("send_index", -1)
                            result = self._set_mixer_property(
                                track_index, track_type, prop, value, send_index)
```

- [ ] **Step 3: Add the handler method**

```python
    def _clamp_param(self, param, value):
        v = float(value)
        if v < param.min:
            v = param.min
        if v > param.max:
            v = param.max
        param.value = v
        return param.value

    def _set_mixer_property(self, track_index, track_type, prop, value, send_index):
        """Set one mixer property. `prop` is already a canonical name
        (server normalizes/validates via mixer_utils before sending)."""
        track = self._resolve_track(track_index, track_type)
        md = track.mixer_device
        out = {"track_type": track_type, "track_index": track_index, "property": prop}

        if prop == "volume":
            out["value"] = self._clamp_param(md.volume, value)
        elif prop == "pan":
            out["value"] = self._clamp_param(md.panning, value)
        elif prop == "send":
            if send_index < 0 or send_index >= len(md.sends):
                raise IndexError("send_index out of range")
            out["value"] = self._clamp_param(md.sends[send_index], value)
            out["send_index"] = send_index
        elif prop == "mute":
            track.mute = bool(value)
            out["value"] = track.mute
        elif prop == "solo":
            track.solo = bool(value)
            out["value"] = track.solo
        elif prop == "arm":
            track.arm = bool(value)
            out["value"] = track.arm
        elif prop == "crossfade_assign":
            md.crossfade_assign = int(value)
            out["value"] = md.crossfade_assign
        else:
            raise ValueError("Unsupported mixer property: " + str(prop))
        return out
```

- [ ] **Step 4: Reinstall + restart Live**

```bash
bash ~/git/ableton-mcp-max/scripts/install_remote_script.sh
```
USER ACTION: ⌘Q Live → reopen.

- [ ] **Step 5: Commit**

```bash
cd ~/git/ableton-mcp-max
git add remote_script/AbletonMCP/__init__.py
git commit -m "feat: add set_mixer_property handler to Remote Script"
```

---

### Task 2.4: Server — `get_mixer` and `set_mixer_property` tools

**Files:**
- Modify: `ableton_mcp_max/server.py` (add import near line 10; two `@mcp.tool()`s after `set_device_parameter`)

- [ ] **Step 1: Add the import** (next to the existing `param_utils` import, ~line 10)

```python
from ableton_mcp_max.mixer_utils import normalize_property, validate_property
```

- [ ] **Step 2: Add the `get_mixer` tool**

```python
@mcp.tool()
def get_mixer(ctx: Context, track_index: int, track_type: str = "regular") -> str:
    """
    Read mixer state (volume, pan, mute, solo, arm, sends, crossfade assign)
    for a track. Fields are present only where the track type supports them.

    Parameters:
    - track_index: index of the track (ignored for master; pass 0)
    - track_type: "regular" (default), "return", or "master"
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command(
            "get_mixer",
            {"track_index": track_index, "track_type": track_type},
        )
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting mixer state: {str(e)}")
        return f"Error getting mixer state: {str(e)}"
```

- [ ] **Step 3: Add the `set_mixer_property` tool**

```python
@mcp.tool()
def set_mixer_property(
    ctx: Context,
    track_index: int,
    property: str,
    value: float,
    track_type: str = "regular",
    send_index: int = -1,
) -> str:
    """
    Set a single mixer property on a track.

    Parameters:
    - track_index: index of the track (ignored for master; pass 0)
    - property: one of volume, pan, mute, solo, arm, send, crossfade_assign
      (aliases accepted: panning, vol, xfade, ...)
    - value: continuous params (volume/pan/send) are clamped to range;
      mute/solo/arm take 0/1; crossfade_assign takes 0=A, 1=None, 2=B
    - track_type: "regular" (default), "return", or "master"
    - send_index: required when property="send" (index of the return-track send)
    """
    try:
        canonical = normalize_property(property)
        validate_property(track_type, canonical)
        if canonical == "send" and send_index < 0:
            return "Error: property 'send' requires send_index >= 0"
        ableton = get_ableton_connection()
        result = ableton.send_command(
            "set_mixer_property",
            {
                "track_index": track_index,
                "track_type": track_type,
                "property": canonical,
                "value": value,
                "send_index": send_index,
            },
        )
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error setting mixer property: {str(e)}")
        return f"Error setting mixer property: {str(e)}"
```

- [ ] **Step 4: Verify the server still imports**

Run: `cd ~/git/ableton-mcp-max && uv run python -c "import ableton_mcp_max.server"`
Expected: no errors.

- [ ] **Step 5: USER ACTION — restart Claude Code** so the two new tools load.

- [ ] **Step 6: Commit**

```bash
cd ~/git/ableton-mcp-max
git add ableton_mcp_max/server.py
git commit -m "feat: add get/set_mixer MCP tools"
```

---

### Task 2.5: Live smoke test

Run through the MCP against the open Live set; record PASS/FAIL in `PROGRESS.md`. Restore any changed values.

- [ ] **Step 1: Read mixer for a regular track** — `get_mixer track_index=0`. Expect volume/pan/mute/solo/arm/crossfade_assign + a `sends` array sized to the 2 return tracks.
- [ ] **Step 2: Read a return track** — `get_mixer track_index=0 track_type="return"`. Expect volume/pan/mute/solo/sends, **no arm**.
- [ ] **Step 3: Read master** — `get_mixer track_type="master"`. Expect volume/pan only.
- [ ] **Step 4: Set continuous** — `set_mixer_property track_index=0 property="volume" value=0.7`; confirm echo + visible fader move. Then `pan` to 0.3 and back.
- [ ] **Step 5: Set toggle** — `set_mixer_property track_index=0 property="mute" value=1`, verify, then `value=0`.
- [ ] **Step 6: Set a send** — `set_mixer_property track_index=0 property="send" value=0.5 send_index=0`; verify echo.
- [ ] **Step 7: Negative checks** — `arm` on a `return` track and `mute` on `master` should return clean validation errors (server-side, no Live mutation).
- [ ] **Step 8: Restore** all changed values to originals captured in Steps 1–3.

---

### Task 2.6: Update PROGRESS.md + finish branch

- [ ] **Step 1: Update PROGRESS.md** — set Phase 2 row to Live-verified with date; add a Phase 2 tools section:

```markdown
## Phase 2 tools
- [x] mixer_utils.normalize_property / validate_property (offline unit tests)
- [ ] get_mixer (live verify)
- [ ] set_mixer_property (live verify)
```
Update the top "Current focus / Next action" to point at Phase 3 (Clip & MIDI Editing). Record any mixer reachability quirks observed.

- [ ] **Step 2: Commit**

```bash
cd ~/git/ableton-mcp-max
git add PROGRESS.md
git commit -m "docs: mark Phase 2 mixer live-verified"
```

- [ ] **Step 3: Open PR and squash-merge** (after live verification passes)

```bash
git push -u origin phase-2-mixer-routing
gh pr create --title "Phase 2: Mixer control" --body "..." --base main
# after review:
gh pr merge --squash --delete-branch
```

---

## Self-Review

**Spec coverage (Phase 2 = "Get/set volume, pan, mute, solo, arm per track; sends to returns; master track; crossfader assign; return tracks"):**
- volume/pan/mute/solo/arm per track → Tasks 2.2–2.4 ✓
- sends to returns → `sends` in `_get_mixer`, `send` property in `_set_mixer_property` ✓
- master track → `track_type="master"` path ✓
- return tracks → `track_type="return"` path ✓
- crossfader assign → `crossfade_assign` property ✓
- input/output routing + monitor → **deferred to Phase 2b** (explicit, settled with user) ✓

**Pattern consistency:** Two consolidated tools mirror `set_device_parameter`'s name-dispatch shape. Read command runs inline; mutation goes through the existing `main_thread_task` queue (preserves the base's main-thread scheduling — critical per spec risk note). Pure validation lives in `mixer_utils`, unit-tested offline, exactly like `param_utils`.

**Track-type asymmetry handled twice (defense in depth):** server validates (track_type, property) via `mixer_utils.validate_property` before sending; Remote Script's `_resolve_track` + per-property branches also guard (e.g. `track.arm` is simply never reached for return/master because the server rejects it first, and `_resolve_track` raises on bad indices). Negative smoke tests (Task 2.5 Step 7) confirm.

**Embedded-Python safety:** handlers use `%`-formatting and plain `for`/`if` — no f-strings or 3.10+ syntax in the Remote Script.

**Placeholder scan:** no TBD/TODO; PR body `"..."` is the only intentional fill-in (depends on live results).
