# render_audio Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bounce the set's Main output to an audio file on disk via Live's Export dialog, with format/bit-depth/sample-rate/range under program control, and return the resolved path.

**Architecture:** Pure resolver (`export_utils.py`) + thin AX executor (`render_audio` in `server.py`) + one new Remote Script handler (`focus_view`). The render RANGE cannot be set through the dialog (its sliders are unwritable), so it is established BEFORE the dialog opens: set the arrangement loop via the LOM -> focus the Arrangement view (Remote Script) -> `Edit > Select Loop` (turns the loop into the time selection the dialog reads).

**Tech Stack:** Python 3, FastMCP, AppleScript/System Events via the existing `_osa` / `_osa_get` / `_click_file_menu` helpers, pytest.

**Spec:** `docs/superpowers/specs/2026-07-13-render-audio-design.md` - read the "Live-verified findings" section; every AX string in this plan was observed against Live 12.4.2, do not invent others.

## Global Constraints

- **Two new tools:** `focus_view` and `render_audio`. Tool count 185 -> **187**.
- **AX description strings are EXACT and verified.** Popups: `Rendered Track Chooser`, `Sample Rate`, `File Type`, `Recording Bit Depth`, `Dither Options`. Toggles: `Include Return and Main Effects`, `Render as Loop`, `Convert to Mono`, `Normalize`, `Create Analysis File`, `Encode PCM`, `Encode MP3`. Buttons: `Export`, `Cancel`. Window: `Export Audio/Video`. Save panel window: `Save`. File menu item: `Export Audio/Video...`. Edit menu item: `Select Loop`.
- **Toggles CLICK-TOGGLE, they do not set.** Always read the current `On`/`Off` and click ONLY on mismatch. A blind click inverts a correct control.
- **Never touch the Render Start/Length sliders.** They are unwritable by `AXSetValue` AND by click-then-type. Range comes from the loop + `Select Loop`.
- Remote Script must stay Py2/3.7-safe: `%`-formatting only, no f-strings, no `match`, no `X | Y` unions.
- `*_utils.py` are imported by `server.py` ONLY (the Remote Script runs in Live's own interpreter and cannot import them).
- Every tool returns `_ok(data)` / `_err(message)` - never raise out of an `@mcp.tool()`.
- Tests: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q`
- No AI attribution anywhere (commits, code comments, docs).

---

### Task 1: `export_utils.py` - the pure resolver

**Files:**
- Create: `ableton_mcp_max/export_utils.py`
- Test: `tests/test_export_utils.py`

**Interfaces:**
- Consumes: nothing (pure).
- Produces, for Task 3:
  - `plan_export(file_type="WAV", bit_depth=24, sample_rate=44100, normalize=False, mp3=False, mono=False, include_returns=True, analysis_file=True, dither="No Dither") -> {"popups": [{"description": str, "value": str}], "toggles": [{"description": str, "want": "On"|"Off"}]}`
  - `clean_render_name(name) -> str`
  - `loop_range_for(start_bar, end_bar, song_length, sig_num) -> (start_beats, length_beats)`
  - Constants: `FILE_TYPES`, `BIT_DEPTHS`, `SAMPLE_RATES`, `DITHER_OPTIONS`.

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from ableton_mcp_max.export_utils import (
    plan_export, clean_render_name, loop_range_for,
)


def _toggle(plan, desc):
    return next(t["want"] for t in plan["toggles"] if t["description"] == desc)


def _popup(plan, desc):
    return next(p["value"] for p in plan["popups"] if p["description"] == desc)


def test_default_plan_is_wav_24_44100_pcm_on_mp3_off():
    p = plan_export()
    assert _popup(p, "File Type") == "WAV"
    assert _popup(p, "Recording Bit Depth") == "24"
    assert _popup(p, "Sample Rate") == "44100"
    assert _toggle(p, "Encode PCM") == "On"
    assert _toggle(p, "Encode MP3") == "Off"
    assert _toggle(p, "Normalize") == "Off"


def test_file_type_mp3_turns_pcm_off_and_mp3_on():
    p = plan_export(file_type="MP3")
    assert _toggle(p, "Encode PCM") == "Off"
    assert _toggle(p, "Encode MP3") == "On"


def test_mp3_flag_alongside_wav_emits_both():
    p = plan_export(file_type="WAV", mp3=True)
    assert _toggle(p, "Encode PCM") == "On"
    assert _toggle(p, "Encode MP3") == "On"


def test_every_managed_toggle_has_an_explicit_want():
    # The executor reads-then-clicks, so a missing want would mean "unknown".
    p = plan_export()
    wants = {t["description"]: t["want"] for t in p["toggles"]}
    for d in ("Include Return and Main Effects", "Render as Loop",
              "Convert to Mono", "Normalize", "Create Analysis File",
              "Encode PCM", "Encode MP3"):
        assert wants[d] in ("On", "Off")


@pytest.mark.parametrize("kw", [
    {"file_type": "OGG"}, {"bit_depth": 12}, {"sample_rate": 12345},
    {"dither": "Loud"},
])
def test_unknown_enum_values_are_rejected(kw):
    with pytest.raises(ValueError):
        plan_export(**kw)


@pytest.mark.parametrize("bad", ["", "a/b", "a:b", "   "])
def test_clean_render_name_rejects(bad):
    with pytest.raises(ValueError):
        clean_render_name(bad)


def test_clean_render_name_passes_and_strips():
    assert clean_render_name("  my track  ") == "my track"


def test_loop_range_bar_math_is_one_based():
    assert loop_range_for(1, 5, 232.0, 4) == (0.0, 16.0)
    assert loop_range_for(5, 13, 232.0, 4) == (16.0, 32.0)


def test_loop_range_honors_time_signature():
    assert loop_range_for(5, 9, 232.0, 3) == (12.0, 12.0)


def test_loop_range_defaults_to_whole_song():
    assert loop_range_for(None, None, 232.0, 4) == (0.0, 232.0)


@pytest.mark.parametrize("args", [(5, 5, 232.0, 4), (9, 5, 232.0, 4),
                                  (None, None, 0.0, 4)])
def test_loop_range_rejects_empty_spans(args):
    with pytest.raises(ValueError):
        loop_range_for(*args)
```

- [ ] **Step 2: Run to verify it fails**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_export_utils.py -q`
Expected: FAIL - `ModuleNotFoundError: ableton_mcp_max.export_utils`

- [ ] **Step 3: Implement `export_utils.py`**

```python
"""Pure resolver for render_audio: validate export options and turn them into a
plan keyed to the Export dialog's real AX description strings.

No I/O. The AX strings here were read off Live 12.4.2's Export Audio/Video
dialog (see the design spec) - do not invent new ones.
"""

FILE_TYPES = ("WAV", "AIFF", "FLAC", "MP3")
BIT_DEPTHS = ("16", "24", "32")
SAMPLE_RATES = ("44100", "48000", "88200", "96000", "176400", "192000")
DITHER_OPTIONS = ("No Dither", "Triangular", "Rectangular",
                  "POW-r 1", "POW-r 2", "POW-r 3")


def _one_of(value, allowed, label):
    v = str(value).strip()
    if v not in allowed:
        raise ValueError("%s must be one of %s (got %r)."
                         % (label, ", ".join(allowed), value))
    return v


def clean_render_name(name):
    """Basename for the render. Rejects the characters that hijack the macOS
    save panel: '/' opens Go-to-Folder, ':' is the legacy path separator."""
    n = (name or "").strip()
    if not n:
        raise ValueError("name is required (the render needs a file name).")
    for ch in ("/", ":"):
        if ch in n:
            raise ValueError("name may not contain %r." % ch)
    return n


def loop_range_for(start_bar, end_bar, song_length, sig_num):
    """(start_beats, length_beats) for the arrangement loop that will seed the
    export range. Bars are 1-based as Live displays them, so bar N begins at
    (N-1)*sig_num beats. Both bars None => the whole song."""
    if start_bar is None and end_bar is None:
        length = float(song_length)
        if length <= 0:
            raise ValueError("The song is empty (song_length is 0) - "
                             "nothing to render.")
        return (0.0, length)
    if start_bar is None or end_bar is None:
        raise ValueError("Pass BOTH start_bar and end_bar, or neither "
                         "(neither = render the whole song).")
    if int(start_bar) < 1:
        raise ValueError("start_bar is 1-based (got %r)." % start_bar)
    if int(end_bar) <= int(start_bar):
        raise ValueError("end_bar (%r) must be greater than start_bar (%r)."
                         % (end_bar, start_bar))
    beats = float(sig_num)
    start = (int(start_bar) - 1) * beats
    length = (int(end_bar) - int(start_bar)) * beats
    return (start, length)


def plan_export(file_type="WAV", bit_depth=24, sample_rate=44100,
                normalize=False, mp3=False, mono=False, include_returns=True,
                analysis_file=True, dither="No Dither"):
    """Validated plan for the Export dialog: which popups to set and what every
    managed toggle's value must END UP as. The executor reads each toggle and
    clicks only on a mismatch (clicking TOGGLES - a blind click inverts a
    control that is already correct)."""
    ft = _one_of(file_type, FILE_TYPES, "file_type")
    depth = _one_of(bit_depth, BIT_DEPTHS, "bit_depth")
    rate = _one_of(sample_rate, SAMPLE_RATES, "sample_rate")
    dith = _one_of(dither, DITHER_OPTIONS, "dither")

    # Live emits one file per enabled encoder: file_type MP3 means MP3 only;
    # mp3=True alongside a PCM type emits BOTH (observed live).
    pcm_on = ft != "MP3"
    mp3_on = bool(mp3) or ft == "MP3"

    popups = [
        {"description": "Rendered Track Chooser", "value": "Main"},
        {"description": "Sample Rate", "value": rate},
    ]
    if pcm_on:
        popups.append({"description": "File Type", "value": ft})
        popups.append({"description": "Recording Bit Depth", "value": depth})
        popups.append({"description": "Dither Options", "value": dith})

    def flag(b):
        return "On" if b else "Off"

    toggles = [
        {"description": "Include Return and Main Effects",
         "want": flag(include_returns)},
        {"description": "Render as Loop", "want": "Off"},
        {"description": "Convert to Mono", "want": flag(mono)},
        {"description": "Normalize", "want": flag(normalize)},
        {"description": "Create Analysis File", "want": flag(analysis_file)},
        {"description": "Encode PCM", "want": flag(pcm_on)},
        {"description": "Encode MP3", "want": flag(mp3_on)},
    ]
    return {"popups": popups, "toggles": toggles,
            "file_type": ft, "bit_depth": depth, "sample_rate": rate,
            "pcm": pcm_on, "mp3": mp3_on}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_export_utils.py -q`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/export_utils.py tests/test_export_utils.py
git commit -m "feat: export_utils - pure resolver for render_audio options and range"
```

---

### Task 2: Remote Script `focus_view` handler + `focus_view` tool

**Files:**
- Modify: `remote_script/AbletonMCP/__init__.py` (add a `focus_view` branch in `_process_command`)
- Modify: `ableton_mcp_max/server.py` (add the `focus_view` `@mcp.tool()`)
- Test: `tests/test_focus_view_tool.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces, for Task 3: an MCP tool `focus_view(view: str = "Arranger")` and the wire command `focus_view` with params `{"view": "Arranger"|"Session"}`. Task 3 calls the tool's underlying socket command before clicking `Select Loop`.

**Context:** `Select Loop` is DISABLED while Live shows the Session view, and the View menu only offers a TOGGLE. `Application.View.is_view_visible/show_view/focus_view` exist in the LOM and are the deterministic path. This is a READ-style command (no song mutation), so it runs inline in `_process_command` - it does NOT go in the `main_thread_task` mutation list.

- [ ] **Step 1: Add the Remote Script handler**

In `remote_script/AbletonMCP/__init__.py`, inside `_process_command`, alongside the other inline read commands, add:

```python
        elif command_type == "focus_view":
            view = params.get("view", "Arranger")
            if view not in ("Arranger", "Session"):
                raise Exception("view must be 'Arranger' or 'Session'")
            app = Live.Application.get_application()
            if not app.view.is_view_visible(view):
                app.view.show_view(view)
            app.view.focus_view(view)
            response["result"] = {"view": view, "focused": True}
```

(Match the surrounding branches' exact response shape - read two neighbours first and mirror them.)

- [ ] **Step 2: Syntax-check the Remote Script**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python -m py_compile remote_script/AbletonMCP/__init__.py`
Expected: no output (exit 0)

- [ ] **Step 3: Write the failing test**

```python
import json
from ableton_mcp_max import server


class _FakeConn:
    def __init__(self):
        self.sent = []

    def send_command(self, cmd, params=None):
        self.sent.append((cmd, params or {}))
        return {"view": (params or {}).get("view"), "focused": True}


def test_focus_view_sends_the_command(monkeypatch):
    conn = _FakeConn()
    monkeypatch.setattr(server, "get_ableton_connection", lambda: conn)
    out = json.loads(server.focus_view(None, "Arranger"))
    assert out["ok"] is True
    assert conn.sent == [("focus_view", {"view": "Arranger"})]


def test_focus_view_rejects_unknown_view(monkeypatch):
    conn = _FakeConn()
    monkeypatch.setattr(server, "get_ableton_connection", lambda: conn)
    out = json.loads(server.focus_view(None, "Mixer"))
    assert out["ok"] is False
    assert conn.sent == []      # validated before the socket call
```

- [ ] **Step 4: Run to verify it fails**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_focus_view_tool.py -q`
Expected: FAIL - `AttributeError: module 'ableton_mcp_max.server' has no attribute 'focus_view'`

- [ ] **Step 5: Add the tool to `server.py`**

Place it next to the other view tools (near `set_selected_track`). Mirror the surrounding tools' `get_ableton_connection()` / `_ok` / `_err` shape:

```python
@mcp.tool()
def focus_view(ctx: Context, view: str = "Arranger") -> str:
    """Show and focus one of Live's main views: 'Arranger' (default) or
    'Session'. Deterministic, unlike the View menu's Toggle item - some
    commands are only available in one view (Edit > Select Loop, which
    render_audio relies on, is disabled in Session view).

    Returns JSON {ok, data:{view, focused}}.
    """
    try:
        v = (view or "Arranger").strip()
        if v not in ("Arranger", "Session"):
            return _err("view must be 'Arranger' or 'Session' (got %r)." % view)
        result = get_ableton_connection().send_command("focus_view", {"view": v})
        return _ok(result)
    except Exception as e:
        logger.error("focus_view error: %s", e)
        return _err("focus_view error: %s" % e)
```

- [ ] **Step 6: Run the tests + import check**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_focus_view_tool.py -q && uv run python -c "import ableton_mcp_max.server"`
Expected: PASS, then no output from the import.

- [ ] **Step 7: Commit**

```bash
git add remote_script/AbletonMCP/__init__.py ableton_mcp_max/server.py tests/test_focus_view_tool.py
git commit -m "feat: focus_view - deterministically show/focus the Arranger or Session view"
```

---

### Task 3: `render_audio` executor

**Files:**
- Modify: `ableton_mcp_max/server.py` (helpers + the `render_audio` `@mcp.tool()`, placed after `save_set_as`)
- Test: `tests/test_render_audio.py`

**Interfaces:**
- Consumes: `export_utils.plan_export` / `clean_render_name` / `loop_range_for` (Task 1); the `focus_view` wire command (Task 2); existing `_osa`, `_osa_get`, `_as_literal`, `_click_file_menu`, `_keystroke`, `_press_return`, `_wait_until`, `_live_window_count`, `_live_app_and_pid`, `_app_name`, `_ok`, `_err`.
- Produces: the `render_audio` tool.

**Read first:** `_save_as_impl` in `server.py` - it is the template for activate -> menu -> wait-for-panel -> select-all -> type -> Return -> resolve-path, including the Accessibility-permission error message. Reuse its idioms rather than inventing new ones.

- [ ] **Step 1: Write the failing tests**

All UI is monkeypatched - these tests never touch Live.

```python
import json
import pytest
from ableton_mcp_max import server


class _FakeUI:
    """Records AX calls and answers reads from a scripted dialog state."""

    def __init__(self, toggles=None, popups=None):
        self.toggles = toggles or {}
        self.popups = popups or {}
        self.clicks = []
        self.menus = []
        self.pressed = []

    def read_toggle(self, desc):
        return self.toggles.get(desc, "Off")

    def click_toggle(self, desc):
        self.clicks.append(desc)
        self.toggles[desc] = "On" if self.toggles.get(desc) == "Off" else "Off"

    def read_popup(self, desc):
        return self.popups.get(desc, "")

    def set_popup(self, desc, value):
        self.popups[desc] = value

    def press(self, desc):
        self.pressed.append(desc)


@pytest.fixture
def wired(monkeypatch):
    ui = _FakeUI()
    monkeypatch.setattr(server, "_live_app_and_pid",
                        lambda: ("/Applications/Live.app", 123))
    monkeypatch.setattr(server, "_app_name", lambda app: "Ableton Live 12 Suite")
    monkeypatch.setattr(server, "_osa", lambda s: None)
    monkeypatch.setattr(server, "_export_ui", ui)
    return ui


def test_toggle_already_correct_is_not_clicked(wired):
    # Normalize wants Off and IS Off -> clicking would turn it ON.
    wired.toggles["Normalize"] = "Off"
    server._apply_toggles([{"description": "Normalize", "want": "Off"}], wired)
    assert wired.clicks == []


def test_toggle_mismatched_is_clicked_once(wired):
    wired.toggles["Normalize"] = "On"
    server._apply_toggles([{"description": "Normalize", "want": "Off"}], wired)
    assert wired.clicks == ["Normalize"]
    assert wired.toggles["Normalize"] == "Off"


def test_render_audio_rejects_bad_name_before_touching_the_ui(wired):
    out = json.loads(server.render_audio(None, "a/b"))
    assert out["ok"] is False
    assert wired.menus == [] and wired.pressed == []


def test_render_audio_errors_when_dialog_never_appears(monkeypatch, wired):
    monkeypatch.setattr(server, "_open_export_dialog", lambda: False)
    out = json.loads(server.render_audio(None, "track"))
    assert out["ok"] is False
    assert "Export" in out["error"]
    assert "Export" not in wired.pressed        # never pressed Export
```

(Add the analogous cases from the spec's test list: verification-mismatch -> Cancel pressed and no Export; completion-poll timeout -> `{ok:false, rendered:false}`. Shape the seams - `_export_ui`, `_open_export_dialog` - so these are testable without Live.)

- [ ] **Step 2: Run to verify it fails**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_render_audio.py -q`
Expected: FAIL - `AttributeError: ... has no attribute 'render_audio'`

- [ ] **Step 3: Implement the executor**

Write the AX seam (an `_ExportUI` object with `read_toggle` / `click_toggle` / `read_popup` / `set_popup` / `press`, each a thin `_osa` / `_osa_get` call against `group 1 of window "Export Audio/Video"`), plus:

- `_apply_toggles(toggles, ui)` - read-then-click, ONLY on mismatch.
- `_open_export_dialog()` -> bool - `_click_file_menu("Export Audio/Video...")` then `_wait_until` the window exists.
- `_resolve_render_path(basename, ext, since)` - `mdfind -name <basename>`, keep files whose extension matches and whose mtime >= `since`. MUST NOT exclude `~/Library` (iCloud Drive lives under `~/Library/Mobile Documents` - a `find ~ -not -path "*/Library/*"` silently misses the file).
- `render_audio(...)` following the spec's step list: validate (pure) -> set loop -> `focus_view("Arranger")` -> `Edit > Select Loop` -> open dialog -> verify seeded range -> apply toggles + popups -> verify -> press Export -> Save panel: select-all + type name + Return -> poll both windows gone (bounded by `timeout`) -> resolve path -> `_ok`.

Every failure path returns `_err` (or `{ok:true, path:null}` when only the path lookup failed - the file DOES exist). On a verification mismatch, press `Cancel` first.

- [ ] **Step 4: Run tests + full suite + import check**

Run:
```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_render_audio.py -q
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python -c "import ableton_mcp_max.server"
```
Expected: focused tests PASS; full suite PASS (no regressions); import silent.

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/server.py tests/test_render_audio.py
git commit -m "feat: render_audio - bounce the Main output to disk via Live's Export dialog"
```

---

### Task 4: Docs, categories, and counts

**Files:**
- Modify: `scripts/build_tool_index.py` (GROUPS)
- Modify: `scripts/gen_docs_site.py` (categories)
- Modify: `README.md` (line 7 hardcodes the tool count)
- Modify: `docs/index.md` (hardcodes the tool + category counts in SIX places)
- Regenerate: `docs/tools/`, `docs/tools/index.md`, `commands/tool-index.md`

**Context:** BOTH regen scripts carry a MANUAL category map and `gen_docs_site.py` ASSERTS every tool is categorized exactly once - so they FAIL until the new tools are filed. File them first, then run the scripts.

- [ ] **Step 1: File the new tools in both category maps**

- `scripts/build_tool_index.py` GROUPS: add `"focus_view"` to `("Session & view", [...])`, and add a new group `("Export", ["render_audio"])`.
- `scripts/gen_docs_site.py`: add `"focus_view"` to the `session-view` category's tool list, and add a new category:
  ```python
  ("export", "Export", "Bounce the set's Main output to an audio file on disk - format, bit depth, sample rate, and bar range under program control - by driving Live's Export Audio/Video dialog (there is no LOM render API).", [
      "render_audio",
  ]),
  ```

- [ ] **Step 2: Regenerate the docs**

Run:
```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python scripts/build_tool_index.py
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python scripts/gen_docs_site.py
```
Expected: both succeed and report **187** tools. If either raises "not categorized", Step 1 is incomplete.

- [ ] **Step 3: Bump the hardcoded counts by hand**

The regen scripts touch NEITHER of these files:
- `README.md` line 7: "reference for all **185** tools" -> **187**.
- `docs/index.md`: SIX hardcoded sites (description, tagline, two `stats__num`, the "exposes the N `@mcp.tool()`" line, and the "Browse all N tools" link). Also bump the CATEGORY count 23 -> 24 wherever it appears.

Verify none are stale: `grep -rn "185\|\b23 categories\b" README.md docs/index.md` should return nothing referring to the tool/category counts.

- [ ] **Step 4: Full suite + commit**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q
git add -A
git commit -m "docs: file render_audio + focus_view, regen tool index (187 tools)"
```

---

## Live gate (controller, after all tasks - NOT a subagent task)

Requires a Claude Code restart (server.py) + a Remote Script reinstall and a Live bounce (`bash scripts/install_remote_script.sh`, then `restart_live`).

- [ ] Put Live in **SESSION** view by hand, then `render_audio(name="mcp_gate", start_bar=1, end_bar=3)` -> must still work (the tool focuses Arrangement itself), file on disk, duration == 2 bars at the set's tempo.
- [ ] `render_audio(name="mcp_gate_full")` with no range -> renders the whole song.
- [ ] `mp3=True` -> both a WAV and an MP3 reported.
- [ ] Re-run with identical options -> no toggle churn (dialog state already correct).
- [ ] `render_audio(name="a/b")` -> rejected before any dialog opens.
- [ ] Delete the gate renders afterwards; restore the loop/view state.
