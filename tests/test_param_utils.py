import pytest
from ableton_mcp_max.param_utils import resolve_parameter_index

PARAMS = [
    {"index": 0, "name": "Device On"},
    {"index": 1, "name": "Filter Freq"},
    {"index": 2, "name": "Filter Res"},
]


def test_resolve_by_int_index():
    assert resolve_parameter_index(PARAMS, 1) == 1


def test_resolve_by_numeric_string():
    assert resolve_parameter_index(PARAMS, "2") == 2


def test_resolve_by_exact_name():
    assert resolve_parameter_index(PARAMS, "Filter Freq") == 1


def test_resolve_by_case_insensitive_name():
    assert resolve_parameter_index(PARAMS, "filter res") == 2


def test_index_out_of_range_raises():
    with pytest.raises(ValueError):
        resolve_parameter_index(PARAMS, 9)


def test_unknown_name_raises_with_available_list():
    with pytest.raises(ValueError) as exc:
        resolve_parameter_index(PARAMS, "Nope")
    assert "Filter Freq" in str(exc.value)
