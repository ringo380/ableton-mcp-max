import pytest
from ableton_mcp_max.preset_utils import (
    match_preset,
    split_preset_path,
)

ITEMS = [
    {"name": "Bass Talk", "uri": "u1", "is_loadable": True, "is_folder": False},
    {"name": "Bass Deep", "uri": "u2", "is_loadable": True, "is_folder": False},
    {"name": "Lead Bright", "uri": "u3", "is_loadable": True, "is_folder": False},
    {"name": "Presets", "uri": None, "is_loadable": False, "is_folder": True},
]


# match_preset ------------------------------------------------------------

def test_match_exact():
    assert match_preset(ITEMS, "Lead Bright")["uri"] == "u3"


def test_match_case_insensitive():
    assert match_preset(ITEMS, "lead bright")["uri"] == "u3"


def test_match_unique_substring():
    assert match_preset(ITEMS, "Lead")["uri"] == "u3"


def test_match_ambiguous_substring_raises():
    with pytest.raises(ValueError) as exc:
        match_preset(ITEMS, "Bass")
    msg = str(exc.value)
    assert "Bass Talk" in msg and "Bass Deep" in msg


def test_match_not_found_lists_available():
    with pytest.raises(ValueError) as exc:
        match_preset(ITEMS, "Pad")
    assert "Lead Bright" in str(exc.value)


def test_match_ignores_non_loadable_folder():
    # The non-loadable "Presets" folder is never selected, even by substring.
    with pytest.raises(ValueError):
        match_preset(ITEMS, "Presets")
    with pytest.raises(ValueError):
        match_preset(ITEMS, "Preset")


def test_match_no_loadable_items_raises():
    with pytest.raises(ValueError):
        match_preset([{"name": "x", "uri": None, "is_loadable": False}], "x")


# split_preset_path -------------------------------------------------------

def test_split_ok():
    assert split_preset_path("a/b/c") == ("a/b", "c")


def test_split_strips_slashes():
    assert split_preset_path("/instruments/Wavetable/Bass/") == (
        "instruments/Wavetable", "Bass")


def test_split_single_segment_raises():
    with pytest.raises(ValueError):
        split_preset_path("instruments")
