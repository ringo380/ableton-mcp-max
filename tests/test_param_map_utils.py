"""Offline tests for the plugin parameter-map pack loader/deriver.

Exercise the pure logic that derives Configure-slot ids from a probed name list
and loads/validates committed packs (serum2.json et al). No Live / no network.
"""
import json

import pytest

from ableton_mcp_max import param_map_utils as pmu


def test_derive_serum_ids_basic():
    names = ["MasterVol", "A Octave", "A Fine", "Filter 1 Freq"]
    out = pmu.derive_serum_ids(names)
    assert out[0] == {"param_id": 2000000, "name": "MasterVol", "index": 0}
    assert out[3] == {"param_id": 2000003, "name": "Filter 1 Freq", "index": 3}
    assert len(out) == 4


def test_derive_serum_ids_custom_base():
    out = pmu.derive_serum_ids(["X", "Y"], id_base=5000)
    assert [p["param_id"] for p in out] == [5000, 5001]


def test_derive_serum_ids_skips_blank_without_shifting():
    # blank at index 1 is dropped but index 2 keeps its positional id
    out = pmu.derive_serum_ids(["A", "  ", "C"])
    assert [(p["name"], p["param_id"], p["index"]) for p in out] == [
        ("A", 2000000, 0),
        ("C", 2000002, 2),
    ]


def _good_pack():
    return {
        "plugin": "Serum 2",
        "id_base": 2000000,
        "params": [
            {"param_id": 2000003, "name": "Filter 1 Freq", "category": "Filter"},
            {"param_id": 2000004, "name": "Filter 1 Res", "category": "Filter"},
        ],
    }


def test_validate_pack_ok():
    pack = _good_pack()
    assert pmu.validate_pack(pack) is pack


def test_validate_pack_rejects_missing_plugin():
    pack = _good_pack()
    pack["plugin"] = ""
    with pytest.raises(ValueError):
        pmu.validate_pack(pack)


def test_validate_pack_rejects_bad_id_base():
    pack = _good_pack()
    pack["id_base"] = "2000000"
    with pytest.raises(ValueError):
        pmu.validate_pack(pack)


def test_validate_pack_rejects_empty_params():
    pack = _good_pack()
    pack["params"] = []
    with pytest.raises(ValueError):
        pmu.validate_pack(pack)


def test_validate_pack_rejects_bad_param_name():
    pack = _good_pack()
    pack["params"][0]["name"] = ""
    with pytest.raises(ValueError):
        pmu.validate_pack(pack)


def test_validate_pack_rejects_non_int_param_id():
    pack = _good_pack()
    pack["params"][0]["param_id"] = "2000003"
    with pytest.raises(ValueError):
        pmu.validate_pack(pack)


def test_validate_pack_rejects_duplicate_param_id():
    pack = _good_pack()
    pack["params"][1]["param_id"] = 2000003
    with pytest.raises(ValueError):
        pmu.validate_pack(pack)


def test_load_pack_roundtrip(tmp_path):
    (tmp_path / "demo.json").write_text(json.dumps(_good_pack()))
    pack = pmu.load_pack("demo", pack_dir=str(tmp_path))
    assert pack["plugin"] == "Serum 2"
    assert len(pack["params"]) == 2


def test_load_pack_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        pmu.load_pack("nope", pack_dir=str(tmp_path))


def test_find_params_substring():
    pack = _good_pack()
    hits = pmu.find_params(pack, "freq")
    assert len(hits) == 1 and hits[0]["name"] == "Filter 1 Freq"


def test_find_params_category_filter():
    pack = _good_pack()
    pack["params"].append(
        {"param_id": 2000099, "name": "MasterVol", "category": "Global"}
    )
    assert len(pmu.find_params(pack, "", category="Filter")) == 2
    assert len(pmu.find_params(pack, "", category="Global")) == 1


def test_find_params_empty_query_matches_all():
    assert len(pmu.find_params(_good_pack(), "")) == 2
