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


def test_pack_modules_selects_requested_within_cap():
    params = [
        {"module": "EQ", "param_id": 1, "name": "EQ: a"},
        {"module": "EQ", "param_id": 2, "name": "EQ: b"},
        {"module": "MAX", "param_id": 3, "name": "MAX: c"},
        {"module": "IMG", "param_id": 4, "name": "IMG: d"},
    ]
    res = oz.pack_modules(params, ["EQ", "MAX"], cap=128)
    assert [p["param_id"] for p in res["selected"]] == [1, 2, 3]
    assert res["dropped"] == 0
    assert res["overflow"] == []


def test_pack_modules_reports_overflow():
    params = [{"module": "EQ", "param_id": i, "name": "EQ: %d" % i} for i in range(5)]
    res = oz.pack_modules(params, ["EQ"], cap=3)
    assert len(res["selected"]) == 3
    assert res["dropped"] == 2
    assert res["overflow"] == ["EQ"]


def test_value_mapping_roundtrip():
    p = {"min": 20.0, "max": 20000.0}
    assert abs(oz.to_native(p, 0.0) - 20.0) < 1e-6
    assert abs(oz.to_native(p, 1.0) - 20000.0) < 1e-6
    assert abs(oz.to_normalized(p, 20000.0) - 1.0) < 1e-6
    # clamp
    assert oz.to_normalized(p, 40000.0) == 1.0
