# Load effects onto master/return Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Let `load_instrument_or_effect` and `load_preset` load an audio effect onto a return or master track via a `track_type` argument.

**Architecture:** Both tools already send the `load_browser_item` command to one `_load_browser_item` handler. Swap that handler's hardcoded `self._song.tracks[track_index]` for the existing `_resolve_track(track_index, track_type)` helper (which `set_selected_track` already uses for master/return), thread `track_type` from the dispatch site, and add `track_type="regular"` to the two server tools. Backward-compatible.

**Tech Stack:** Python FastMCP server + Live embedded Py2/3.7 Remote Script; pytest + py_compile.

**Spec:** `docs/superpowers/specs/2026-06-16-load-devices-onto-master-return-design.md`

**Test runner:** `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q`

---

### Task 1: Server-side `track_type` on load tools (offline TDD)

**Files:**
- Test: `tests/test_load_track_type.py` (create)
- Modify: `ableton_mcp_max/server.py` — `load_instrument_or_effect` (~2401), `load_preset` (~3268)

- [ ] **Step 1: Write the failing test**

Create `tests/test_load_track_type.py`:

```python
"""Server-side tests: load_instrument_or_effect / load_preset forward track_type
into the load_browser_item command payload. Connection mocked - no Live."""
import json

from ableton_mcp_max import server


class _RecordingConn:
    def __init__(self):
        self.calls = []

    def send_command(self, cmd, params=None):
        self.calls.append((cmd, params or {}))
        if cmd == "get_browser_presets":
            return {"presets": [{"name": "Dark.adg", "relative_path": "Dark.adg",
                                 "uri": "query:UserLibrary#Dark.adg"}]}
        if cmd == "load_browser_item":
            return {"loaded": True, "item_name": "X", "track_name": "T"}
        return {"ok": True}


def test_load_instrument_defaults_to_regular(monkeypatch):
    conn = _RecordingConn()
    monkeypatch.setattr(server, "get_ableton_connection", lambda: conn)
    server.load_instrument_or_effect(None, 0, "query:AudioFx#EQ%20Eight")
    call = next(c for c in conn.calls if c[0] == "load_browser_item")
    assert call[1]["track_type"] == "regular"


def test_load_instrument_forwards_master(monkeypatch):
    conn = _RecordingConn()
    monkeypatch.setattr(server, "get_ableton_connection", lambda: conn)
    server.load_instrument_or_effect(None, 0, "query:AudioFx#EQ%20Eight",
                                     track_type="master")
    call = next(c for c in conn.calls if c[0] == "load_browser_item")
    assert call[1]["track_type"] == "master"


def test_load_preset_forwards_return(monkeypatch):
    conn = _RecordingConn()
    monkeypatch.setattr(server, "get_ableton_connection", lambda: conn)
    out = json.loads(
        server.load_preset(None, 0, "audio_effects", name="Dark.adg",
                           track_type="return")
    )
    assert out["ok"] is True
    call = next(c for c in conn.calls if c[0] == "load_browser_item")
    assert call[1]["track_type"] == "return"
```

- [ ] **Step 2: Run, confirm FAIL**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_load_track_type.py -q`
Expected: FAIL — `TypeError: ... unexpected keyword argument 'track_type'`.

- [ ] **Step 3: Edit `load_instrument_or_effect`**

Change its signature from `(ctx: Context, track_index: int, uri: str)` to add `track_type: str = "regular"` as the last param, add a docstring line `- track_type: 'regular' (default), 'return', or 'master'. Only audio effects are valid on return/master tracks.`, and change the `send_command("load_browser_item", {...})` payload to include `"track_type": track_type`:

```python
        result = ableton.send_command("load_browser_item", {
            "track_index": track_index,
            "item_uri": uri,
            "track_type": track_type,
        })
```

(Leave the rest of the function body unchanged.)

- [ ] **Step 4: Edit `load_preset`**

Change its signature from `(ctx: Context, track_index: int, path: str, name: str = None)` to add `track_type: str = "regular"` as the last param. Add a docstring line documenting `track_type` ('regular' default; only audio effects valid on return/master). Change the load `send_command("load_browser_item", {...})` payload (the one near the end, with `item_uri": uri`) to include `"track_type": track_type`:

```python
        load_result = ableton.send_command("load_browser_item", {
            "track_index": track_index,
            "item_uri": uri,
            "track_type": track_type,
        })
```

(Do NOT change the `get_browser_presets` pre-fetch call — only the load call.)

- [ ] **Step 5: Run new test + full suite**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_load_track_type.py -q` → PASS (3).
Then: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q` → all pass.
Then: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python -c "import ableton_mcp_max.server"` → clean.

- [ ] **Step 6: Commit**

```bash
git add tests/test_load_track_type.py ableton_mcp_max/server.py
git commit -m "feat(devices): track_type on load_instrument_or_effect/load_preset (server side)"
```

---

### Task 2: Remote Script `_load_browser_item` resolves master/return

**Files:**
- Modify: `remote_script/AbletonMCP/__init__.py` — `_load_browser_item` (~3226), dispatch (~275)

- [ ] **Step 1: Edit `_load_browser_item`**

Replace the method's signature and the track-resolution lines. New method:

```python
    def _load_browser_item(self, track_index, item_uri, track_type="regular"):
        """Load a browser item onto a track by its URI"""
        try:
            track = self._resolve_track(track_index, track_type)

            # Access the application's browser instance instead of creating a new one
            app = self.application()

            # Find the browser item by URI
            item = self._find_browser_item_by_uri(app.browser, item_uri)

            if not item:
                raise ValueError("Browser item with URI '{0}' not found".format(item_uri))

            # Select the track
            self._song.view.selected_track = track

            # Load the item
            app.browser.load_item(item)

            result = {
                "loaded": True,
                "item_name": item.name,
                "track_name": track.name,
                "track_type": track_type,
                "uri": item_uri
            }
            return result
        except Exception as e:
            self.log_message("Error loading browser item: {0}".format(str(e)))
            self.log_message(traceback.format_exc())
            raise
```

(This removes the `if track_index < 0 or track_index >= len(self._song.tracks): raise IndexError` block and the `track = self._song.tracks[track_index]` line, replacing both with `_resolve_track`, which does its own bounds/type checks. Adds `"track_type"` to the result.)

- [ ] **Step 2: Edit the dispatch site**

Find:
```python
        elif command_type == "load_browser_item":
            track_index = params.get("track_index", 0)
            item_uri = params.get("item_uri", "")
            result = self._load_browser_item(track_index, item_uri)
```
Replace with:
```python
        elif command_type == "load_browser_item":
            track_index = params.get("track_index", 0)
            item_uri = params.get("item_uri", "")
            track_type = params.get("track_type", "regular")
            result = self._load_browser_item(track_index, item_uri, track_type)
```

- [ ] **Step 3: py_compile**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python -m py_compile remote_script/AbletonMCP/__init__.py`
Expected: clean exit 0. Confirm `_resolve_track` exists (~line 1048) and returns a track object.

- [ ] **Step 4: Commit**

```bash
git add remote_script/AbletonMCP/__init__.py
git commit -m "feat(devices): load_browser_item resolves master/return target track"
```

---

### Task 3: Regenerate docs

- [ ] **Step 1: Run generators**
```
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python scripts/build_tool_index.py
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python scripts/gen_docs_site.py
```
- [ ] **Step 2: Confirm only docs changed, tool count unchanged**

Run `git status --short` and `git diff --stat`. Expect only `docs/` (+ maybe `commands/tool-index.md`). Confirm `track_type` now appears on the two load tools and the count is unchanged. If a count changed or source files changed, STOP and report.

- [ ] **Step 3: Commit** (only the files actually changed)
```bash
git add docs/ commands/tool-index.md
git commit -m "docs: regenerate tool index for load track_type"
```

---

### Task 4: Live verification (feasibility gate) + PROGRESS.md

Controller-run against the live Live 12 session.

- [ ] **Step 1:** Full offline gate: `PATH=... uv run --with pytest pytest -q` (all pass) + py_compile.
- [ ] **Step 2:** Reinstall RS + bounce Live (`bash scripts/install_remote_script.sh` then `restart_live`), restart Claude Code so server.py reloads. (Combined with the gap #0 live-verify.)
- [ ] **Step 3:** `load_instrument_or_effect(<return idx>, <EQ Eight uri>, track_type="return")` → confirm device appears via `get_device_info(..., track_type="return")`. FEASIBILITY GATE: if no device appears or `load_item` errors, STOP and reassess (no holder-track hack).
- [ ] **Step 4:** `load_instrument_or_effect(0, <EQ Eight uri>, track_type="master")` → confirm via `get_device_info(..., track_type="master")`. This master device then unblocks the gap #0 master param read/write/restore verification.
- [ ] **Step 5:** Confirm a regular-track load still works with no `track_type`. Clean up scratch devices with `delete_device` (correct `track_type`).
- [ ] **Step 6:** Record results in PROGRESS.md; commit.

---

## Self-Review

- Spec change point 1 (RS handler + dispatch) → Task 2. ✅
- Spec change point 2 (two server tools forward track_type, docstrings) → Task 1. ✅
- Spec change point 3 (docs regen) → Task 3. ✅
- load_drum_kit unchanged → not in any task. ✅
- Testing (offline payload incl. load_preset pre-fetch stub; py_compile; live feasibility gate on return + master; regular unchanged) → Task 1 + Task 4. ✅
- Backward-compat default 'regular' → Task 1 `test_load_instrument_defaults_to_regular` + Task 4 Step 5. ✅
- Type consistency: `_resolve_track(track_index, track_type)` returns a track object (existing helper, ~line 1048); `load_browser_item` command name + payload keys (`track_index`/`item_uri`/`track_type`) consistent across server tools, dispatch, handler. ✅
- No placeholders: live-verify URIs are runtime data (the operator picks the EQ Eight URI from the browser), not plan gaps.
