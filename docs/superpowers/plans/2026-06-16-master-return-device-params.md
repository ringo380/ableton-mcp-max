# Master/return device-parameter access Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let `get_device_parameters` and `set_device_parameter` read/write devices on return and master tracks via a `track_type` argument, matching the convention already used by `get_device_info` / `set_device_on` / `set_chain_property`.

**Architecture:** Server tools gain a `track_type="regular"` arg forwarded in the command payload (offline-testable with a mocked connection). The two Remote Script handlers swap their hardcoded `self._song.tracks[track_index]` lookup for the existing `_resolve_device(track_index, device_index, track_type)` helper, and the two dispatch sites read `track_type` from params. Fully backward-compatible (default `"regular"`).

**Tech Stack:** Python (FastMCP server-side; Live embedded Py2/3.7-safe Remote Script), pytest + py_compile offline gate, `uv` runner.

**Spec:** `docs/superpowers/specs/2026-06-16-master-return-device-params-design.md`

**Test runner (note the PATH - the clobber workaround drops `uv`):**
`PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q`

---

### Task 1: Server-side `track_type` pass-through (offline-testable)

Both server tools accept `track_type` and forward it. `set_device_parameter` has a pre-fetch `get_device_parameters` call (to resolve a name -> index) that MUST also carry `track_type`, or name resolution reads the wrong track's device.

**Files:**
- Test: `tests/test_device_params_track_type.py` (create)
- Modify: `ableton_mcp_max/server.py` (`get_device_parameters` ~1422-1449, `set_device_parameter` ~1450-1493)

- [ ] **Step 1: Write the failing test**

Create `tests/test_device_params_track_type.py`:

```python
"""Server-side tests: get_device_parameters / set_device_parameter forward
track_type into the command payload (incl. the name-resolution pre-fetch in
set_device_parameter). Connection is mocked - no Live needed."""
import json

from ableton_mcp_max import server


class _RecordingConn:
    """Records every send_command call. Returns a one-parameter device list
    for get_device_parameters so name->index resolution works."""

    def __init__(self):
        self.calls = []

    def send_command(self, cmd, params=None):
        self.calls.append((cmd, params or {}))
        if cmd == "get_device_parameters":
            return {
                "device_name": "Reverb",
                "parameters": [
                    {"index": 0, "name": "Device On", "value": 1.0,
                     "min": 0.0, "max": 1.0, "is_quantized": True},
                    {"index": 1, "name": "Decay Time", "value": 0.5,
                     "min": 0.0, "max": 1.0, "is_quantized": False},
                ],
            }
        return {"ok": True}


def test_get_device_parameters_defaults_to_regular(monkeypatch):
    conn = _RecordingConn()
    monkeypatch.setattr(server, "get_ableton_connection", lambda: conn)
    out = json.loads(server.get_device_parameters(None, 0, 0))
    assert out["ok"] is True
    cmd, params = conn.calls[0]
    assert cmd == "get_device_parameters"
    assert params["track_type"] == "regular"


def test_get_device_parameters_forwards_master(monkeypatch):
    conn = _RecordingConn()
    monkeypatch.setattr(server, "get_ableton_connection", lambda: conn)
    server.get_device_parameters(None, 0, 0, track_type="master")
    assert conn.calls[0][1]["track_type"] == "master"


def test_set_device_parameter_forwards_track_type_to_both_calls(monkeypatch):
    conn = _RecordingConn()
    monkeypatch.setattr(server, "get_ableton_connection", lambda: conn)
    out = json.loads(
        server.set_device_parameter(None, 0, 0, "Decay Time", 0.8,
                                    track_type="return")
    )
    assert out["ok"] is True
    # First call = pre-fetch to resolve the name; second = the actual set.
    prefetch = next(c for c in conn.calls if c[0] == "get_device_parameters")
    setcall = next(c for c in conn.calls if c[0] == "set_device_parameter")
    assert prefetch[1]["track_type"] == "return"
    assert setcall[1]["track_type"] == "return"
    # Name resolved to the right index from the mocked list.
    assert setcall[1]["parameter_index"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_device_params_track_type.py -q`
Expected: FAIL - `TypeError: ... got an unexpected keyword argument 'track_type'` (tools don't accept it yet), or KeyError on `params["track_type"]`.

- [ ] **Step 3: Implement - edit `get_device_parameters`**

Replace the current `get_device_parameters` (server.py ~1422-1449) with:

```python
def get_device_parameters(
    ctx: Context, track_index: int, device_index: int, track_type: str = "regular"
) -> str:
    """
    List all automatable parameters of a device on a track, with current
    value, min, max, whether it's quantized, and (for quantized params) the
    list of selectable value items.

    Parameters:
    - track_index: index of the track (ignored for master)
    - device_index: index of the device on that track (0 = first device)
    - track_type: 'regular' (default), 'return', or 'master'

    Returns JSON with the device name and a parameters list (each: index, name,
    value, min, max, is_quantized, value_items).
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command(
            "get_device_parameters",
            {
                "track_index": track_index,
                "device_index": device_index,
                "track_type": track_type,
            },
        )
        return _ok(result)
    except Exception as e:
        logger.error(f"Error getting device parameters: {str(e)}")
        return _err(f"Error getting device parameters: {str(e)}")
```

- [ ] **Step 4: Implement - edit `set_device_parameter`**

Replace the current `set_device_parameter` (server.py ~1450-1493) with:

```python
def set_device_parameter(
    ctx: Context,
    track_index: int,
    device_index: int,
    parameter: Union[int, str],
    value: float,
    track_type: str = "regular",
) -> str:
    """
    Set a single device/instrument parameter.

    Parameters:
    - track_index: index of the track (ignored for master)
    - device_index: index of the device on that track
    - parameter: parameter index (int) OR parameter name (str, case-insensitive)
    - value: target value (clamped to the parameter's min/max). For quantized
      parameters, pass the integer index of the desired value item.
    - track_type: 'regular' (default), 'return', or 'master'
    """
    try:
        ableton = get_ableton_connection()
        # Fetch the parameter list to resolve name->index and validate.
        info = ableton.send_command(
            "get_device_parameters",
            {
                "track_index": track_index,
                "device_index": device_index,
                "track_type": track_type,
            },
        )
        params = info.get("parameters", [])
        idx = resolve_parameter_index(params, parameter)
        result = ableton.send_command(
            "set_device_parameter",
            {
                "track_index": track_index,
                "device_index": device_index,
                "parameter_index": idx,
                "value": value,
                "track_type": track_type,
            },
        )
        return _ok(result)
    except Exception as e:
        logger.error(f"Error setting device parameter: {str(e)}")
        return _err(f"Error setting device parameter: {str(e)}")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_device_params_track_type.py -q`
Expected: PASS (3 passed).

- [ ] **Step 6: Verify the server still imports**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python -c "import ableton_mcp_max.server"`
Expected: no output, exit 0.

- [ ] **Step 7: Commit**

```bash
git add tests/test_device_params_track_type.py ableton_mcp_max/server.py
git commit -m "feat(devices): track_type on get/set_device_parameter (server side)"
```

---

### Task 2: Remote Script handlers + dispatch (master/return resolution)

The handlers currently hardcode `self._song.tracks[track_index]`. Swap to the existing `_resolve_device` helper and thread `track_type` from the two dispatch sites. This half runs in Live's interpreter and cannot be unit-tested offline; correctness is gated by `py_compile` here and live verification in Task 4.

**Files:**
- Modify: `remote_script/AbletonMCP/__init__.py`
  - `_get_device_parameters` (~1225-1258)
  - `_set_device_parameter` (~1260-1287)
  - dispatch: `get_device_parameters` (~729-732), `set_device_parameter` (~279-285)

- [ ] **Step 1: Edit `_get_device_parameters` to use `_resolve_device`**

Replace the handler body header (the index check + track/device lookup) so the method becomes:

```python
    def _get_device_parameters(self, track_index, device_index, track_type="regular"):
        """List all automatable parameters of a device on a track."""
        track, device = self._resolve_device(track_index, device_index, track_type)

        parameters = []
        for p_index, param in enumerate(device.parameters):
            info = {
                "index": p_index,
                "name": param.name,
                "value": param.value,
                "min": param.min,
                "max": param.max,
                "is_quantized": param.is_quantized,
                "is_enabled": param.is_enabled,
            }
            if param.is_quantized and hasattr(param, "value_items"):
                try:
                    info["value_items"] = [str(v) for v in param.value_items]
                except Exception:
                    pass
            parameters.append(info)

        return {
            "track_index": track_index,
            "track_type": track_type,
            "device_index": device_index,
            "device_name": device.name,
            "parameter_count": len(parameters),
            "parameters": parameters,
        }
```

(This removes the old `if track_index < 0 or track_index >= len(self._song.tracks): ...` block and the `track = self._song.tracks[track_index]` / device bounds check, which `_resolve_device` now handles. Adds `"track_type"` to the result, matching `_get_device_info`.)

- [ ] **Step 2: Edit `_set_device_parameter` to use `_resolve_device`**

Replace the method so it becomes:

```python
    def _set_device_parameter(self, track_index, device_index, parameter_index, value,
                              track_type="regular"):
        """Set one device parameter by integer index, clamped to its range."""
        track, device = self._resolve_device(track_index, device_index, track_type)
        if parameter_index < 0 or parameter_index >= len(device.parameters):
            raise IndexError("Parameter index out of range")
        param = device.parameters[parameter_index]
        if not param.is_enabled:
            raise RuntimeError("Parameter '%s' is not settable (disabled)" % param.name)

        v = float(value)
        if v < param.min:
            v = param.min
        if v > param.max:
            v = param.max
        param.value = v

        return {
            "track_index": track_index,
            "track_type": track_type,
            "device_index": device_index,
            "parameter_index": parameter_index,
            "name": param.name,
            "value": param.value,
        }
```

- [ ] **Step 3: Edit the `get_device_parameters` dispatch site**

In the read-dispatch block (~729-732), change:

```python
            elif command_type == "get_device_parameters":
                track_index = params.get("track_index", 0)
                device_index = params.get("device_index", 0)
                response["result"] = self._get_device_parameters(track_index, device_index)
```

to:

```python
            elif command_type == "get_device_parameters":
                track_index = params.get("track_index", 0)
                device_index = params.get("device_index", 0)
                track_type = params.get("track_type", "regular")
                response["result"] = self._get_device_parameters(
                    track_index, device_index, track_type)
```

- [ ] **Step 4: Edit the `set_device_parameter` dispatch site**

In the mutation-dispatch block (~279-285), change:

```python
        elif command_type == "set_device_parameter":
            track_index = params.get("track_index", 0)
            device_index = params.get("device_index", 0)
            parameter_index = params.get("parameter_index", 0)
            value = params.get("value", 0.0)
            result = self._set_device_parameter(
                track_index, device_index, parameter_index, value)
```

to:

```python
        elif command_type == "set_device_parameter":
            track_index = params.get("track_index", 0)
            device_index = params.get("device_index", 0)
            parameter_index = params.get("parameter_index", 0)
            value = params.get("value", 0.0)
            track_type = params.get("track_type", "regular")
            result = self._set_device_parameter(
                track_index, device_index, parameter_index, value, track_type)
```

(No change needed to the mutation membership list at ~640; `"set_device_parameter"` is already present.)

- [ ] **Step 5: Verify the Remote Script compiles (Py2/3.7-safe)**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python -m py_compile remote_script/AbletonMCP/__init__.py`
Expected: no output, exit 0.

- [ ] **Step 6: Commit**

```bash
git add remote_script/AbletonMCP/__init__.py
git commit -m "feat(devices): resolve master/return devices in param handlers"
```

---

### Task 3: Regenerate docs

The two tools have new signatures; regenerate the generated tool docs. No tool count changes, so the hand-edited `docs/index.md` hero counts stay as-is.

**Files:**
- Modify (generated): `docs/tools/devices-racks.md`, `docs/tools/index.md`, `commands/tool-index.md`

- [ ] **Step 1: Run the doc generators**

Run:
```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python scripts/build_tool_index.py
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python scripts/gen_docs_site.py
```
Expected: scripts run clean; `git status` shows only doc files changed.

- [ ] **Step 2: Sanity-check the diff**

Run: `git diff --stat`
Expected: only `docs/tools/*.md` and/or `commands/tool-index.md` changed; the `track_type` arg now appears on both device-parameter tools. Confirm the tool COUNT in `docs/tools/index.md` is unchanged (still the current total).

- [ ] **Step 3: Commit**

```bash
git add docs/ commands/tool-index.md
git commit -m "docs: regenerate tool index for device-param track_type"
```

---

### Task 4: Live verification + PROGRESS.md

Requires Live running with the MCP control surface. This is the only step that exercises master/return resolution end to end.

**Files:**
- Modify: `PROGRESS.md`

- [ ] **Step 1: Run the full offline gate**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q`
Expected: all pass (prior suite total + 3 new).

- [ ] **Step 2: Reinstall the Remote Script and bounce Live**

Run: `bash scripts/install_remote_script.sh`
Then bounce Live via the `restart_live` MCP tool (or `/ableton:restart`), or quit+reopen by hand. Give Live ~10-15s to load the set + control surface before the next MCP call. (Also restart Claude Code so the edited server.py loads, then reload the two tools as deferred tools if needed: `ToolSearch select:mcp__AbletonDev__get_device_parameters,mcp__AbletonDev__set_device_parameter`.)

- [ ] **Step 3: Verify a RETURN-track device**

- `get_device_parameters(track_index=0, device_index=0, track_type="return")` -> expect the factory return device's params (e.g. Reverb). If the return has no device, load one in Live first or pick a return that does.
- `set_device_parameter(track_index=0, device_index=0, parameter="<a non-quantized param name>", value=<new>, track_type="return")`.
- Re-read with a SEPARATE `get_device_parameters` call (per the write-lag note) and confirm the value changed.
- Restore the original value.

- [ ] **Step 4: Verify a MASTER-track device**

- Ensure the master has a device (load one in Live if empty).
- `get_device_parameters(track_index=0, device_index=0, track_type="master")` -> expect the master device's params.
- Write one param, re-read via a separate call, confirm, then restore.

- [ ] **Step 5: Confirm regular-track behavior is unchanged**

- `get_device_parameters(track_index=<a regular track with a device>, device_index=0)` with NO `track_type` -> still works exactly as before.

- [ ] **Step 6: Record results + commit**

Add a dated entry to `PROGRESS.md` summarizing the change and the live-verification results (return + master read/write/restore confirmed, regular unchanged).

```bash
git add PROGRESS.md
git commit -m "docs(progress): master/return device-param access live-verified"
```

---

## Self-Review

**Spec coverage:**
- Spec change point 1 (Remote Script handlers + dispatch) -> Task 2. ✅
- Spec change point 2 (server tools + pre-fetch `track_type` + docstrings) -> Task 1. ✅
- Spec change point 3 (docs regen, no count change) -> Task 3. ✅
- Spec testing (offline server-side payload tests incl. pre-fetch; py_compile; live verify return + master + regular-unchanged; PROGRESS) -> Task 1 Steps 1-6, Task 2 Step 5, Task 4. ✅
- Backward-compat (default `"regular"`) -> Task 1 `test_get_device_parameters_defaults_to_regular` + Task 4 Step 5. ✅
- Out-of-scope (B automation, C loading) -> not in any task, as intended. ✅

**Placeholder scan:** No TBD/TODO; all code shown in full; commands have expected output. Task 4 Step 3 intentionally leaves the exact param name to the live operator (it depends on which device is on the return) - this is runtime data, not a plan placeholder.

**Type consistency:** `_resolve_device(track_index, device_index, track_type)` returns `(track, device)` - used consistently in Task 2 Steps 1-2 (matches the existing helper at line 1291). `resolve_parameter_index(parameters, identifier)` returns an int index - test mock returns dicts with `index`/`name` keys as that function expects. `track_type` default `"regular"` is uniform across server tools, handlers, and dispatch.
