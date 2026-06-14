import json
import ableton_mcp_max.server as server


class _FakeConn:
    def __init__(self, raw):
        self._raw = raw

    def send_command(self, command_type, params=None, **kwargs):
        assert command_type == "get_analysis_snapshot"
        return self._raw


_RAW = {
    "transport": {"tempo": 120.0, "is_playing": False,
                  "signature_numerator": 4, "signature_denominator": 4},
    "tracks": [
        {"name": "Lead", "type": "midi", "volume": 0.95, "panning": 0.0,
         "sends": [0.0], "mute": False, "solo": False, "arm": False,
         "has_instrument": True, "is_grouped": False,
         "devices": [{"index": 0, "name": "Wavetable", "class_name": "InstrumentVector",
                      "on": True, "is_instrument": True}],
         "clips": {"count": 1, "named": 1, "warped": 1, "empty_slots": 7},
         "routing": {"audio_to": "Master", "audio_from": "No Input"}},
    ],
    "returns": [],
    "master": {"name": "Master", "volume": 0.85, "panning": 0.0, "devices": []},
}


def test_analyze_set_returns_envelope(monkeypatch):
    monkeypatch.setattr(server, "get_ableton_connection", lambda: _FakeConn(_RAW))
    out = json.loads(server.analyze_set(ctx=None, focus="all"))
    assert out["ok"] is True
    data = out["data"]
    assert "snapshot" in data and "findings" in data and "summary" in data
    # master has no limiter -> a mastering fail finding
    ids = {f["id"]: f for f in data["findings"]}
    assert ids["mastering.limiter_present"]["status"] == "fail"
    # Lead fader 0.95 (> unity 0.85) -> mixing warn
    assert ids["mixing.fader_headroom"]["status"] == "warn"


def test_analyze_set_rejects_bad_focus():
    out = json.loads(server.analyze_set(ctx=None, focus="loudness"))
    assert out["ok"] is False


_MIX_IDS = {"mixing.spectral_masking", "mixing.loudness_balance",
            "mixing.headroom_per_track", "mixing.stereo_correlation"}

_RAW_MIX = {
    "transport": {"tempo": 120.0, "is_playing": False,
                  "signature_numerator": 4, "signature_denominator": 4},
    "tracks": [
        {"index": 0, "name": "Kick", "type": "audio", "volume": 0.85, "panning": 0.0,
         "sends": [0.0], "mute": False, "solo": False, "arm": False,
         "has_instrument": False, "is_grouped": False, "devices": [],
         "clips": {"count": 1, "named": 1, "warped": 1, "empty_slots": 7},
         "routing": {"audio_to": "Master", "audio_from": "Ext In"}},
        {"index": 1, "name": "Bass", "type": "audio", "volume": 0.85, "panning": 0.0,
         "sends": [0.0], "mute": False, "solo": False, "arm": False,
         "has_instrument": False, "is_grouped": False, "devices": [],
         "clips": {"count": 1, "named": 1, "warped": 1, "empty_slots": 7},
         "routing": {"audio_to": "Master", "audio_from": "Ext In"}},
    ],
    "returns": [],
    "master": {"name": "Master", "volume": 0.85, "panning": 0.0, "devices": []},
}


def _register_two_blank_taps():
    # blank device names + matching indices -> exercises LOM name enrichment.
    # hello (identity) survives the measure-pass buffer reset; blocks are
    # streamed by the stubbed playback below to mimic the live device.
    reg = server._tap_registry
    reg.state.reset()
    reg.state._by_conn.clear()
    reg.state._identity.clear()
    reg.feed("c0", '{"type":"hello","track":{"uuid":"k","name":"","index":0,"kind":"regular"}}\n')
    reg.feed("c1", '{"type":"hello","track":{"uuid":"b","name":"","index":1,"kind":"regular"}}\n')


def _stream_overlapping_blocks(*a, **k):
    reg = server._tap_registry
    blk = ('{"type":"block","data":{"ms_k_l":0.01,"ms_k_r":0.01,"peak":0.5,'
           '"rms":0.1,"bands":[1,0,0,0,0,0,0,0],"mid":1,"side":0}}\n')
    for _ in range(40):
        reg.feed("c0", blk)
        reg.feed("c1", blk)
    return True


def test_analyze_set_defers_mix_rules_without_measure(monkeypatch):
    monkeypatch.setattr(server, "get_ableton_connection", lambda: _FakeConn(_RAW_MIX))
    out = json.loads(server.analyze_set(ctx=None, focus="all"))
    data = out["data"]
    assert "mix_signal" not in data
    deferred = {d["id"] for d in data["deferred_rules"]}
    assert _MIX_IDS <= deferred


def test_analyze_set_measure_adds_mix_signal_and_promotes(monkeypatch):
    monkeypatch.setattr(server, "get_ableton_connection", lambda: _FakeConn(_RAW_MIX))
    monkeypatch.setattr(server, "_run_measure_playback", _stream_overlapping_blocks)
    _register_two_blank_taps()
    out = json.loads(server.analyze_set(ctx=None, focus="all", measure=True))
    data = out["data"]
    assert "mix_signal" in data
    mix = data["mix_signal"]
    # names enriched from the LOM index (device sent "")
    names = {t["name"] for t in mix["tracks"]}
    assert {"Kick", "Bass"} <= names
    by_id = {f["id"]: f for f in mix["findings"]}
    assert _MIX_IDS <= set(by_id)
    # Kick + Bass share band 0 -> masking flagged
    assert by_id["mixing.spectral_masking"]["status"] == "warn"
    assert by_id["mixing.spectral_masking"]["items"]
    # promoted out of deferred
    deferred = {d["id"] for d in data["deferred_rules"]}
    assert not (_MIX_IDS & deferred)
    # summary tally stays in step with the promotion
    assert data["summary"]["deferred"] == len(data["deferred_rules"])


def test_analyze_set_measure_no_taps_stays_deferred(monkeypatch):
    monkeypatch.setattr(server, "get_ableton_connection", lambda: _FakeConn(_RAW_MIX))
    server._tap_registry.state.reset()
    # drop any connections from prior tests so no taps are "connected"
    server._tap_registry.state._by_conn.clear()
    server._tap_registry.state._identity.clear()
    out = json.loads(server.analyze_set(ctx=None, focus="all", measure=True))
    data = out["data"]
    assert "mix_signal" not in data
    deferred = {d["id"] for d in data["deferred_rules"]}
    assert _MIX_IDS <= deferred
