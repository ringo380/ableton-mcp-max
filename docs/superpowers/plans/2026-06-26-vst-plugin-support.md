# VST/AU Plugin Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **NOTE on execution mode:** This plan is gated by a live, interactive Ableton spike (Task 0) and its downstream tasks all require live MCP verification against a running Live set (plus the dual-restart protocol that needs the user). Tasks are sequential and gated, not independent. **Inline execution in the main loop is the correct mode**, not subagent fan-out - subagents cannot drive the live set, hit stream-idle timeouts on Live operations, and cannot trigger the Claude Code restart. Use offline subagents only for read-only review of the pure `*_utils.py` if desired.

**Goal:** Let the MCP expose, control, and author parameters of third-party VST3/AU plugins (Serum 2 first) by writing Live's Configure-list XML directly, so plugin knobs become ordinary LOM `DeviceParameter`s.

**Architecture:** A generic XML "exposure" engine fills `<PluginFloatParameter>` slots in a plugin device's saved XML from a per-plugin param-map pack; on reload Live presents those params to the LOM, and the existing `get_device_parameters` / `set_device_parameter` tools handle control and authoring. Per-plugin support is a new pack + curation, not new mechanism.

**Tech Stack:** Python 3 (server-side, `uv`), FastMCP `@mcp.tool()`, the embedded-Python Remote Script (Py2/3.7-safe), the shared `preset_patch.py` XML core, gzip `.als`/`.adv`, pytest (offline pure-logic only).

## Global Constraints

- **Restart protocol:** Remote Script edits -> `bash scripts/install_remote_script.sh` + quit/reopen Live; `server.py`/`*_utils.py` edits -> restart Claude Code (MCP loads at session start). Use the **AbletonDev** tools (working tree) to live-test server edits, not the cached `plugin:ableton` tools.
- **`*_utils.py` are imported by server.py ONLY** - the Remote Script runs in Live's separate Python and cannot import them. Resolve/encode on the server; send already-resolved values to the handler.
- **Remote Script is Py2/3.7-safe:** `%`-formatting only, no f-strings / `match` / `X | Y` unions; `import Live` for LOM types; probe unsupported endpoints with `try/except`, never `hasattr`.
- **Preset-XML regex needs `re.DOTALL`** - real `.adv`/`.als` are multi-line; one-line synthetic fixtures pass without it but real files fail. XML-escape/unescape `&`/`<`/`>` in display names. Never assert on the first `re.search` of a recurring tag; navigate to it.
- **128-slot pool is a hard cap** (confirmed by the XML and the Serumify product). If a plugin exposes >128 host params, curate and `log()` what was dropped - no silent truncation.
- **Offline gate:** `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q`, `uv run python -c "import ableton_mcp_max.server"`, `uv run python -m py_compile remote_script/AbletonMCP/__init__.py`. Do NOT reformat existing files.
- **Live set changes between sessions** - re-read track/device indices; never assume track 0. Restore/clean any scratch tracks/devices.
- **No AI attribution** in any commit/PR/doc.

## Known encoding (from the 2026-06-26 save-diff, Serum 2 VST3)

A filled `<PluginFloatParameter>` slot, derived empirically:

```xml
<PluginFloatParameter Id="{slot_index}">
  <ParameterName Value="{name}" />
  <ParameterId Value="{vst3_param_id}" />
  <ParameterIdFlankBool Value="false" />
  <VisualIndex Value="{display_order}" />
  <ParameterValue>
    <LomId Value="0" />
    <Manual Value="{native_unit_value}" />
    <MidiControllerRange><Min Value="0" /><Max Value="1" /></MidiControllerRange>
    <AutomationTarget Id="{unique_id}"><LockEnvelope Value="0" /></AutomationTarget>
    <ModulationTarget Id="{unique_id}"><LockEnvelope Value="0" /></ModulationTarget>
  </ParameterValue>
  <LastUserRange><First Value="Invalid" /><Last Value="Invalid" /></LastUserRange>
  <LastInternalRange><First Value="0" /><Last Value="1" /></LastInternalRange>
</PluginFloatParameter>
```

Observed example ids (Filter 1 block, contiguous): Freq=2000003, Res=2000004, Drive=2000005, Var=2000006. Empty slot sentinels: `ParameterId=-1`, `ParameterName=""`, `Manual=0.1234567687`, `VisualIndex=1073741823`. **Open questions Task 0 must answer:** whether `AutomationTarget`/`ModulationTarget` `Id`s must be unique/non-zero (Live 12 corrupts on duplicate FloatEvent ids in arrangement envelopes - same risk class), and whether an externally-written slot is honored on reload.

---

### Task 0: GATE - prove external slot-patch round-trips (live spike)

This is exploratory live verification, not TDD. It gates every task below. **If it fails, stop and reconvene** - the design pivots.

**Files:**
- Scratch only: work from the existing `~/Desktop/serum2_test Project/serum2_test.als` (already holds Serum 2 + 4 Configured Filter params) and a throwaway patch script in the scratchpad. No repo files change.

**Interfaces:**
- Produces (as findings recorded in PROGRESS.md, consumed by all later tasks): confirmation that a patched slot becomes a live LOM `DeviceParameter`; the required `AutomationTarget`/`ModulationTarget` `Id` rule; whether `.adv` hot-swap preserves patch state (decides Option B vs A).

- [ ] **Step 1: Snapshot the baseline param count.** With `serum2_test.als` loaded in Live, via the AbletonDev MCP call `get_device_parameters(track_index=<serum track>, device_index=0)`. Expected: 5 params (`Device On` + the 4 Filter params). Record names/values.

- [ ] **Step 2: Patch one extra slot into the `.als`.** In the scratchpad, gunzip the `.als`, find the first empty `<PluginFloatParameter>` (ParameterId=-1), and rewrite it to expose a known un-Configured Serum param - use `ParameterId=2000007` (next after the Filter block), `ParameterName="MCP Probe"`, `Manual` a mid value, `VisualIndex=4`, and **unique** `AutomationTarget`/`ModulationTarget` `Id`s not used elsewhere in the file (scan for the max existing Id, add +1/+2). Gzip back over the file. (Script lives in scratchpad; keep a `.bak`.)

- [ ] **Step 3: Reload the set in Live.** Have the user reopen `serum2_test.als` (File > Open Recent, or the restart flow). Do NOT use `save_set_as` (modal-panel risk). Wait for the control surface to rebind (~10-15s).

- [ ] **Step 4: Verify the patched param is live.** `get_device_parameters(...)` again. Expected: param_count = 6, including a settable param resolving to a real Serum control name (Live may relabel `2000007` to its true name, e.g. another Filter/Env param - record what it becomes). PASS = the new slot appears.

- [ ] **Step 5: Verify it is settable and audible.** `set_device_parameter(...)` on the new param to a different value; re-read to confirm it took; listen/inspect that Serum responded. PASS = external patch yields real control.

- [ ] **Step 6: Decide Option B vs A.** Save the Serum device as an `.adv` (user drags it to the browser User Library, or right-click > Save), patch one extra slot in the `.adv` the same way, load it via `load_preset`/browser onto a scratch track, and check whether (a) the exposed param appears and (b) the sound/patch state is preserved. PASS for B = both true. If hot-swap drops state, mark Option A primary.

- [ ] **Step 7: Record findings in PROGRESS.md** - round-trip result, the Id-uniqueness rule, the id->resolved-name observation, and B-vs-A decision. Commit the PROGRESS note.

```bash
git add PROGRESS.md && git commit -m "spike: Serum 2 external Configure-slot patch round-trips (Task 0 findings)"
```

**Gate:** Steps 4 + 5 must PASS to proceed. If they fail, stop.

---

### Task 1: `plugin_config_utils.py` - slot encoder (offline TDD)

Pure server-side XML logic for building/parsing Configure slots. No Live needed.

**Files:**
- Create: `ableton_mcp_max/plugin_config_utils.py`
- Test: `tests/test_plugin_config_utils.py`
- Reference (read, do not edit): `ableton_mcp_max/preset_patch.py`, `ableton_mcp_max/rack_preset_utils.py` (existing backdoor patterns).

**Interfaces:**
- Produces:
  - `EMPTY_PARAM_ID = -1`, `EMPTY_MANUAL = "0.1234567687"`, `EMPTY_VISUAL = "1073741823"`
  - `find_empty_slots(parameter_list_xml: str) -> list[int]` - slot `Id`s where ParameterId == -1.
  - `count_slots(parameter_list_xml: str) -> int`
  - `max_target_id(full_xml: str) -> int` - largest `AutomationTarget`/`ModulationTarget` `Id` in the doc (for allocating unique ids).
  - `build_slot(slot_id: int, param_id: int, name: str, manual: str, visual_index: int, auto_id: int, mod_id: int) -> str` - returns one `<PluginFloatParameter>` block (XML-escaped name).
  - `fill_slots(parameter_list_xml: str, params: list[dict], start_target_id: int) -> tuple[str, int]` - replace the first N empty slots with the given params (each `{param_id, name, manual, visual_index}`), allocating unique target ids from `start_target_id`; returns (new_xml, dropped_count). Raises if `len(params)` exceeds available empty slots only after filling the max possible; returns dropped_count for the overflow (caller logs it).

- [ ] **Step 1: Write failing tests.**

```python
from ableton_mcp_max import plugin_config_utils as pcu

EMPTY = '<PluginFloatParameter Id="0"><ParameterName Value="" /><ParameterId Value="-1" /><ParameterIdFlankBool Value="false" /><VisualIndex Value="1073741823" /><ParameterValue><LomId Value="0" /><Manual Value="0.1234567687" /><MidiControllerRange><Min Value="0" /><Max Value="1" /></MidiControllerRange><AutomationTarget Id="100"><LockEnvelope Value="0" /></AutomationTarget><ModulationTarget Id="101"><LockEnvelope Value="0" /></ModulationTarget></ParameterValue><LastUserRange><First Value="Invalid" /><Last Value="Invalid" /></LastUserRange><LastInternalRange><First Value="0" /><Last Value="1" /></LastInternalRange></PluginFloatParameter>'

def test_find_empty_slots():
    assert pcu.find_empty_slots(EMPTY) == [0]

def test_max_target_id():
    assert pcu.max_target_id(EMPTY) == 101

def test_build_slot_sets_fields():
    blk = pcu.build_slot(0, 2000003, "Filter 1 Freq", "1547.45", 0, 200, 201)
    assert 'ParameterId Value="2000003"' in blk
    assert 'ParameterName Value="Filter 1 Freq"' in blk
    assert 'Manual Value="1547.45"' in blk
    assert 'VisualIndex Value="0"' in blk
    assert 'AutomationTarget Id="200"' in blk

def test_build_slot_escapes_name():
    blk = pcu.build_slot(0, 1, "A & B <x>", "0.5", 0, 1, 2)
    assert "A &amp; B &lt;x&gt;" in blk

def test_fill_slots_fills_and_reports_overflow():
    params = [{"param_id": 2000003, "name": "Filter 1 Freq", "manual": "1547.45", "visual_index": 0}]
    out, dropped = pcu.fill_slots(EMPTY, params, start_target_id=200)
    assert 'ParameterId Value="2000003"' in out
    assert dropped == 0
    out2, dropped2 = pcu.fill_slots(EMPTY, params * 3, start_target_id=200)
    assert dropped2 == 2  # only one empty slot available
```

- [ ] **Step 2: Run, verify fail.** `PATH=... uv run --with pytest pytest tests/test_plugin_config_utils.py -v` -> FAIL (module missing).

- [ ] **Step 3: Implement `plugin_config_utils.py`** with `re.DOTALL` block matching (mirror `rack_preset_utils.py` style), XML-escaping via the `preset_patch` helper if present (else `xml.sax.saxutils.escape`). Allocate `auto_id`/`mod_id` sequentially from `start_target_id`. Replace empty slots in document order.

- [ ] **Step 4: Run, verify pass.** Same command -> PASS.

- [ ] **Step 5: Commit.**

```bash
git add ableton_mcp_max/plugin_config_utils.py tests/test_plugin_config_utils.py
git commit -m "feat(plugin): plugin_config_utils - Configure-slot XML encoder"
```

---

### Task 2: Param-map pack format + Serum 2 discovery probe (Remote Script + tool)

Reads a live plugin's parameter names and writes a reusable pack. Adjust field specifics to Task 0 findings (esp. the id->name resolution).

**Files:**
- Modify: `remote_script/AbletonMCP/__init__.py` - add read-only `probe_plugin_parameters` to `_process_command` (inline read; no main_thread mutation).
- Modify: `ableton_mcp_max/server.py` - add `@mcp.tool() probe_plugin_parameters(track_index, device_index, track_type='regular')`.
- Create: `ableton_mcp_max/param_maps/__init__.py` (empty) and `ableton_mcp_max/param_maps/serum2.json` (generated, committed).
- Create: `ableton_mcp_max/param_map_utils.py` (load/validate a pack) + `tests/test_param_map_utils.py`.

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces:
  - RS command `probe_plugin_parameters` -> `{device_name, parameter_count, names: [str], bank_indices: [[int]]}` using `device.get_parameter_names(0, -1)` and `device.get_bank_parameters(-1)` (guard with try/except; both are PluginDevice methods).
  - `param_map_utils.load_pack(name: str) -> dict` -> `{plugin, id_base, params: [{param_id, name, category}]}`.
  - `param_map_utils.derive_serum_ids(names: list[str], id_base: int = 2000000) -> list[dict]` - apply the `id = id_base + index` hypothesis (validated in Step 3).

- [ ] **Step 1: Add the RS handler** (Py3.7-safe, `import Live`):

```python
elif command_type == "probe_plugin_parameters":
    track = self._get_track(params.get("track_index"), params.get("track_type", "regular"))
    dev = track.devices[params.get("device_index", 0)]
    names = []
    try:
        names = list(dev.get_parameter_names(0, -1))
    except Exception as e:
        self.log_message("probe_plugin_parameters names err: %s" % e)
    banks = []
    try:
        banks = [list(dev.get_bank_parameters(-1))]
    except Exception:
        pass
    response = {"status": "success", "result": {"device_name": dev.name,
        "parameter_count": len(names), "names": names, "bank_indices": banks}}
```

- [ ] **Step 2: Reinstall RS + bounce Live.** `bash scripts/install_remote_script.sh` then quit/reopen Live (Claude may self-drive the Live bounce). Add the server tool (thin wrapper sending the command); restart Claude Code to load it.

- [ ] **Step 3: Run the probe live + validate the id hypothesis.** With Serum 2 on a track, call `probe_plugin_parameters`. Confirm `names[3] == "Filter 1 Freq"`, `names[4] == "Filter 1 Res"`, etc., matching the Task 0 ids (2000003 at index 3 => `id = 2000000 + index`). If the offset differs or ids are sparse, record the true mapping. Record the full `names` list.

- [ ] **Step 4: Generate `serum2.json`** from the probe output via `derive_serum_ids`, with hand-curated `category` tags (Osc/Filter/Env/LFO/FX/Macro/Global). If `parameter_count > 128`, mark a `curated: true` subset of <=128 and record the dropped names.

- [ ] **Step 5: Offline tests for `param_map_utils`** (load/validate/derive), TDD as in Task 1. Run -> PASS.

- [ ] **Step 6: Commit.**

```bash
git add remote_script/AbletonMCP/__init__.py ableton_mcp_max/server.py \
  ableton_mcp_max/param_maps/ ableton_mcp_max/param_map_utils.py tests/test_param_map_utils.py
git commit -m "feat(plugin): probe_plugin_parameters + Serum 2 param-map pack"
```

---

### Task 3: `expose_plugin_parameters` tool (engine, Option A live-set patch, live-verified)

**Release 1 = Option A (decided post-spike):** patch the live set's `.als` and reload. Serum stays
a top-level device, so the existing get/set tools control it (no new tooling). Option B (pre-exposed
rack `.adg` + nested param access) is a deferred Release-2 task (see Task 6).

The exposure flow, proven manually in Task 0, now automated:
1. **Save** the current set so its state (incl. the plugin chunk) is on disk. Already-saved set ->
   `Cmd+S` (clean); Untitled -> surface a clear error asking the user to name+save first (the
   Save-As panel is not reliably scriptable and risks the multi-monitor modal trap hit in Task 0).
2. **Read** the `.als`, locate the target track's `<PluginDevice>` `<ParameterList>`, `fill_slots`
   from the pack (allocate the two target ids per slot FROM `<NextPointeeId>` and advance it by 2
   per slot), `log()` any >128 overflow.
3. **Reload** the set via the existing `restart_live`/reopen path; re-read params to confirm.

**Files:**
- Modify: `ableton_mcp_max/server.py` - add `@mcp.tool() expose_plugin_parameters(track_index, device_index=0, pack="serum2", track_type='regular', curated=True)`; add `_patch_als_parameter_list(als_path, track_index, device_index, params)` helper using `plugin_config_utils`.
- Reference: existing save/reload helpers (`save_set`, `restart_live`/`_restart_live_impl`, the `_reload_set` pattern from arrangement automation) and the Task 0 scratchpad patch script.

**Interfaces:**
- Consumes: `plugin_config_utils.fill_slots` + `find_empty_slots` + the `<NextPointeeId>` bump (add `bump_next_pointee_id(full_xml, count) -> (xml, start_id)` to `plugin_config_utils` in Task 1 if not already), `param_map_utils.load_pack`.
- Produces: `expose_plugin_parameters(...)` -> `{ok, exposed_count, dropped_count, method: "live_set", reloaded: bool, error?}`.

- [ ] **Step 1: Extend `plugin_config_utils`** with `bump_next_pointee_id(full_xml, count)` (read `<NextPointeeId>`, return the doc with it advanced by `2*count` and the first allocatable id) - TDD offline against a synthetic doc; assert the new counter == old + 2*count and exceeds all target ids. Run -> PASS.

- [ ] **Step 2: Implement `_patch_als_parameter_list` + the tool** - locate the Nth track's Nth `<PluginDevice>` `<ParameterList>` (navigate, do not match the first `<ParameterList>` blindly - per the preset-XML gotcha), `fill_slots` with pack params, splice back, gzip-write. Untitled-set guard returns a clear error. `log()` overflow.

- [ ] **Step 3: Offline guard test** - a synthetic `.als` fragment (PluginDevice + ParameterList + NextPointeeId) round-trips: N empty slots filled, NextPointeeId advanced by 2N, names XML-escaped. Run -> PASS.

- [ ] **Step 4: Live verify** - load Serum 2 on a scratch track, save the set, call `expose_plugin_parameters`, let it reload, then `get_device_parameters` -> expect the curated param set present and settable. Set 3-4 params (a filter, an env, an osc level), confirm audible/readable change. Clean up the scratch track.

- [ ] **Step 5: Record live results in PROGRESS.md; commit.**

```bash
git add ableton_mcp_max/server.py ableton_mcp_max/plugin_config_utils.py tests/ PROGRESS.md
git commit -m "feat(plugin): expose_plugin_parameters - live-set Configure-slot exposure (Option A)"
```

---

### Task 4: Library navigation - presets (live-verified, conditional)

Wrap `presets` / `selected_preset_index` if they populate for Serum 2 (probe first per CLAUDE.md); else document `.adv` recall as the path.

**Files:**
- Modify: `remote_script/AbletonMCP/__init__.py` - add read `get_plugin_presets` (returns `device.presets` + `selected_preset_index`) and mutation `select_plugin_preset` (sets `selected_preset_index`, in the mutation list + `main_thread_task`).
- Modify: `ableton_mcp_max/server.py` - add the two thin tools.

**Interfaces:**
- Produces: `get_plugin_presets(track_index, device_index)` -> `{count, selected, names: [str]}`; `select_plugin_preset(track_index, device_index, index)` -> `{ok, selected}`.

- [ ] **Step 1: Probe first** - add the read handler, reinstall + bounce, and check whether `device.presets` is non-empty for Serum 2. If empty, STOP this task and instead add a one-paragraph note to the docs that Serum patches are recalled via Ableton `.adv` (existing `load_preset`), and skip to Task 5.

- [ ] **Step 2 (if populated): implement `select_plugin_preset`** (mutation; remember song-property write-lag - verify via a separate follow-up read, not the returned dict).

- [ ] **Step 3: Live verify** select changes the patch; record in PROGRESS.md.

- [ ] **Step 4: Commit.**

```bash
git add remote_script/AbletonMCP/__init__.py ableton_mcp_max/server.py PROGRESS.md
git commit -m "feat(plugin): plugin preset list + selection"
```

---

### Task 5: Curation, docs, ship (Release 1)

**Files:**
- Modify: `ableton_mcp_max/param_maps/serum2.json` (final curation/grouping).
- Modify: docs/tool-index regen outputs via `scripts/gen_docs_site.py` + `scripts/build_tool_index.py`; **hand-bump** the hardcoded tool counts in `docs/index.md` (5 spots) and `README.md:7`.
- Modify: `pyproject.toml` + `.claude-plugin/plugin.json` version, then `uv lock`.

- [ ] **Step 1: Finalize curation** - confirm the curated Serum 2 set covers all macros + filters + envs + LFOs + osc levels + FX (the high-value surface), <=128, dropped list logged.

- [ ] **Step 2: Offline gate** - pytest + server import + RS py_compile all green.

- [ ] **Step 3: Regen docs + bump counts by hand** (new tool count). Run the two regen scripts; edit the 5 hardcoded spots in `docs/index.md` and the count in `README.md:7`.

- [ ] **Step 4: Bump version in 3 files + `uv lock`; commit.**

- [ ] **Step 5: PR.** `gh pr create` (verify `gh api user --jq .login` == ringo380 first), squash-merge, then `gh release create vX.Y.Z`, bump the `ref` in the marketplace `marketplace.json`, `node scripts/build-readme.js`, push the marketplace repo. Confirm the release chain (local main = origin/main = `git ls-remote` tag commit).

---

### Task 6: Release 2 (fast-follow) - pre-exposed rack `.adg` + nested param access

Deferred per the post-spike decision (C). Removes Release 1's per-instance save+reload friction.
Plan it in detail when Release 1 has shipped and the engine + Serum pack are validated; sketch:

- **Nested-device param access:** extend `get_device_parameters` / `set_device_parameter` (or add
  `get_chain_device_parameters` / `set_chain_device_parameter`) to address a device inside a rack
  chain (the released tools only index `track.devices`). Reuse the existing `get_rack_chains` +
  macro-mapping nested-navigation code.
- **Rack `.adg` synthesizer:** build a pre-exposed Serum rack `.adg`, storing exposure as
  `<PluginParameterSettings>` (Index/VisualIndex/ParameterId/Type) - confirmed in Task 0 to carry
  exposure + plugin state, loads with no set reload, no `<NextPointeeId>` needed. Ship it as the
  "Serum 2 (MCP)" preset; load via the User-Library browser path (ensure `_find_browser_item`
  traverses the `user_library` branch - the released `load_preset` did not resolve it in Task 0).
- **Live verify:** load the rack preset, reach Serum's nested exposed params, set them, confirm
  audible change with zero set reloads.

---

## Self-Review

**Spec coverage:** wall/opening findings -> Task 0 (gate PASSED); slot encoding -> Task 1; param-map discovery + id hypothesis -> Task 2; exposure engine via Option A live-set patch -> Task 3; library navigation (`presets`/`selected_preset_index`) -> Task 4; curation/128-cap/docs/ship Release 1 -> Task 5; Option B rack `.adg` + nested access deferred to Release 2 -> Task 6. Knob control + authoring are delivered by the existing `get_device_parameters`/`set_device_parameter` once exposed (no new task needed, by design). Hidden-state (wavetable file/mod-matrix) is surfaced via the Task 2 probe (names list shows whether they are host params) - no dedicated task, correctly, since it may be infeasible.

**Placeholder scan:** Task 0 is a spike (exploratory by nature, not a code placeholder); all code steps carry real code or exact handler patterns. Conditional branches (Task 4 stop-if-empty, Option A vs B) are decisions gated on recorded findings, not TODOs.

**Type consistency:** `fill_slots` returns `(xml, dropped_count)` used consistently in Tasks 1 and 3; `load_pack`/`derive_serum_ids` shapes consistent across Tasks 2 and 3; `build_slot` signature matches its test.
