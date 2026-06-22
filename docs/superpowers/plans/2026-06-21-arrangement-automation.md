# Arrangement Timeline Automation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `set_arrangement_automation` - write device-parameter/rack-macro breakpoint envelopes onto the Arrangement timeline by patching the `.als` set file and reloading Live in place.

**Architecture:** Pure XML logic in `ableton_mcp_max/als_automation_utils.py` (gzip read/write + a depth-aware navigator that resolves a param's `<AutomationTarget Id>` + an envelope builder/injector), imported by `server.py` only. The tool saves the set, patches the on-disk `.als`, and reloads in place (⌘N + `open`). The Remote Script is untouched.

**Tech Stack:** Python 3 stdlib (`gzip`, `re`), FastMCP tool, System Events (osascript) for the in-place reload, pytest offline.

## Global Constraints

- Tool count goes 145 -> 146; new tool in the **Composition** category.
- `als_automation_utils.py` is imported by `server.py` ONLY (the Remote Script runs in Live's Python and cannot import it).
- Times are in **beats**; values are the parameter's **native units** (v1 = device params + rack macros; NO mixer volume/pan/sends, NO dB-curve conversion).
- Arrangement automation lives in the owning track's `<AutomationEnvelopes><Envelopes>` list as `<AutomationEnvelope>` with `<EnvelopeTarget><PointeeId Value="N"/>` where `N` = the param's `<AutomationTarget Id="N">`.
- Events: leading `-63072000` sentinel holding the first point's value, then `<FloatEvent Time Value/>` sorted by time (duplicate times allowed = vertical steps). Omit FloatEvent `Id` attrs.
- Offline gate: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q`, plus `uv run python -c "import ableton_mcp_max.server"`.
- No AI attribution in any commit/PR (public repo). gh account = `ringo380`.

---

### Task 1: gzip read/write core

**Files:**
- Create: `ableton_mcp_max/als_automation_utils.py`
- Test: `tests/test_als_automation_utils.py`

**Interfaces:**
- Produces: `read_als(path) -> str` (gunzip+decode utf-8), `write_als(path, xml) -> None` (encode+gzip).

- [ ] Write failing tests: `write_als` then `read_als` round-trips a unicode-bearing XML string byte-faithfully; `read_als` on a real `.als` fixture returns a string containing `<Ableton`.
- [ ] Run: expect FAIL (module missing).
- [ ] Implement `read_als`/`write_als` using `gzip.open`.
- [ ] Run: expect PASS.
- [ ] Commit `feat(automation): als gzip read/write core`.

---

### Task 2: points -> events + envelope XML builder

**Files:**
- Modify: `ableton_mcp_max/als_automation_utils.py`
- Test: `tests/test_als_automation_utils.py`

**Interfaces:**
- Produces:
  - `points_to_events(points) -> list[(time, value)]` - input `[{"time": float, "value": float}]`; output sorted by time with a leading `(-63072000.0, first_value)` sentinel; preserves duplicate times; raises ValueError on empty.
  - `build_envelope_xml(pointee_id, points, env_id, value_min=None, value_max=None) -> str` - renders `<AutomationEnvelope Id="{env_id}"><EnvelopeTarget><PointeeId Value="{pointee_id}"/></EnvelopeTarget><Automation><Events>...</Events><AutomationTransformViewState><IsTransformPending Value="false"/><TimeAndValueTransforms /></AutomationTransformViewState></Automation></AutomationEnvelope>`; values clamped to `[value_min, value_max]` when both given; floats formatted without scientific notation.

- [ ] Write failing tests: sentinel inserted with first value; sorting; duplicate-time preserved; clamping when min/max given; envelope XML contains the PointeeId and one FloatEvent per point + sentinel; well-formed (parses via `xml.etree.ElementTree.fromstring`).
- [ ] Run: expect FAIL.
- [ ] Implement both functions. Format floats with `repr`/`"%.10g"` style matching Live's precision; no `Id` attr on FloatEvent.
- [ ] Run: expect PASS.
- [ ] Commit `feat(automation): points-to-events + envelope XML builder`.

---

### Task 3: track/device/param navigator -> AutomationTarget Id

**Files:**
- Modify: `ableton_mcp_max/als_automation_utils.py`
- Test: `tests/test_als_automation_utils.py`

**Interfaces:**
- Produces:
  - `find_track_span(xml, track_index) -> (start, end)` - char span of the Nth regular track block (`<MidiTrack`/`<AudioTrack`, in document order under `<Tracks>`; excludes return/master).
  - `resolve_device_param_target(xml, track_index, device_index, parameter) -> {"pointee_id": str, "value_min": float|None, "value_max": float|None, "param_name": str}` - within the track span, locate the `device_index`-th device in its device chain, then the parameter by name (case-insensitive) or by int index among that device's automatable parameter elements, and return its `<AutomationTarget Id>` plus `MidiControllerRange` Min/Max if present. Raises `ValueError` with a precise message when the track/device/param is not found.

**Implementation notes (depth-aware, anchored on the track span - never the first global match):**
- Tracks: iterate `<MidiTrack ...>`/`<AudioTrack ...>` openings under `<Tracks>`; balance to the matching close to get the span.
- Device chain inside a track: `<DeviceChain><DeviceChain><Devices>` then the direct child device elements (each device is one element like `<PluginDevice>`, `<AuOriginalFileRef>`-bearing, `<InstrumentGroupDevice>`, etc.). `device_index` selects among `Devices`' direct children.
- A device parameter element is a direct child of the device with a `<AutomationTarget Id="..">` and usually a `<MidiControllerRange>` + `<Manual>`. Build the ordered list of such parameter elements; match `parameter` by the element tag/`Name` (case-insensitive) or by position.
- Rack macro: handled in Task 4 (separate resolver), but `resolve_device_param_target` covers plain device params.

- [ ] Write failing tests against a **synthetic** XML fixture (a minimal `<Tracks>` with two MidiTracks, each a device with two params having distinct AutomationTarget Ids + ranges): resolve by name and by index returns the right Id/range; wrong track/device/param raises with a clear message; the navigator picks the param in the *correct* track (not the first global match).
- [ ] Add a real-file test gated with `@pytest.mark.skipif` on a sample `.als` (reuse the live scratch set or a committed fixture) that resolves a known device param's AutomationTarget Id.
- [ ] Run: expect FAIL.
- [ ] Implement `find_track_span` + `resolve_device_param_target`.
- [ ] Run: expect PASS.
- [ ] Commit `feat(automation): device-param AutomationTarget navigator`.

---

### Task 4: rack-macro resolver

**Files:**
- Modify: `ableton_mcp_max/als_automation_utils.py`
- Test: `tests/test_als_automation_utils.py`

**Interfaces:**
- Produces: `resolve_macro_target(xml, track_index, device_index, macro_index) -> {"pointee_id": str, "value_min": float, "value_max": float, "param_name": str}` - within the track span, find the `device_index`-th device (a rack `GroupDevice`), then its `MacroControls.<macro_index>` element's `<AutomationTarget Id>` (range 0..127).

- [ ] Write failing test on a synthetic rack fixture (`<...GroupDevice>` with `<MacroControls.0>`/`<MacroControls.1>` each with an AutomationTarget Id): resolve macro 0 and 1 to the right Ids; out-of-range macro raises.
- [ ] Run: expect FAIL.
- [ ] Implement `resolve_macro_target`.
- [ ] Run: expect PASS.
- [ ] Commit `feat(automation): rack-macro AutomationTarget resolver`.

---

### Task 5: inject envelope into the track's Envelopes list

**Files:**
- Modify: `ableton_mcp_max/als_automation_utils.py`
- Test: `tests/test_als_automation_utils.py`

**Interfaces:**
- Produces:
  - `next_envelope_id(track_xml) -> int` - max existing `AutomationEnvelope Id` in the track span + 1, else 0.
  - `inject_envelope(xml, track_index, pointee_id, envelope_builder, replace=True) -> str` - locate the track span's `<AutomationEnvelopes><Envelopes ...>` (handles both `<Envelopes />` self-closing and `<Envelopes>...</Envelopes>`); if `replace`, remove any existing `<AutomationEnvelope>` whose `PointeeId` == `pointee_id`; allocate `next_envelope_id`; insert the built envelope; return the new XML. `envelope_builder(env_id) -> str` lets the caller bind points/clamp before the Id is known.

- [ ] Write failing tests: injecting into a self-closing `<Envelopes />` produces a non-empty list with the envelope; injecting a second different PointeeId appends with Id+1; `replace=True` on an existing PointeeId swaps it (count stays 1, new points); the injected region re-parses as valid XML; injection targets the correct track's list (two-track fixture).
- [ ] Run: expect FAIL.
- [ ] Implement `next_envelope_id` + `inject_envelope`.
- [ ] Run: expect PASS.
- [ ] Commit `feat(automation): envelope injection into track Envelopes list`.

---

### Task 6: real-file end-to-end util round-trip

**Files:**
- Modify: `tests/test_als_automation_utils.py`
- (Optional) Create: `tests/fixtures/automation_sample.als` (a small committed set) OR gate on the live scratch set path.

**Interfaces:** none new - exercises Tasks 1-5 together.

- [ ] Write a `skipif`-gated test: `read_als` a real set -> `resolve_device_param_target` for a known device param -> `build_envelope_xml`/`inject_envelope` with 3 points -> `write_als` to a temp path -> `read_als` back -> assert the envelope is present in the right track's list with the right PointeeId and 3 points + sentinel, and the whole doc re-parses.
- [ ] Run: expect PASS (or SKIP if no fixture).
- [ ] Commit `test(automation): real-file envelope round-trip`.

---

### Task 7: `_reload_set` server helper (in-place reload)

**Files:**
- Modify: `ableton_mcp_max/server.py`
- Test: `tests/test_arrangement_automation.py` (mock the osascript/connection layer)

**Interfaces:**
- Produces: `_reload_set(path, set_name, settle=...) -> {"reloaded": bool, "title": str}` - activates Live, sends ⌘N (defensively answers a save dialog with ⌘D), runs `open <path>`, waits until the front window title == `set_name` and a probe MCP read succeeds (absorbing one `None.None(Song)` stale-handle error with a short retry). Pure osascript/`open` orchestration; no app quit.

- [ ] Write failing test: with the osascript/`open`/probe functions monkeypatched, `_reload_set` issues new-set then open then polls the probe, returns `reloaded:True` when the probe succeeds; returns `reloaded:False` if the title never matches within the timeout.
- [ ] Run: expect FAIL.
- [ ] Implement `_reload_set` (mirror `_restart_live_impl`'s osascript style; reuse the graceful-dialog keystrokes). Factor the System-Events calls behind small seams so the test can monkeypatch them.
- [ ] Run: expect PASS.
- [ ] Commit `feat(automation): in-place set reload helper`.

---

### Task 8: `set_arrangement_automation` MCP tool

**Files:**
- Modify: `ableton_mcp_max/server.py` (add the `@mcp.tool()` near `set_automation`)
- Test: `tests/test_arrangement_automation.py`

**Interfaces:**
- Consumes: Tasks 1-7 (`read_als`/`write_als`/`resolve_device_param_target`/`resolve_macro_target`/`build_envelope_xml`/`inject_envelope`/`_reload_set`), plus existing `save_set` impl + `get_ableton_connection`.
- Produces: tool
  `set_arrangement_automation(ctx, lanes: List[dict], reload: bool = True) -> str` where each lane = `{track_index, device_index=0, parameter (name|index) OR macro_index, points: [{time, value}], replace=True}`.

**Behavior:**
- Resolve the current set path; if Untitled (no path / save_set reports untitled) -> `_err("save the set first via save_set_as")`.
- `save_set` (in place) to flush Live's state to disk.
- `read_als(path)`; for each lane resolve target (macro vs device param), `build_envelope_xml` (clamped to range), `inject_envelope`. Collect per-lane results; a lane that fails to resolve is recorded `ok:false` and skipped (others still written).
- If >=1 lane succeeded: `write_als(path)`; if `reload`, `_reload_set(path, set_name)`.
- Return `_ok({set_path, reloaded, lanes:[{track_index, device_index, parameter|macro_index, pointee_id, points_written, ok, error?}]})`.

- [ ] Write failing tests (mock `save_set`/connection/`read_als`/`write_als`/`_reload_set`): a single device-param lane writes the envelope and reports `points_written`; an unresolved param yields `ok:false` without aborting a sibling lane; Untitled set short-circuits with the save-first error; `reload=False` skips `_reload_set`.
- [ ] Run: expect FAIL.
- [ ] Implement the tool.
- [ ] Run: expect PASS, then full offline gate (`pytest -q`, server import).
- [ ] Commit `feat(automation): set_arrangement_automation tool (#30)`.

---

### Task 9: docs + tool index + counts

**Files:**
- Modify: `scripts/build_tool_index.py` (add `set_arrangement_automation` to Composition), `scripts/gen_docs_site.py` (same)
- Regenerate: `commands/tool-index.md`, `docs/tools/composition.md`, `docs/tools/index.md`
- Modify: `docs/index.md` (5 hardcoded counts 145 -> 146)

- [ ] Add the tool to both GROUPS lists (Composition).
- [ ] Run `uv run python scripts/build_tool_index.py` and `uv run python scripts/gen_docs_site.py`; expect "146 tools".
- [ ] `sed` the 5 count spots in `docs/index.md` 145 -> 146.
- [ ] Run offline gate again (counts/categorization assertions pass).
- [ ] Commit `docs: set_arrangement_automation (146 tools)`.

---

### Task 10: live verification (main loop, not a subagent)

**Files:** none (verification + PROGRESS/memory note)

- [ ] Reinstall is NOT needed (Remote Script unchanged); restart Claude Code to load the new server tool (note for the user) OR use the AbletonDev working-tree server after restart.
- [ ] Load a scratch named set with a device (e.g. the live test set with `808 Drifter`). Call `set_arrangement_automation` on a device param across several beats.
- [ ] Confirm in-place reload happened; re-save and verify Live wrote back the `<AutomationEnvelope>` for that PointeeId with the expected points (proves Live accepted it), and that the param value moves across the arrangement.
- [ ] Record results in PROGRESS.md + memory.
- [ ] Ship: version bump (pyproject + plugin.json + `uv lock`), PR, squash-merge, `gh release`, marketplace ref bump + `build-readme.js`, verify chain.

## Self-Review

- **Spec coverage:** gzip core (T1), events/builder (T2), navigator (T3), macros (T4), injection (T5), real-file round-trip (T6), reload helper (T7), tool (T8), docs/counts (T9), live verify + ship (T10). All spec sections covered. Mixer/Bool/Enum/read-back explicitly deferred (spec Follow-ups).
- **Placeholders:** none - each task names exact files, function signatures, and concrete test assertions.
- **Type consistency:** `pointee_id` (str) flows from `resolve_*_target` -> `build_envelope_xml`/`inject_envelope`; `points` shape `[{time,value}]` consistent T2/T8; `_reload_set` returns `{reloaded,title}` consumed by T8.
