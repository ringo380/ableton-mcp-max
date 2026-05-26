import pytest
from ableton_mcp_max.arrangement_utils import (
    coerce_time,
    coerce_index,
    cue_exists_at,
)


# coerce_time -------------------------------------------------------------

def test_coerce_time_float():
    assert coerce_time(8.5) == 8.5


def test_coerce_time_int_to_float():
    assert coerce_time(4) == 4.0
    assert isinstance(coerce_time(4), float)


def test_coerce_time_zero_ok():
    assert coerce_time(0) == 0.0


def test_coerce_time_negative_raises():
    with pytest.raises(ValueError):
        coerce_time(-1)


def test_coerce_time_non_numeric_raises():
    with pytest.raises(ValueError):
        coerce_time("nope")


# coerce_index ------------------------------------------------------------

def test_coerce_index_valid():
    assert coerce_index(3) == 3


def test_coerce_index_zero_ok():
    assert coerce_index(0) == 0


def test_coerce_index_string_digit():
    assert coerce_index("5") == 5


def test_coerce_index_negative_raises():
    with pytest.raises(ValueError):
        coerce_index(-2)


def test_coerce_index_non_numeric_raises():
    with pytest.raises(ValueError):
        coerce_index("x")


# cue_exists_at -----------------------------------------------------------

def test_cue_exists_exact():
    assert cue_exists_at([0.0, 16.0, 32.0], 16.0) == (True, 1)


def test_cue_exists_within_epsilon():
    assert cue_exists_at([0.0, 16.0], 16.0000001) == (True, 1)


def test_cue_exists_no_match():
    assert cue_exists_at([0.0, 16.0], 8.0) == (False, None)


def test_cue_exists_empty_list():
    assert cue_exists_at([], 0.0) == (False, None)
