import pytest
from ableton_mcp_max.scene_utils import (
    normalize_scene_property,
    coerce_scene_value,
)


# normalize_scene_property ------------------------------------------------

def test_scene_property_aliases():
    assert normalize_scene_property("colour") == "color"
    assert normalize_scene_property("BPM") == "tempo"
    assert normalize_scene_property("tempo_on") == "tempo_enabled"
    assert normalize_scene_property("time sig") == "time_signature"
    assert normalize_scene_property("signature") == "time_signature"


def test_scene_property_canonical_passthrough():
    assert normalize_scene_property("tempo") == "tempo"
    assert normalize_scene_property("time_signature") == "time_signature"


def test_scene_property_unknown_raises_with_list():
    with pytest.raises(ValueError) as exc:
        normalize_scene_property("nope")
    assert "tempo" in str(exc.value)


# coerce_scene_value ------------------------------------------------------

def test_coerce_tempo_enabled_bool():
    assert coerce_scene_value("tempo_enabled", "on") is True
    assert coerce_scene_value("tempo_enabled", "off") is False


def test_coerce_tempo_float():
    assert coerce_scene_value("tempo", "128") == 128.0


def test_coerce_tempo_clamps():
    assert coerce_scene_value("tempo", 5) == 20.0
    assert coerce_scene_value("tempo", 9999) == 999.0


def test_coerce_color_int():
    assert coerce_scene_value("color", "5") == 5


def test_coerce_time_signature_tuple():
    assert coerce_scene_value("time_signature", "6/8") == (6, 8)


def test_coerce_time_signature_bad_raises():
    with pytest.raises(ValueError):
        coerce_scene_value("time_signature", "4/3")
