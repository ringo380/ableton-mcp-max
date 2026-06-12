import pytest
from ableton_mcp_max.analysis_utils import resolve_path


SNAP = {
    "transport": {"tempo": 120.0},
    "master": {"device_names": ["EQ Eight", "Limiter"]},
    "tracks": [
        {"name": "Bass", "mixer": {"volume_db": -6.0}, "devices": [{"class": "Eq8"}]},
        {"name": "Lead", "mixer": {"volume_db": 2.0}, "devices": [{"class": "Compressor2"}]},
    ],
}


def test_resolve_scalar():
    assert resolve_path(SNAP, "transport.tempo") == 120.0


def test_resolve_missing_is_none():
    assert resolve_path(SNAP, "transport.nope") is None
    assert resolve_path(SNAP, "nope.deep.path") is None


def test_resolve_list_projection():
    assert resolve_path(SNAP, "tracks[*].name") == ["Bass", "Lead"]


def test_resolve_nested_list_projection_flattens():
    assert resolve_path(SNAP, "tracks[*].devices[*].class") == ["Eq8", "Compressor2"]


def test_resolve_plain_list():
    assert resolve_path(SNAP, "master.device_names") == ["EQ Eight", "Limiter"]
