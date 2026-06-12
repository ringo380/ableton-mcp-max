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
