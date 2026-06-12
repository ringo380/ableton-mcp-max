import pytest
from ableton_mcp_max.analysis_utils import normalize_snapshot, live_volume_to_db


def test_live_volume_to_db_unity():
    # Live's linear mixer value 0.85 == 0 dB (unity).
    assert round(live_volume_to_db(0.85)) == 0


def test_live_volume_to_db_silence_is_floor():
    assert live_volume_to_db(0.0) <= -70


RAW = {
    "transport": {"tempo": 120.0, "is_playing": False,
                  "signature_numerator": 4, "signature_denominator": 4},
    "tracks": [
        {"name": "1-MIDI", "type": "midi", "volume": 0.85, "panning": 0.0,
         "sends": [0.0], "mute": False, "solo": False, "arm": True,
         "is_grouped": False, "has_instrument": False,
         "devices": [{"index": 0, "name": "EQ Eight", "class_name": "Eq8", "on": True, "is_instrument": False}],
         "clips": {"count": 2, "named": 1, "warped": 2, "empty_slots": 6},
         "routing": {"audio_to": "Master", "audio_from": "No Input"}},
        {"name": "Group", "type": "group", "volume": 0.85, "panning": 0.0,
         "sends": [0.0], "mute": False, "solo": False,
         "is_grouped": False, "has_instrument": False,
         "devices": [], "clips": {"count": 0, "named": 0, "warped": 0, "empty_slots": 8},
         "routing": {"audio_to": "Master", "audio_from": "No Input"}},
    ],
    "returns": [
        {"name": "A-Reverb", "type": "return", "volume": 0.85, "panning": 0.0,
         "mute": False, "solo": False,
         "devices": [{"index": 0, "name": "Reverb", "class_name": "Reverb", "on": True, "is_instrument": False}]},
    ],
    "master": {"name": "Master", "volume": 0.85, "panning": 0.0,
               "devices": [{"index": 0, "name": "Limiter", "class_name": "Limiter", "on": True, "is_instrument": False}]},
}


def test_normalize_adds_db_and_device_names():
    snap = normalize_snapshot(RAW)
    t0 = snap["tracks"][0]
    assert round(t0["mixer"]["volume_db"]) == 0
    assert t0["device_names"] == ["EQ Eight"]
    assert t0["devices"][0]["class"] == "Eq8"


def test_normalize_reserves_signal_null():
    snap = normalize_snapshot(RAW)
    assert snap["tracks"][0]["signal"] is None
    assert snap["master"]["signal"] is None


def test_normalize_group_track_arm_defaults_false():
    snap = normalize_snapshot(RAW)
    # group track had no 'arm' key -> normalized to False, never KeyError
    assert snap["tracks"][1]["mixer"]["arm"] is False


def test_normalize_master_device_names():
    snap = normalize_snapshot(RAW)
    assert snap["master"]["device_names"] == ["Limiter"]


def test_normalize_returns_subset():
    snap = normalize_snapshot(RAW)
    assert snap["returns"][0]["type"] == "return"
    assert snap["returns"][0]["device_names"] == ["Reverb"]
