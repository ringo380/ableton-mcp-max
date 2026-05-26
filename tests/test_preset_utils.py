import pytest
from ableton_mcp_max.preset_utils import (
    match_preset,
    match_recursive_preset,
    split_preset_path,
)

# Recursive listing as returned by get_browser_presets (all loadable leaves,
# carrying a relative_path that may include subfolders).
PRESETS = [
    {"name": "Dark Swarm.adg", "relative_path": "Ambient/Dark Swarm.adg", "uri": "u1"},
    {"name": "Talking Bass.adv", "relative_path": "Bass/Talking Bass.adv", "uri": "u2"},
    {"name": "Deep Bass.adv", "relative_path": "Bass/Deep Bass.adv", "uri": "u3"},
]

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


# match_recursive_preset --------------------------------------------------

def test_recursive_match_by_name_in_subfolder():
    # The leaf name resolves even though it lives under a subfolder — this is
    # the list->load workflow that the direct match_preset could not satisfy.
    assert match_recursive_preset(PRESETS, "Dark Swarm.adg")["uri"] == "u1"


def test_recursive_match_by_relative_path():
    assert match_recursive_preset(PRESETS, "Bass/Talking Bass.adv")["uri"] == "u2"


def test_recursive_match_case_insensitive():
    assert match_recursive_preset(PRESETS, "dark swarm.adg")["uri"] == "u1"


def test_recursive_match_unique_substring():
    assert match_recursive_preset(PRESETS, "Talking")["uri"] == "u2"


def test_recursive_match_ambiguous_substring_raises():
    with pytest.raises(ValueError) as exc:
        match_recursive_preset(PRESETS, "Bass")
    msg = str(exc.value)
    assert "Talking Bass.adv" in msg and "Deep Bass.adv" in msg


def test_recursive_match_not_found_lists_available():
    with pytest.raises(ValueError) as exc:
        match_recursive_preset(PRESETS, "Nope")
    assert "Dark Swarm.adg" in str(exc.value)


def test_recursive_match_empty_raises():
    with pytest.raises(ValueError):
        match_recursive_preset([], "anything")


def test_recursive_match_available_list_capped():
    many = [
        {"name": "p%d" % i, "relative_path": "f/p%d" % i, "uri": "u%d" % i}
        for i in range(50)
    ]
    with pytest.raises(ValueError) as exc:
        match_recursive_preset(many, "zzz-no-match")
    assert "(+20 more)" in str(exc.value)


# split_preset_path -------------------------------------------------------

def test_split_ok():
    assert split_preset_path("a/b/c") == ("a/b", "c")


def test_split_strips_slashes():
    assert split_preset_path("/instruments/Wavetable/Bass/") == (
        "instruments/Wavetable", "Bass")


def test_split_single_segment_raises():
    with pytest.raises(ValueError):
        split_preset_path("instruments")
