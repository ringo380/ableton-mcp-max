# ableton-mcp-max — Phase 2b Routing Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans / subagent-driven-development. Steps use `- [ ]` checkboxes.

**Goal:** Add input/output routing + input monitoring control, completing the "& Routing" half of Phase 2. Two consolidated MCP tools (`get_routing`, `set_routing`) + matching Remote Script commands + a pure unit-tested `routing_utils` helper. Lands on the existing `phase-2-mixer-routing` branch (PR #1).

**Architecture:** Same as Phase 2. Read inline (`get_routing`); mutation on the main thread (`set_routing`). Live's routing endpoints are **objects** (`RoutingType`/`RoutingChannel` with `.display_name` + `.identifier`), assigned from `available_*` lists — never raw strings. The pure helper resolves a user-supplied display-name/identifier against an available list and validates the track-type asymmetry, keeping the handler trivial.

**Design decisions:**
- Consolidated get/set, mirroring `get_mixer`/`set_mixer_property`.
- Routing endpoints addressed by **display_name** (case-insensitive) or integer identifier; monitor by int (0=In, 1=Auto, 2=Off).
- Track-type asymmetry: regular = input_type/input_channel/output_type/output_channel/monitor; return & master = output_type/output_channel only.
- Defensive `hasattr`/try guards in the read handler so a track lacking an endpoint omits the field rather than crashing (empirical-discovery posture from the spec).

---

## LOM reference (Live 10.1+ object routing)

| Endpoint | Read | Set |
|----------|------|-----|
| Input type | `track.input_routing_type.display_name` | assign obj from `track.available_input_routing_types` |
| Input channel | `track.input_routing_channel.display_name` | assign obj from `track.available_input_routing_channels` |
| Output type | `track.output_routing_type.display_name` | assign obj from `track.available_output_routing_types` |
| Output channel | `track.output_routing_channel.display_name` | assign obj from `track.available_output_routing_channels` |
| Monitor | `track.current_monitoring_state` (int) | assign int 0/1/2 |

- Each available entry exposes `.display_name` (str) and `.identifier` (int).
- Return/master tracks lack input routing + monitoring (guarded).

---

## File Structure

| File | Responsibility |
|------|----------------|
| `ableton_mcp_max/routing_utils.py` | **Pure**: `normalize_routing_property`, `validate_routing_property`, `resolve_routing_choice`. Unit-tested. |
| `tests/test_routing_utils.py` | Offline unit tests. |
| `ableton_mcp_max/server.py` | `get_routing` + `set_routing` tools after `set_mixer_property`. |
| `remote_script/AbletonMCP/__init__.py` | `get_routing` (read) dispatch+handler; `set_routing` (mutation) list+branch+handler. |
| `PROGRESS.md` | Phase 2b status + tools. |

---

## Tool contract

```
get_routing(track_index: int, track_type: str = "regular") -> str
  → {track_type, track_index, name,
     input_type?: {current, available: [display_name,...]},
     input_channel?: {...}, output_type: {...}, output_channel: {...},
     monitoring_state?: int}     # fields present per track type

set_routing(track_index: int, property: str, value, track_type: str = "regular") -> str
  property ∈ {input_type, input_channel, output_type, output_channel, monitor}
  - routing props: value = display_name (str, case-insensitive) or int identifier
  - monitor: value = int 0|1|2
  → {track_type, track_index, property, value}
```

---

## Tasks

### Task 2b.1: Pure helper `routing_utils` (TDD)

- [ ] **Step 1: Failing tests** — `tests/test_routing_utils.py`

```python
import pytest
from ableton_mcp_max.routing_utils import (
    normalize_routing_property, validate_routing_property, resolve_routing_choice,
)

AVAIL = [
    {"display_name": "Ext. In", "identifier": 17},
    {"display_name": "Resampling", "identifier": 18},
    {"display_name": "1-Wavetable", "identifier": 5},
]

def test_normalize_aliases():
    assert normalize_routing_property("input_type") == "input_type"
    assert normalize_routing_property("in_type") == "input_type"
    assert normalize_routing_property("monitor") == "monitor"
    assert normalize_routing_property("Output Channel") == "output_channel"

def test_normalize_unknown_raises():
    with pytest.raises(ValueError):
        normalize_routing_property("sidechain")

def test_validate_regular_all():
    for p in ("input_type","input_channel","output_type","output_channel","monitor"):
        validate_routing_property("regular", p)

def test_validate_return_output_only():
    validate_routing_property("return", "output_type")
    with pytest.raises(ValueError):
        validate_routing_property("return", "input_type")
    with pytest.raises(ValueError):
        validate_routing_property("return", "monitor")

def test_validate_master_output_only():
    validate_routing_property("master", "output_channel")
    with pytest.raises(ValueError):
        validate_routing_property("master", "input_type")

def test_resolve_by_display_name():
    assert resolve_routing_choice(AVAIL, "Resampling")["identifier"] == 18

def test_resolve_case_insensitive():
    assert resolve_routing_choice(AVAIL, "ext. in")["identifier"] == 17

def test_resolve_by_identifier_int():
    assert resolve_routing_choice(AVAIL, 5)["display_name"] == "1-Wavetable"

def test_resolve_unknown_lists_available():
    with pytest.raises(ValueError) as exc:
        resolve_routing_choice(AVAIL, "Nope")
    assert "Resampling" in str(exc.value)
```

- [ ] **Step 2: Run — expect fail (ModuleNotFoundError).**

- [ ] **Step 3: Implement** — `ableton_mcp_max/routing_utils.py`

```python
"""Pure helpers for track routing. No Live dependencies."""

_ALIASES = {
    "input_type": {"input_type", "in_type", "input"},
    "input_channel": {"input_channel", "in_channel", "in_chan"},
    "output_type": {"output_type", "out_type", "output"},
    "output_channel": {"output_channel", "out_channel", "out_chan"},
    "monitor": {"monitor", "monitoring", "current_monitoring_state"},
}

_SUPPORTED = {
    "regular": {"input_type", "input_channel", "output_type", "output_channel", "monitor"},
    "return": {"output_type", "output_channel"},
    "master": {"output_type", "output_channel"},
}


def normalize_routing_property(name):
    lowered = str(name).strip().lower().replace(" ", "_")
    for canonical, aliases in _ALIASES.items():
        if lowered == canonical or lowered in aliases:
            return canonical
    raise ValueError(
        "Unknown routing property '%s'. Valid: %s"
        % (name, ", ".join(sorted(_ALIASES.keys())))
    )


def validate_routing_property(track_type, canonical_property):
    if track_type not in _SUPPORTED:
        raise ValueError(
            "Unknown track_type '%s'. Valid: regular, return, master" % track_type
        )
    if canonical_property not in _SUPPORTED[track_type]:
        raise ValueError(
            "Routing property '%s' not supported on %s tracks. Supported: %s"
            % (canonical_property, track_type,
               ", ".join(sorted(_SUPPORTED[track_type])))
        )
    return canonical_property


def resolve_routing_choice(available, identifier):
    """Match `identifier` (display_name str, or int/numeric identifier) against
    a list of {display_name, identifier} dicts. Returns the matched dict."""
    is_numeric_str = isinstance(identifier, str) and identifier.lstrip("-").isdigit()
    if isinstance(identifier, int) or is_numeric_str:
        ident = int(identifier)
        for c in available:
            if c.get("identifier") == ident:
                return c
    else:
        lowered = str(identifier).strip().lower()
        for c in available:
            if str(c.get("display_name", "")).lower() == lowered:
                return c
    names = ", ".join(str(c.get("display_name", "")) for c in available)
    raise ValueError("Routing choice '%s' not found. Available: %s" % (identifier, names))
```

- [ ] **Step 4: Run — expect pass.** **Step 5: Commit** `feat: add pure routing helper with tests`.

---

### Task 2b.2: Remote Script — `get_routing` (read)

- [ ] **Step 1: Dispatch branch** (after the `get_mixer` elif)

```python
            elif command_type == "get_routing":
                track_index = params.get("track_index", 0)
                track_type = params.get("track_type", "regular")
                response["result"] = self._get_routing(track_index, track_type)
```

- [ ] **Step 2: Handler** (after `_get_mixer`, reusing `_resolve_track`)

```python
    def _routing_endpoint(self, track, current_attr, available_attr):
        """Return {current, available:[display_name,...]} for a routing endpoint,
        or None if the track lacks it."""
        if not hasattr(track, current_attr) or not hasattr(track, available_attr):
            return None
        try:
            current = getattr(track, current_attr)
            current_name = current.display_name if current is not None else None
            available = [c.display_name for c in getattr(track, available_attr)]
            return {"current": current_name, "available": available}
        except Exception:
            return None

    def _get_routing(self, track_index, track_type):
        track = self._resolve_track(track_index, track_type)
        result = {"track_type": track_type, "track_index": track_index, "name": track.name}
        it = self._routing_endpoint(track, "input_routing_type", "available_input_routing_types")
        ic = self._routing_endpoint(track, "input_routing_channel", "available_input_routing_channels")
        ot = self._routing_endpoint(track, "output_routing_type", "available_output_routing_types")
        oc = self._routing_endpoint(track, "output_routing_channel", "available_output_routing_channels")
        if it is not None:
            result["input_type"] = it
        if ic is not None:
            result["input_channel"] = ic
        if ot is not None:
            result["output_type"] = ot
        if oc is not None:
            result["output_channel"] = oc
        if hasattr(track, "current_monitoring_state"):
            try:
                result["monitoring_state"] = track.current_monitoring_state
            except Exception:
                pass
        return result
```

- [ ] **Step 3: Commit** `feat: add get_routing handler to Remote Script` (reinstall batched with 2b.3).

---

### Task 2b.3: Remote Script — `set_routing` (mutation)

- [ ] **Step 1: Add `"set_routing"` to the modifying-command `elif command_type in [...]` list.**

- [ ] **Step 2: Branch in `main_thread_task`** (after `set_mixer_property`)

```python
                        elif command_type == "set_routing":
                            track_index = params.get("track_index", 0)
                            track_type = params.get("track_type", "regular")
                            prop = params.get("property", "")
                            value = params.get("value", None)
                            result = self._set_routing(track_index, track_type, prop, value)
```

- [ ] **Step 3: Handler**

```python
    def _assign_routing(self, track, current_attr, available_attr, value):
        """Match value (display_name or identifier) against the available list
        and assign the matching object to current_attr."""
        available = list(getattr(track, available_attr))
        chosen = None
        is_num = isinstance(value, int) or (
            isinstance(value, str) and value.lstrip("-").isdigit())
        if is_num:
            ident = int(value)
            for c in available:
                if c.identifier == ident:
                    chosen = c
                    break
        else:
            lowered = str(value).strip().lower()
            for c in available:
                if c.display_name.lower() == lowered:
                    chosen = c
                    break
        if chosen is None:
            names = ", ".join(c.display_name for c in available)
            raise ValueError("Routing choice '%s' not found. Available: %s"
                             % (value, names))
        setattr(track, current_attr, chosen)
        return chosen.display_name

    def _set_routing(self, track_index, track_type, prop, value):
        track = self._resolve_track(track_index, track_type)
        out = {"track_type": track_type, "track_index": track_index, "property": prop}
        if prop == "input_type":
            out["value"] = self._assign_routing(track, "input_routing_type",
                                                 "available_input_routing_types", value)
        elif prop == "input_channel":
            out["value"] = self._assign_routing(track, "input_routing_channel",
                                                 "available_input_routing_channels", value)
        elif prop == "output_type":
            out["value"] = self._assign_routing(track, "output_routing_type",
                                                 "available_output_routing_types", value)
        elif prop == "output_channel":
            out["value"] = self._assign_routing(track, "output_routing_channel",
                                                 "available_output_routing_channels", value)
        elif prop == "monitor":
            track.current_monitoring_state = int(value)
            out["value"] = track.current_monitoring_state
        else:
            raise ValueError("Unsupported routing property: " + str(prop))
        return out
```

- [ ] **Step 4: Reinstall** (`bash scripts/install_remote_script.sh`) — batched single restart. **Step 5: Commit** `feat: add set_routing handler to Remote Script`.

---

### Task 2b.4: Server — `get_routing` + `set_routing` tools

- [ ] **Step 1: Import** `from ableton_mcp_max.routing_utils import normalize_routing_property, validate_routing_property`
- [ ] **Step 2: `get_routing` tool** (passes through to the `get_routing` command).
- [ ] **Step 3: `set_routing` tool** — normalize + validate property server-side, then dispatch:

```python
@mcp.tool()
def set_routing(
    ctx: Context,
    track_index: int,
    property: str,
    value: Union[int, str],
    track_type: str = "regular",
) -> str:
    """
    Set an input/output routing endpoint or input monitoring on a track.

    Parameters:
    - track_index: index of the track (ignored for master; pass 0)
    - property: input_type, input_channel, output_type, output_channel, or monitor
    - value: for routing props, the target's display_name (str) or integer
      identifier; for monitor, an int (0=In, 1=Auto, 2=Off)
    - track_type: "regular" (default), "return", or "master"
      (return/master support output_type/output_channel only)
    """
    try:
        canonical = normalize_routing_property(property)
        validate_routing_property(track_type, canonical)
        ableton = get_ableton_connection()
        result = ableton.send_command(
            "set_routing",
            {"track_index": track_index, "track_type": track_type,
             "property": canonical, "value": value},
        )
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error setting routing: {str(e)}")
        return f"Error setting routing: {str(e)}"
```

- [ ] **Step 4:** `uv run python -c "import ableton_mcp_max.server"` — clean. **Step 5: USER restart Live + Claude Code.** **Step 6: Commit** `feat: add get/set_routing MCP tools`.

---

### Task 2b.5: Live smoke test

- [ ] Read routing for a regular track — expect input_type/channel + output_type/channel (`available` lists populated) + monitoring_state.
- [ ] Read a return + master — expect output_type/channel only, no input, no monitoring.
- [ ] Set `monitor` to 2 (Off) then back to 1 (Auto); verify echo.
- [ ] Set `output_type` to another available display_name and back; verify echo + visible change in Live.
- [ ] Negative: `input_type` on a return → clean server-side validation error; bogus display_name → "Available: ..." error.
- [ ] Restore all changed values.

---

### Task 2b.6: PROGRESS + PR

- [ ] Mark Phase 2b Live-verified; add Phase 2b tools section. Commit `docs: mark Phase 2b routing live-verified`.
- [ ] Push; PR #1 (phase-2-mixer-routing) now contains mixer + routing. Squash-merge when ready.

---

## Self-Review
- Spec "input/output routing + monitor state" → Tasks 2b.2–2b.4 ✓
- Object-assignment model (not raw strings) handled in `_assign_routing` + `resolve_routing_choice` ✓
- Track-type asymmetry validated server-side (`routing_utils`) and guarded in read handler (`hasattr`) ✓
- Embedded-Python safety: `%`-formatting, no f-strings/3.10 syntax in Remote Script ✓
- Pure logic unit-tested offline; live shape confirmed empirically in 2b.5 ✓
