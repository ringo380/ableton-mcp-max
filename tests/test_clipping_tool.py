import json
import ableton_mcp_max.server as server


class _FakeConn:
    def __init__(self, raw):
        self._raw = raw

    def send_command(self, command_type, params=None, **kwargs):
        assert command_type == "get_analysis_snapshot"
        return self._raw


# Snapshot: Drums (idx 1) sits hot; Bass (idx 0) is fine.
_RAW = {
    "transport": {"tempo": 120.0, "is_playing": False,
                  "signature_numerator": 4, "signature_denominator": 4},
    "tracks": [
        {"index": 0, "name": "Bass", "type": "audio", "volume": 0.85, "panning": 0.0,
         "sends": [0.0], "mute": False, "solo": False, "arm": False,
         "has_instrument": False, "is_grouped": False, "devices": [],
         "clips": {"count": 1, "named": 1, "warped": 1, "empty_slots": 7},
         "routing": {"audio_to": "Master", "audio_from": "Ext In"}},
        {"index": 1, "name": "Drums", "type": "audio", "volume": 0.9, "panning": 0.0,
         "sends": [0.0], "mute": False, "solo": False, "arm": False,
         "has_instrument": False, "is_grouped": False, "devices": [],
         "clips": {"count": 1, "named": 1, "warped": 1, "empty_slots": 7},
         "routing": {"audio_to": "Master", "audio_from": "Ext In"}},
    ],
    "returns": [],
    "master": {"name": "Master", "volume": 0.85, "panning": 0.0, "devices": []},
}


def _held_drums_clipping(*a, **k):
    # Drums (idx 1) peaks at 1.2 linear (~+1.6 dBFS), Bass clean, master hot too.
    return {
        "tracks": {0: 0.5, 1: 1.2},
        "returns": {},
        "master": 1.05,
        "names": {("regular", 0): "Bass", ("regular", 1): "Drums"},
        "played": True,
    }


def _held_clean(*a, **k):
    return {"tracks": {0: 0.5, 1: 0.6}, "returns": {}, "master": 0.7,
            "names": {("regular", 0): "Bass", ("regular", 1): "Drums"},
            "played": True}


# --- check_clipping standalone tool ---------------------------------------

def test_check_clipping_flags_offenders(monkeypatch):
    monkeypatch.setattr(server, "_peak_hold_pass", _held_drums_clipping)
    out = json.loads(server.check_clipping(ctx=None, window_s=1.0))
    assert out["ok"] is True
    data = out["data"]
    assert data["any_clipping"] is True
    clip_names = {c["name"] for c in data["clipping"]}
    assert {"Drums", "Master"} <= clip_names
    assert "Bass" not in clip_names
    # every entity reported, Bass present and not clipping
    by_name = {e["name"]: e for e in data["entities"]}
    assert by_name["Bass"]["is_clipping"] is False
    assert by_name["Drums"]["is_clipping"] is True


def test_check_clipping_clean_set(monkeypatch):
    monkeypatch.setattr(server, "_peak_hold_pass", _held_clean)
    out = json.loads(server.check_clipping(ctx=None, window_s=1.0))
    assert out["data"]["any_clipping"] is False
    assert out["data"]["clipping"] == []


def test_check_clipping_custom_ceiling(monkeypatch):
    monkeypatch.setattr(server, "_peak_hold_pass", _held_clean)
    # ceiling -6 dBFS: 0.6 (~-4.4) and 0.7 (~-3.1) both clip
    out = json.loads(server.check_clipping(ctx=None, window_s=1.0, ceiling_db=-6.0))
    assert out["data"]["any_clipping"] is True


# --- analyze_set no-tap clipping path -------------------------------------

def test_analyze_set_no_tap_clipping_fail_and_action(monkeypatch):
    monkeypatch.setattr(server, "get_ableton_connection", lambda: _FakeConn(_RAW))
    monkeypatch.setattr(server, "_peak_hold_pass", _held_drums_clipping)
    server._tap_registry.state.reset()
    server._tap_registry.state._by_conn.clear()
    server._tap_registry.state._identity.clear()
    out = json.loads(server.analyze_set(ctx=None, focus="all", measure=True))
    data = out["data"]
    clips = [f for f in data["findings"] if f["id"] == "health.no_clipping"
             and f["status"] == "fail"]
    by_entity = {f["entity"]: f for f in clips}
    assert "Drums" in by_entity and "Master" in by_entity
    drums = by_entity["Drums"]
    assert drums["track_index"] == 1
    assert drums["action"]["tool"] == "set_mixer_property"
    assert drums["action"]["params"]["property"] == "volume"
    assert drums["action"]["params"]["track_index"] == 1
    # promoted out of deferred
    deferred = {d["id"] for d in data["deferred_rules"]}
    assert "health.no_clipping" not in deferred


def test_analyze_set_no_tap_clean_reports_pass(monkeypatch):
    monkeypatch.setattr(server, "get_ableton_connection", lambda: _FakeConn(_RAW))
    monkeypatch.setattr(server, "_peak_hold_pass", _held_clean)
    server._tap_registry.state.reset()
    server._tap_registry.state._by_conn.clear()
    server._tap_registry.state._identity.clear()
    out = json.loads(server.analyze_set(ctx=None, focus="all", measure=True))
    data = out["data"]
    clips = [f for f in data["findings"] if f["id"] == "health.no_clipping"]
    assert len(clips) == 1 and clips[0]["status"] == "pass"
    deferred = {d["id"] for d in data["deferred_rules"]}
    assert "health.no_clipping" not in deferred


def _register_two_taps():
    reg = server._tap_registry
    reg.state.reset()
    reg.state._by_conn.clear()
    reg.state._identity.clear()
    reg.feed("c0", '{"type":"hello","track":{"uuid":"b","name":"","index":0,"kind":"regular"}}\n')
    reg.feed("c1", '{"type":"hello","track":{"uuid":"d","name":"","index":1,"kind":"regular"}}\n')


def _stream_drums_hot(*a, **k):
    reg = server._tap_registry
    bass = ('{"type":"block","data":{"ms_k_l":0.01,"ms_k_r":0.01,"peak":0.5,'
            '"rms":0.1,"bands":[1,0,0,0,0,0,0,0],"mid":1,"side":0}}\n')
    drums = ('{"type":"block","data":{"ms_k_l":0.2,"ms_k_r":0.2,"peak":1.2,'
             '"rms":0.4,"bands":[1,0,0,0,0,0,0,0],"mid":1,"side":0}}\n')
    for _ in range(40):
        reg.feed("c0", bass)
        reg.feed("c1", drums)
    return True


def test_analyze_set_tap_path_clipping(monkeypatch):
    monkeypatch.setattr(server, "get_ableton_connection", lambda: _FakeConn(_RAW))
    monkeypatch.setattr(server, "_run_measure_playback", _stream_drums_hot)
    _register_two_taps()
    out = json.loads(server.analyze_set(ctx=None, focus="all", measure=True))
    data = out["data"]
    # tap path still builds mix_signal AND derives clipping from the tap peaks
    assert "mix_signal" in data
    clips = {f["entity"]: f for f in data["findings"]
             if f["id"] == "health.no_clipping" and f["status"] == "fail"}
    assert "Drums" in clips and "Bass" not in clips
    assert clips["Drums"]["action"]["params"]["track_index"] == 1


def test_analyze_set_defers_clipping_without_measure(monkeypatch):
    monkeypatch.setattr(server, "get_ableton_connection", lambda: _FakeConn(_RAW))
    out = json.loads(server.analyze_set(ctx=None, focus="all"))
    data = out["data"]
    deferred = {d["id"] for d in data["deferred_rules"]}
    assert "health.no_clipping" in deferred
    assert not any(f["id"] == "health.no_clipping" for f in data["findings"])
