import pytest
from ableton_mcp_max.mixer_utils import normalize_property, validate_property


# --- normalize_property: case/alias folding ---
def test_normalize_canonical():
    assert normalize_property("volume") == "volume"


def test_normalize_case_insensitive():
    assert normalize_property("Volume") == "volume"


def test_normalize_pan_aliases():
    assert normalize_property("pan") == "pan"
    assert normalize_property("panning") == "pan"


def test_normalize_unknown_raises_with_list():
    with pytest.raises(ValueError) as exc:
        normalize_property("nope")
    assert "volume" in str(exc.value)


# --- validate_property: track-type asymmetries ---
def test_regular_supports_all():
    for p in ("volume", "pan", "mute", "solo", "arm", "send", "crossfade_assign"):
        validate_property("regular", p)  # no raise


def test_return_has_no_arm():
    with pytest.raises(ValueError):
        validate_property("return", "arm")


def test_master_has_no_mute_solo_arm_send():
    for p in ("mute", "solo", "arm", "send"):
        with pytest.raises(ValueError):
            validate_property("master", p)


def test_master_allows_volume_pan():
    validate_property("master", "volume")
    validate_property("master", "pan")


def test_unknown_track_type_raises():
    with pytest.raises(ValueError):
        validate_property("bus", "volume")
