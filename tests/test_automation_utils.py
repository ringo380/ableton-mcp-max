import pytest
from ableton_mcp_max.automation_utils import (
    normalize_clip_location,
    normalize_target_type,
    normalize_mixer_target,
    coerce_resolution,
    coerce_time,
    coerce_duration,
    coerce_value,
    normalize_breakpoints,
)

# --- clip_location ---
def test_clip_location_default_session():
    assert normalize_clip_location("session") == "session"

def test_clip_location_case_insensitive():
    assert normalize_clip_location("Arrangement") == "arrangement"

def test_clip_location_bad_raises():
    with pytest.raises(ValueError):
        normalize_clip_location("timeline")

# --- target_type ---
def test_target_type_device():
    assert normalize_target_type("device") == "device"

def test_target_type_mixer_case():
    assert normalize_target_type("MIXER") == "mixer"

def test_target_type_bad_raises():
    with pytest.raises(ValueError):
        normalize_target_type("macro")

# --- mixer target ---
def test_mixer_target_volume():
    assert normalize_mixer_target("volume", -1) == ("volume", -1)

def test_mixer_target_pan_alias():
    assert normalize_mixer_target("panning", -1) == ("pan", -1)

def test_mixer_target_send_requires_index():
    with pytest.raises(ValueError):
        normalize_mixer_target("send", -1)

def test_mixer_target_send_ok():
    assert normalize_mixer_target("send", 0) == ("send", 0)

# --- resolution clamp ---
def test_resolution_clamps_to_one():
    assert coerce_resolution(0) == 1
    assert coerce_resolution(-5) == 1

def test_resolution_passthrough():
    assert coerce_resolution(32) == 32

# --- time / duration / value ---
def test_time_negative_raises():
    with pytest.raises(ValueError):
        coerce_time(-0.5)

def test_duration_negative_raises():
    with pytest.raises(ValueError):
        coerce_duration(-1.0)

def test_value_coerces_float():
    assert coerce_value(1) == 1.0

# --- breakpoints ---
def test_breakpoints_single_form():
    bps = normalize_breakpoints(None, 2.0, 0.5, 0.0)
    assert bps == [{"time": 2.0, "value": 0.5, "duration": 0.0}]

def test_breakpoints_list_form():
    bps = normalize_breakpoints(
        [{"time": 0.0, "value": 0.0}, {"time": 4.0, "value": 1.0, "duration": 1.0}],
        None, None, 0.0)
    assert bps == [
        {"time": 0.0, "value": 0.0, "duration": 0.0},
        {"time": 4.0, "value": 1.0, "duration": 1.0},
    ]

def test_breakpoints_empty_raises():
    with pytest.raises(ValueError):
        normalize_breakpoints([], None, None, 0.0)

def test_breakpoints_none_raises():
    with pytest.raises(ValueError):
        normalize_breakpoints(None, None, None, 0.0)

def test_breakpoints_missing_value_raises():
    with pytest.raises(ValueError):
        normalize_breakpoints([{"time": 1.0}], None, None, 0.0)

def test_breakpoints_negative_time_raises():
    with pytest.raises(ValueError):
        normalize_breakpoints([{"time": -1.0, "value": 0.5}], None, None, 0.0)
