import pytest
from ableton_mcp_max.clip_utils import (
    normalize_clip_property,
    validate_clip_property,
    coerce_clip_value,
    resolve_quantize_grid,
    normalize_note,
    NOTE_MOD_FIELDS,
    QUANTIZE_GRID_MAP,
)


# --- normalize_clip_property: case/alias/space folding ---
def test_normalize_canonical():
    assert normalize_clip_property("looping") == "looping"


def test_normalize_case_and_space():
    assert normalize_clip_property("Loop Start") == "loop_start"


def test_normalize_aliases():
    assert normalize_clip_property("loop") == "looping"
    assert normalize_clip_property("pitch") == "pitch_coarse"
    assert normalize_clip_property("detune") == "pitch_fine"
    assert normalize_clip_property("warp") == "warping"


def test_normalize_unknown_raises_with_list():
    with pytest.raises(ValueError) as exc:
        normalize_clip_property("nope")
    assert "looping" in str(exc.value)


# --- validate_clip_property: midi vs audio asymmetry ---
def test_midi_supports_common():
    for p in ("looping", "loop_start", "loop_end", "start_marker",
              "end_marker", "signature_numerator", "signature_denominator"):
        validate_clip_property("midi", p)  # no raise


def test_audio_only_rejected_on_midi():
    for p in ("warping", "warp_mode", "gain", "pitch_coarse", "pitch_fine"):
        with pytest.raises(ValueError) as exc:
            validate_clip_property("midi", p)
        assert "audio-only" in str(exc.value)


def test_audio_supports_all():
    for p in ("looping", "warping", "warp_mode", "gain",
              "pitch_coarse", "pitch_fine"):
        validate_clip_property("audio", p)  # no raise


def test_unknown_clip_kind_raises():
    with pytest.raises(ValueError):
        validate_clip_property("video", "looping")


# --- coerce_clip_value: type casting + pure clamps ---
def test_coerce_bool():
    assert coerce_clip_value("looping", 1) is True
    assert coerce_clip_value("looping", 0) is False
    assert coerce_clip_value("warping", "true") is True
    assert coerce_clip_value("warping", "off") is False


def test_coerce_int_props():
    assert coerce_clip_value("signature_numerator", 4.0) == 4
    assert isinstance(coerce_clip_value("warp_mode", 2.0), int)


def test_coerce_float_props():
    assert coerce_clip_value("loop_start", 2) == 2.0
    assert isinstance(coerce_clip_value("loop_end", 4), float)


def test_coerce_gain_clamp():
    assert coerce_clip_value("gain", 2.0) == 1.0
    assert coerce_clip_value("gain", -1.0) == 0.0


def test_coerce_pitch_clamp():
    assert coerce_clip_value("pitch_coarse", 99) == 48
    assert coerce_clip_value("pitch_coarse", -99) == -48
    assert coerce_clip_value("pitch_fine", 99) == 50
    assert coerce_clip_value("pitch_fine", -99) == -50


# --- resolve_quantize_grid ---
def test_resolve_grid_known():
    assert resolve_quantize_grid("1/16") == QUANTIZE_GRID_MAP["1/16"]
    assert resolve_quantize_grid("1/8T") == QUANTIZE_GRID_MAP["1/8t"]


def test_resolve_grid_enum_ints_match_live():
    # Confirmed live against Live 11 RecordingQuantization (no 1/4t member).
    assert resolve_quantize_grid("none") == 0
    assert resolve_quantize_grid("1/4") == 1
    assert resolve_quantize_grid("1/8") == 2
    assert resolve_quantize_grid("1/8t") == 3
    assert resolve_quantize_grid("1/32") == 8


def test_resolve_grid_unknown_raises_with_list():
    with pytest.raises(ValueError) as exc:
        resolve_quantize_grid("1/3")
    assert "Available" in str(exc.value)


# --- normalize_note: defaults + clamps for the extended note API ---
def test_normalize_note_defaults():
    n = normalize_note({"pitch": 64, "start_time": 1.0, "duration": 0.5})
    assert n["pitch"] == 64
    assert n["velocity"] == 100
    assert n["mute"] is False
    assert n["probability"] == 1.0
    assert n["velocity_deviation"] == 0.0
    assert n["release_velocity"] == 64.0
    assert set(n.keys()) == set(NOTE_MOD_FIELDS)


def test_normalize_note_passthrough_extended():
    n = normalize_note({
        "pitch": 60, "probability": 0.5,
        "velocity_deviation": 10.0, "release_velocity": 80,
    })
    assert n["probability"] == 0.5
    assert n["velocity_deviation"] == 10.0
    assert n["release_velocity"] == 80.0


def test_normalize_note_clamps():
    n = normalize_note({"pitch": 200, "velocity": 999, "probability": 2.0})
    assert n["pitch"] == 127
    assert n["velocity"] == 127.0
    assert n["probability"] == 1.0
    n2 = normalize_note({"pitch": -5, "probability": -1.0, "release_velocity": -3})
    assert n2["pitch"] == 0
    assert n2["probability"] == 0.0
    assert n2["release_velocity"] == 0.0
