import pytest
from ableton_mcp_max.transport_utils import (
    parse_time_signature,
    resolve_cue_direction,
    coerce_song_time,
    coerce_jump_beats,
    coerce_loop_fields,
    coerce_punch_fields,
    coerce_unit_float,
    resolve_clip_trigger_quantization,
    resolve_midi_recording_quantization,
    normalize_nudge_direction,
    resolve_capture_destination,
    resolve_capture_mode,
    coerce_record_length,
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


# Phase 10 — global feel / quantization -----------------------------------

def test_unit_float_clamps():
    assert coerce_unit_float(0.5) == 0.5
    assert coerce_unit_float(-1) == 0.0
    assert coerce_unit_float(2) == 1.0
    assert coerce_unit_float("0.25") == 0.25


def test_unit_float_non_numeric_raises():
    with pytest.raises(ValueError):
        coerce_unit_float("nope")


def test_clip_trigger_quant_int_passthrough():
    assert resolve_clip_trigger_quantization(7) == 7
    assert resolve_clip_trigger_quantization("4") == 4


def test_clip_trigger_quant_by_name():
    assert resolve_clip_trigger_quantization("none") == 0
    assert resolve_clip_trigger_quantization("1_bar") == 4
    assert resolve_clip_trigger_quantization("1/16") == 11


def test_clip_trigger_quant_bad_name_raises_with_list():
    with pytest.raises(ValueError) as exc:
        resolve_clip_trigger_quantization("nope")
    assert "1_bar" in str(exc.value)


def test_clip_trigger_quant_bool_rejected():
    with pytest.raises(ValueError):
        resolve_clip_trigger_quantization(True)


def test_midi_rec_quant_int_and_name():
    assert resolve_midi_recording_quantization(2) == 2
    assert resolve_midi_recording_quantization("none") == 0
    assert resolve_midi_recording_quantization("1/4") == 1
    assert resolve_midi_recording_quantization("1/8") == 2


def test_midi_rec_quant_bad_name_raises():
    with pytest.raises(ValueError):
        resolve_midi_recording_quantization("8_bars")


def test_nudge_direction():
    assert normalize_nudge_direction("Up") == "up"
    assert normalize_nudge_direction("DOWN") == "down"


def test_nudge_direction_bad_raises():
    with pytest.raises(ValueError):
        normalize_nudge_direction("sideways")


# Phase 11 — capture & recording ------------------------------------------

def test_capture_destination_default_and_names():
    assert resolve_capture_destination(None) == "auto"
    assert resolve_capture_destination("auto") == "auto"
    assert resolve_capture_destination("Session") == "session"
    assert resolve_capture_destination("ARRANGEMENT") == "arrangement"


def test_capture_destination_bad_raises_with_list():
    with pytest.raises(ValueError) as exc:
        resolve_capture_destination("nope")
    assert "auto" in str(exc.value) and "arrangement" in str(exc.value)


def test_capture_mode_default_and_name():
    assert resolve_capture_mode(None) == "all"
    assert resolve_capture_mode("All") == "all"


def test_capture_mode_bad_raises():
    with pytest.raises(ValueError):
        resolve_capture_mode("some")


def test_record_length_none_passthrough():
    assert coerce_record_length(None) is None


def test_record_length_positive_float():
    assert coerce_record_length(4) == 4.0
    assert coerce_record_length("8.5") == 8.5


def test_record_length_non_positive_raises():
    with pytest.raises(ValueError):
        coerce_record_length(0)
    with pytest.raises(ValueError):
        coerce_record_length(-2)


def test_record_length_non_numeric_raises():
    with pytest.raises(ValueError):
        coerce_record_length("soon")
