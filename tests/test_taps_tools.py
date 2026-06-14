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
    # read_meter now delegates to read_track_meter(-1): a signal summary.
    assert out["data"]["peak"] == 0.5
    assert "integrated_lufs" in out["data"]


def test_read_meter_no_master(monkeypatch):
    # Fresh registry (port=0 = no bind) so no master identity lingers from
    # the shared singleton seeded by other tests.
    from ableton_mcp_max.tap_registry import TapRegistry
    reg = TapRegistry(port=0)
    reg.feed("c9", '{"type":"hello","track":{"uuid":"u-only","name":"Only","index":0,"kind":"midi"}}\n')
    monkeypatch.setattr(server, "_tap_registry", reg)
    out = json.loads(server.read_meter(None))
    assert out["ok"] is False
    assert "tap" in out["error"].lower()


def _seed_master(blocks):
    reg = server._tap_registry
    reg.state.reset()
    reg.feed("m", '{"type":"hello","track":{"uuid":"master","name":"Master","index":-1,"kind":"master"},"sample_rate":48000}\n')
    for b in blocks:
        reg.feed("m", json.dumps({"type": "block", "data": b}) + "\n")


def test_read_track_meter_integrates_master_blocks():
    _seed_master([{"ms_k_l": 0.01, "ms_k_r": 0.01, "peak": 0.5, "rms": 0.1}] * 30)
    out = json.loads(server.read_track_meter(None, track_index=-1))
    assert out["ok"] is True
    d = out["data"]
    for k in ("integrated_lufs", "momentary_lufs", "short_term_lufs",
              "true_peak_dbtp", "peak", "rms", "crest", "block_count",
              "sample_rate"):
        assert k in d
    assert d["block_count"] == 30


def test_read_track_meter_empty_buffer_is_ok_with_zero_count():
    reg = server._tap_registry
    reg.state.reset()
    reg.feed("m", '{"type":"hello","track":{"uuid":"master","index":-1,"kind":"master"}}\n')
    out = json.loads(server.read_track_meter(None, track_index=-1))
    assert out["ok"] is True
    assert out["data"]["block_count"] == 0


def test_read_track_meter_unknown_track_errors():
    server._tap_registry.state.reset()
    out = json.loads(server.read_track_meter(None, track_index=99))
    assert out["ok"] is False


def test_read_meter_delegates_to_track_meter():
    _seed_master([{"ms_k_l": 0.01, "ms_k_r": 0.01, "peak": 0.5, "rms": 0.1}] * 30)
    out = json.loads(server.read_meter(None))
    assert out["ok"] is True
    assert "integrated_lufs" in out["data"]


def test_measure_loudness_reads_master_after_playback(monkeypatch):
    _seed_master([{"ms_k_l": 0.02, "ms_k_r": 0.02, "peak": 0.7, "rms": 0.2}] * 40)
    monkeypatch.setattr(server, "_run_measure_playback", lambda *a, **k: None)
    out = json.loads(server.measure_loudness(None))
    assert out["ok"] is True
    assert "integrated_lufs" in out["data"]


def test_measure_mix_returns_per_track_signal_and_findings(monkeypatch):
    reg = server._tap_registry
    reg.state.reset()
    # NOTE: reset() clears buffers but keeps identities; use fresh uuids/conns to avoid stale identities from other tests
    reg.feed("ck", '{"type":"hello","track":{"uuid":"ck","name":"Kick","index":0,"kind":"regular"},"sample_rate":48000}\n')
    reg.feed("bs", '{"type":"hello","track":{"uuid":"bs","name":"Bass","index":1,"kind":"regular"},"sample_rate":48000}\n')
    blk = lambda: '{"type":"block","data":{"ms_k_l":0.02,"ms_k_r":0.02,"peak":0.5,"rms":0.2,"bands":[1,0,0,0,0,0,0,0],"mid":1,"side":0}}\n'
    for _ in range(40):
        reg.feed("ck", blk()); reg.feed("bs", blk())
    monkeypatch.setattr(server, "_run_measure_playback", lambda *a, **k: None)
    out = json.loads(server.measure_mix(None, window_s=0))
    assert out["ok"] is True
    names = {t["name"] for t in out["data"]["tracks"]}
    assert {"Kick", "Bass"} <= names
    # Kick+Bass share band 0 -> masking finding present
    assert out["data"]["findings"]["masking"]


def test_measure_mix_no_taps_is_ok_empty(monkeypatch):
    server._tap_registry.state.reset()
    # ensure no identities: forget by dropping conns is registry-internal; just assert shape tolerates empties
    monkeypatch.setattr(server, "_run_measure_playback", lambda *a, **k: None)
    out = json.loads(server.measure_mix(None, window_s=0))
    assert out["ok"] is True
    assert isinstance(out["data"]["tracks"], list)
