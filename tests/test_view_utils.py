import pytest
from ableton_mcp_max.view_utils import normalize_track_type, coerce_index


# --- normalize_track_type ---
def test_track_type_default_regular():
    assert normalize_track_type(None) == "regular"


def test_track_type_case_fold():
    assert normalize_track_type("Regular") == "regular"
    assert normalize_track_type("RETURN") == "return"
    assert normalize_track_type("Master") == "master"


def test_track_type_bad_raises_with_list():
    with pytest.raises(ValueError) as exc:
        normalize_track_type("bus")
    assert "regular" in str(exc.value)


# --- coerce_index ---
def test_coerce_index_ok():
    assert coerce_index(0) == 0
    assert coerce_index("5") == 5


def test_coerce_index_negative_raises():
    with pytest.raises(ValueError):
        coerce_index(-1)


def test_coerce_index_non_numeric_raises():
    with pytest.raises(ValueError):
        coerce_index("nope")
