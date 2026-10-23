# tests/test_rack_preset_utils.py
import gzip
import os
import sys

import pytest

from ableton_mcp_max import platform_utils as plat

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


# A drum rack: top-level device is DrumGroupDevice, but its pad chains load
# instruments so the XML ALSO embeds InstrumentGroupDevice (after, in document
# order). Position-based detection must still return "drum".
DRUM_RACK = (
    '<Ableton><GroupDevicePreset><Device><DrumGroupDevice>'
    '<NumVisibleMacroControls Value="0" />'
    '</DrumGroupDevice></Device><BranchPresets>'
    '<DrumBranchPreset Id="0"><Name Value="" /><UserName Value="Kick" />'
    '<BranchSelectorRange><Min Value="0" /><Max Value="0" /><CrossfadeMin Value="0" /><CrossfadeMax Value="0" /></BranchSelectorRange>'
    '<DeviceChain><InstrumentGroupDevice /></DeviceChain>'
    '</DrumBranchPreset></BranchPresets>'
    '</GroupDevicePreset></Ableton>'
)
MIDI_RACK = (
    '<Ableton><GroupDevicePreset><Device><MidiEffectGroupDevice>'
    '<NumVisibleMacroControls Value="0" />'
    '</MidiEffectGroupDevice></Device><BranchPresets>'
    '<MidiEffectBranchPreset Id="0"><Name Value="" /><UserName Value="Arp" />'
    '<BranchSelectorRange><Min Value="0" /><Max Value="0" /><CrossfadeMin Value="0" /><CrossfadeMax Value="0" /></BranchSelectorRange>'
    '<DeviceChain></DeviceChain>'
    '</MidiEffectBranchPreset></BranchPresets>'
    '</GroupDevicePreset></Ableton>'
)


def test_detect_instrument():
    assert detect_rack_type(INSTR_RACK) == "instrument"


def test_detect_audio_effect():
    assert detect_rack_type(AUDIO_RACK) == "audio_effect"


def test_detect_drum():
    assert detect_rack_type(DRUM_RACK) == "drum"   # despite embedded InstrumentGroupDevice


def test_detect_midi_effect():
    assert detect_rack_type(MIDI_RACK) == "midi_effect"


def test_detect_instrument_with_nested_drum():
    # an instrument rack whose chain contains a nested drum rack stays "instrument"
    nested = INSTR_RACK.replace("<DeviceChain></DeviceChain>",
                                "<DeviceChain><DrumGroupDevice /></DeviceChain>")
    assert detect_rack_type(nested) == "instrument"


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


# --- Task 2: depth-aware branch scanner + direct-child finders ---

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


# --- Task 3: summarizer ---

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


# --- Task 4: macro patchers ---

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


def test_patch_macro_color_no_color_sentinel():
    out = patch_macros(INSTR_RACK, colors={1: -1})
    s = summarize_rack_adg(out)
    assert s["macros"][0]["color"] == -1


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


# --- Task 5: zone patcher ---

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


# --- Task 6: real factory-file integration tests ---

import glob


def _factory_rack(subdir):
    hits = glob.glob(
        os.path.join(plat.core_library_glob(sys.platform), "Racks", subdir, "*", "*.adg"))
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


@pytest.mark.skipif(_factory_rack("Instrument Racks") is None,
                    reason="Ableton Live factory racks not installed")
def test_real_instrument_rack_patch_roundtrips():
    with gzip.open(_factory_rack("Instrument Racks"), "rt") as f:
        xml = f.read()
    # macro name round-trips through real (large, multi-line) XML
    out = patch_macros(xml, names={1: "RT & Test"}, colors={1: -1}, defaults={1: 100.0})
    s = summarize_rack_adg(out)
    assert s["macros"][0]["name"] == "RT & Test"
    assert s["macros"][0]["color"] == -1
    assert s["macros"][0]["default"] == 100.0
    # chain-level key zone patch round-trips on a real chain
    out2 = patch_chain_zone(out, "instrument", 0, "key", [24, 96])
    z = read_chain_zone(out2, "InstrumentBranchPreset", 0, "KeyRange")
    assert z == {"min": 24, "max": 96, "crossfade_min": 24, "crossfade_max": 96}


@pytest.mark.skipif(_factory_rack("Audio Effect Racks") is None,
                    reason="Ableton Live factory racks not installed")
def test_real_audio_effect_rack_no_keyvel():
    with gzip.open(_factory_rack("Audio Effect Racks"), "rt") as f:
        xml = f.read()
    s = summarize_rack_adg(xml)
    assert s["rack_type"] == "audio_effect"
    assert all(c["key_zone"] is None for c in s["chains"])


# --- Task 1 (Phase B): depth-aware direct-child element scanner ---

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


# --- Task 2 (Phase B): patch_macro_mappings ---

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


# --- Task 3 (Phase B): real factory-file macro-mapping round-trip ---

import re

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
    # first real parameter child of the device element (has a <LomId> and
    # <Manual>) that is NOT already macro-mapped - mapping an already-mapped
    # param replaces its <KeyMidi> rather than adding one (e.g. Basic Bass Amp's
    # Gate 'On', which the Windows glob order picks first).
    param_tag = None
    inner = device_el[ds:de]
    for t, s, e in _child_elements(inner):
        block = inner[s:e]
        if "<LomId" in block and "<Manual" in block and "<KeyMidi>" not in block:
            param_tag = t
            break
    assert param_tag is not None

    out = patch_macro_mappings(xml, detect_rack_type(xml),
                               [{"macro": 2, "chain": 0, "device": 0, "parameter": param_tag}])
    # exactly one new KeyMidi appeared vs the original count, with index 1
    assert out.count("<KeyMidi>") == xml.count("<KeyMidi>") + 1
    # find the param block that was actually patched (may not be the first occurrence
    # — e.g. <On> appears in every device; search all and find the one with our sentinel)
    blk = None
    for m in re.finditer(r'<%s>.*?</%s>' % (param_tag, param_tag), out, re.S):
        if '<Channel Value="16" />' in m.group(0):
            blk = m.group(0)
            break
    assert blk is not None, "patched <%s> with KeyMidi not found" % param_tag
    assert '<NoteOrController Value="1" />' in blk


# --- v2 Feature B: nested rack-in-rack parameter addressing (path) ---

from ableton_mcp_max.rack_preset_utils import _descend_to_device

# Instrument Rack whose chain0/device0 is itself an Audio Effect Rack (a nested
# rack with a DIFFERENT branch_tag) containing chain0/device0 = StereoGain/Gain.
# Structure mirrors REAL Live XML: a nested rack is a <GroupDevicePreset> wrapper
# whose chains live in a <BranchPresets> SIBLING of its <Device> (confirmed
# 2026-05-29 against factory Drum Rack pads). The earlier synthetic shape — a
# nested rack wrapped in <AbletonDevicePreset> with <BranchPresets> inside the
# device element — does not occur in practice.
NESTED_RACK = (
    '<Ableton><GroupDevicePreset><Device><InstrumentGroupDevice>'
    '<UserName Value="Outer" />'
    '</InstrumentGroupDevice></Device><BranchPresets>'
    '<InstrumentBranchPreset Id="0"><UserName Value="OuterChain" />'
    '<DevicePresets>'
    '<GroupDevicePreset Id="0"><Device><AudioEffectGroupDevice>'
    '<UserName Value="Nested" />'
    '</AudioEffectGroupDevice></Device>'
    '<BranchPresets>'
    '<AudioEffectBranchPreset Id="0"><UserName Value="InnerChain" />'
    '<DevicePresets>'
    '<AbletonDevicePreset Id="0"><Device><StereoGain Id="0"><LomId Value="0" />'
    '<Gain><LomId Value="0" /><Manual Value="1" />'
    '<MidiControllerRange><Min Value="0" /><Max Value="1" /></MidiControllerRange></Gain>'
    '<Balance><LomId Value="0" /><Manual Value="0" /></Balance>'
    '</StereoGain></Device></AbletonDevicePreset>'
    '</DevicePresets>'
    '<DeviceChain></DeviceChain>'
    '</AudioEffectBranchPreset>'
    '</BranchPresets>'
    '</GroupDevicePreset>'
    '</DevicePresets>'
    '<DeviceChain></DeviceChain>'
    '</InstrumentBranchPreset></BranchPresets>'
    '</GroupDevicePreset></Ableton>'
)


def test_nested_path_injects_keymidi_in_inner_param():
    out = patch_macro_mappings(NESTED_RACK, "instrument", [{
        "macro": 1,
        "path": [{"chain": 0, "device": 0}, {"chain": 0, "device": 0}],
        "parameter": "Gain",
    }])
    km = _gain_keymidi(out)
    assert km is not None
    assert '<Channel Value="16" />' in km
    assert '<NoteOrController Value="0" />' in km
    g = _re.search(r'<Gain>.*?</Gain>', out, _re.S).group(0)
    assert g.index('<LomId') < g.index('<KeyMidi>') < g.index('<Manual')


def test_flat_equiv_to_single_step_path():
    flat = patch_macro_mappings(MAP_RACK, "audio_effect",
                                [{"macro": 3, "chain": 0, "device": 0, "parameter": "Gain"}])
    via_path = patch_macro_mappings(MAP_RACK, "audio_effect",
                                    [{"macro": 3, "path": [{"chain": 0, "device": 0}],
                                      "parameter": "Gain"}])
    assert flat == via_path


def test_descend_detects_nested_branch_tag_differs():
    # outer = instrument, inner = audio_effect: descent must switch branch_tag
    dtag, s, e = _descend_to_device(
        NESTED_RACK, "InstrumentBranchPreset",
        [{"chain": 0, "device": 0}, {"chain": 0, "device": 0}])
    assert dtag == "StereoGain"


def test_path_descend_into_non_rack_errors():
    # MAP_RACK chain0/device0 is a plain StereoGain, not a rack -> cannot descend
    with pytest.raises(ValueError, match="not a rack"):
        patch_macro_mappings(MAP_RACK, "audio_effect", [{
            "macro": 1,
            "path": [{"chain": 0, "device": 0}, {"chain": 0, "device": 0}],
            "parameter": "Gain",
        }])


def test_path_chain_out_of_range_carries_step_index():
    with pytest.raises(ValueError, match="path step 1"):
        patch_macro_mappings(NESTED_RACK, "instrument", [{
            "macro": 1,
            "path": [{"chain": 0, "device": 0}, {"chain": 9, "device": 0}],
            "parameter": "Gain",
        }])


def test_path_device_out_of_range_carries_step_index():
    with pytest.raises(ValueError, match="path step 0"):
        patch_macro_mappings(NESTED_RACK, "instrument", [{
            "macro": 1,
            "path": [{"chain": 0, "device": 9}, {"chain": 0, "device": 0}],
            "parameter": "Gain",
        }])


def test_path_and_flat_both_given_rejected():
    with pytest.raises(ValueError, match="EITHER 'path' OR"):
        patch_macro_mappings(MAP_RACK, "audio_effect", [{
            "macro": 1, "chain": 0, "device": 0,
            "path": [{"chain": 0, "device": 0}], "parameter": "Gain",
        }])


def test_path_empty_rejected():
    with pytest.raises(ValueError, match="non-empty"):
        patch_macro_mappings(MAP_RACK, "audio_effect",
                             [{"macro": 1, "path": [], "parameter": "Gain"}])


def test_path_step_missing_device_rejected():
    with pytest.raises(ValueError, match="path step 0 requires 'device'"):
        patch_macro_mappings(MAP_RACK, "audio_effect",
                             [{"macro": 1, "path": [{"chain": 0}], "parameter": "Gain"}])


def test_nested_param_not_found_lists_available():
    with pytest.raises(ValueError, match="Available:.*Balance"):
        patch_macro_mappings(NESTED_RACK, "instrument", [{
            "macro": 1,
            "path": [{"chain": 0, "device": 0}, {"chain": 0, "device": 0}],
            "parameter": "Nope",
        }])


# ---- v2 Feature A: custom / inverted mapping ranges ----
# Encoding confirmed by save-diff (2026-05-29): the range is the param's
# <MidiControllerRange><Min>/<Max> in NATIVE units; inversion = Min > Max;
# default (omitted) leaves the intrinsic full-range block untouched; KeyMidi is
# unaffected by the range. MAP_RACK's <Gain> carries <Min Value="0"/><Max Value="1"/>.

def _gain_range(xml):
    g = _re.search(r'<Gain>.*?</Gain>', xml, _re.S).group(0)
    mcr = _re.search(r'<MidiControllerRange>.*?</MidiControllerRange>', g, _re.S).group(0)
    lo = _re.search(r'<Min Value="([^"]*)"', mcr).group(1)
    hi = _re.search(r'<Max Value="([^"]*)"', mcr).group(1)
    return lo, hi


def test_custom_range_writes_min_max():
    out = patch_macro_mappings(MAP_RACK, "audio_effect", [{
        "macro": 1, "chain": 0, "device": 0, "parameter": "Gain",
        "range": {"min": 0.2511886358, "max": 1},
    }])
    assert _gain_range(out) == ("0.2511886358", "1")
    # KeyMidi still injected, range did not disturb it
    assert '<NoteOrController Value="0" />' in _gain_keymidi(out)


def test_inverted_range_writes_min_gt_max_verbatim():
    out = patch_macro_mappings(MAP_RACK, "audio_effect", [{
        "macro": 1, "chain": 0, "device": 0, "parameter": "Gain",
        "range": {"min": 1, "max": 0.2511886358},
    }])
    # written verbatim, NOT sorted -> Min > Max encodes inversion
    assert _gain_range(out) == ("1", "0.2511886358")


def test_no_range_leaves_midicontrollerrange_untouched():
    out = patch_macro_mappings(MAP_RACK, "audio_effect",
                               [{"macro": 1, "chain": 0, "device": 0, "parameter": "Gain"}])
    assert _gain_range(out) == ("0", "1")  # MAP_RACK's intrinsic full range, unchanged


def test_range_on_nested_path():
    out = patch_macro_mappings(NESTED_RACK, "instrument", [{
        "macro": 2,
        "path": [{"chain": 0, "device": 0}, {"chain": 0, "device": 0}],
        "parameter": "Gain",
        "range": {"min": 0.5, "max": 0.8},
    }])
    # range landed in the INNER Gain's MidiControllerRange, with KeyMidi intact
    assert _gain_range(out) == ("0.5", "0.8")
    assert '<NoteOrController Value="1" />' in _gain_keymidi(out)


def test_range_requires_both_min_and_max():
    with pytest.raises(ValueError, match="requires both 'min' and 'max'"):
        patch_macro_mappings(MAP_RACK, "audio_effect", [{
            "macro": 1, "chain": 0, "device": 0, "parameter": "Gain",
            "range": {"min": 0.5},
        }])


def test_range_non_numeric_rejected():
    with pytest.raises(ValueError, match="min/max must be numbers"):
        patch_macro_mappings(MAP_RACK, "audio_effect", [{
            "macro": 1, "chain": 0, "device": 0, "parameter": "Gain",
            "range": {"min": "loud", "max": 1},
        }])


def test_range_non_finite_rejected():
    with pytest.raises(ValueError, match="must be finite"):
        patch_macro_mappings(MAP_RACK, "audio_effect", [{
            "macro": 1, "chain": 0, "device": 0, "parameter": "Gain",
            "range": {"min": 0, "max": float("inf")},
        }])


def test_range_on_param_without_controller_range_errors():
    # MAP_RACK's <Balance> has no <MidiControllerRange>; a range there must raise.
    with pytest.raises(ValueError, match="no <MidiControllerRange>"):
        patch_macro_mappings(MAP_RACK, "audio_effect", [{
            "macro": 1, "chain": 0, "device": 0, "parameter": "Balance",
            "range": {"min": 0, "max": 1},
        }])


# --- v2 Feature B: REAL factory nested-rack descent (regression guard) ---
# A nested rack in a chain is a <GroupDevicePreset> whose chains live in a
# <BranchPresets> SIBLING of its <Device> — NOT an <AbletonDevicePreset> with
# chains inside the device element. This test descends a genuine factory rack so a
# future structural regression (e.g. reverting to AbletonDevicePreset-only) fails.

def _factory_nested_rack():
    """First factory rack whose chain 0 contains a nested-rack <GroupDevicePreset>;
    returns (path, rack_type, branch_tag, device_index) or None.
    """
    for f in sorted(glob.glob(
            os.path.join(plat.core_library_glob(sys.platform), "Racks", "**", "*.adg"), recursive=True)):
        try:
            with gzip.open(f, "rt", errors="replace") as fh:
                x = fh.read()
            top = detect_rack_type(x)
        except Exception:
            continue
        btag = RACK_TYPES[top]["branch_tag"]
        chains = top_branches(x, btag)
        if not chains:
            continue
        b = x[chains[0][0]:chains[0][1]]
        dp = _find_child(b, "DevicePresets")
        if not dp:
            continue
        dpx = b[dp[0]:dp[1]]
        wraps = [t for (t, s, e) in _child_elements(dpx)
                 if t in ("AbletonDevicePreset", "GroupDevicePreset")]
        for di, t in enumerate(wraps):
            if t == "GroupDevicePreset":
                return f, top, btag, di
    return None


@pytest.mark.skipif(_factory_nested_rack() is None,
                    reason="no factory rack with a nested GroupDevicePreset")
def test_real_factory_nested_descent_reaches_inner_device():
    f, top, btag, di = _factory_nested_rack()
    with gzip.open(f, "rt", errors="replace") as fh:
        xml = fh.read()
    # one level: chain0/device<di> resolves to the nested rack's GroupDevice element
    dtag, s, e = _descend_to_device(xml, btag, [{"chain": 0, "device": di}])
    assert dtag.endswith("GroupDevice")
    nested_kind = detect_rack_type(xml[s:e])
    assert nested_kind in RACK_TYPES
    # two levels: into the nested rack's chain0/device0 (a real, non-rack device)
    dtag2, s2, e2 = _descend_to_device(
        xml, btag, [{"chain": 0, "device": di}, {"chain": 0, "device": 0}])
    # the deep device element exposes parameter tags (it's a real device span)
    deep_tags = {t for (t, a, b) in _child_elements(xml[s2:e2])}
    assert deep_tags, "deep device element has no child params"
