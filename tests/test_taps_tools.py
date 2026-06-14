"""Tool-level tests for the per-track tap tools, driven through the in-process
tap registry singleton hosted in server.py (no real socket needed - feed frames
straight into the registry via its testable ingest seam)."""
import json

from ableton_mcp_max import server


def _seed_registry():
    reg = server._tap_registry
    reg.state.reset()
    # master + one regular track identity, each with one block frame
    reg.feed("c1", '{"type":"hello","track":{"uuid":"master","name":"Master","index":-1,"kind":"master"}}\n')
    reg.feed("c1", '{"type":"block","data":{"ms_k_l":0.01,"ms_k_r":0.01,"peak":0.5,"rms":0.1}}\n')
    reg.feed("c2", '{"type":"hello","track":{"uuid":"u-bass","name":"Bass","index":2,"kind":"midi"}}\n')


def test_get_audio_tap_status_reports_connected():
    _seed_registry()
    out = json.loads(server.get_audio_tap_status(None))
    assert out["ok"] is True
    assert out["data"]["connected"] is True
    assert any(t["uuid"] == "master" for t in out["data"]["tracks"])


def test_list_taps_lists_tracks():
    _seed_registry()
    out = json.loads(server.list_taps(None))
    assert out["ok"] is True
    assert out["data"]["count"] >= 2


def test_uuid_for_index_matches_master_and_track():
    _seed_registry()
    assert server._uuid_for_index(-1) == "master"
    assert server._uuid_for_index(2) == "u-bass"
    assert server._uuid_for_index(99) is None


def test_reset_meter_all_and_one():
    _seed_registry()
    assert json.loads(server.reset_meter(None))["ok"] is True
    assert json.loads(server.reset_meter(None, track_index=-1))["ok"] is True


def test_read_meter_master_snapshot():
    _seed_registry()
    out = json.loads(server.read_meter(None))
    assert out["ok"] is True
    assert out["data"]["block_count"] == 1
    assert out["data"]["last"]["peak"] == 0.5


def test_read_meter_no_master(monkeypatch):
    # Fresh registry (port=0 = no bind) so no master identity lingers from
    # the shared singleton seeded by other tests.
    from ableton_mcp_max.tap_registry import TapRegistry
    reg = TapRegistry(port=0)
    reg.feed("c9", '{"type":"hello","track":{"uuid":"u-only","name":"Only","index":0,"kind":"midi"}}\n')
    monkeypatch.setattr(server, "_tap_registry", reg)
    out = json.loads(server.read_meter(None))
    assert out["ok"] is False
    assert "master" in out["error"].lower()
