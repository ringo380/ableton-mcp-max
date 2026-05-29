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
