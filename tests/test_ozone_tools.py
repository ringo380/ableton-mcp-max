from ableton_mcp_max import ozone_utils as oz
from ableton_mcp_max import ozone_param_catalog as cat


def test_expose_selection_respects_modules_and_cap():
    pack = cat.load()
    res = oz.pack_modules(pack["params"], ["MAX", "IMG"], cap=128)
    # Maximizer + Imager both fit comfortably under 128
    assert res["dropped"] == 0 and res["overflow"] == []
    assert all(p["module"] in ("MAX", "IMG") for p in res["selected"])
    assert len(res["selected"]) > 0


def test_find_param_resolves_maximizer_output_level():
    pack = cat.load()
    p = cat.find_param(pack, "MAX", "output level")
    assert p is not None and p["name"] == "MAX: Output Level"


def test_find_param_bypass():
    pack = cat.load()
    p = cat.find_param(pack, "IMG", "bypass")
    assert p is not None and p["name"].endswith("Bypass")
