import pytest
from ableton_mcp_max.transport_utils import (
    parse_time_signature,
    resolve_cue_direction,
    coerce_song_time,
    coerce_jump_beats,
    coerce_loop_fields,
    coerce_punch_fields,
)


# parse_time_signature ----------------------------------------------------

def test_time_signature_string():
    assert parse_time_signature("4/4") == (4, 4)
    assert parse_time_signature("6/8") == (6, 8)


def test_time_signature_tuple_and_list():
    assert parse_time_signature((3, 4)) == (3, 4)
    assert parse_time_signature([7, 16]) == (7, 16)


def test_time_signature_no_slash_raises():
    with pytest.raises(ValueError):
        parse_time_signature("44")


def test_time_signature_bad_denominator_raises_with_list():
    with pytest.raises(ValueError) as exc:
        parse_time_signature("4/3")
    assert "16" in str(exc.value)


def test_time_signature_numerator_out_of_range_raises():
    with pytest.raises(ValueError):
        parse_time_signature("0/4")
    with pytest.raises(ValueError):
        parse_time_signature("100/4")


# resolve_cue_direction ---------------------------------------------------

def test_cue_direction_next_aliases():
    for s in ("next", "forward", "Fwd"):
        assert resolve_cue_direction(s) == "next"


def test_cue_direction_prev_aliases():
    for s in ("prev", "previous", "back", "Backward"):
        assert resolve_cue_direction(s) == "prev"


def test_cue_direction_unknown_raises_with_options():
    with pytest.raises(ValueError) as exc:
        resolve_cue_direction("sideways")
    assert "next" in str(exc.value) and "prev" in str(exc.value)


# coerce_song_time / coerce_jump_beats ------------------------------------

def test_song_time_ok():
    assert coerce_song_time("8.0") == 8.0
    assert coerce_song_time(0) == 0.0


def test_song_time_negative_raises():
    with pytest.raises(ValueError):
        coerce_song_time(-1)


def test_jump_beats_allows_negative():
    assert coerce_jump_beats("-2") == -2.0
    assert coerce_jump_beats(4) == 4.0


def test_jump_beats_non_numeric_raises():
    with pytest.raises(ValueError):
        coerce_jump_beats("soon")


# coerce_loop_fields ------------------------------------------------------

def test_loop_fields_all_provided():
    out = coerce_loop_fields("on", 4, 8)
    assert out == {"enabled": True, "start": 4.0, "length": 8.0}


def test_loop_fields_partial():
    assert coerce_loop_fields(True, None, None) == {"enabled": True}


def test_loop_fields_all_none_raises():
    with pytest.raises(ValueError):
        coerce_loop_fields(None, None, None)


def test_loop_fields_bad_start_and_length_raise():
    with pytest.raises(ValueError):
        coerce_loop_fields(None, -1, None)
    with pytest.raises(ValueError):
        coerce_loop_fields(None, None, 0)


# coerce_punch_fields -----------------------------------------------------

def test_punch_fields_partial():
    assert coerce_punch_fields("on", None) == {"punch_in": True}
    assert coerce_punch_fields(None, "off") == {"punch_out": False}


def test_punch_fields_both_none_raises():
    with pytest.raises(ValueError):
        coerce_punch_fields(None, None)
