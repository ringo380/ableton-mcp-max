import pytest
from ableton_mcp_max.listener_utils import (
    normalize_scope,
    normalize_listener_property,
    build_descriptor,
    coerce_max_events,
    needs_device_resolution,
)


# --- scope ---
def test_scope_case_insensitive():
    assert normalize_scope("Transport") == "transport"

def test_scope_bad_raises():
    with pytest.raises(ValueError):
        normalize_scope("galaxy")


# --- property alias folding ---
def test_transport_bpm_alias():
    assert normalize_listener_property("transport", "bpm") == "tempo"

def test_transport_position_alias():
    assert normalize_listener_property("transport", "position") == "current_song_time"

def test_mixer_panning_alias():
    assert normalize_listener_property("mixer", "panning") == "pan"

def test_clip_playing_alias():
    assert normalize_listener_property("clip", "playing") == "playing_status"

def test_device_param_alias():
    assert normalize_listener_property("device", "parameter") == "value"

def test_bad_property_raises():
    with pytest.raises(ValueError):
        normalize_listener_property("transport", "wobble")


# --- descriptor: transport ---
def test_descriptor_transport_is_playing():
    d = build_descriptor("transport", "is_playing")
    assert d["target_kind"] == "song"
    assert d["listener_method"] == "add_is_playing_listener"
    assert d["remove_method"] == "remove_is_playing_listener"
    assert d["readback"] == "is_playing"
    assert d["selectors"] == {}

def test_descriptor_transport_tempo_via_alias():
    d = build_descriptor("transport", "bpm")
    assert d["property"] == "tempo"
    assert d["listener_method"] == "add_tempo_listener"


# --- descriptor: mixer ---
def test_descriptor_mixer_volume():
    d = build_descriptor("mixer", "volume", track_index=0)
    assert d["target_kind"] == "track_mixer"
    assert d["mixer_sub"] == "volume"
    assert d["listener_method"] == "add_value_listener"
    assert d["readback"] == "value"
    assert d["selectors"]["track_index"] == 0
    assert d["selectors"]["track_type"] == "regular"

def test_descriptor_mixer_pan_sub_is_panning():
    d = build_descriptor("mixer", "pan", track_index=2)
    assert d["mixer_sub"] == "panning"

def test_descriptor_mixer_mute_on_track():
    d = build_descriptor("mixer", "mute", track_index=1)
    assert d["target_kind"] == "track"
    assert d["listener_method"] == "add_mute_listener"

def test_descriptor_mixer_requires_track_index():
    with pytest.raises(ValueError):
        build_descriptor("mixer", "volume")

def test_descriptor_mixer_arm_on_return_rejected():
    with pytest.raises(ValueError):
        build_descriptor("mixer", "arm", track_index=0, track_type="return")

def test_descriptor_mixer_arm_on_master_rejected():
    with pytest.raises(ValueError):
        build_descriptor("mixer", "arm", track_index=0, track_type="master")


# --- descriptor: clip ---
def test_descriptor_clip_playing_status():
    d = build_descriptor("clip", "playing_status", track_index=0, clip_index=3)
    assert d["target_kind"] == "clip"
    assert d["listener_method"] == "add_playing_status_listener"
    assert d["readback"] == "is_playing"
    assert d["selectors"]["clip_index"] == 3

def test_descriptor_clip_has_clip_on_slot():
    d = build_descriptor("clip", "has_clip", track_index=0, clip_index=1)
    assert d["target_kind"] == "clip_slot"
    assert d["listener_method"] == "add_has_clip_listener"

def test_descriptor_clip_notes_no_readback():
    d = build_descriptor("clip", "notes", track_index=0, clip_index=0)
    assert d["readback"] is None
    assert d["listener_method"] == "add_notes_listener"

def test_descriptor_clip_requires_clip_index():
    with pytest.raises(ValueError):
        build_descriptor("clip", "playing_status", track_index=0)

def test_descriptor_selected_scene_on_song_view():
    d = build_descriptor("clip", "selected_scene")
    assert d["target_kind"] == "song_view"
    assert d["listener_method"] == "add_selected_scene_listener"


# --- descriptor: device ---
def test_descriptor_device_param():
    d = build_descriptor("device", "value", track_index=0,
                         device_index=0, parameter_index=5)
    assert d["target_kind"] == "device_param"
    assert d["listener_method"] == "add_value_listener"
    assert d["selectors"]["device_index"] == 0
    assert d["selectors"]["parameter_index"] == 5

def test_descriptor_device_requires_device_and_param():
    with pytest.raises(ValueError):
        build_descriptor("device", "value", track_index=0)
    with pytest.raises(ValueError):
        build_descriptor("device", "value", track_index=0, device_index=0)


# --- misc ---
def test_coerce_max_events_none_means_all():
    assert coerce_max_events(None) is None

def test_coerce_max_events_clamps_to_one():
    assert coerce_max_events(0) == 1
    assert coerce_max_events(-5) == 1
    assert coerce_max_events(50) == 50

def test_needs_device_resolution():
    assert needs_device_resolution("device", "value") is True
    assert needs_device_resolution("mixer", "volume") is False
