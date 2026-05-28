import pytest

from ableton_mcp_max.preset_patch import (
    set_attr,
    set_manual,
    scope,
    get_attr,
    validate_preset_name,
    validate_unit,
    validate_int_range,
    validate_choice,
)

XML = (
    '<Root>'
    '<Name Value="x" />'
    '<Dup Value="1" /><Dup Value="2" />'
    '<Vol><Manual Value="0.1" /></Vol>'
    '<Bands.0><Pa><Mode><Manual Value="0" /></Mode></Pa></Bands.0>'
    '<Bands.1><Pa><Mode><Manual Value="0" /></Mode></Pa></Bands.1>'
    '</Root>'
)


# set_attr ---------------------------------------------------------------

def test_set_attr_basic():
    assert 'Value="y"' in set_attr(XML, "Name", "y")


def test_set_attr_missing_required():
    with pytest.raises(ValueError):
        set_attr(XML, "Nope", "1")


def test_set_attr_missing_optional_noop():
    assert set_attr(XML, "Nope", "1", required=False) == XML


def test_set_attr_ambiguous_raises():
    with pytest.raises(ValueError):
        set_attr(XML, "Dup", "9")


# set_manual -------------------------------------------------------------

def test_set_manual_basic():
    out = set_manual(XML, "Vol", "0.9")
    assert '<Vol><Manual Value="0.9" /></Vol>' in out


def test_set_manual_missing_container():
    with pytest.raises(ValueError):
        set_manual(XML, "Ghost", "1")


# scope ------------------------------------------------------------------

def test_scope_targets_nth_block():
    out = scope(XML, "Bands.1", lambda b: set_manual(b, "Mode", "3"))
    # Bands.1 changed, Bands.0 untouched
    assert '<Bands.1><Pa><Mode><Manual Value="3" />' in out
    assert '<Bands.0><Pa><Mode><Manual Value="0" />' in out


def test_scope_missing_raises():
    with pytest.raises(ValueError):
        scope(XML, "Bands.9", lambda b: b)


# get_attr ---------------------------------------------------------------

def test_get_attr():
    assert get_attr(XML, "Name") == "x"
    assert get_attr(XML, "Missing") is None


# validators -------------------------------------------------------------

def test_validate_preset_name_ok():
    assert validate_preset_name("  My Patch ") == "My Patch"


@pytest.mark.parametrize("bad", ["", "a/b", "a\\b", ".hidden", 'a"b'])
def test_validate_preset_name_bad(bad):
    with pytest.raises(ValueError):
        validate_preset_name(bad)


def test_validate_unit():
    assert validate_unit(0.5, "x") == 0.5
    with pytest.raises(ValueError):
        validate_unit(2, "x")


def test_validate_int_range():
    assert validate_int_range("4", 2, 8, "n") == 4
    with pytest.raises(ValueError):
        validate_int_range(9, 2, 8, "n")


def test_validate_choice_name_and_int():
    choices = ["lowpass", "highpass", "bandpass"]
    assert validate_choice("Highpass", choices, "type") == 1
    assert validate_choice(2, choices, "type") == 2
    with pytest.raises(ValueError):
        validate_choice("ladder", choices, "type")
    with pytest.raises(ValueError):
        validate_choice(True, choices, "type")
