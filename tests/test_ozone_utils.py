# tests/test_ozone_utils.py
from ableton_mcp_max import ozone_utils as oz


def test_modules_registry_has_core_mastering_modules():
    for key in ("EQ", "MAX", "DYN", "IMG", "DYNEQ", "EXC", "VLIM", "STEMEQ", "UNLIMITER"):
        assert key in oz.MODULES
    assert oz.MODULES["MAX"] == "Maximizer"
    assert oz.MODULES["IMG"] == "Imager"


def test_parse_stereo_main_banded():
    r = oz.parse_param_name("EQ: Stereo/Main Frequency 3")
    assert r["module"] == "EQ"
    assert r["module_name"] == "Equalizer"
    assert r["section"] == "stereo_main"
    assert r["role"] == "frequency"
    assert r["band"] == 3


def test_parse_aux_multiword_role_banded():
    r = oz.parse_param_name("DYN: Aux Band 2 Comp Threshold")
    assert r["module"] == "DYN"
    assert r["section"] == "aux"
    assert r["band"] == 2
    assert r["role"] == "band comp threshold"


def test_parse_module_unbanded():
    r = oz.parse_param_name("MAX: Output Level")
    assert r["module"] == "MAX"
    assert r["section"] is None
    assert r["role"] == "output level"
    assert r["band"] is None


def test_parse_bypass_and_global():
    b = oz.parse_param_name("MAX: Bypass")
    assert b["module"] == "MAX" and b["role"] == "bypass"
    g = oz.parse_param_name("Global Bypass")
    assert g["module"] is None and g["role"] == "global bypass"
