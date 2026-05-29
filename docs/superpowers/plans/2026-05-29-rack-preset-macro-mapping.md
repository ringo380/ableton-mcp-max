# Rack Preset — Macro Mapping & Zones Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add preset-patch tools that reach rack `.adg` state the LOM can't write — macro names/colors/defaults and chain key/velocity/chain-selector zones (Phase A) — plus a gated experiment to decide whether macro→parameter mappings are buildable (Phase B).

**Architecture:** Pure XML logic in a new `ableton_mcp_max/rack_preset_utils.py` (server-side only, on the shared `preset_patch` core). Tools follow the established pipeline-on-a-working-preset model: `clone_rack` copies a template into the User Library, then `rename_rack_macros` / `set_rack_zones` read+repatch it in place, then the existing `load_preset` tool loads the finished `.adg` onto a track. Chain zones are located with a depth-aware scanner that finds the zone block that is a *direct child* of a top-level branch element (ignoring the dozens of nested multisample `KeyRange`s a sampler-based chain injects).

**Tech Stack:** Python 3 (server side, modern syntax OK — NOT the Live 3.7 Remote Script), regex string-patching of gzipped Ableton preset XML, FastMCP `@mcp.tool()`, pytest offline. No Remote Script changes (so: restart Claude Code to reload the server, but **no `install_remote_script.sh`, no Live bounce**).

**Spec:** `docs/superpowers/specs/2026-05-29-rack-preset-macro-mapping-design.md`

---

## Background facts (probed 2026-05-29 against Live 11 factory racks)

Verified tag shapes — the plan's regexes depend on these:

- **Device-type child** names the rack kind: `<InstrumentGroupDevice>`, `<AudioEffectGroupDevice>`, `<MidiEffectGroupDevice>`, `<DrumGroupDevice>`.
- **Chain (branch) element** per rack type: `InstrumentBranchPreset`, `AudioEffectBranchPreset`, `MidiEffectBranchPreset`, `DrumBranchPreset`.
- **Macros** (always 16, period-indexed, self-closing): `<MacroDisplayNames.N Value="..." />`, `<MacroColor.N Value="..." />`, `<MacroDefaults.N Value="..." />`, plus `<NumVisibleMacroControls Value="N" />`.
- **Chain zones** are `<KeyRange>`, `<VelocityRange>`, `<BranchSelectorRange>` blocks; each holds four self-closing ints `<Min/>`, `<Max/>`, `<CrossfadeMin/>`, `<CrossfadeMax/>`.
  - Instrument + Drum chains have all three zones.
  - Audio-effect + MIDI-effect chains have **only** `BranchSelectorRange` (no key/velocity).
- **Nesting hazard (the crux):** a sampler-based instrument chain contains many `<MultiSamplePart>` blocks each with their own `<KeyRange>`/`<VelocityRange>`; drum racks contain many `<DrumBranchPreset>` pads. The chain-level zone is the one that is a **direct child** of the branch element — depth-aware scanning is required, not "first KeyRange in branch". This was proven: the direct-child finder returns exactly 1 clean chain zone for Grand Piano (a 129-KeyRange sampler rack).

## File Structure

- **Create** `ableton_mcp_max/rack_preset_utils.py` — all pure XML logic: rack-type detection, top-level branch span scanner, direct-child zone finder, macro patchers, zone patcher, summarizer, validators.
- **Create** `tests/test_rack_preset_utils.py` — offline unit tests over synthetic + (when present) real factory XML.
- **Modify** `ableton_mcp_max/server.py` — add `_read_rack_template()` and `_read_user_preset()` helpers; add 4 Phase A `@mcp.tool()` functions. Reuse existing `_user_library_dir`, `_write_user_preset`, `_load_user_preset`, `validate_preset_name`.
- **Modify** `PROGRESS.md` — record the new tools + live-verification results.

---

## Task 1: Rack type detection + branch/zone constants

**Files:**
- Create: `ableton_mcp_max/rack_preset_utils.py`
- Test: `tests/test_rack_preset_utils.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_rack_preset_utils.py
import gzip
import os
import pytest

from ableton_mcp_max.rack_preset_utils import (
    detect_rack_type, RACK_TYPES,
)

# Minimal synthetic racks carrying only the tags the utils touch.
INSTR_RACK = (
    '<Ableton><GroupDevicePreset><Device><InstrumentGroupDevice>'
    '<NumVisibleMacroControls Value="2" />'
    '<MacroDisplayNames.0 Value="Cutoff" /><MacroColor.0 Value="27" /><MacroDefaults.0 Value="56" />'
    '<MacroDisplayNames.1 Value="Reso" /><MacroColor.1 Value="27" /><MacroDefaults.1 Value="39" />'
    '</InstrumentGroupDevice></Device>'
    '<BranchPresets><InstrumentBranchPreset Id="0"><Name Value="" /><UserName Value="Chain A" />'
    '<BranchSelectorRange><Min Value="0" /><Max Value="0" /><CrossfadeMin Value="0" /><CrossfadeMax Value="0" /></BranchSelectorRange>'
    '<KeyRange><Min Value="0" /><Max Value="127" /><CrossfadeMin Value="0" /><CrossfadeMax Value="127" /></KeyRange>'
    '<VelocityRange><Min Value="1" /><Max Value="127" /><CrossfadeMin Value="1" /><CrossfadeMax Value="127" /></VelocityRange>'
    '<DeviceChain></DeviceChain>'
    '</InstrumentBranchPreset></BranchPresets>'
    '</GroupDevicePreset></Ableton>'
)
AUDIO_RACK = (
    '<Ableton><GroupDevicePreset><Device><AudioEffectGroupDevice>'
    '<NumVisibleMacroControls Value="1" />'
    '<MacroDisplayNames.0 Value="Mix" /><MacroColor.0 Value="13" /><MacroDefaults.0 Value="64" />'
    '</AudioEffectGroupDevice></Device>'
    '<BranchPresets><AudioEffectBranchPreset Id="0"><Name Value="" /><UserName Value="FX A" />'
    '<BranchSelectorRange><Min Value="0" /><Max Value="0" /><CrossfadeMin Value="0" /><CrossfadeMax Value="0" /></BranchSelectorRange>'
    '<DeviceChain></DeviceChain>'
    '</AudioEffectBranchPreset></BranchPresets>'
    '</GroupDevicePreset></Ableton>'
)


def test_detect_instrument():
    assert detect_rack_type(INSTR_RACK) == "instrument"


def test_detect_audio_effect():
    assert detect_rack_type(AUDIO_RACK) == "audio_effect"


def test_detect_unknown_raises():
    with pytest.raises(ValueError):
        detect_rack_type("<Ableton></Ableton>")


def test_rack_types_has_metadata():
    meta = RACK_TYPES["instrument"]
    assert meta["branch_tag"] == "InstrumentBranchPreset"
    assert meta["category"] == "Instruments"
    assert meta["device_folder"] == "Instrument Rack"
    assert meta["has_key_velocity"] is True
    assert RACK_TYPES["audio_effect"]["has_key_velocity"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_rack_preset_utils.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'ableton_mcp_max.rack_preset_utils'`.

- [ ] **Step 3: Write minimal implementation**

```python
# ableton_mcp_max/rack_preset_utils.py
"""Pure helpers for patching Ableton rack presets (.adg). No Live dependencies.

The LOM exposes a rack's macro *values* and chain *names* but not macro
display-names/colors/defaults, chain key/velocity/chain-selector zones, or
macro->parameter mappings. Those live only in the gzipped rack XML. These
helpers (server-side only, like the other *_utils modules) read and patch that
XML by tag.

The one structural subtlety: a chain that hosts a sampler contains many nested
<MultiSamplePart> KeyRange/VelocityRange blocks, and drum racks contain many
<DrumBranchPreset> pads. So a chain-level zone is found as the zone block that
is a DIRECT CHILD of a top-level branch element (depth-aware), never "the first
KeyRange in the branch".
"""
import re

from ableton_mcp_max.preset_patch import validate_preset_name, validate_int_range

# rack kind -> tags + User Library destination + whether chains have key/vel zones.
RACK_TYPES = {
    "instrument": {
        "device_tag": "InstrumentGroupDevice",
        "branch_tag": "InstrumentBranchPreset",
        "category": "Instruments", "device_folder": "Instrument Rack",
        "has_key_velocity": True,
    },
    "audio_effect": {
        "device_tag": "AudioEffectGroupDevice",
        "branch_tag": "AudioEffectBranchPreset",
        "category": "Audio Effects", "device_folder": "Audio Effect Rack",
        "has_key_velocity": False,
    },
    "midi_effect": {
        "device_tag": "MidiEffectGroupDevice",
        "branch_tag": "MidiEffectBranchPreset",
        "category": "MIDI Effects", "device_folder": "MIDI Effect Rack",
        "has_key_velocity": False,
    },
    "drum": {
        "device_tag": "DrumGroupDevice",
        "branch_tag": "DrumBranchPreset",
        "category": "Drums", "device_folder": "Drum Rack",
        "has_key_velocity": True,
    },
}


def detect_rack_type(xml):
    """Return 'instrument'|'audio_effect'|'midi_effect'|'drum' for a rack .adg XML.

    Raises ValueError if no known rack device-type tag is present.
    """
    for kind, meta in RACK_TYPES.items():
        if "<%s" % meta["device_tag"] in xml:
            return kind
    raise ValueError(
        "not a recognized rack preset: no Instrument/AudioEffect/MidiEffect/"
        "Drum GroupDevice tag found."
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_rack_preset_utils.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/rack_preset_utils.py tests/test_rack_preset_utils.py
git commit -m "feat(rack-preset): rack type detection + type metadata"
```

---

## Task 2: Depth-aware branch span scanner + direct-child finders

This is the load-bearing primitive. `top_branches` returns the `(start, end)` span of each top-level chain via open/close depth counting on the branch tag (so nested racks don't confuse it). `_direct_child_offset` finds a tag that is a direct child of the branch — used for both zone blocks and the chain's `<UserName>`.

**Files:**
- Modify: `ableton_mcp_max/rack_preset_utils.py`
- Test: `tests/test_rack_preset_utils.py`

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_rack_preset_utils.py
from ableton_mcp_max.rack_preset_utils import (
    top_branches, read_chain_zone, chain_name,
)

# A sampler-style chain: a nested MultiSamplePart injects extra KeyRange/Velocity
# that MUST be ignored; only the branch's direct-child zones count.
SAMPLER_RACK = (
    '<Ableton><GroupDevicePreset><Device><InstrumentGroupDevice>'
    '<NumVisibleMacroControls Value="0" />'
    '</InstrumentGroupDevice></Device><BranchPresets>'
    '<InstrumentBranchPreset Id="0"><Name Value="" /><UserName Value="Lo" />'
    '<BranchSelectorRange><Min Value="0" /><Max Value="0" /><CrossfadeMin Value="0" /><CrossfadeMax Value="0" /></BranchSelectorRange>'
    '<KeyRange><Min Value="0" /><Max Value="59" /><CrossfadeMin Value="0" /><CrossfadeMax Value="59" /></KeyRange>'
    '<VelocityRange><Min Value="1" /><Max Value="127" /><CrossfadeMin Value="1" /><CrossfadeMax Value="127" /></VelocityRange>'
    '<DeviceChain><MultiSamplePart>'
    '<KeyRange><Min Value="20" /><Max Value="40" /><CrossfadeMin Value="20" /><CrossfadeMax Value="40" /></KeyRange>'
    '<VelocityRange><Min Value="1" /><Max Value="64" /><CrossfadeMin Value="1" /><CrossfadeMax Value="64" /></VelocityRange>'
    '</MultiSamplePart></DeviceChain>'
    '</InstrumentBranchPreset>'
    '<InstrumentBranchPreset Id="1"><Name Value="" /><UserName Value="Hi" />'
    '<BranchSelectorRange><Min Value="0" /><Max Value="0" /><CrossfadeMin Value="0" /><CrossfadeMax Value="0" /></BranchSelectorRange>'
    '<KeyRange><Min Value="60" /><Max Value="127" /><CrossfadeMin Value="60" /><CrossfadeMax Value="127" /></KeyRange>'
    '<VelocityRange><Min Value="1" /><Max Value="127" /><CrossfadeMin Value="1" /><CrossfadeMax Value="127" /></VelocityRange>'
    '<DeviceChain></DeviceChain>'
    '</InstrumentBranchPreset></BranchPresets>'
    '</GroupDevicePreset></Ableton>'
)


def test_top_branches_counts_chains():
    spans = top_branches(SAMPLER_RACK, "InstrumentBranchPreset")
    assert len(spans) == 2


def test_read_chain_zone_ignores_nested_multisample():
    # chain 0's direct-child KeyRange is 0..59, NOT the nested 20..40.
    z = read_chain_zone(SAMPLER_RACK, "InstrumentBranchPreset", 0, "KeyRange")
    assert z == {"min": 0, "max": 59, "crossfade_min": 0, "crossfade_max": 59}


def test_read_chain_zone_second_chain():
    z = read_chain_zone(SAMPLER_RACK, "InstrumentBranchPreset", 1, "KeyRange")
    assert z["min"] == 60 and z["max"] == 127


def test_read_chain_zone_absent_returns_none():
    # audio-effect chain has no KeyRange.
    assert read_chain_zone(AUDIO_RACK, "AudioEffectBranchPreset", 0, "KeyRange") is None


def test_chain_name_direct_child():
    assert chain_name(SAMPLER_RACK, "InstrumentBranchPreset", 0) == "Lo"
    assert chain_name(SAMPLER_RACK, "InstrumentBranchPreset", 1) == "Hi"


def test_top_branches_out_of_range():
    with pytest.raises(ValueError):
        read_chain_zone(SAMPLER_RACK, "InstrumentBranchPreset", 9, "KeyRange")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_rack_preset_utils.py -q`
Expected: FAIL — `ImportError: cannot import name 'top_branches'`.

- [ ] **Step 3: Write minimal implementation**

```python
# add to ableton_mcp_max/rack_preset_utils.py

# Container tags that establish nesting depth inside a branch. A zone or attr is
# a "direct child" of the branch when no container is open between the branch's
# own opening tag and the zone/attr.
_CONTAINERS = (
    "InstrumentBranchPreset", "AudioEffectBranchPreset", "MidiEffectBranchPreset",
    "DrumBranchPreset", "DeviceChain", "MultiSamplePart",
)
_ZONE_FIELDS = ("Min", "Max", "CrossfadeMin", "CrossfadeMax")


def top_branches(xml, branch_tag):
    """Return [(start, end), ...] spans of each TOP-LEVEL branch element.

    Depth-counts opens/closes of `branch_tag` so a rack-in-rack's inner branches
    are contained within (not counted as) a top-level span.
    """
    spans = []
    depth = 0
    start = None
    for m in re.finditer(r'<(/?)%s[ >]' % re.escape(branch_tag), xml):
        if m.group(1) == "":
            if depth == 0:
                start = m.start()
            depth += 1
        else:
            depth -= 1
            if depth == 0 and start is not None:
                spans.append((start, m.end()))
                start = None
    return spans


def _branch_span(xml, branch_tag, chain_index):
    spans = top_branches(xml, branch_tag)
    if chain_index < 0 or chain_index >= len(spans):
        raise ValueError(
            "chain index %d out of range (rack has %d chains)."
            % (chain_index, len(spans))
        )
    return spans[chain_index]


def _direct_child_match(branch_xml, branch_tag, pattern):
    """Find the first regex match for `pattern` that is a DIRECT child of the
    branch (depth 0, skipping the branch's own opening tag). Returns the match
    object (offsets relative to branch_xml) or None.
    """
    container_re = re.compile(r'<(/?)(%s)[ >]' % "|".join(map(re.escape, _CONTAINERS)))
    target_re = re.compile(pattern)
    depth = 0
    saw_self = False
    pos = 0
    while pos < len(branch_xml):
        cm = container_re.search(branch_xml, pos)
        tm = target_re.search(branch_xml, pos)
        # The target counts only if it occurs before the next container token
        # AND we are currently at depth 0.
        if tm and (not cm or tm.start() < cm.start()):
            if depth == 0 and saw_self:
                return tm
            pos = tm.end()
            continue
        if not cm:
            return None
        tag = cm.group(2)
        closing = cm.group(1) == "/"
        if not saw_self and tag == branch_tag and not closing:
            saw_self = True  # the branch's own opening tag — don't count it
        elif closing:
            depth -= 1
        else:
            depth += 1
        pos = cm.end()
    return None


def read_chain_zone(xml, branch_tag, chain_index, zone_tag):
    """Return {min,max,crossfade_min,crossfade_max} for the chain-level zone, or
    None if that chain has no such zone (e.g. KeyRange on an audio-effect chain).
    """
    s, e = _branch_span(xml, branch_tag, chain_index)
    branch = xml[s:e]
    m = _direct_child_match(branch, branch_tag, r'<%s>.*?</%s>' % (zone_tag, zone_tag))
    if not m:
        return None
    block = m.group(0)
    vals = dict(re.findall(r'<(Min|Max|CrossfadeMin|CrossfadeMax) Value="([^"]*)"', block))
    return {
        "min": int(vals["Min"]), "max": int(vals["Max"]),
        "crossfade_min": int(vals["CrossfadeMin"]),
        "crossfade_max": int(vals["CrossfadeMax"]),
    }


def chain_name(xml, branch_tag, chain_index):
    """Return the chain's display name (direct-child <UserName>), or ''."""
    s, e = _branch_span(xml, branch_tag, chain_index)
    branch = xml[s:e]
    m = _direct_child_match(branch, branch_tag, r'<UserName Value="([^"]*)" />')
    return m.group(1) if m else ""
```

Note: `re.finditer`/`search` over the zone pattern uses non-greedy `.*?` so it stops at the first `</zone>`; a zone block has no nested same-name tags, so this is safe once scoped to a direct-child match.

- [ ] **Step 4: Run test to verify it passes**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_rack_preset_utils.py -q`
Expected: PASS (now 10 tests).

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/rack_preset_utils.py tests/test_rack_preset_utils.py
git commit -m "feat(rack-preset): depth-aware branch scanner + direct-child zone reader"
```

---

## Task 3: Rack summarizer (`summarize_rack_adg`)

Builds the `inspect_rack_preset` payload: rack type, visible-macro count, all 16 macros, and each chain's zones.

**Files:**
- Modify: `ableton_mcp_max/rack_preset_utils.py`
- Test: `tests/test_rack_preset_utils.py`

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_rack_preset_utils.py
from ableton_mcp_max.rack_preset_utils import summarize_rack_adg


def test_summarize_instrument_shape():
    s = summarize_rack_adg(INSTR_RACK)
    assert s["rack_type"] == "instrument"
    assert s["num_visible_macros"] == 2
    assert len(s["macros"]) == 16
    assert s["macros"][0] == {"macro": 1, "name": "Cutoff", "color": 27, "default": 56.0}
    assert s["macros"][1]["name"] == "Reso"
    # macros without display-name tags come back with name "" (defaults present or 0)
    assert s["macros"][5]["macro"] == 6
    assert len(s["chains"]) == 1
    c = s["chains"][0]
    assert c["chain"] == 0
    assert c["name"] == "Chain A"
    assert c["key_zone"]["max"] == 127
    assert c["velocity_zone"]["min"] == 1
    assert c["chain_selector_zone"] == {"min": 0, "max": 0, "crossfade_min": 0, "crossfade_max": 0}


def test_summarize_audio_effect_null_keyvel():
    s = summarize_rack_adg(AUDIO_RACK)
    assert s["rack_type"] == "audio_effect"
    c = s["chains"][0]
    assert c["key_zone"] is None
    assert c["velocity_zone"] is None
    assert c["chain_selector_zone"]["min"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_rack_preset_utils.py -q`
Expected: FAIL — `ImportError: cannot import name 'summarize_rack_adg'`.

- [ ] **Step 3: Write minimal implementation**

```python
# add to ableton_mcp_max/rack_preset_utils.py
from ableton_mcp_max.preset_patch import get_attr as _get_attr


def _macro_field(xml, prefix, index):
    """Value of <prefix.N Value="..."/> or None."""
    m = re.search(r'<%s\.%d Value="([^"]*)" />' % (re.escape(prefix), index), xml)
    return m.group(1) if m else None


def summarize_rack_adg(xml):
    """Structured summary of a rack .adg: type, visible-macro count, 16 macros,
    and per-chain zones. key_zone/velocity_zone are None on audio/midi-fx racks.
    """
    kind = detect_rack_type(xml)
    meta = RACK_TYPES[kind]
    btag = meta["branch_tag"]
    nvis = _get_attr(xml, "NumVisibleMacroControls")

    macros = []
    for i in range(16):
        name = _macro_field(xml, "MacroDisplayNames", i)
        color = _macro_field(xml, "MacroColor", i)
        default = _macro_field(xml, "MacroDefaults", i)
        macros.append({
            "macro": i + 1,
            "name": name if name is not None else "",
            "color": int(color) if color is not None and color.lstrip("-").isdigit() else None,
            "default": float(default) if default is not None else None,
        })

    chains = []
    for ci in range(len(top_branches(xml, btag))):
        entry = {
            "chain": ci,
            "name": chain_name(xml, btag, ci),
            "chain_selector_zone": read_chain_zone(xml, btag, ci, "BranchSelectorRange"),
        }
        if meta["has_key_velocity"]:
            entry["key_zone"] = read_chain_zone(xml, btag, ci, "KeyRange")
            entry["velocity_zone"] = read_chain_zone(xml, btag, ci, "VelocityRange")
        else:
            entry["key_zone"] = None
            entry["velocity_zone"] = None
        chains.append(entry)

    return {
        "rack_type": kind,
        "num_visible_macros": int(nvis) if nvis is not None and nvis.isdigit() else None,
        "macros": macros,
        "chains": chains,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_rack_preset_utils.py -q`
Expected: PASS (12 tests).

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/rack_preset_utils.py tests/test_rack_preset_utils.py
git commit -m "feat(rack-preset): summarize_rack_adg readback"
```

---

## Task 4: Macro patchers (names / colors / defaults)

**Files:**
- Modify: `ableton_mcp_max/rack_preset_utils.py`
- Test: `tests/test_rack_preset_utils.py`

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_rack_preset_utils.py
from ableton_mcp_max.rack_preset_utils import patch_macros


def test_patch_macro_names():
    out = patch_macros(INSTR_RACK, names={1: "Brightness", 2: "Resonance"})
    s = summarize_rack_adg(out)
    assert s["macros"][0]["name"] == "Brightness"
    assert s["macros"][1]["name"] == "Resonance"


def test_patch_macro_names_xml_escaped():
    out = patch_macros(INSTR_RACK, names={1: "Low & High"})
    assert '<MacroDisplayNames.0 Value="Low &amp; High" />' in out
    assert summarize_rack_adg(out)["macros"][0]["name"] == "Low & High"


def test_patch_macro_colors_and_defaults():
    out = patch_macros(INSTR_RACK, colors={1: 5}, defaults={2: 100.0})
    s = summarize_rack_adg(out)
    assert s["macros"][0]["color"] == 5
    assert s["macros"][1]["default"] == 100.0


def test_patch_macro_only_listed_changed():
    out = patch_macros(INSTR_RACK, names={2: "Reso2"})
    s = summarize_rack_adg(out)
    assert s["macros"][0]["name"] == "Cutoff"  # macro 1 untouched
    assert s["macros"][1]["name"] == "Reso2"


def test_patch_macro_rejects_quote_in_name():
    with pytest.raises(ValueError):
        patch_macros(INSTR_RACK, names={1: 'bad" />'})


@pytest.mark.parametrize("bad", [0, 17, -1])
def test_patch_macro_rejects_out_of_range_number(bad):
    with pytest.raises(ValueError):
        patch_macros(INSTR_RACK, names={bad: "x"})


def test_patch_macro_is_pure():
    src = INSTR_RACK
    patch_macros(src, names={1: "Z"})
    assert src == INSTR_RACK
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_rack_preset_utils.py -q`
Expected: FAIL — `ImportError: cannot import name 'patch_macros'`.

- [ ] **Step 3: Write minimal implementation**

```python
# add to ableton_mcp_max/rack_preset_utils.py

def _xml_escape(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _set_macro_field(xml, prefix, index, value):
    """Replace Value on <prefix.N Value="..."/>; raise if that macro slot absent."""
    pattern = r'(<%s\.%d Value=")[^"]*("\s*/>)' % (re.escape(prefix), index)
    new, n = re.subn(pattern, lambda m: m.group(1) + str(value) + m.group(2), xml)
    if n == 0:
        raise ValueError("macro slot <%s.%d> not found in preset." % (prefix, index))
    return new


def _check_macro_number(num):
    if isinstance(num, bool) or not isinstance(num, int):
        raise ValueError("macro number must be an int 1..16, got %r." % (num,))
    if not (1 <= num <= 16):
        raise ValueError("macro number %d out of range 1..16." % num)
    return num - 1  # -> 0-based XML index


def patch_macros(xml, names=None, colors=None, defaults=None):
    """Patch macro display names / colors / defaults in a rack .adg XML.

    names/colors/defaults are dicts keyed by 1-based macro number. Only listed
    macros change. Names are XML-escaped; a literal double-quote is rejected.
    Colors are ints >= 0; defaults are floats 0..127. Pure: returns new XML.
    """
    out = xml
    for num, name in (names or {}).items():
        idx = _check_macro_number(num)
        text = str(name)
        if '"' in text:
            raise ValueError("macro %d name must not contain a double-quote." % num)
        out = _set_macro_field(out, "MacroDisplayNames", idx, _xml_escape(text))
    for num, color in (colors or {}).items():
        idx = _check_macro_number(num)
        c = validate_int_range(color, 0, 70, "macro %d color" % num)
        out = _set_macro_field(out, "MacroColor", idx, c)
    for num, dflt in (defaults or {}).items():
        idx = _check_macro_number(num)
        try:
            f = float(dflt)
        except (TypeError, ValueError):
            raise ValueError("macro %d default must be a number 0..127." % num)
        if not (0.0 <= f <= 127.0):
            raise ValueError("macro %d default %s out of range 0..127." % (num, f))
        out = _set_macro_field(out, "MacroDefaults", idx, f)
    return out
```

Note: the Live color palette is 0..69 (70 swatches); `validate_int_range(..., 0, 70, ...)` allows 0..70 inclusive as a safe upper bound.

- [ ] **Step 4: Run test to verify it passes**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_rack_preset_utils.py -q`
Expected: PASS (now ~21 tests).

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/rack_preset_utils.py tests/test_rack_preset_utils.py
git commit -m "feat(rack-preset): macro name/color/default patcher"
```

---

## Task 5: Zone patcher (`patch_chain_zone`) + validation

Patches a chain-level zone in place using the depth-aware direct-child locator from Task 2, with full range + crossfade-ordering validation, and rejection of key/velocity on audio/midi-fx racks.

**Files:**
- Modify: `ableton_mcp_max/rack_preset_utils.py`
- Test: `tests/test_rack_preset_utils.py`

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_rack_preset_utils.py
from ableton_mcp_max.rack_preset_utils import patch_chain_zone, normalize_zone


def test_normalize_zone_shorthand():
    assert normalize_zone([0, 60], "key") == {
        "min": 0, "max": 60, "crossfade_min": 0, "crossfade_max": 60}


def test_normalize_zone_full_object():
    z = normalize_zone({"min": 0, "max": 60, "crossfade_min": 10, "crossfade_max": 50}, "key")
    assert z["crossfade_min"] == 10 and z["crossfade_max"] == 50


def test_normalize_zone_bad_ordering():
    with pytest.raises(ValueError):
        normalize_zone({"min": 0, "max": 60, "crossfade_min": 50, "crossfade_max": 10}, "key")


def test_normalize_zone_crossfade_outside_minmax():
    with pytest.raises(ValueError):
        normalize_zone({"min": 10, "max": 60, "crossfade_min": 5, "crossfade_max": 60}, "key")


def test_patch_chain_zone_key_roundtrip():
    out = patch_chain_zone(SAMPLER_RACK, "instrument", 0, "key", [0, 48])
    z = read_chain_zone(out, "InstrumentBranchPreset", 0, "KeyRange")
    assert z == {"min": 0, "max": 48, "crossfade_min": 0, "crossfade_max": 48}
    # nested multisample KeyRange untouched (still 20..40)
    assert "<KeyRange><Min Value=\"20\" />" in out


def test_patch_chain_zone_does_not_touch_other_chain():
    out = patch_chain_zone(SAMPLER_RACK, "instrument", 0, "key", [0, 48])
    z1 = read_chain_zone(out, "InstrumentBranchPreset", 1, "KeyRange")
    assert z1["min"] == 60  # chain 1 unchanged


def test_patch_chain_zone_rejects_key_on_audio_effect():
    with pytest.raises(ValueError):
        patch_chain_zone(AUDIO_RACK, "audio_effect", 0, "key", [0, 60])


def test_patch_chain_zone_selector_on_audio_effect_ok():
    out = patch_chain_zone(AUDIO_RACK, "audio_effect", 0, "chain_selector", [0, 63])
    z = read_chain_zone(out, "AudioEffectBranchPreset", 0, "BranchSelectorRange")
    assert z["max"] == 63
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_rack_preset_utils.py -q`
Expected: FAIL — `ImportError: cannot import name 'patch_chain_zone'`.

- [ ] **Step 3: Write minimal implementation**

```python
# add to ableton_mcp_max/rack_preset_utils.py

# tool zone key -> XML zone tag.
_ZONE_TAGS = {
    "key": "KeyRange",
    "velocity": "VelocityRange",
    "chain_selector": "BranchSelectorRange",
}


def normalize_zone(value, label):
    """Coerce a zone arg into {min,max,crossfade_min,crossfade_max} and validate.

    Accepts shorthand [min, max] (crossfades = min/max, i.e. no crossfade) or a
    full object. Enforces 0..127 ints and min <= crossfade_min <= crossfade_max
    <= max.
    """
    if isinstance(value, (list, tuple)):
        if len(value) != 2:
            raise ValueError("%s shorthand must be [min, max]." % label)
        lo = validate_int_range(value[0], 0, 127, "%s min" % label)
        hi = validate_int_range(value[1], 0, 127, "%s max" % label)
        z = {"min": lo, "max": hi, "crossfade_min": lo, "crossfade_max": hi}
    elif isinstance(value, dict):
        lo = validate_int_range(value.get("min"), 0, 127, "%s min" % label)
        hi = validate_int_range(value.get("max"), 0, 127, "%s max" % label)
        cmin = validate_int_range(value.get("crossfade_min", lo), 0, 127, "%s crossfade_min" % label)
        cmax = validate_int_range(value.get("crossfade_max", hi), 0, 127, "%s crossfade_max" % label)
        z = {"min": lo, "max": hi, "crossfade_min": cmin, "crossfade_max": cmax}
    else:
        raise ValueError("%s must be [min, max] or an object." % label)
    if not (z["min"] <= z["crossfade_min"] <= z["crossfade_max"] <= z["max"]):
        raise ValueError(
            "%s requires min <= crossfade_min <= crossfade_max <= max "
            "(got %s)." % (label, z)
        )
    return z


def patch_chain_zone(xml, rack_type, chain_index, zone_key, value):
    """Patch chain `chain_index`'s `zone_key` ('key'|'velocity'|'chain_selector').

    `rack_type` is from detect_rack_type. Raises if key/velocity is requested on
    a rack type whose chains lack them (audio_effect/midi_effect). Pure.
    """
    if zone_key not in _ZONE_TAGS:
        raise ValueError("unknown zone %r (use key|velocity|chain_selector)." % zone_key)
    meta = RACK_TYPES[rack_type]
    if zone_key in ("key", "velocity") and not meta["has_key_velocity"]:
        raise ValueError(
            "%s racks have no %s zone (only chain_selector)." % (rack_type, zone_key)
        )
    z = normalize_zone(value, zone_key)
    zone_tag = _ZONE_TAGS[zone_key]
    btag = meta["branch_tag"]
    s, e = _branch_span(xml, btag, chain_index)
    branch = xml[s:e]
    m = _direct_child_match(branch, btag, r'<%s>.*?</%s>' % (zone_tag, zone_tag))
    if not m:
        raise ValueError(
            "chain %d has no <%s> to patch." % (chain_index, zone_tag)
        )
    block = m.group(0)
    for field, key in (("Min", "min"), ("Max", "max"),
                       ("CrossfadeMin", "crossfade_min"), ("CrossfadeMax", "crossfade_max")):
        block = re.sub(
            r'(<%s Value=")[^"]*("\s*/>)' % field,
            lambda mm, v=z[key]: mm.group(1) + str(v) + mm.group(2),
            block, count=1,
        )
    new_branch = branch[:m.start()] + block + branch[m.end():]
    return xml[:s] + new_branch + xml[e:]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_rack_preset_utils.py -q`
Expected: PASS (now ~30 tests).

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/rack_preset_utils.py tests/test_rack_preset_utils.py
git commit -m "feat(rack-preset): chain zone patcher + zone validation"
```

---

## Task 6: Real-factory-file integration test (offline, skip if Live absent)

Guards against the synthetic fixtures drifting from real Ableton serialization.

**Files:**
- Test: `tests/test_rack_preset_utils.py`

- [ ] **Step 1: Write the test**

```python
# add to tests/test_rack_preset_utils.py
import glob

def _factory_rack(subdir):
    hits = glob.glob(
        "/Applications/Ableton*Live*.app/Contents/App-Resources/Core Library/"
        "Racks/%s/*/*.adg" % subdir)
    return hits[0] if hits else None


@pytest.mark.skipif(_factory_rack("Instrument Racks") is None,
                    reason="Ableton Live factory racks not installed")
def test_real_instrument_rack_summarizes():
    with gzip.open(_factory_rack("Instrument Racks"), "rt") as f:
        xml = f.read()
    s = summarize_rack_adg(xml)
    assert s["rack_type"] == "instrument"
    assert len(s["macros"]) == 16
    assert len(s["chains"]) >= 1
    # every chain has a clean key zone with sane bounds (not a nested 20..40 sample zone)
    for c in s["chains"]:
        assert c["key_zone"] is not None
        assert 0 <= c["key_zone"]["min"] <= c["key_zone"]["max"] <= 127


@pytest.mark.skipif(_factory_rack("Audio Effect Racks") is None,
                    reason="Ableton Live factory racks not installed")
def test_real_audio_effect_rack_no_keyvel():
    with gzip.open(_factory_rack("Audio Effect Racks"), "rt") as f:
        xml = f.read()
    s = summarize_rack_adg(xml)
    assert s["rack_type"] == "audio_effect"
    assert all(c["key_zone"] is None for c in s["chains"])
```

- [ ] **Step 2: Run the test**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_rack_preset_utils.py -q`
Expected: PASS (the two real-file tests run on this machine since Live 11 is installed).

- [ ] **Step 3: Commit**

```bash
git add tests/test_rack_preset_utils.py
git commit -m "test(rack-preset): real factory-file summarize integration tests"
```

---

## Task 7: Server helpers — `_read_rack_template` + `_read_user_preset`

Adds the read side of the pipeline to `server.py`, alongside the existing `_read_default_adv` / `_write_user_preset` / `_load_user_preset`.

**Files:**
- Modify: `ableton_mcp_max/server.py` (insert after `_load_user_preset`, around line 2571)

- [ ] **Step 1: Add the helpers**

```python
# in ableton_mcp_max/server.py, after _load_user_preset(...)

def _read_user_preset(category, device_folder, name, ext="adg"):
    """Read + gunzip an existing User Library preset to XML (the pipeline's read
    side). Raises FileNotFoundError if it's not there yet.
    """
    lib = _user_library_dir()
    path = os.path.join(lib, "Presets", category, device_folder, "%s.%s" % (name, ext))
    if not os.path.isfile(path):
        raise FileNotFoundError(
            "User Library preset not found: %s. Run clone_rack first." % path)
    with gzip.open(path, "rt") as f:
        return f.read(), path


def _read_rack_template(template):
    """Read + gunzip a rack .adg template to XML.

    Resolves `template` two ways:
      (a) an absolute path or glob to a factory rack (e.g. under Core Library/
          Racks/...) — NOT Defaults/, so _read_default_adv does not apply;
      (b) a bare name of a rack already in the User Library (searched across all
          rack device-folders).
    Returns (xml, resolved_path). Raises FileNotFoundError if unresolved.
    """
    expanded = os.path.expanduser(str(template))
    # (a) direct path / glob
    if os.path.sep in expanded or "*" in expanded:
        hits = glob.glob(expanded)
        if hits:
            with gzip.open(hits[0], "rt") as f:
                return f.read(), hits[0]
    # (b) factory rack by name under any Racks/<kind>/<sub>/<name>.adg
    name = os.path.splitext(os.path.basename(expanded))[0]
    for root in (
        "%s/Racks/**/%s.adg" % (_APP_CORE, name),
    ):
        hits = glob.glob(root, recursive=True)
        if hits:
            with gzip.open(hits[0], "rt") as f:
                return f.read(), hits[0]
    # (c) user-library rack by name across rack device-folders
    lib = _user_library_dir()
    hits = glob.glob(os.path.join(lib, "Presets", "*", "*", "%s.adg" % name))
    if hits:
        with gzip.open(hits[0], "rt") as f:
            return f.read(), hits[0]
    raise FileNotFoundError(
        "Rack template %r not found as a path, a factory rack name, or a User "
        "Library preset name." % (template,))
```

- [ ] **Step 2: Syntax-check the server imports**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python -c "import ableton_mcp_max.server"`
Expected: no output (clean import).

- [ ] **Step 3: Commit**

```bash
git add ableton_mcp_max/server.py
git commit -m "feat(rack-preset): server read helpers (_read_rack_template, _read_user_preset)"
```

---

## Task 8: Server tools — `inspect_rack_preset` + `clone_rack`

**Files:**
- Modify: `ableton_mcp_max/server.py` (add after `create_simpler_instrument`, around line 2775)

- [ ] **Step 1: Add the import + both tools**

Add to the rack_preset_utils import area near the other preset-utils imports at the top of `server.py` (match the existing `from ableton_mcp_max.wavetable_preset_utils import ...` style):

```python
from ableton_mcp_max.rack_preset_utils import (
    summarize_rack_adg, detect_rack_type, RACK_TYPES,
    patch_macros, patch_chain_zone,
)
```

Then add the tools:

```python
@mcp.tool()
def inspect_rack_preset(ctx: Context, template: str) -> str:
    """
    Inspect a rack preset (.adg) and report its macros and chain zones.

    Reads a rack by path (a factory rack under Core Library/Racks/...) or by
    name (a factory rack name, or a preset already in your User Library) and
    returns its structure — the inputs you need for rename_rack_macros and
    set_rack_zones. Reads only; nothing is written or loaded.

    Macros are reported 1-based (matching set_rack_macro); chains 0-based
    (matching get_rack_chains). key_zone/velocity_zone are null on audio-effect
    and midi-effect racks (those chains have only a chain_selector_zone).

    Parameters:
    - template: a .adg path/glob, OR a factory/User-Library rack name.

    Returns JSON {rack_type, num_visible_macros, macros:[...16...], chains:[...]}.
    """
    try:
        xml, path = _read_rack_template(template)
        summary = summarize_rack_adg(xml)
        summary["template_path"] = path
        return json.dumps(summary, separators=(",", ":"))
    except (ValueError, FileNotFoundError) as e:
        return f"Error: {str(e)}"
    except Exception as e:
        logger.error(f"Error inspecting rack preset: {str(e)}")
        return f"Error inspecting rack preset: {str(e)}"


@mcp.tool()
def clone_rack(ctx: Context, template: str, name: str) -> str:
    """
    Copy a rack preset into your User Library as a new working preset.

    Racks have no blank/default template, so the rack-preset pipeline starts by
    cloning an existing rack (factory or User Library). The clone becomes the
    working preset that rename_rack_macros / set_rack_zones edit in place; load
    the finished result later with load_preset using the returned browser_path.

    The User Library category and device-folder are derived from the rack type
    (instrument -> Instruments/Instrument Rack, audio_effect -> Audio Effects/
    Audio Effect Rack, midi_effect -> MIDI Effects/MIDI Effect Rack, drum ->
    Drums/Drum Rack).

    Parameters:
    - template: source rack — a .adg path/glob, or a factory/User-Library name.
    - name: new preset name (becomes '<name>.adg'; no slashes or leading dot).

    Returns JSON {written, path, browser_path, summary:{...inspect shape...}}.
    """
    try:
        safe = validate_preset_name(name)
        xml, _src = _read_rack_template(template)
        kind = detect_rack_type(xml)
        meta = RACK_TYPES[kind]
        dest, browser_path = _write_user_preset(
            xml, safe, meta["device_folder"], category=meta["category"], ext="adg")
        return json.dumps({
            "written": True,
            "path": dest,
            "browser_path": browser_path,
            "summary": summarize_rack_adg(xml),
        }, separators=(",", ":"))
    except (ValueError, FileNotFoundError) as e:
        return f"Error: {str(e)}"
    except Exception as e:
        logger.error(f"Error cloning rack: {str(e)}")
        return f"Error cloning rack: {str(e)}"
```

- [ ] **Step 2: Syntax-check the server imports**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python -c "import ableton_mcp_max.server"`
Expected: clean import.

- [ ] **Step 3: Commit**

```bash
git add ableton_mcp_max/server.py
git commit -m "feat(rack-preset): inspect_rack_preset + clone_rack tools"
```

---

## Task 9: Server tools — `rename_rack_macros` + `set_rack_zones`

These edit the named working preset in place: read it from the User Library, patch, rewrite (overwrite the same file so no re-index is needed), and return the updated summary.

**Files:**
- Modify: `ableton_mcp_max/server.py` (add after `clone_rack`)

- [ ] **Step 1: Add both tools**

```python
def _user_rack_category(name):
    """Find which rack device-folder a User Library rack <name>.adg lives in.

    Returns (category, device_folder, xml). Raises FileNotFoundError if absent.
    """
    for kind, meta in RACK_TYPES.items():
        try:
            xml, _path = _read_user_preset(
                meta["category"], meta["device_folder"], name, ext="adg")
            return meta["category"], meta["device_folder"], xml
        except FileNotFoundError:
            continue
    raise FileNotFoundError(
        "No User Library rack named %r in any rack folder. Run clone_rack first."
        % name)


@mcp.tool()
def rename_rack_macros(ctx: Context, name: str, macro_names: dict = None,
                       macro_colors: dict = None,
                       macro_defaults: dict = None) -> str:
    """
    Rename / recolor / set defaults for a User Library rack's macros, in place.

    Operates on a rack preset previously created by clone_rack (the working
    preset). Only the macros you list are changed; the rest keep their values.
    Macro display names are NOT settable via the LOM — this preset edit is the
    only MCP route. Macros are addressed 1-based (matching set_rack_macro).

    Parameters:
    - name: the User Library rack preset name (from clone_rack).
    - macro_names: object {macro_number: "Display Name"} (no double-quote).
    - macro_colors: object {macro_number: color_int} (0..70).
    - macro_defaults: object {macro_number: default_float} (0..127).

    The file is overwritten in place, so it reloads fresh with load_preset
    without re-indexing. Returns JSON {written, path, macros:[...16...]}.
    """
    try:
        safe = validate_preset_name(name)
        category, device_folder, xml = _user_rack_category(safe)
        names = {int(k): v for k, v in (macro_names or {}).items()}
        colors = {int(k): v for k, v in (macro_colors or {}).items()}
        defaults = {int(k): v for k, v in (macro_defaults or {}).items()}
        out = patch_macros(xml, names=names, colors=colors, defaults=defaults)
        dest, _bp = _write_user_preset(
            out, safe, device_folder, category=category, ext="adg")
        return json.dumps({
            "written": True, "path": dest,
            "macros": summarize_rack_adg(out)["macros"],
        }, separators=(",", ":"))
    except (ValueError, FileNotFoundError) as e:
        return f"Error: {str(e)}"
    except Exception as e:
        logger.error(f"Error renaming rack macros: {str(e)}")
        return f"Error renaming rack macros: {str(e)}"


@mcp.tool()
def set_rack_zones(ctx: Context, name: str, zones: list) -> str:
    """
    Set chain key / velocity / chain-selector zones on a User Library rack.

    Operates in place on a rack created by clone_rack. Chain zones are not
    settable via the LOM — this preset edit is the only MCP route. Chains are
    addressed 0-based (matching get_rack_chains). key and velocity are rejected
    for audio-effect / midi-effect racks (those chains only have a
    chain_selector zone).

    Each entry in `zones` is an object:
      {"chain": 0,
       "key": [0, 60]                 // shorthand [min,max], OR a full object:
       "velocity": {"min":0,"max":127,"crossfade_min":0,"crossfade_max":127},
       "chain_selector": [0, 63]}
    Provide only the zones you want to change. Validation enforces 0..127 and
    min <= crossfade_min <= crossfade_max <= max.

    Returns JSON {written, path, chains:[...]}.
    """
    try:
        safe = validate_preset_name(name)
        category, device_folder, xml = _user_rack_category(safe)
        kind = detect_rack_type(xml)
        if not isinstance(zones, list):
            return "Error: zones must be a list of {chain, key?, velocity?, chain_selector?} objects."
        out = xml
        for entry in zones:
            if not isinstance(entry, dict) or "chain" not in entry:
                return "Error: each zones entry needs a 'chain' index."
            ci = int(entry["chain"])
            for zone_key in ("key", "velocity", "chain_selector"):
                if zone_key in entry and entry[zone_key] is not None:
                    out = patch_chain_zone(out, kind, ci, zone_key, entry[zone_key])
        dest, _bp = _write_user_preset(
            out, safe, device_folder, category=category, ext="adg")
        return json.dumps({
            "written": True, "path": dest,
            "chains": summarize_rack_adg(out)["chains"],
        }, separators=(",", ":"))
    except (ValueError, FileNotFoundError) as e:
        return f"Error: {str(e)}"
    except Exception as e:
        logger.error(f"Error setting rack zones: {str(e)}")
        return f"Error setting rack zones: {str(e)}"
```

- [ ] **Step 2: Syntax-check the server imports**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python -c "import ableton_mcp_max.server"`
Expected: clean import.

- [ ] **Step 3: Run the full offline gate**

Run:
```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python -c "import ableton_mcp_max.server"
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python -m py_compile remote_script/AbletonMCP/__init__.py
```
Expected: all pass (the new rack tests plus the prior offline suite; remote script unchanged but compiles).

- [ ] **Step 4: Commit**

```bash
git add ableton_mcp_max/server.py
git commit -m "feat(rack-preset): rename_rack_macros + set_rack_zones tools"
```

---

## Task 10: Live verification (manual, requires restart)

No Remote Script change — **do not** reinstall the script or bounce Live. Only restart Claude Code so the server reloads with the 4 new tools (they arrive as deferred tools).

- [ ] **Step 1: Restart Claude Code, then load the new tools**

After the user restarts Claude Code:
Run (tool, not bash): `ToolSearch` with query `select:mcp__AbletonDev__inspect_rack_preset,mcp__AbletonDev__clone_rack,mcp__AbletonDev__rename_rack_macros,mcp__AbletonDev__set_rack_zones`
Expected: the 4 tool schemas load.

- [ ] **Step 2: Inspect a factory rack**

Call `inspect_rack_preset` with `template="808 Drifter"` (or any installed instrument rack name).
Expected: JSON with `rack_type="instrument"`, 16 macros, ≥1 chain, non-null key/velocity zones.

- [ ] **Step 3: Clone it to a working preset**

Call `clone_rack` with `template="808 Drifter"`, `name="MCP RackTest"`.
Expected: `{written:true, path:.../Audio? no -> Instruments/Instrument Rack/MCP RackTest.adg, browser_path:"user_library/Presets/Instruments/Instrument Rack", summary:{...}}`.

- [ ] **Step 4: Rename macros + set a zone**

Call `rename_rack_macros` with `name="MCP RackTest"`, `macro_names={"1":"MCP One","2":"MCP Two"}`, `macro_colors={"1":5}`.
Call `set_rack_zones` with `name="MCP RackTest"`, `zones=[{"chain":0,"key":[24,96]}]`.
Expected: both return `written:true`; the returned `macros`/`chains` reflect the edits.

- [ ] **Step 5: Load and verify in Live**

Call `load_preset` with `track_index=<an empty regular track>`, `path="user_library/Presets/Instruments/Instrument Rack"`, `name="MCP RackTest"`.
- If first-time load reports "not indexed yet", ask the user to refresh the User Library (right-click → Refresh) or note it, then retry.
Then verify: `get_rack_macros` shows macro 1 named "MCP One"; `get_rack_chains` shows chain 0; visually confirm the macro names + key zone in Live.

- [ ] **Step 6: Clean up**

`delete_track` the scratch track. Delete the test preset:
```bash
rm -f "$HOME/Library/Mobile Documents/com~apple~CloudDocs/Production/User Library/Presets/Instruments/Instrument Rack/MCP RackTest.adg"
```
(Adjust the path to the actual `path` returned by clone_rack.)

- [ ] **Step 7: Record results in PROGRESS.md**

Add a preset-patch section entry: the 4 Phase A rack tools, live-verified date 2026-05-29 (or actual), with the rack name tested. Note Phase B remains gated.

```bash
git add PROGRESS.md
git commit -m "docs: record rack-preset Phase A live verification"
```

---

## Task 11: Phase B gate — macro→mapping save-diff experiment (user-performed)

Phase B (`add_rack_macro_mappings`) is **not implemented in this plan**. The static finding (all `AutomationTarget Id` zeroed in `.adg`, no mapping registry) means the encoding must be observed, not guessed. This task runs the experiment and records the go/no-go decision; the actual implementation is planned separately *after* the gate resolves.

- [ ] **Step 1: Ask the user to perform the save-diff in Live**

1. Load a rack with one device (e.g. Utility) on chain 0.
2. Map **Macro 1 → Utility ▸ Gain** by hand (macro-map mode).
3. Save to User Library as `MCP_MapTest_mapped`.
4. Remove the mapping; save as `MCP_MapTest_unmapped`.

- [ ] **Step 2: Diff the two presets**

```bash
LIB="$HOME/Library/Mobile Documents/com~apple~CloudDocs/Production/User Library/Presets/Audio Effects/Audio Effect Rack"
gzip -dc "$LIB/MCP_MapTest_mapped.adg"   > /tmp/mapped.xml
gzip -dc "$LIB/MCP_MapTest_unmapped.adg" > /tmp/unmapped.xml
# pretty-print each onto its own lines so diff is readable, then diff
/opt/homebrew/bin/python3 -c "import sys,re; x=open(sys.argv[1]).read(); open(sys.argv[1]+'.nl','w').write(re.sub(r'><','>\n<',x))" /tmp/mapped.xml
/opt/homebrew/bin/python3 -c "import sys,re; x=open(sys.argv[1]).read(); open(sys.argv[1]+'.nl','w').write(re.sub(r'><','>\n<',x))" /tmp/unmapped.xml
diff /tmp/unmapped.xml.nl /tmp/mapped.xml.nl
```
Expected: the diff isolates exactly what a mapping adds — likely a non-zero target id on a `MacroControls.N` / `ControllerTargets` entry plus a paired target block under the device parameter with a min/max range.

- [ ] **Step 3: Record the gate decision**

Append findings to the spec (`docs/superpowers/specs/2026-05-29-rack-preset-macro-mapping-design.md`) Section 3 and pick a branch:
- **Cleanly patchable** → write a follow-up plan for `add_rack_macro_mappings`.
- **Fragile** → write a follow-up plan for a narrowed single-device/single-chain version with caveats.
- **Infeasible** → document the limitation; Phase A is the final deliverable.

```bash
git add docs/superpowers/specs/2026-05-29-rack-preset-macro-mapping-design.md
git commit -m "docs: rack macro-mapping save-diff findings + Phase B gate decision"
```

---

## Self-Review notes (completed during authoring)

- **Spec coverage:** Section 1 tool set → Tasks 8–9 (4 Phase A tools) + load via existing `load_preset`. Section 2 data shapes → `summarize_rack_adg` (Task 3), `patch_macros` (Task 4), `patch_chain_zone`/`normalize_zone` (Task 5), addressing (macros 1-based, chains 0-based) enforced in Tasks 4–5 and tool wrappers. Section 3 Phase B → Task 11 (gate only, no implementation, as specced).
- **Placeholder scan:** none — every code step has complete code; commands have expected output.
- **Type consistency:** `RACK_TYPES` shape (`branch_tag`/`category`/`device_folder`/`has_key_velocity`) used identically in Tasks 1, 3, 5, 8, 9. `read_chain_zone`/`patch_chain_zone` zone keys (`key`/`velocity`/`chain_selector`) consistent across utils + tools. `_read_user_preset(category, device_folder, name, ext)` signature matches its callers in Task 9. `_write_user_preset(..., ext="adg")` matches the existing server helper signature (Task 7/8/9). Macro dicts keyed by 1-based int throughout.
- **Known constraint (documented, not a gap):** zone tools target *top-level* rack chains; a rack-in-rack's inner chains are out of scope — `top_branches` depth-counting keeps inner branches contained rather than miscounting them. Drum racks are supported by the type map but are the least-exercised; live verification (Task 10) uses an instrument rack.
