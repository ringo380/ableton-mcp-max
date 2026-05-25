import pytest
from ableton_mcp_max.device_utils import (
    resolve_device_index,
    resolve_macro,
    normalize_chain_property,
    validate_chain_property,
    coerce_chain_value,
    coerce_on_value,
)

DEVICES = [
    {"index": 0, "name": "Wavetable"},
    {"index": 1, "name": "Reverb"},
    {"index": 2, "name": "EQ Eight"},
]

# Macros: 'index' is the device-parameter index; 'macro_number' is 1-based
# position. First two carry custom labels (renamed), the rest default names.
MACROS = [
    {"index": 1, "macro_number": 1, "name": "Filter Cutoff"},
    {"index": 2, "macro_number": 2, "name": "Drive"},
    {"index": 3, "macro_number": 3, "name": "Macro 3"},
]


# resolve_device_index ----------------------------------------------------

def test_device_by_int_index():
    assert resolve_device_index(DEVICES, 1) == 1


def test_device_by_numeric_string():
    assert resolve_device_index(DEVICES, "2") == 2


def test_device_by_exact_name():
    assert resolve_device_index(DEVICES, "Reverb") == 1


def test_device_by_case_insensitive_name():
    assert resolve_device_index(DEVICES, "eq eight") == 2


def test_device_index_out_of_range_raises():
    with pytest.raises(ValueError):
        resolve_device_index(DEVICES, 9)


def test_device_unknown_name_raises_with_available_list():
    with pytest.raises(ValueError) as exc:
        resolve_device_index(DEVICES, "Nope")
    assert "Wavetable" in str(exc.value)


# resolve_macro -----------------------------------------------------------

def test_macro_by_number_int_positional():
    # macro number 1 -> first macro (renamed "Filter Cutoff") at param index 1
    assert resolve_macro(MACROS, 1) == 1
    assert resolve_macro(MACROS, 2) == 2


def test_macro_by_number_string():
    assert resolve_macro(MACROS, "3") == 3


def test_macro_by_custom_label_name():
    assert resolve_macro(MACROS, "Drive") == 2


def test_macro_by_case_insensitive_name():
    assert resolve_macro(MACROS, "filter cutoff") == 1


def test_macro_by_default_name():
    assert resolve_macro(MACROS, "Macro 3") == 3


def test_macro_number_out_of_range_raises():
    with pytest.raises(ValueError) as exc:
        resolve_macro(MACROS, 8)
    assert "Filter Cutoff" in str(exc.value)


def test_macro_unknown_name_raises():
    with pytest.raises(ValueError):
        resolve_macro(MACROS, "Nonexistent")


# chain property normalize/validate --------------------------------------

def test_chain_property_aliases():
    assert normalize_chain_property("vol") == "volume"
    assert normalize_chain_property("Pan") == "panning"
    assert normalize_chain_property("MUTE") == "mute"
    assert normalize_chain_property("solo") == "solo"


def test_chain_property_unknown_raises():
    with pytest.raises(ValueError):
        normalize_chain_property("gain")


def test_validate_chain_property_ok():
    assert validate_chain_property("volume") == "volume"


def test_validate_chain_property_bad_raises():
    with pytest.raises(ValueError):
        validate_chain_property("frobnicate")


# coerce_chain_value ------------------------------------------------------

def test_coerce_chain_value_bool_props():
    assert coerce_chain_value("mute", "on") is True
    assert coerce_chain_value("solo", "off") is False


def test_coerce_chain_value_float_props():
    assert coerce_chain_value("volume", "0.5") == 0.5
    assert coerce_chain_value("panning", -1) == -1.0


# coerce_on_value ---------------------------------------------------------

def test_coerce_on_value_real_bool():
    assert coerce_on_value(True) is True
    assert coerce_on_value(False) is False


def test_coerce_on_value_numeric():
    assert coerce_on_value(1) is True
    assert coerce_on_value(0) is False


def test_coerce_on_value_strings():
    for s in ("on", "true", "yes", "1", "enable", "Enabled"):
        assert coerce_on_value(s) is True
    for s in ("off", "false", "no", "0", "disable", "Disabled"):
        assert coerce_on_value(s) is False


def test_coerce_on_value_bad_raises():
    with pytest.raises(ValueError):
        coerce_on_value("maybe")
