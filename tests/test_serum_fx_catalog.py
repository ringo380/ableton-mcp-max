import os
import pytest
from ableton_mcp_max import serum_fx_catalog as cat

CATALOG = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                       "ableton_mcp_max", "param_maps", "serum2_fx.json")

@pytest.mark.skipif(not os.path.exists(CATALOG), reason="catalog not generated")
def test_load_and_lookup():
    c = cat.load_catalog()
    assert c["plugin"] == "Serum2"
    info = cat.fx_type_info(c, 12)          # FXUtils
    assert info["wrapper_key"] == "FXUtils"
    assert any(p["kparam"] == "kParamWet" for p in info["params"])
    assert cat.wrapper_key(c, 12) == "FXUtils"

def test_unknown_type_lists_valid():
    c = {"plugin": "Serum2", "fx_types": {"12": {"name": "Utils", "wrapper_key": "FXUtils", "params": [], "default_template": {}}}}
    with pytest.raises(ValueError) as e:
        cat.fx_type_info(c, 999)
    assert "12" in str(e.value)

def test_unknown_param_lists_valid():
    c = {"plugin": "Serum2", "fx_types": {"12": {"name": "Utils", "wrapper_key": "FXUtils",
        "params": [{"kparam": "kParamWet", "native_min": 0.0, "native_max": 1.0}], "default_template": {}}}}
    with pytest.raises(ValueError) as e:
        cat.param_info(c, 12, "kParamDoesNotExist")
    assert "kParamWet" in str(e.value)
