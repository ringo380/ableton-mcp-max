import gzip
import os

import pytest

from ableton_mcp_max.wavetable_preset_utils import (
    UNISON_MODES,
    resolve_unison_mode,
    unison_mode_name,
    validate_voices,
    build_wavetable_adv,
    summarize_wavetable_adv,
)

FACTORY_DEFAULT = (
    "/Applications/Ableton Live 11 Suite.app/Contents/App-Resources/"
    "Core Library/Defaults/Instruments/Wavetable.adv"
)

# A tiny synthetic stand-in so tests run even without Live installed. It carries
# just the tags build_wavetable_adv touches, in the same self-closing /
# <Manual> shapes as the real preset.
SYNTH_DEFAULT = (
    '<Ableton>'
    '<UserName Value="Wavetable" />'
    '<SpriteName1 Value="Basic Shapes" />'
    '<SpriteName2 Value="Basic Shapes" />'
    '<Voice_Unison_Mode Value="0" />'
    '<Voice_Unison_VoiceCount Value="3" />'
    '<Voice_Unison_Amount><Manual Value="0.3" /></Voice_Unison_Amount>'
    '<Voice_Oscillator2_On><Manual Value="false" /></Voice_Oscillator2_On>'
    '<Voice_Oscillator1_Wavetables_WavePosition><Manual Value="0" />'
    '</Voice_Oscillator1_Wavetables_WavePosition>'
    '<Voice_Oscillator2_Wavetables_WavePosition><Manual Value="0" />'
    '</Voice_Oscillator2_Wavetables_WavePosition>'
    '</Ableton>'
)


def _default_xml():
    if os.path.exists(FACTORY_DEFAULT):
        with gzip.open(FACTORY_DEFAULT, "rt") as f:
            return f.read()
    return SYNTH_DEFAULT


# resolve_unison_mode ----------------------------------------------------

def test_resolve_mode_by_name():
    assert resolve_unison_mode("classic") == 1
    assert resolve_unison_mode("Phase Sync") == 4
    assert resolve_unison_mode("  RANDOM NOTE ") == 6


def test_resolve_mode_by_int():
    assert resolve_unison_mode(0) == 0
    assert resolve_unison_mode(6) == 6


def test_resolve_mode_bad_name():
    with pytest.raises(ValueError):
        resolve_unison_mode("supersaw")


def test_resolve_mode_out_of_range():
    with pytest.raises(ValueError):
        resolve_unison_mode(7)


def test_resolve_mode_rejects_bool():
    with pytest.raises(ValueError):
        resolve_unison_mode(True)


def test_unison_mode_name_roundtrip():
    for name, val in UNISON_MODES.items():
        assert unison_mode_name(val) == name


# validate_voices --------------------------------------------------------

def test_voices_ok():
    assert validate_voices(7) == 7
    assert validate_voices("4") == 4


@pytest.mark.parametrize("bad", [1, 9, 0, -3])
def test_voices_out_of_range(bad):
    with pytest.raises(ValueError):
        validate_voices(bad)


def test_voices_non_int():
    with pytest.raises(ValueError):
        validate_voices("lots")


# build_wavetable_adv ----------------------------------------------------

def test_build_sets_all_core_fields():
    out = build_wavetable_adv(
        _default_xml(), table1="Quad Saw", table2="Logue Saw",
        unison_mode="classic", voices=7, amount=0.85,
        osc1_pos=0.66, osc2_pos=0.66, osc2_on=True, name="MCP Supersaw",
    )
    s = summarize_wavetable_adv(out)
    assert s["table1"] == "Quad Saw"
    assert s["table2"] == "Logue Saw"
    assert s["unison_mode"] == 1
    assert s["unison_mode_name"] == "classic"
    assert s["voices"] == 7
    assert s["name"] == "MCP Supersaw"


def test_build_table2_defaults_to_table1():
    out = build_wavetable_adv(_default_xml(), table1="Basic Shapes")
    s = summarize_wavetable_adv(out)
    assert s["table1"] == s["table2"] == "Basic Shapes"


def test_build_osc2_off_flag():
    import re
    out = build_wavetable_adv(_default_xml(), table1="Basic Shapes", osc2_on=False)
    block = re.search(r"<Voice_Oscillator2_On>.*?</Voice_Oscillator2_On>", out, re.S)
    assert block and 'Manual Value="false"' in block.group(0)
    out_on = build_wavetable_adv(_default_xml(), table1="Basic Shapes", osc2_on=True)
    block_on = re.search(r"<Voice_Oscillator2_On>.*?</Voice_Oscillator2_On>", out_on, re.S)
    assert block_on and 'Manual Value="true"' in block_on.group(0)


def test_build_rejects_bad_amount():
    with pytest.raises(ValueError):
        build_wavetable_adv(_default_xml(), table1="Basic Shapes", amount=1.5)


def test_build_rejects_empty_table():
    with pytest.raises(ValueError):
        build_wavetable_adv(_default_xml(), table1="  ")


def test_build_rejects_quote_in_table():
    with pytest.raises(ValueError):
        build_wavetable_adv(_default_xml(), table1='Saw" />')


def test_build_missing_tag_raises():
    with pytest.raises(ValueError):
        build_wavetable_adv("<Ableton></Ableton>", table1="Basic Shapes")


def test_build_is_pure_does_not_mutate_input():
    src = _default_xml()
    before = src
    build_wavetable_adv(src, table1="Quad Saw")
    assert src == before
