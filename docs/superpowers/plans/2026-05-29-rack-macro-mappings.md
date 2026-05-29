# Rack Macro→Parameter Mappings (Phase B v1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `add_rack_macro_mappings` — write macro→parameter mappings into a User Library rack `.adg` (impossible via the LOM), using the encoding cracked by the 2026-05-29 save-diff experiment.

**Architecture:** Pure XML logic in the existing `ableton_mcp_max/rack_preset_utils.py` (one new depth-aware navigator + one patch function on the shared `preset_patch`/regex approach). One new `@mcp.tool()` in `server.py` that reads the working preset, patches in place, and rewrites it. Same pipeline-on-a-working-preset model as Phase A; load via the existing `load_preset`.

**Tech Stack:** Python 3 (server-side, modern syntax OK — NOT the Live Remote Script), regex string-patching of gzipped Ableton preset XML, FastMCP, pytest offline. No Remote Script changes → restart Claude Code to reload; no Live bounce.

**Spec:** `docs/superpowers/specs/2026-05-29-rack-preset-macro-mapping-design.md` (Section 3 "FINDINGS" + the `add_rack_macro_mappings` def).

---

## The confirmed encoding (from the experiment)

A macro→parameter mapping is a self-contained `<KeyMidi>` block injected into the **target
parameter element**, right after its `<LomId .../>`:

```xml
<KeyMidi>
  <PersistentKeyString Value="" />
  <IsNote Value="false" />
  <Channel Value="16" />            <!-- constant macro sentinel (real MIDI ch = 0..15) -->
  <NoteOrController Value="N" />     <!-- N = 0-based macro index: Macro 1 => 0 -->
  <LowerRangeNote Value="-1" />
  <UpperRangeNote Value="-1" />
  <ControllerMapMode Value="0" />
</KeyMidi>
```

No IDs, no registry. Many params may share a macro (same `N`). Default full-range mapping
needs no range edit (v1 scope; custom ranges = deferred v2).

### Preset device nesting (verified against a real saved rack)

In a `.adg` **preset** (not an `.als` project), devices live under:

```
<XBranchPreset>                       (one per chain; X = Instrument/AudioEffect/MidiEffect/Drum)
  <DevicePresets>                     (direct child of the branch)
    <AbletonDevicePreset>            (one per device on the chain)
      <Device>
        <StereoGain ...>             (the device element; tag = Live internal name, e.g. Utility = StereoGain)
          <LomId Value="0" />
          <Gain> <LomId/> <Manual/> ... </Gain>   (parameters are DIRECT children of the device element)
          ...
```

So navigation for chain C, device D, parameter P:
branch[C] → direct-child `<DevicePresets>` → D-th `<AbletonDevicePreset>` → `<Device>` →
its single child (the device element) → direct-child `<P>` → inject `<KeyMidi>` after `<LomId>`.

(`branch[C]` uses the existing depth-aware `top_branches` so a rack-in-rack's inner branches
don't miscount. The `<AbletonDevicePreset>` enumeration must likewise be depth-aware: a nested
rack device contains its own nested `<AbletonDevicePreset>` elements.)

## File Structure

- **Modify** `ableton_mcp_max/rack_preset_utils.py` — add a generic depth-aware direct-child
  element scanner `_child_elements`, a `_find_child` convenience, and `patch_macro_mappings`.
- **Modify** `tests/test_rack_preset_utils.py` — add fixtures + tests for the scanner and the
  patcher.
- **Modify** `ableton_mcp_max/server.py` — add the `add_rack_macro_mappings` tool.

---

## Task 1: Depth-aware direct-child element scanner

**Files:**
- Modify: `ableton_mcp_max/rack_preset_utils.py`
- Test: `tests/test_rack_preset_utils.py`

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_rack_preset_utils.py
from ableton_mcp_max.rack_preset_utils import _child_elements, _find_child

ELEM = (
    '<Root>'
    '<LomId Value="0" />'
    '<A><Inner Value="1" /><Nested><A /></Nested></A>'
    '<B Value="x" />'
    '<A><Two Value="2" /></A>'
    '</Root>'
)

def test_child_elements_direct_only():
    kids = _child_elements(ELEM)
    tags = [t for (t, s, e) in kids]
    # direct children only: LomId, A, B, A — the <A/> nested inside <Nested> is NOT counted
    assert tags == ["LomId", "A", "B", "A"]

def test_child_elements_spans_roundtrip():
    kids = _child_elements(ELEM)
    # the first <A> span must include its full nested content
    t, s, e = kids[1]
    assert t == "A"
    assert ELEM[s:e] == '<A><Inner Value="1" /><Nested><A /></Nested></A>'

def test_child_elements_selfclosing_with_slashes_in_attr():
    el = '<P><Path Value="a/b/c" /><Manual Value="1" /></P>'
    assert [t for (t, s, e) in _child_elements(el)] == ["Path", "Manual"]

def test_find_child_first_match():
    span = _find_child(ELEM, "A")
    assert span is not None and ELEM[span[0]:span[1]].startswith("<A><Inner")

def test_find_child_absent():
    assert _find_child(ELEM, "Nope") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_rack_preset_utils.py -q`
Expected: FAIL — `ImportError: cannot import name '_child_elements'`.

- [ ] **Step 3: Write minimal implementation**

```python
# add to ableton_mcp_max/rack_preset_utils.py

# Matches one XML tag token: opening <Tag ...>, self-closing <Tag ... />, or close </Tag>.
# Attribute values may contain '/', so selfclose is the trailing '/' immediately before '>'.
_TAG_TOKEN = re.compile(r'<(/?)([A-Za-z0-9_.]+)((?:\s[^>]*?)?)(/?)>')


def _child_elements(element_xml):
    """Return [(tag, start, end), ...] for the DIRECT child elements of the single
    element whose full text is `element_xml` (it starts with the element's own
    opening tag and ends with its closing tag). Offsets are relative to
    element_xml. Handles self-closing children and arbitrary nesting/tag names.
    """
    spans = []
    depth = 0
    stack = []
    seen_root = False
    for m in _TAG_TOKEN.finditer(element_xml):
        closing, tag, _attrs, selfclose = m.group(1), m.group(2), m.group(3), m.group(4)
        if not seen_root:
            # first token is the root element's own opening tag
            seen_root = True
            depth = 1
            continue
        if closing:
            depth -= 1
            if depth == 1:
                st_tag, st_pos = stack.pop()
                spans.append((st_tag, st_pos, m.end()))
            elif depth == 0:
                break  # root element closed
        elif selfclose == "/":
            if depth == 1:
                spans.append((tag, m.start(), m.end()))
        else:
            if depth == 1:
                stack.append((tag, m.start()))
            depth += 1
    return spans


def _find_child(element_xml, tag):
    """Return (start, end) of the first direct-child element named `tag`, or None."""
    for t, s, e in _child_elements(element_xml):
        if t == tag:
            return (s, e)
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_rack_preset_utils.py -q`
Expected: PASS (5 new tests).

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/rack_preset_utils.py tests/test_rack_preset_utils.py
git commit -m "feat(rack-preset): depth-aware direct-child element scanner"
```

---

## Task 2: `patch_macro_mappings` — inject KeyMidi mappings

**Files:**
- Modify: `ableton_mcp_max/rack_preset_utils.py`
- Test: `tests/test_rack_preset_utils.py`

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_rack_preset_utils.py
from ableton_mcp_max.rack_preset_utils import patch_macro_mappings
import re as _re

# A minimal audio-effect rack with one chain, one device (StereoGain) with two params.
MAP_RACK = (
    '<Ableton><GroupDevicePreset><Device><AudioEffectGroupDevice>'
    '<NumVisibleMacroControls Value="2" />'
    '</AudioEffectGroupDevice></Device><BranchPresets>'
    '<AudioEffectBranchPreset Id="0"><Name Value="" /><UserName Value="A" />'
    '<DevicePresets>'
    '<AbletonDevicePreset Id="0"><Device>'
    '<StereoGain Id="0"><LomId Value="0" />'
    '<Gain><LomId Value="0" /><Manual Value="1" /><MidiControllerRange><Min Value="0" /><Max Value="1" /></MidiControllerRange></Gain>'
    '<Balance><LomId Value="0" /><Manual Value="0" /></Balance>'
    '</StereoGain></Device></AbletonDevicePreset>'
    '</DevicePresets>'
    '<DeviceChain></DeviceChain>'
    '</AudioEffectBranchPreset></BranchPresets>'
    '</GroupDevicePreset></Ableton>'
)

def _gain_keymidi(xml):
    g = _re.search(r'<Gain>.*?</Gain>', xml, _re.S).group(0)
    m = _re.search(r'<KeyMidi>.*?</KeyMidi>', g, _re.S)
    return m.group(0) if m else None

def test_patch_mapping_injects_keymidi():
    out = patch_macro_mappings(MAP_RACK, "audio_effect",
                               [{"macro": 1, "chain": 0, "device": 0, "parameter": "Gain"}])
    km = _gain_keymidi(out)
    assert km is not None
    assert '<Channel Value="16" />' in km
    assert '<NoteOrController Value="0" />' in km   # Macro 1 -> index 0
    assert '<ControllerMapMode Value="0" />' in km
    # injected after the param's <LomId>, before <Manual>
    g = _re.search(r'<Gain>.*?</Gain>', out, _re.S).group(0)
    assert g.index('<KeyMidi>') < g.index('<Manual')
    assert g.index('<LomId') < g.index('<KeyMidi>')

def test_patch_mapping_macro_index_is_zero_based():
    out = patch_macro_mappings(MAP_RACK, "audio_effect",
                               [{"macro": 8, "chain": 0, "device": 0, "parameter": "Gain"}])
    assert '<NoteOrController Value="7" />' in _gain_keymidi(out)

def test_patch_mapping_idempotent_replace():
    out = patch_macro_mappings(MAP_RACK, "audio_effect",
                               [{"macro": 1, "chain": 0, "device": 0, "parameter": "Gain"}])
    out2 = patch_macro_mappings(out, "audio_effect",
                                [{"macro": 3, "chain": 0, "device": 0, "parameter": "Gain"}])
    # exactly one KeyMidi on Gain, now pointing at macro index 2
    g = _re.search(r'<Gain>.*?</Gain>', out2, _re.S).group(0)
    assert g.count('<KeyMidi>') == 1
    assert '<NoteOrController Value="2" />' in g

def test_patch_mapping_many_to_one():
    out = patch_macro_mappings(MAP_RACK, "audio_effect", [
        {"macro": 1, "chain": 0, "device": 0, "parameter": "Gain"},
        {"macro": 1, "chain": 0, "device": 0, "parameter": "Balance"},
    ])
    assert '<NoteOrController Value="0" />' in _gain_keymidi(out)
    bal = _re.search(r'<Balance>.*?</Balance>', out, _re.S).group(0)
    assert '<KeyMidi>' in bal and '<NoteOrController Value="0" />' in bal

def test_patch_mapping_bad_parameter():
    with pytest.raises(ValueError):
        patch_macro_mappings(MAP_RACK, "audio_effect",
                             [{"macro": 1, "chain": 0, "device": 0, "parameter": "Nope"}])

def test_patch_mapping_bad_device_index():
    with pytest.raises(ValueError):
        patch_macro_mappings(MAP_RACK, "audio_effect",
                             [{"macro": 1, "chain": 0, "device": 5, "parameter": "Gain"}])

def test_patch_mapping_bad_macro_number():
    with pytest.raises(ValueError):
        patch_macro_mappings(MAP_RACK, "audio_effect",
                             [{"macro": 17, "chain": 0, "device": 0, "parameter": "Gain"}])

def test_patch_mapping_is_pure():
    src = MAP_RACK
    patch_macro_mappings(src, "audio_effect",
                         [{"macro": 1, "chain": 0, "device": 0, "parameter": "Gain"}])
    assert src == MAP_RACK
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_rack_preset_utils.py -q`
Expected: FAIL — `ImportError: cannot import name 'patch_macro_mappings'`.

- [ ] **Step 3: Write minimal implementation**

```python
# add to ableton_mcp_max/rack_preset_utils.py

_KEYMIDI_TEMPLATE = (
    "<KeyMidi>"
    '<PersistentKeyString Value="" />'
    '<IsNote Value="false" />'
    '<Channel Value="16" />'
    '<NoteOrController Value="%d" />'
    '<LowerRangeNote Value="-1" />'
    '<UpperRangeNote Value="-1" />'
    '<ControllerMapMode Value="0" />'
    "</KeyMidi>"
)


def _locate_param(xml, branch_tag, chain_index, device_index, parameter):
    """Return absolute (start, end) of the target parameter element, or raise
    ValueError with a clear message. Navigates branch -> DevicePresets ->
    Nth AbletonDevicePreset -> Device -> device element -> direct-child <parameter>.
    """
    bs, be = _branch_span(xml, branch_tag, chain_index)  # raises if chain bad
    branch = xml[bs:be]

    dp = _find_child(branch, "DevicePresets")
    if not dp:
        raise ValueError("chain %d has no <DevicePresets> (no devices)." % chain_index)
    base_dp = bs + dp[0]
    devicepresets = xml[base_dp:bs + dp[1]]

    devs = [(s, e) for (t, s, e) in _child_elements(devicepresets)
            if t == "AbletonDevicePreset"]
    if device_index < 0 or device_index >= len(devs):
        raise ValueError(
            "device index %d out of range (chain %d has %d device(s))."
            % (device_index, chain_index, len(devs)))
    ds, de = devs[device_index]
    base_adp = base_dp + ds
    adp = xml[base_adp:base_dp + de]

    dev = _find_child(adp, "Device")
    if not dev:
        raise ValueError("device %d has no <Device> wrapper." % device_index)
    base_dev = base_adp + dev[0]
    device_block = xml[base_dev:base_adp + dev[1]]

    devkids = _child_elements(device_block)
    if not devkids:
        raise ValueError("device %d <Device> has no device element." % device_index)
    dtag, des, dee = devkids[0]
    base_el = base_dev + des
    device_el = xml[base_el:base_dev + dee]

    p = _find_child(device_el, parameter)
    if not p:
        avail = sorted({t for (t, s, e) in _child_elements(device_el)})
        raise ValueError(
            "parameter <%s> not found as a direct child of device <%s> "
            "(chain %d, device %d). Available: %s"
            % (parameter, dtag, chain_index, device_index, ", ".join(avail)))
    return base_el + p[0], base_el + p[1]


def _inject_keymidi(param_el, macro_index):
    """Return param_el with a <KeyMidi> mapping for `macro_index` (0-based).

    Idempotent: if a <KeyMidi> already exists, replace its NoteOrController;
    otherwise insert after the param's first <LomId .../> (or after the opening
    tag if it has none).
    """
    if "<KeyMidi>" in param_el:
        return re.sub(
            r'(<KeyMidi>.*?<NoteOrController Value=")[^"]*(".*?</KeyMidi>)',
            lambda m: m.group(1) + str(macro_index) + m.group(2),
            param_el, count=1, flags=re.S)
    block = _KEYMIDI_TEMPLATE % macro_index
    lom = re.search(r'<LomId Value="[^"]*" />', param_el)
    if lom:
        return param_el[:lom.end()] + block + param_el[lom.end():]
    ot = re.match(r'<[A-Za-z0-9_.]+(?:\s[^>]*?)?>', param_el)
    if not ot:
        raise ValueError("malformed parameter element; cannot inject mapping.")
    return param_el[:ot.end()] + block + param_el[ot.end():]


def patch_macro_mappings(xml, rack_type, mappings):
    """Add macro->parameter mappings to a rack .adg XML. Pure: returns new XML.

    `mappings`: list of {macro (1-based), chain (0-based), device (0-based),
    parameter (XML tag name of the param within the device, e.g. 'Gain')}.
    Default full-range mappings (no min/max). Many params may share a macro.
    Re-mapping a param replaces its existing mapping.
    """
    btag = RACK_TYPES[rack_type]["branch_tag"]
    out = xml
    for mp in mappings:
        if not isinstance(mp, dict):
            raise ValueError("each mapping must be an object.")
        macro_index = _check_macro_number(mp.get("macro"))  # 0-based, validates 1..16
        chain = int(mp.get("chain"))
        device = int(mp.get("device"))
        parameter = str(mp.get("parameter", "")).strip()
        if not parameter:
            raise ValueError("mapping requires a 'parameter' tag name.")
        ps, pe = _locate_param(out, btag, chain, device, parameter)
        out = out[:ps] + _inject_keymidi(out[ps:pe], macro_index) + out[pe:]
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_rack_preset_utils.py -q`
Expected: PASS (8 new tests).

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/rack_preset_utils.py tests/test_rack_preset_utils.py
git commit -m "feat(rack-preset): patch_macro_mappings (KeyMidi macro->param injection)"
```

---

## Task 3: Real-factory round-trip test (offline, skip if Live absent)

Proves navigation + injection works on a real Ableton-serialized rack, not just the
synthetic fixture.

**Files:**
- Test: `tests/test_rack_preset_utils.py`

- [ ] **Step 1: Write the test**

```python
# add to tests/test_rack_preset_utils.py

@pytest.mark.skipif(_factory_rack("Audio Effect Racks") is None,
                    reason="Ableton Live factory racks not installed")
def test_real_audio_rack_mapping_roundtrip():
    # Use a factory audio-effect rack; map macro 2 onto the first param of its
    # first device, then confirm the KeyMidi is present with the right index.
    with gzip.open(_factory_rack("Audio Effect Racks"), "rt") as f:
        xml = f.read()
    # discover the first device's first parameter tag via the navigator
    from ableton_mcp_max.rack_preset_utils import (
        _branch_span, _find_child, _child_elements, RACK_TYPES, detect_rack_type,
    )
    btag = RACK_TYPES[detect_rack_type(xml)]["branch_tag"]
    bs, be = _branch_span(xml, btag, 0)
    branch = xml[bs:be]
    dp = _find_child(branch, "DevicePresets")
    devicepresets = branch[dp[0]:dp[1]]
    adp = [s for s in _child_elements(devicepresets) if s[0] == "AbletonDevicePreset"][0]
    adp_xml = devicepresets[adp[1]:adp[2]]
    dev = _find_child(adp_xml, "Device")
    device_el = adp_xml[dev[0]:dev[1]]
    dtag, ds, de = _child_elements(device_el)[0]
    # first real parameter child of the device element (has a <LomId> and <Manual>)
    param_tag = None
    inner = device_el[ds:de]
    for t, s, e in _child_elements(inner):
        block = inner[s:e]
        if "<LomId" in block and "<Manual" in block:
            param_tag = t
            break
    assert param_tag is not None

    out = patch_macro_mappings(xml, detect_rack_type(xml),
                               [{"macro": 2, "chain": 0, "device": 0, "parameter": param_tag}])
    # exactly one new KeyMidi appeared vs the original count, with index 1
    assert out.count("<KeyMidi>") == xml.count("<KeyMidi>") + 1
    blk = re.search(r'<%s>.*?</%s>' % (param_tag, param_tag), out, re.S).group(0)
    assert '<Channel Value="16" />' in blk and '<NoteOrController Value="1" />' in blk
```

- [ ] **Step 2: Run the test**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_rack_preset_utils.py -q`
Expected: PASS (runs on this machine — Live 11 installed).

- [ ] **Step 3: Commit**

```bash
git add tests/test_rack_preset_utils.py
git commit -m "test(rack-preset): real factory-file macro-mapping round-trip"
```

---

## Task 4: Server tool `add_rack_macro_mappings`

**Files:**
- Modify: `ableton_mcp_max/server.py`

- [ ] **Step 1: Extend the rack_preset_utils import**

Find the existing import block added in Phase A:
```python
from ableton_mcp_max.rack_preset_utils import (
    summarize_rack_adg, detect_rack_type, RACK_TYPES,
    patch_macros, patch_chain_zone,
)
```
Change it to also import the new function:
```python
from ableton_mcp_max.rack_preset_utils import (
    summarize_rack_adg, detect_rack_type, RACK_TYPES,
    patch_macros, patch_chain_zone, patch_macro_mappings,
)
```

- [ ] **Step 2: Add the tool after `set_rack_zones`**

```python
@mcp.tool()
def add_rack_macro_mappings(ctx: Context, name: str, mappings: list) -> str:
    """
    Map rack macros to device parameters on a User Library rack, in place.

    Macro->parameter mappings are NOT settable via the LOM — this preset edit is
    the only MCP route. Operates on a rack created by clone_rack (the working
    preset). Macros are addressed 1-based (matching set_rack_macro); chains
    0-based (matching get_rack_chains).

    Each entry in `mappings` is an object:
      {"macro": 1, "chain": 0, "device": 0, "parameter": "Gain"}
    - macro: 1..16 macro number.
    - chain: 0-based chain index.
    - device: 0-based device index within that chain.
    - parameter: the parameter's XML tag name within the device (e.g. "Gain",
            "Volume"). Use inspect-style trial or Live's device to find tag names;
            an invalid name returns an error listing the device's available tags.

    Mappings are default full-range (the macro sweeps the parameter's whole
    range). Re-mapping a parameter replaces its existing mapping; several
    parameters may share one macro. Load the result with load_preset, then verify
    by moving the macro (set_rack_macro) and reading the device parameter.

    Returns JSON {written, path, mappings:[...]}.
    """
    try:
        safe = validate_preset_name(name)
        if not isinstance(mappings, list) or not mappings:
            return "Error: mappings must be a non-empty list of {macro, chain, device, parameter} objects."
        category, device_folder, xml = _user_rack_category(safe)
        kind = detect_rack_type(xml)
        out = patch_macro_mappings(xml, kind, mappings)
        dest, _bp = _write_user_preset(
            out, safe, device_folder, category=category, ext="adg")
        return json.dumps({
            "written": True, "path": dest, "mappings": mappings,
        }, separators=(",", ":"))
    except (ValueError, FileNotFoundError) as e:
        return f"Error: {str(e)}"
    except Exception as e:
        logger.error(f"Error adding rack macro mappings: {str(e)}")
        return f"Error adding rack macro mappings: {str(e)}"
```

- [ ] **Step 3: Syntax-check + full offline gate**

Run:
```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python -c "import ableton_mcp_max.server"
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python -m py_compile remote_script/AbletonMCP/__init__.py
```
Expected: clean import; all tests pass (Phase A + the new mapping tests); remote script compiles.

- [ ] **Step 4: Commit**

```bash
git add ableton_mcp_max/server.py
git commit -m "feat(rack-preset): add_rack_macro_mappings tool"
```

---

## Task 5: Live verification (manual, requires restart)

No Remote Script change — restart Claude Code only (no Live bounce). The new tool arrives as
a deferred tool.

- [ ] **Step 1: Load the new tool after restart**

`ToolSearch` query: `select:mcp__AbletonDev__add_rack_macro_mappings`

- [ ] **Step 2: Build a mapped rack via the pipeline**

- `clone_rack` template="Basic Bass Amp" (or any audio-effect rack) name="MCP MapVerify".
- `add_rack_macro_mappings` name="MCP MapVerify", mappings=`[{"macro":1,"chain":0,"device":0,"parameter":"Gain"}]`
  (pick a parameter the device actually has; the error lists valid tags if wrong).
- `load_preset` track_index=<empty regular track> path="user_library/Presets/Audio Effects/Audio Effect Rack" name="MCP MapVerify".

- [ ] **Step 3: Programmatically confirm the mapping is live**

The LOM can't read mapping targets, so verify by EFFECT:
- `get_device_parameters` on the mapped device (the rack is device 0; the Utility/Gain is a
  device inside chain 0 — read its current value).
- `set_rack_macro` macro 1 to a high value, then re-read `get_device_parameters` — the mapped
  parameter must move. Set macro 1 low, read again — it moves back. That round-trip proves the
  mapping works.

- [ ] **Step 4: Clean up + record**

- `delete_track` the scratch track; `rm` the "MCP MapVerify.adg" from the User Library.
- Update PROGRESS.md: `add_rack_macro_mappings` live-verified (date), with the macro/param tested.

```bash
git add PROGRESS.md
git commit -m "docs: record add_rack_macro_mappings live verification"
```

---

## Task 6: Ship v0.3.0

- [ ] **Step 1: Bump plugin version**

Edit `.claude-plugin/plugin.json`: `"version": "0.2.0"` → `"version": "0.3.0"`; extend the
description's preset clause to mention macro mappings, e.g. "…rack macro names/colors/defaults,
macro→parameter mappings, and chain zones…". Commit:
```bash
git add .claude-plugin/plugin.json
git commit -m "chore(release): bump ableton plugin to 0.3.0 (macro mappings)"
```

- [ ] **Step 2: Merge to main**

```bash
git push -u origin feat/rack-macro-mappings
gh pr create --title "feat: add_rack_macro_mappings (rack macro->parameter mappings)" --body "<summary + test plan>"
gh pr merge <N> --squash --delete-branch
git checkout main && git pull --ff-only && git remote prune origin
```
Verify merged `main` is green: `PATH=... uv run --with pytest pytest -q`.

- [ ] **Step 3: Release + marketplace**

```bash
gh release create v0.3.0 --title "v0.3.0 — rack macro->parameter mappings" --notes "<notes>"
```
Then in `/Users/ryanrobson/git/robworks-claude-code-plugins`: bump the `ableton` entry `ref`
`v0.2.0` → `v0.3.0` and refresh its description in `.claude-plugin/marketplace.json`;
`node scripts/build-readme.js`; commit (`chore: bump ableton ref to v0.3.0`) and `git push`.

---

## Self-Review notes (completed during authoring)

- **Spec coverage:** spec Section 3 `add_rack_macro_mappings` v1 → Tasks 2 (helper) + 4 (tool);
  KeyMidi encoding (Channel=16, NoteOrController=macro-1, after `<LomId>`) → `_KEYMIDI_TEMPLATE`
  + `_inject_keymidi`; preset device nesting (DevicePresets→AbletonDevicePreset→Device→element→param)
  → `_locate_param`; many-to-one + idempotent replace + default full-range → covered by tests;
  custom ranges explicitly deferred (not in scope).
- **Placeholder scan:** none — all code complete; commands have expected output. (Task 6 PR
  title/body and release notes are author-supplied prose at ship time, not code placeholders.)
- **Type consistency:** `patch_macro_mappings(xml, rack_type, mappings)` signature identical in
  utils (Task 2), tests (Tasks 2–3), and the tool (Task 4). `_check_macro_number` returns the
  0-based index (reused from Phase A) → fed straight into `NoteOrController`. `RACK_TYPES`,
  `_branch_span`, `top_branches`, `_child_elements`, `_find_child` names match their definitions.
- **Known limitation (documented):** v1 addresses parameters that are DIRECT children of a
  (non-rack) device element; mapping a parameter inside a nested rack-in-rack device is out of
  scope. Custom/inverted mapping ranges deferred to v2 pending a follow-up save-diff.
