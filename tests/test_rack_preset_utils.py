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
