import pytest
from ableton_mcp_max.routing_utils import (
    normalize_routing_property,
    validate_routing_property,
    resolve_routing_choice,
)

AVAIL = [
    {"display_name": "Ext. In", "identifier": 17},
    {"display_name": "Resampling", "identifier": 18},
    {"display_name": "1-Wavetable", "identifier": 5},
]


def test_normalize_aliases():
    assert normalize_routing_property("input_type") == "input_type"
    assert normalize_routing_property("in_type") == "input_type"
    assert normalize_routing_property("monitor") == "monitor"
    assert normalize_routing_property("Output Channel") == "output_channel"


def test_normalize_unknown_raises():
    with pytest.raises(ValueError):
        normalize_routing_property("sidechain")


def test_validate_regular_all():
    for p in ("input_type", "input_channel", "output_type", "output_channel", "monitor"):
        validate_routing_property("regular", p)


def test_validate_return_output_only():
    validate_routing_property("return", "output_type")
    with pytest.raises(ValueError):
        validate_routing_property("return", "input_type")
    with pytest.raises(ValueError):
        validate_routing_property("return", "monitor")


def test_validate_master_output_only():
    validate_routing_property("master", "output_channel")
    with pytest.raises(ValueError):
        validate_routing_property("master", "input_type")


def test_resolve_by_display_name():
    assert resolve_routing_choice(AVAIL, "Resampling")["identifier"] == 18


def test_resolve_case_insensitive():
    assert resolve_routing_choice(AVAIL, "ext. in")["identifier"] == 17


def test_resolve_by_identifier_int():
    assert resolve_routing_choice(AVAIL, 5)["display_name"] == "1-Wavetable"


def test_resolve_unknown_lists_available():
    with pytest.raises(ValueError) as exc:
        resolve_routing_choice(AVAIL, "Nope")
    assert "Resampling" in str(exc.value)
