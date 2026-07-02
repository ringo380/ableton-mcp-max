from ableton_mcp_max import ozone_param_catalog as cat


def test_catalog_loads_and_validates():
    pack = cat.load()
    assert pack["plugin"] == "Ozone12"
    assert len(pack["params"]) == 873
    ids = [p["param_id"] for p in pack["params"]]
    assert len(ids) == len(set(ids))  # unique


def test_catalog_by_module_groups():
    pack = cat.load()
    groups = cat.catalog_by_module(pack)
    assert "MAX" in groups
    assert any(p["role"] == "output level" for p in groups["MAX"])


def test_find_param_banded():
    pack = cat.load()
    p = cat.find_param(pack, "EQ", "frequency", band=3, section="stereo_main")
    assert p is not None and p["name"] == "EQ: Stereo/Main Frequency 3"
