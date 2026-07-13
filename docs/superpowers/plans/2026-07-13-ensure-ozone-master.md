# ensure_ozone_master Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an `ensure_ozone_master` MCP tool that guarantees the master has exactly one enabled Ozone 12 (older Ozone disabled, not deleted) whose state blob is immediately authorable, so `apply_master` runs hands-off.

**Architecture:** A pure resolver `master_ozone_utils.py` decides the action plan from the master's device list (exact-name Ozone detection); a thin `ensure_ozone_master` executor in `server.py` enumerates devices, applies the plan via existing tool functions (`get_device_info` / `set_device_on` / `load_instrument_or_effect`), then runs a bounded save-with-retry + blob-probe loop that works around the racy window state after a structural change.

**Tech Stack:** Python 3 (server side), FastMCP `@mcp.tool()`, pytest. Remote Script is NOT touched (no Live-side handler needed - this tool only orchestrates existing tools).

## Global Constraints

- Ozone suite detection is EXACT-name only: `Ozone 9`, `Ozone 10`, `Ozone 11`, `Ozone 12` (after `str.strip()`). Never substring - the component plugins (`Ozone 12 Maximizer`, etc.) must NOT match.
- Ozone 12 browser URI is exactly `query:Plugins#VST3:iZotope:Ozone%2012`.
- `*_utils.py` modules are imported by `server.py` only, are pure (no I/O), and are unit-tested offline.
- Never delete an older Ozone - disable it via `set_device_on(false)`.
- Precondition: the set must already be saved to a file; an untitled set returns a clear error (matches `apply_master` / `set_ozone_state`).
- Every tool returns a JSON string built by `_ok(data)` / `_err(message)`; the executor checks `ok`, never string-sniffs.
- Offline gate for every task: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q`, plus `uv run python -c "import ableton_mcp_max.server"` after any server.py change. Do NOT reformat existing files to ruff style.
- No AI attribution anywhere in commits or code (this repo ships as a public plugin).

---

### Task 1: Pure resolver `master_ozone_utils.py`

**Files:**
- Create: `ableton_mcp_max/master_ozone_utils.py`
- Test: `tests/test_master_ozone_utils.py`

**Interfaces:**
- Consumes: nothing (pure, stdlib only).
- Produces:
  - `OZONE_SUITE_NAMES: frozenset[str]` = `{"Ozone 9","Ozone 10","Ozone 11","Ozone 12"}`
  - `OZONE_12: str` = `"Ozone 12"`
  - `OZONE_12_URI: str` = `"query:Plugins#VST3:iZotope:Ozone%2012"`
  - `plan_master_ozone(devices) -> dict` where `devices` is an ordered list of `{"index": int, "name": str, "is_on": bool}`. Returns `{"target_index": int|None, "action": "reused"|"reused_reenabled"|"loaded", "disable_indices": list[int], "load_required": bool}`.
  - `pick_loaded_target(before, after) -> int|None` - given the device lists before and after a load, return the newly-appeared Ozone 12 index (lowest new; fallback lowest Ozone 12 present; else None).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_master_ozone_utils.py`:

```python
import ableton_mcp_max.master_ozone_utils as mou


def _dev(index, name, is_on=True):
    return {"index": index, "name": name, "is_on": is_on}


def test_empty_master_requires_load():
    plan = mou.plan_master_ozone([])
    assert plan == {"target_index": None, "action": "loaded",
                    "disable_indices": [], "load_required": True}


def test_only_ozone12_on_is_reused():
    plan = mou.plan_master_ozone([_dev(0, "Ozone 12", True)])
    assert plan["action"] == "reused"
    assert plan["target_index"] == 0
    assert plan["disable_indices"] == []
    assert plan["load_required"] is False


def test_only_ozone12_off_is_reenabled():
    plan = mou.plan_master_ozone([_dev(2, "Ozone 12", False)])
    assert plan["action"] == "reused_reenabled"
    assert plan["target_index"] == 2
    assert plan["load_required"] is False


def test_only_older_ozone_loads_and_disables():
    plan = mou.plan_master_ozone([_dev(0, "Ozone 10", True)])
    assert plan["action"] == "loaded"
    assert plan["load_required"] is True
    assert plan["disable_indices"] == [0]
    assert plan["target_index"] is None


def test_mixed_older_and_12_reuses_and_disables_older():
    plan = mou.plan_master_ozone([_dev(0, "Ozone 9", True),
                                  _dev(1, "Ozone 12", True)])
    assert plan["action"] == "reused"
    assert plan["target_index"] == 1
    assert plan["disable_indices"] == [0]
    assert plan["load_required"] is False


def test_multiple_ozone12_picks_lowest_index():
    plan = mou.plan_master_ozone([_dev(3, "Ozone 12", True),
                                  _dev(1, "Ozone 12", True)])
    assert plan["target_index"] == 1


def test_component_plugins_do_not_match():
    devices = [_dev(0, "Ozone 12 Maximizer", True),
               _dev(1, "Ozone 12 Equalizer", True)]
    plan = mou.plan_master_ozone(devices)
    assert plan["action"] == "loaded"
    assert plan["load_required"] is True
    assert plan["disable_indices"] == []
    assert plan["target_index"] is None


def test_name_matched_exactly_after_strip():
    # Trailing space is stripped; lower-case is NOT a canonical Live name.
    assert mou.plan_master_ozone([_dev(0, "Ozone 12 ", True)])["action"] == "reused"
    assert mou.plan_master_ozone([_dev(0, "ozone 12", True)])["load_required"] is True


def test_none_name_is_safe():
    plan = mou.plan_master_ozone([_dev(0, None, True)])
    assert plan["load_required"] is True


def test_pick_loaded_target_finds_new_ozone12():
    before = [_dev(0, "Ozone 10", False), _dev(1, "MCP Tap", True)]
    after = [_dev(0, "Ozone 10", False), _dev(1, "MCP Tap", True),
             _dev(2, "Ozone 12", True)]
    assert mou.pick_loaded_target(before, after) == 2


def test_pick_loaded_target_none_when_no_new():
    before = [_dev(0, "Ozone 12", True)]
    after = [_dev(0, "Ozone 12", True)]
    assert mou.pick_loaded_target(before, after) == 0  # fallback: lowest present


def test_pick_loaded_target_none_when_absent():
    assert mou.pick_loaded_target([], []) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q tests/test_master_ozone_utils.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'ableton_mcp_max.master_ozone_utils'`.

- [ ] **Step 3: Write the resolver**

Create `ableton_mcp_max/master_ozone_utils.py`:

```python
"""Master-track Ozone preparation logic (pure, imported by server.py only).

Given the master's device list, decide which older Ozone versions to disable,
whether an Ozone 12 can be reused, and whether a fresh Ozone 12 must be loaded.
Detection is EXACT-name (after strip) so the single-module component plugins
(e.g. 'Ozone 12 Maximizer') are never mistaken for the full suite. PROPOSE
ONLY - the executor in server.py performs the device I/O.
"""

OZONE_SUITE_NAMES = frozenset(["Ozone 9", "Ozone 10", "Ozone 11", "Ozone 12"])
OZONE_12 = "Ozone 12"
OZONE_12_URI = "query:Plugins#VST3:iZotope:Ozone%2012"


def _name(device):
    return (device.get("name") or "").strip()


def plan_master_ozone(devices):
    """Return the action plan for the master's device list.

    devices: ordered list of {"index": int, "name": str, "is_on": bool}.
    Returns {"target_index", "action", "disable_indices", "load_required"}.
    """
    disable_indices = [d["index"] for d in devices
                       if _name(d) in OZONE_SUITE_NAMES and _name(d) != OZONE_12]
    twelves = [d for d in devices if _name(d) == OZONE_12]
    if twelves:
        target = min(twelves, key=lambda d: d["index"])
        action = "reused" if target.get("is_on") else "reused_reenabled"
        return {"target_index": target["index"], "action": action,
                "disable_indices": disable_indices, "load_required": False}
    return {"target_index": None, "action": "loaded",
            "disable_indices": disable_indices, "load_required": True}


def pick_loaded_target(before, after):
    """Index of the Ozone 12 that appeared after a load.

    Prefers an index present in `after` but not `before`; falls back to the
    lowest Ozone 12 index present; None if none exist.
    """
    before_12 = {d["index"] for d in before if _name(d) == OZONE_12}
    after_12 = sorted(d["index"] for d in after if _name(d) == OZONE_12)
    new = [i for i in after_12 if i not in before_12]
    if new:
        return new[0]
    return after_12[0] if after_12 else None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q tests/test_master_ozone_utils.py`
Expected: PASS (12 passed).

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/master_ozone_utils.py tests/test_master_ozone_utils.py
git commit -m "feat: master_ozone_utils resolver for ensure_ozone_master"
```

---

### Task 2: `ensure_ozone_master` executor + blob-ready retry

**Files:**
- Modify: `ableton_mcp_max/server.py` (add near `apply_master`, before `def main()`)
- Test: `tests/test_ensure_ozone_master_tool.py`

**Interfaces:**
- Consumes from Task 1: `master_ozone_utils.plan_master_ozone`, `master_ozone_utils.pick_loaded_target`, `master_ozone_utils.OZONE_12_URI`.
- Consumes existing `server.py` tool functions (all return JSON strings): `get_device_info(ctx, track_index, device_index, track_type)`, `set_device_on(ctx, track_index, device_index, on, track_type)`, `load_instrument_or_effect(ctx, track_index, uri, track_type)`, `save_set(ctx, name)`, `get_ozone_state(ctx, track_index, device_index, track_type, module)`, plus `_ok`, `_err`, `get_ableton_connection`, `logger`, `time`.
- Produces: `ensure_ozone_master(ctx, track_index=0, track_type="master") -> str` returning `_ok({"device_index", "action", "disabled_indices", "blob_ready"})` on success, `_err(...)` on precondition failure / load failure / blob-not-ready.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ensure_ozone_master_tool.py`:

```python
import json
import ableton_mcp_max.server as server


def _install(monkeypatch, devices, load_appends=None, saves=None,
             ozone_ok=True):
    """devices: mutable list of {"index","name","is_on"} the fake master holds.
    load_appends: dict to append on load (or None -> append Ozone 12).
    saves: list of save_set data dicts to return in sequence (cycled/last).
    """
    monkeypatch.setattr(server, "get_ableton_connection", lambda: object())

    def fake_get_device_info(ctx, track_index, device_index, track_type="regular"):
        for d in devices:
            if d["index"] == device_index:
                return json.dumps({"ok": True, "data": {
                    "device_index": device_index, "name": d["name"],
                    "is_on": d["is_on"]}})
        return json.dumps({"ok": False, "error": "no device at index %d" % device_index})

    def fake_set_device_on(ctx, track_index, device_index, on, track_type="regular"):
        for d in devices:
            if d["index"] == device_index:
                d["is_on"] = bool(on)
        return json.dumps({"ok": True, "data": {"device_index": device_index,
                                                "is_on": bool(on)}})

    def fake_load(ctx, track_index, uri, track_type="regular"):
        new = load_appends or {"index": len(devices), "name": "Ozone 12",
                               "is_on": True}
        new = dict(new)
        new["index"] = max([d["index"] for d in devices], default=-1) + 1
        devices.append(new)
        return json.dumps({"ok": True, "data": "loaded"})

    save_seq = list(saves or [{"saved": True, "title": "myset", "untitled": False}])

    def fake_save_set(ctx, name=""):
        data = save_seq[0] if len(save_seq) == 1 else save_seq.pop(0)
        return json.dumps({"ok": True, "data": data})

    def fake_get_ozone_state(ctx, track_index, device_index=0,
                             track_type="master", module=None):
        if ozone_ok:
            return json.dumps({"ok": True, "data": {"module": "Maximizer",
                                                    "params": []}})
        return json.dumps({"ok": False,
                           "error": "Could not resolve the current set's .als path."})

    monkeypatch.setattr(server, "get_device_info", fake_get_device_info)
    monkeypatch.setattr(server, "set_device_on", fake_set_device_on)
    monkeypatch.setattr(server, "load_instrument_or_effect", fake_load)
    monkeypatch.setattr(server, "save_set", fake_save_set)
    monkeypatch.setattr(server, "get_ozone_state", fake_get_ozone_state)
    # Make the retry loop instant.
    monkeypatch.setattr(server.time, "sleep", lambda *_a, **_k: None)
    return devices


def test_reuse_existing_ozone12(monkeypatch):
    _install(monkeypatch, [{"index": 0, "name": "Ozone 12", "is_on": True},
                           {"index": 1, "name": "MCP Tap", "is_on": True}])
    out = json.loads(server.ensure_ozone_master(ctx=None))
    assert out["ok"] is True
    d = out["data"]
    assert d["device_index"] == 0
    assert d["action"] == "reused"
    assert d["disabled_indices"] == []
    assert d["blob_ready"] is True


def test_reenable_disabled_ozone12(monkeypatch):
    devs = _install(monkeypatch, [{"index": 0, "name": "Ozone 12", "is_on": False}])
    out = json.loads(server.ensure_ozone_master(ctx=None))
    d = out["data"]
    assert d["action"] == "reused_reenabled"
    assert d["device_index"] == 0
    assert devs[0]["is_on"] is True  # executor re-enabled it


def test_disable_older_and_load_fresh(monkeypatch):
    devs = _install(monkeypatch, [{"index": 0, "name": "Ozone 10", "is_on": True},
                                  {"index": 1, "name": "MCP Tap", "is_on": True}])
    out = json.loads(server.ensure_ozone_master(ctx=None))
    d = out["data"]
    assert d["action"] == "loaded"
    assert d["disabled_indices"] == [0]
    assert d["device_index"] == 2   # appended after 0,1
    assert devs[0]["is_on"] is False


def test_untitled_set_precondition_errors(monkeypatch):
    _install(monkeypatch, [{"index": 0, "name": "Ozone 12", "is_on": True}],
             saves=[{"saved": False, "untitled": True, "title": ""}])
    out = json.loads(server.ensure_ozone_master(ctx=None))
    assert out["ok"] is False
    assert "untitled" in out["error"].lower()


def test_transient_untitled_then_recovers(monkeypatch):
    # First save reports transient empty title; retry succeeds. Precondition
    # save (call 1) is titled, loop save (call 2) transient, (call 3) good.
    _install(monkeypatch, [{"index": 0, "name": "Ozone 12", "is_on": True}],
             saves=[{"saved": True, "title": "myset", "untitled": False},
                    {"saved": False, "untitled": True, "title": ""},
                    {"saved": True, "title": "myset", "untitled": False}])
    out = json.loads(server.ensure_ozone_master(ctx=None))
    assert out["ok"] is True
    assert out["data"]["blob_ready"] is True


def test_blob_never_ready_returns_error(monkeypatch):
    _install(monkeypatch, [{"index": 0, "name": "Ozone 12", "is_on": True}],
             ozone_ok=False)
    out = json.loads(server.ensure_ozone_master(ctx=None))
    assert out["ok"] is False
    assert "blob" in out["error"].lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q tests/test_ensure_ozone_master_tool.py`
Expected: FAIL with `AttributeError: module 'ableton_mcp_max.server' has no attribute 'ensure_ozone_master'`.

- [ ] **Step 3: Add the import**

At the top of `ableton_mcp_max/server.py`, next to the other `*_utils` imports (search for `import ableton_mcp_max.master_select` or `from ableton_mcp_max import master_profiles` and add alongside):

```python
from ableton_mcp_max import master_ozone_utils
```

- [ ] **Step 4: Write the executor**

In `ableton_mcp_max/server.py`, immediately AFTER the `apply_master` function (search for `def apply_master(` and place this before `def recommend_instrument(`):

```python
def _enumerate_master_devices(ctx, track_index, track_type, limit=64):
    """Walk device indices until one is absent; return [{index,name,is_on}]."""
    devices = []
    for di in range(limit):
        try:
            raw = json.loads(get_device_info(ctx, track_index, di, track_type))
        except Exception:
            break
        if not raw.get("ok"):
            break
        d = raw["data"]
        devices.append({"index": di, "name": d.get("name"),
                        "is_on": d.get("is_on")})
    return devices


def _master_blob_ready(ctx, track_index, target_index, track_type,
                       attempts=5):
    """Save-with-retry, then probe get_ozone_state. Works around the racy
    empty-title / stale-.als-path window right after a structural change.
    Returns (ready: bool, last_error: str|None)."""
    last = None
    for _ in range(attempts):
        saved = json.loads(save_set(ctx, "")).get("data", {})
        if not saved.get("saved") or saved.get("untitled"):
            last = saved.get("error") or "save did not land (transient title)"
            time.sleep(0.6)
            continue
        probe = json.loads(get_ozone_state(ctx, track_index, target_index,
                                           track_type, None))
        if probe.get("ok"):
            return True, None
        last = probe.get("error")
        time.sleep(0.6)
    return False, last


@mcp.tool()
def ensure_ozone_master(ctx: Context, track_index: int = 0,
                        track_type: str = "master") -> str:
    """Prepare the master for mastering: guarantee exactly one enabled Ozone 12,
    with older Ozone versions (9/10/11) disabled (never deleted), and confirm the
    instance's state blob is authorable before returning. Reuses an existing
    Ozone 12 (re-enabling it if off; lowest index if several), else loads one onto
    the master (appends - existing master devices are untouched). Detection is
    exact-name so the single-module 'Ozone 12 <Module>' component plugins are
    ignored. The set must already be saved to a file (an untitled set errors).
    Hand data.device_index straight to apply_master. Returns {ok, data:{
    device_index, action: reused|reused_reenabled|loaded, disabled_indices,
    blob_ready}}."""
    try:
        get_ableton_connection()  # fail fast if Live is unreachable
        # Precondition: window is settled pre-change, so this read is reliable.
        pre = json.loads(save_set(ctx, "")).get("data", {})
        if pre.get("untitled"):
            return _err("Save the set to a file first (it is untitled), then retry.")
        before = _enumerate_master_devices(ctx, track_index, track_type)
        plan = master_ozone_utils.plan_master_ozone(before)
        for di in plan["disable_indices"]:
            set_device_on(ctx, track_index, di, False, track_type)
        if plan["load_required"]:
            loaded = json.loads(load_instrument_or_effect(
                ctx, track_index, master_ozone_utils.OZONE_12_URI, track_type))
            if not loaded.get("ok"):
                return _err("ensure_ozone_master: load failed: %s"
                            % loaded.get("error"))
            after = _enumerate_master_devices(ctx, track_index, track_type)
            target = master_ozone_utils.pick_loaded_target(before, after)
            if target is None:
                return _err("ensure_ozone_master: Ozone 12 did not appear after load.")
        else:
            target = plan["target_index"]
            if plan["action"] == "reused_reenabled":
                set_device_on(ctx, track_index, target, True, track_type)
        ready, err = _master_blob_ready(ctx, track_index, target, track_type)
        if not ready:
            return _err("ensure_ozone_master: master prepared (action=%s, "
                        "device_index=%s) but the Ozone blob was not authorable "
                        "after retries: %s" % (plan["action"], target, err))
        return _ok({"device_index": target, "action": plan["action"],
                    "disabled_indices": plan["disable_indices"],
                    "blob_ready": True})
    except Exception as e:
        logger.error("ensure_ozone_master error: %s", e)
        return _err("ensure_ozone_master error: %s" % e)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q tests/test_ensure_ozone_master_tool.py`
Expected: PASS (6 passed).

- [ ] **Step 6: Syntax-check the server import and run the full offline suite**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python -c "import ableton_mcp_max.server"`
Expected: no output, exit 0.

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q`
Expected: PASS (all existing tests + the new files).

- [ ] **Step 7: Commit**

```bash
git add ableton_mcp_max/server.py tests/test_ensure_ozone_master_tool.py
git commit -m "feat: ensure_ozone_master tool (prepare master for mastering)"
```

---

### Task 3: Tool-count/doc regen

**Files:**
- Modify: `scripts/build_tool_index.py` (category map - add the tool)
- Modify: `scripts/gen_docs_site.py` (category map - add the tool; it ASSERTS every tool is categorized exactly once)
- Modify: `README.md` (the hardcoded tool count on line ~7)
- Modify: `docs/index.md` (5 hardcoded count spots per CLAUDE.md)
- Regen: `docs/tools/`, `docs/tools/index.md`, `commands/tool-index.md` via the repo scripts

**Interfaces:**
- Consumes: the new `ensure_ozone_master` tool being present in `server.py` (Task 2).
- Produces: doc artifacts reflecting the new tool count (184 -> 185) with `ensure_ozone_master` under the "Mastering (Ozone)" category.

- [ ] **Step 1: Register the tool in BOTH category maps**

The category lists are manual and `gen_docs_site.py` asserts every tool appears exactly once, so the regen scripts FAIL until the tool is registered. Add `"ensure_ozone_master"` to the "Mastering (Ozone)" list, right after `"apply_master"`, in BOTH files:

In `scripts/build_tool_index.py`, the `("Mastering (Ozone)", [ ... ])` block:

```python
    ("Mastering (Ozone)", [
        "get_ozone_modules", "expose_ozone_modules", "get_ozone_module",
        "set_ozone_module_param", "set_ozone_module_enabled",
        "set_ozone_eq_band", "set_ozone_maximizer", "set_ozone_dynamics_band",
        "get_ozone_state", "set_ozone_state",
        "recommend_master", "apply_master", "ensure_ozone_master",
    ]),
```

In `scripts/gen_docs_site.py`, the `("mastering-ozone", "Mastering (Ozone)", "...", [ ... ])` block:

```python
        "get_ozone_state", "set_ozone_state",
        "recommend_master", "apply_master", "ensure_ozone_master",
    ]),
```

- [ ] **Step 2: Confirm the new count**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python scripts/build_tool_index.py && PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python scripts/gen_docs_site.py`
Expected: scripts regenerate `docs/tools/`, `docs/tools/index.md`, `commands/tool-index.md`; the printed count reads `Generated 185 tools across N categories`.

- [ ] **Step 3: Bump the hardcoded counts by hand**

Edit `README.md` line ~7 ("reference for all N tools") from the old count to `185`.
Edit `docs/index.md` the 5 hardcoded spots (description, tagline, two `stats__num`, and the "exposes the N `@mcp.tool()`" line) from the old count to `185`. Verify with:

Run: `grep -rn "184" README.md docs/index.md`
Expected: no remaining `184` occurrences that refer to the tool count (unrelated numbers, if any, are left alone).

- [ ] **Step 4: Verify tests still green (docs-only change is safe)**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add README.md docs/ commands/ scripts/
git commit -m "docs: regen tool index for ensure_ozone_master (185 tools)"
```

---

## Live verification (manual, after merge-candidate is built)

Per repo convention Live tests are manual via MCP tools against the open set. Restart Claude Code first (server.py changed - MCP loads at session start). Then, on a set saved to a file:

1. Master already has Ozone 12: `ensure_ozone_master()` -> `action:"reused"`, `blob_ready:true`, `device_index` = its index.
2. Master without Ozone 12 (delete it first, or use a fresh set): `ensure_ozone_master()` -> `action:"loaded"`, `blob_ready:true`; confirm `get_device_info` shows the appended Ozone 12 at the returned index.
3. Older Ozone present (if available): confirm it ends `is_on:false` and a 12 is present/loaded.
4. End-to-end: `ensure_ozone_master()` then `apply_master(device_index=<data.device_index>, chain=<from recommend_master>)` succeeds without manual loading.
5. Untitled set: on a never-saved set, `ensure_ozone_master()` returns `ok:false` with the "save the set first" error.

Record results in `PROGRESS.md`.

## Notes for the implementer

- `time` is already imported in `server.py` (used by `_save_set_impl`); do not re-import.
- `save_set(ctx, "")` returns a JSON string with `data.saved` (bool), `data.untitled` (bool), `data.title` (str). It wraps even the untitled case in `_ok`, so check `data`, not `ok`.
- `get_ozone_state`'s signature is `(ctx, track_index, device_index=0, track_type="master", module=None)`; pass `module=None` for the whole-instance summary probe.
- The Remote Script is NOT modified - no `install_remote_script.sh` / Live bounce needed for this feature; only a Claude Code restart to load the new tool for live testing.
