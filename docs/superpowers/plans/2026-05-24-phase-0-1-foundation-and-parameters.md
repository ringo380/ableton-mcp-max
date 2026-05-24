# ableton-mcp-max — Phase 0 + Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up a self-owned Ableton MCP (forked from ahujasid/ableton-mcp) with full parity, then add device/instrument parameter read + set so Claude can dial synth controls (e.g. Wavetable) directly.

**Architecture:** Two halves over localhost:9877 — an MCP server (`ableton_mcp_max/server.py`, FastMCP) that sends JSON commands, and a Live Remote Script (`remote_script/AbletonMCP/__init__.py`) that runs them against the Live Object Model with state mutations scheduled on Live's main thread. We vendor both halves as single files (preserving parity), then add two new commands/tools for parameters. Name→index resolution lives in a pure, unit-tested helper on the server side so the Remote Script handler stays trivial.

**Tech Stack:** Python 3.10+ (server, via `uv`), Python 3.7-era embedded interpreter (Remote Script, inside Live), MCP `FastMCP`, `pytest` for the offline helper.

**Scope note (deviation from spec's aspirational layout):** The spec sketched `tools/` and `handlers/` sub-packages. For Phase 0+1 we vendor the upstream files as single modules and add new code inline/grouped-by-comment. Splitting the 1062-line Remote Script across importable submodules is fragile in Live's embedded import environment and unnecessary at this size (YAGNI). The domain-module refactor becomes a tracked task only if/when files grow unwieldy.

**Source material (already downloaded this session):**
- Upstream server: `/tmp/ableton_mcp-1.0.4/MCP_Server/server.py`
- Upstream Remote Script: `/tmp/ableton_remote_init.py`
- Currently-installed Remote Script: `/Applications/Ableton Live 11 Suite.app/Contents/App-Resources/MIDI Remote Scripts/AbletonMCP/__init__.py`

---

## File Structure

| File | Responsibility |
|------|----------------|
| `ableton_mcp_max/__init__.py` | Package marker |
| `ableton_mcp_max/server.py` | FastMCP server: connection mgmt + all `@mcp.tool()` definitions (vendored + new) |
| `ableton_mcp_max/param_utils.py` | **Pure** helper: resolve a parameter name/index against a parameter list. Unit-tested offline. |
| `remote_script/AbletonMCP/__init__.py` | Live control surface: socket server + `_process_command` dispatch + LOM handlers (vendored + new) |
| `scripts/install_remote_script.sh` | Copy Remote Script into Live's MIDI Remote Scripts dir, `chown` to user, back up any existing copy |
| `scripts/register_mcp.sh` | Register the new MCP server with Claude Code; print deregistration steps for the old one |
| `tests/test_param_utils.py` | Offline unit tests for `param_utils` |
| `pyproject.toml` | Package metadata + console entry point `ableton-mcp-max` |
| `PROGRESS.md` | Phase/tool completion tracker (durability requirement) |
| `README.md` | What it is, how to install/run |

---

## Phase 0 — Foundation

### Task 0.1: Scaffold package + vendor upstream files

**Files:**
- Create: `ableton_mcp_max/__init__.py`
- Create: `ableton_mcp_max/server.py` (copied from upstream)
- Create: `remote_script/AbletonMCP/__init__.py` (copied from upstream)
- Create: `pyproject.toml`
- Create: `README.md`

- [ ] **Step 1: Create package dirs and vendor the two upstream files**

```bash
cd ~/git/ableton-mcp-max
mkdir -p ableton_mcp_max remote_script/AbletonMCP scripts tests
touch ableton_mcp_max/__init__.py
cp /tmp/ableton_mcp-1.0.4/MCP_Server/server.py ableton_mcp_max/server.py
cp /tmp/ableton_remote_init.py remote_script/AbletonMCP/__init__.py
```

- [ ] **Step 2: Rename the FastMCP instance label so it's distinguishable**

In `ableton_mcp_max/server.py`, change the server name from `"AbletonMCP"` to `"AbletonMCPMax"`:

```python
# was: mcp = FastMCP("AbletonMCP", lifespan=server_lifespan)
mcp = FastMCP(
    "AbletonMCPMax",
    lifespan=server_lifespan
)
```
(Leave the socket host/port `localhost:9877` unchanged — the Remote Script keeps the same port.)

- [ ] **Step 3: Write `pyproject.toml`**

```toml
[project]
name = "ableton-mcp-max"
version = "0.1.0"
description = "Self-owned, extensible Ableton Live MCP server"
requires-python = ">=3.10"
dependencies = [
    "mcp[cli]>=1.3.0",
]

[project.scripts]
ableton-mcp-max = "ableton_mcp_max.server:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["ableton_mcp_max"]
```

- [ ] **Step 4: Write a minimal `README.md`**

```markdown
# ableton-mcp-max

A self-owned, extensible MCP server for Ableton Live, forked from
[ahujasid/ableton-mcp](https://github.com/ahujasid/ableton-mcp) and extended
toward broad Live Object Model coverage.

## Install
1. `bash scripts/install_remote_script.sh` — installs the Live Remote Script.
2. Restart Ableton Live; enable **AbletonMCP** under Settings → Link, Tempo & MIDI → Control Surface.
3. `bash scripts/register_mcp.sh` — registers the MCP server with Claude Code.
4. Restart Claude Code.

See `PROGRESS.md` for capability status and `docs/superpowers/specs/` for the design.
```

- [ ] **Step 5: Verify the server imports and starts (offline — will fail to reach Live, which is expected)**

Run: `cd ~/git/ableton-mcp-max && uv run ableton-mcp-max` then Ctrl-C after a few seconds.
Expected: logs show `AbletonMCPMax server starting up` / `Connecting to Ableton` then connection-refused warnings (Live not wired to this build yet) — no Python import/syntax errors.

- [ ] **Step 6: Commit**

```bash
cd ~/git/ableton-mcp-max
git add ableton_mcp_max pyproject.toml README.md remote_script
git commit -m "feat: vendor ahujasid base as ableton-mcp-max foundation"
```

---

### Task 0.2: Install script (with backup + chown)

**Files:**
- Create: `scripts/install_remote_script.sh`

- [ ] **Step 1: Write the install script**

```bash
#!/usr/bin/env bash
# Installs the ableton-mcp-max Remote Script into Ableton Live 11,
# backing up any existing AbletonMCP script and fixing ownership.
set -u

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$REPO_DIR/remote_script/AbletonMCP"
LIVE_RS="/Applications/Ableton Live 11 Suite.app/Contents/App-Resources/MIDI Remote Scripts"
DEST="$LIVE_RS/AbletonMCP"

if [ ! -d "$LIVE_RS" ]; then
  echo "ERROR: Live MIDI Remote Scripts dir not found: $LIVE_RS" >&2
  exit 1
fi

# Back up an existing install once (timestamped).
if [ -d "$DEST" ]; then
  BK="$LIVE_RS/AbletonMCP.bak.$(date +%Y%m%d-%H%M%S)"
  echo "Backing up existing $DEST -> $BK"
  sudo cp -R "$DEST" "$BK"
fi

echo "Installing Remote Script -> $DEST"
sudo mkdir -p "$DEST"
sudo cp "$SRC/__init__.py" "$DEST/__init__.py"
# CRITICAL: chown to the user. Live (sandboxed) silently skips root-owned
# remote-script folders during its control-surface scan.
sudo chown -R "$(id -un):admin" "$DEST"

echo "Done. Restart Ableton Live, then select 'AbletonMCP' as a Control Surface."
exit 0
```

- [ ] **Step 2: Make it executable and run it**

```bash
chmod +x ~/git/ableton-mcp-max/scripts/install_remote_script.sh
bash ~/git/ableton-mcp-max/scripts/install_remote_script.sh
```
Expected: prints a backup line (existing ahujasid script) + "Installing..." + "Done."

- [ ] **Step 3: Verify install ownership matches built-ins**

Run: `stat -f "%Sp %Su:%Sg %N" "/Applications/Ableton Live 11 Suite.app/Contents/App-Resources/MIDI Remote Scripts/AbletonMCP/__init__.py"`
Expected: owner `ryanrobson`, not `root`.

- [ ] **Step 4: Commit**

```bash
cd ~/git/ableton-mcp-max
git add scripts/install_remote_script.sh
git commit -m "feat: add Remote Script install script with backup + chown"
```

---

### Task 0.3: Register new MCP server, swap from old, parity smoke test

**Files:**
- Create: `scripts/register_mcp.sh`

- [ ] **Step 1: Write the register script**

```bash
#!/usr/bin/env bash
# Registers ableton-mcp-max with Claude Code (local/project scope) and
# prints how to remove the old ahujasid server.
set -u
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "Registering AbletonMCPMax..."
claude mcp add AbletonMCPMax -- uv run --directory "$REPO_DIR" ableton-mcp-max

echo
echo "To remove the old server, run:  claude mcp remove AbletonMCP"
echo "Then restart Claude Code so the new tools load."
exit 0
```

- [ ] **Step 2: Run it, then remove the old server**

```bash
chmod +x ~/git/ableton-mcp-max/scripts/register_mcp.sh
bash ~/git/ableton-mcp-max/scripts/register_mcp.sh
claude mcp remove AbletonMCP
claude mcp list | grep -i ableton
```
Expected: `AbletonMCPMax` present; old `AbletonMCP` gone.

- [ ] **Step 3: USER ACTION — restart Live + Claude Code**

The Remote Script was replaced and the MCP server swapped. User must: fully quit Live (⌘Q) → reopen → confirm **AbletonMCP** still selected as Control Surface; then restart Claude Code so `mcp__AbletonMCPMax__*` tools load.

- [ ] **Step 4: Parity smoke test (live, through the new server)**

Once reconnected, verify the vendored tools still work:
- `get_session_info` → returns tempo/track counts (proves socket + dispatch intact).
- `get_track_info track_index=0` → returns the Wavetable device in `devices`.

Record PASS/FAIL for each in `PROGRESS.md`.

- [ ] **Step 5: Commit**

```bash
cd ~/git/ableton-mcp-max
git add scripts/register_mcp.sh
git commit -m "feat: add MCP registration script"
```

---

## Phase 1 — Device & Parameter Control

### Task 1.1: Pure helper `param_utils.resolve_parameter_index` (TDD)

**Files:**
- Create: `ableton_mcp_max/param_utils.py`
- Test: `tests/test_param_utils.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_param_utils.py
import pytest
from ableton_mcp_max.param_utils import resolve_parameter_index

PARAMS = [
    {"index": 0, "name": "Device On"},
    {"index": 1, "name": "Filter Freq"},
    {"index": 2, "name": "Filter Res"},
]

def test_resolve_by_int_index():
    assert resolve_parameter_index(PARAMS, 1) == 1

def test_resolve_by_numeric_string():
    assert resolve_parameter_index(PARAMS, "2") == 2

def test_resolve_by_exact_name():
    assert resolve_parameter_index(PARAMS, "Filter Freq") == 1

def test_resolve_by_case_insensitive_name():
    assert resolve_parameter_index(PARAMS, "filter res") == 2

def test_index_out_of_range_raises():
    with pytest.raises(ValueError):
        resolve_parameter_index(PARAMS, 9)

def test_unknown_name_raises_with_available_list():
    with pytest.raises(ValueError) as exc:
        resolve_parameter_index(PARAMS, "Nope")
    assert "Filter Freq" in str(exc.value)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/git/ableton-mcp-max && uv run --with pytest pytest tests/test_param_utils.py -v`
Expected: FAIL — `ModuleNotFoundError: ableton_mcp_max.param_utils`.

- [ ] **Step 3: Implement the helper**

```python
# ableton_mcp_max/param_utils.py
"""Pure helpers for resolving device parameters. No Live dependencies."""


def resolve_parameter_index(parameters, identifier):
    """Resolve a parameter identifier (int index, numeric string, or name)
    to its integer index within `parameters` (a list of dicts with
    'index' and 'name' keys, as returned by get_device_parameters).

    Raises ValueError if it can't be resolved.
    """
    # Integer index or numeric string -> validate range.
    is_numeric_str = isinstance(identifier, str) and identifier.lstrip("-").isdigit()
    if isinstance(identifier, int) or is_numeric_str:
        idx = int(identifier)
        if idx < 0 or idx >= len(parameters):
            raise ValueError(
                "Parameter index %d out of range (0..%d)" % (idx, len(parameters) - 1)
            )
        return idx

    # Exact name match.
    for p in parameters:
        if p.get("name") == identifier:
            return p["index"]

    # Case-insensitive name match.
    lowered = str(identifier).lower()
    for p in parameters:
        if str(p.get("name", "")).lower() == lowered:
            return p["index"]

    names = ", ".join(str(p.get("name", "")) for p in parameters)
    raise ValueError("Parameter '%s' not found. Available: %s" % (identifier, names))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ~/git/ableton-mcp-max && uv run --with pytest pytest tests/test_param_utils.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
cd ~/git/ableton-mcp-max
git add ableton_mcp_max/param_utils.py tests/test_param_utils.py
git commit -m "feat: add pure parameter-resolution helper with tests"
```

---

### Task 1.2: Remote Script — `_get_device_parameters` handler (read command)

**Files:**
- Modify: `remote_script/AbletonMCP/__init__.py` (dispatch in `_process_command` ~line 326, and add handler method near `_get_track_info`)

- [ ] **Step 1: Add the dispatch branch**

In `_process_command`, add alongside the other read commands (after the `get_browser_items_at_path` branch, before the `else`):

```python
            elif command_type == "get_device_parameters":
                track_index = params.get("track_index", 0)
                device_index = params.get("device_index", 0)
                response["result"] = self._get_device_parameters(track_index, device_index)
```

- [ ] **Step 2: Add the handler method** (place near `_get_track_info`)

```python
    def _get_device_parameters(self, track_index, device_index):
        """List all automatable parameters of a device on a track."""
        if track_index < 0 or track_index >= len(self._song.tracks):
            raise IndexError("Track index out of range")
        track = self._song.tracks[track_index]
        if device_index < 0 or device_index >= len(track.devices):
            raise IndexError("Device index out of range")
        device = track.devices[device_index]

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
            "device_index": device_index,
            "device_name": device.name,
            "parameter_count": len(parameters),
            "parameters": parameters,
        }
```

- [ ] **Step 3: Reinstall the Remote Script and restart Live**

```bash
bash ~/git/ableton-mcp-max/scripts/install_remote_script.sh
```
Then USER ACTION: ⌘Q Live → reopen (Control Surface stays AbletonMCP). No Claude Code restart needed (read command needs no new server tool yet — test via Step 4 after Task 1.4, or temporarily via raw command).

- [ ] **Step 4: Commit**

```bash
cd ~/git/ableton-mcp-max
git add remote_script/AbletonMCP/__init__.py
git commit -m "feat: add get_device_parameters handler to Remote Script"
```

---

### Task 1.3: Remote Script — `_set_device_parameter` handler (main-thread mutation)

**Files:**
- Modify: `remote_script/AbletonMCP/__init__.py` (modifying-command elif list ~line 229, `main_thread_task` body ~line 240, and new handler method)

- [ ] **Step 1: Add `set_device_parameter` to the modifying-command list**

Change the elif condition (currently ending `..., "start_playback", "stop_playback", "load_browser_item"]`) to include the new command:

```python
            elif command_type in ["create_midi_track", "set_track_name",
                                 "create_clip", "add_notes_to_clip", "set_clip_name",
                                 "set_tempo", "fire_clip", "stop_clip",
                                 "start_playback", "stop_playback", "load_browser_item",
                                 "set_device_parameter"]:
```

- [ ] **Step 2: Add the branch inside `main_thread_task`** (after the `load_browser_item` branch)

```python
                        elif command_type == "set_device_parameter":
                            track_index = params.get("track_index", 0)
                            device_index = params.get("device_index", 0)
                            parameter_index = params.get("parameter_index", 0)
                            value = params.get("value", 0.0)
                            result = self._set_device_parameter(
                                track_index, device_index, parameter_index, value)
```

- [ ] **Step 3: Add the handler method**

```python
    def _set_device_parameter(self, track_index, device_index, parameter_index, value):
        """Set one device parameter by integer index, clamped to its range."""
        if track_index < 0 or track_index >= len(self._song.tracks):
            raise IndexError("Track index out of range")
        track = self._song.tracks[track_index]
        if device_index < 0 or device_index >= len(track.devices):
            raise IndexError("Device index out of range")
        device = track.devices[device_index]
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
            "device_index": device_index,
            "parameter_index": parameter_index,
            "name": param.name,
            "value": param.value,
        }
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
git commit -m "feat: add set_device_parameter handler to Remote Script"
```

---

### Task 1.4: Server — `get_device_parameters` and `set_device_parameter` tools

**Files:**
- Modify: `ableton_mcp_max/server.py` (add import + two `@mcp.tool()` functions after `get_track_info`)

- [ ] **Step 1: Add the import near the top of `server.py`**

```python
from ableton_mcp_max.param_utils import resolve_parameter_index
```

- [ ] **Step 2: Add the `get_device_parameters` tool** (after `get_track_info`)

```python
@mcp.tool()
def get_device_parameters(ctx: Context, track_index: int, device_index: int) -> str:
    """
    List all automatable parameters of a device on a track, with current
    value, min, max, whether it's quantized, and (for quantized params) the
    list of selectable value items.

    Parameters:
    - track_index: index of the track
    - device_index: index of the device on that track (0 = first device)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command(
            "get_device_parameters",
            {"track_index": track_index, "device_index": device_index},
        )
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting device parameters: {str(e)}")
        return f"Error getting device parameters: {str(e)}"
```

- [ ] **Step 3: Add the `set_device_parameter` tool**

```python
@mcp.tool()
def set_device_parameter(
    ctx: Context,
    track_index: int,
    device_index: int,
    parameter: Union[int, str],
    value: float,
) -> str:
    """
    Set a single device/instrument parameter.

    Parameters:
    - track_index: index of the track
    - device_index: index of the device on that track
    - parameter: parameter index (int) OR parameter name (str, case-insensitive)
    - value: target value (clamped to the parameter's min/max). For quantized
      parameters, pass the integer index of the desired value item.
    """
    try:
        ableton = get_ableton_connection()
        # Fetch the parameter list to resolve name->index and validate.
        info = ableton.send_command(
            "get_device_parameters",
            {"track_index": track_index, "device_index": device_index},
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
            },
        )
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error setting device parameter: {str(e)}")
        return f"Error setting device parameter: {str(e)}"
```

- [ ] **Step 4: Verify the server still imports**

Run: `cd ~/git/ableton-mcp-max && uv run python -c "import ableton_mcp_max.server"`
Expected: no errors (exits cleanly).

- [ ] **Step 5: USER ACTION — restart Claude Code** so the two new tools load.

- [ ] **Step 6: Commit**

```bash
cd ~/git/ableton-mcp-max
git add ableton_mcp_max/server.py
git commit -m "feat: add get/set_device_parameter MCP tools"
```

---

### Task 1.5: Live smoke test — dial the Wavetable patch

- [ ] **Step 1: List Wavetable parameters**

Call `get_device_parameters track_index=0 device_index=0`.
Expected: JSON with `device_name: "Wavetable"` and a `parameters` array. Record the exact names for filter cutoff, resonance, unison amount/voices, oscillator gains, and envelope times (these names drive the next step). Note which are quantized.

- [ ] **Step 2: Set a continuous parameter and verify echo**

Call `set_device_parameter track_index=0 device_index=0 parameter="<filter cutoff name from Step 1>" value=<midrange>`.
Expected: returns `{name, value}` with value within min/max. Confirm audibly/visually in Live that the filter moved.

- [ ] **Step 3: Document reachable vs unreachable controls**

In `PROGRESS.md`, record for Wavetable: which controls are settable (continuous knobs, envelopes) and any menu selections that did NOT appear as parameters (e.g. the loaded wavetable waveform), per the spec's caveat.

- [ ] **Step 4: Dial the "I Remember" patch** (using the recipe from the session) on tracks 0 and 1, then commit any helper notes.

---

### Task 1.6: Update PROGRESS.md

**Files:**
- Create/Modify: `PROGRESS.md`

- [ ] **Step 1: Write PROGRESS.md**

```markdown
# ableton-mcp-max — Progress

**Current focus:** Phase 1 complete → next is Phase 2 (Mixer & Routing).
**Next action:** Plan Phase 2 tools (volume/pan/sends/mute/solo/arm, returns, master, routing).

## Phases
| Phase | Title | Status | Completed |
|-------|-------|--------|-----------|
| 0 | Foundation (fork + parity + install) | ☐/☑ | YYYY-MM-DD |
| 1 | Device & Parameter Control | ☐/☑ | YYYY-MM-DD |
| 2 | Mixer & Routing | ☐ | |
| 3 | Clip & MIDI Editing | ☐ | |
| 4 | Devices & Racks | ☐ | |
| 5 | Scenes, Transport, Arrangement | ☐ | |
| 6 | Automation Envelopes | ☐ | |
| 7 | Change Listeners (stretch) | ☐ | |

## Phase 0 tools (parity, vendored)
- [ ] get_session_info, get_track_info, create_midi_track, set_track_name,
      create_clip, add_notes_to_clip, set_clip_name, set_tempo, fire_clip,
      stop_clip, start_playback, stop_playback, load_instrument_or_effect,
      get_browser_tree, get_browser_items_at_path, load_drum_kit

## Phase 1 tools
- [ ] get_device_parameters
- [ ] set_device_parameter

## Device parameter reachability notes
- Wavetable: (fill in from Task 1.5 Step 3)
```

- [ ] **Step 2: Commit**

```bash
cd ~/git/ableton-mcp-max
git add PROGRESS.md
git commit -m "docs: add phase/tool progress tracker"
```

---

## Self-Review

**Spec coverage:**
- Standalone fork owning both halves → Tasks 0.1–0.3 ✓
- Parity preserved → Task 0.1 (vendor) + Task 0.3 Step 4 (parity smoke test) ✓
- In-place `AbletonMCP` replacement, same port, backup original → Task 0.2 ✓
- root-chown gotcha handled → Task 0.2 Step 1 ✓
- Phase 1 get/set device parameters → Tasks 1.2–1.4 ✓
- name-or-index, quantized handling, clamping → Task 1.1 (resolve) + Task 1.3 (clamp, is_enabled) + tool docs ✓
- Persistent progress tracking → Task 1.6 (PROGRESS.md) ✓
- Honest testing (offline pure logic + live smoke checklist) → Task 1.1 (pytest) + Tasks 0.3/1.5 (smoke) ✓
- Local-first run via uv → pyproject scripts + register script ✓

**Placeholder scan:** No TBD/TODO; all code blocks complete; PROGRESS.md template has explicit fill-in markers only where live results are required (Task 1.5 outputs), which is intentional, not a plan gap.

**Type consistency:** `resolve_parameter_index(parameters, identifier)` signature consistent across Task 1.1 (def + tests) and Task 1.4 (call). Command name `set_device_parameter` / `get_device_parameters` consistent across server (1.4) and Remote Script (1.2, 1.3). Remote Script `_set_device_parameter` takes `parameter_index` (int); server resolves name→index before sending — consistent.

**Memory pointer:** After Phase 0 lands, update project memory (`ableton-mcp-setup.md`) to point at `~/git/ableton-mcp-max/PROGRESS.md` as the source of truth and note the server swap (AbletonMCP → AbletonMCPMax).
