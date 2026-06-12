import pytest
from ableton_mcp_max.analysis_utils import resolve_path


SNAP = {
    "transport": {"tempo": 120.0},
    "master": {"device_names": ["EQ Eight", "Limiter"]},
    "tracks": [
        {"name": "Bass", "mixer": {"volume_db": -6.0}, "devices": [{"class": "Eq8"}]},
        {"name": "Lead", "mixer": {"volume_db": 2.0}, "devices": [{"class": "Compressor2"}]},
    ],
}


def test_resolve_scalar():
    assert resolve_path(SNAP, "transport.tempo") == 120.0


def test_resolve_missing_is_none():
    assert resolve_path(SNAP, "transport.nope") is None
    assert resolve_path(SNAP, "nope.deep.path") is None


def test_resolve_list_projection():
    assert resolve_path(SNAP, "tracks[*].name") == ["Bass", "Lead"]


def test_resolve_nested_list_projection_flattens():
    assert resolve_path(SNAP, "tracks[*].devices[*].class") == ["Eq8", "Compressor2"]


def test_resolve_plain_list():
    assert resolve_path(SNAP, "master.device_names") == ["EQ Eight", "Limiter"]


from ableton_mcp_max.analysis_utils import evaluate_check


def test_op_includes():
    assert evaluate_check({"field": "master.device_names", "op": "includes", "value": "Limiter"}, SNAP) is True
    assert evaluate_check({"field": "master.device_names", "op": "includes", "value": "Saturator"}, SNAP) is False


def test_op_numeric():
    assert evaluate_check({"field": "transport.tempo", "op": "gt", "value": 100}, SNAP) is True
    assert evaluate_check({"field": "transport.tempo", "op": "lte", "value": 120}, SNAP) is True
    assert evaluate_check({"field": "transport.tempo", "op": "equals", "value": 120.0}, SNAP) is True


def test_op_exists_and_missing():
    assert evaluate_check({"field": "master", "op": "exists"}, SNAP) is True
    assert evaluate_check({"field": "nope", "op": "exists"}, SNAP) is False
    # numeric op on a missing field is False, never raises
    assert evaluate_check({"field": "nope", "op": "gt", "value": 0}, SNAP) is False


def test_op_matches_list_any():
    assert evaluate_check({"field": "tracks[*].devices[*].class", "op": "matches", "value": "^Eq"}, SNAP) is True
    assert evaluate_check({"field": "tracks[*].name", "op": "matches", "value": "^Drum"}, SNAP) is False


def test_op_count():
    assert evaluate_check({"field": "tracks[*].name", "op": "count_gt", "value": 1}, SNAP) is True
    assert evaluate_check({"field": "tracks[*].name", "op": "count_lt", "value": 5}, SNAP) is True


def test_composition_all_any_not():
    chk = {"all": [
        {"field": "transport.tempo", "op": "gt", "value": 100},
        {"any": [
            {"field": "master.device_names", "op": "includes", "value": "Limiter"},
            {"field": "master.device_names", "op": "includes", "value": "Saturator"},
        ]},
        {"not": {"field": "tracks[*].name", "op": "includes", "value": "Vocals"}},
    ]}
    assert evaluate_check(chk, SNAP) is True
