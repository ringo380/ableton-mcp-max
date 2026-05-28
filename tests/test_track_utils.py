import pytest
from ableton_mcp_max.track_utils import (
    coerce_create_index,
    coerce_track_index,
)


# coerce_create_index -----------------------------------------------------

def test_create_index_none_means_append():
    assert coerce_create_index(None) == -1


def test_create_index_minus_one_ok():
    assert coerce_create_index(-1) == -1


def test_create_index_zero_ok():
    assert coerce_create_index(0) == 0


def test_create_index_positive_ok():
    assert coerce_create_index(5) == 5


def test_create_index_float_coerces():
    assert coerce_create_index(3.0) == 3
    assert isinstance(coerce_create_index(3.0), int)


def test_create_index_below_minus_one_raises():
    with pytest.raises(ValueError):
        coerce_create_index(-2)


def test_create_index_non_numeric_raises():
    with pytest.raises(ValueError):
        coerce_create_index("nope")


# coerce_track_index ------------------------------------------------------

def test_track_index_valid():
    assert coerce_track_index(4) == 4


def test_track_index_zero_ok():
    assert coerce_track_index(0) == 0


def test_track_index_negative_raises():
    with pytest.raises(ValueError):
        coerce_track_index(-1)


def test_track_index_non_numeric_raises():
    with pytest.raises(ValueError):
        coerce_track_index("nope")
