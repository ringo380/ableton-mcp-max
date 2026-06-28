import pytest
from ableton_mcp_max import serum_fx_utils as fx

CAT = {"plugin": "Serum2", "fx_types": {
    "12": {"name": "Utils", "wrapper_key": "FXUtils", "params": [
        {"kparam": "kParamWet", "native_min": 0.0, "native_max": 100.0}], "default_template": {}},
    "4": {"name": "Delay", "wrapper_key": "FXDelay", "params": [
        {"kparam": "kParamWet", "native_min": 0.0, "native_max": 100.0}], "default_template": {}},
}}

def _tree():
    return {"FXRack0": {"FX": [
        {"type": 12, "FXUtils": {"plainParams": {"kParamWet": 96.7}}, "kUIParamMixOrGain": 0.0}],
        "displayName": "", "plainParams": {}},
        "FXRack1": {"FX": [], "displayName": "", "plainParams": {}},
        "FXRack2": {"FX": [], "displayName": "", "plainParams": {}}}

def test_list_fx():
    items = fx.list_fx(_tree())
    assert items[0]["rack"] == 0 and items[0]["slot"] == 0 and items[0]["type"] == 12
    assert items[0]["params"]["kParamWet"] == 96.7

def test_set_fx_param_in_range():
    t = _tree()
    fx.set_fx_param(CAT, t, 0, 0, "kParamWet", 50.0)
    assert fx.get_fx_params(t, 0, 0)["kParamWet"] == 50.0

def test_set_fx_param_out_of_range_raises():
    t = _tree()
    with pytest.raises(ValueError):
        fx.set_fx_param(CAT, t, 0, 0, "kParamWet", 999.0)

def test_insert_and_remove_fx():
    t = _tree()
    fx.insert_fx(CAT, t, 1, 0, 4)
    assert t["FXRack1"]["FX"][0]["type"] == 4
    assert "FXDelay" in t["FXRack1"]["FX"][0]
    fx.remove_fx(t, 1, 0)
    assert t["FXRack1"]["FX"] == []

def test_reorder_fx():
    t = _tree()
    fx.insert_fx(CAT, t, 0, 1, 4)          # rack0 now [12, 4]
    fx.reorder_fx(t, 0, 0, 1)              # -> [4, 12]
    assert [f["type"] for f in t["FXRack0"]["FX"]] == [4, 12]

def test_set_enabled():
    t = _tree()
    fx.set_fx_enabled(t, 0, 0, False)
    assert fx.get_fx_params(t, 0, 0)["kParamEnable"] == 0.0

def test_bad_rack_slot_raises():
    t = _tree()
    with pytest.raises(ValueError):
        fx.get_fx_params(t, 0, 5)
    with pytest.raises(ValueError):
        fx.get_fx_params(t, 9, 0)
