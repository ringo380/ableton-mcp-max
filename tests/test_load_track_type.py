"""Server-side tests: load_instrument_or_effect / load_preset forward track_type
into the load_browser_item command payload. Connection mocked - no Live."""
import json

from ableton_mcp_max import server


class _RecordingConn:
    def __init__(self):
        self.calls = []

    def send_command(self, cmd, params=None):
        self.calls.append((cmd, params or {}))
        if cmd == "get_browser_presets":
            return {"presets": [{"name": "Dark.adg", "relative_path": "Dark.adg",
                                 "uri": "query:UserLibrary#Dark.adg"}]}
        if cmd == "load_browser_item":
            return {"loaded": True, "item_name": "X", "track_name": "T"}
        return {"ok": True}


def test_load_instrument_defaults_to_regular(monkeypatch):
    conn = _RecordingConn()
    monkeypatch.setattr(server, "get_ableton_connection", lambda: conn)
    server.load_instrument_or_effect(None, 0, "query:AudioFx#EQ%20Eight")
    call = next(c for c in conn.calls if c[0] == "load_browser_item")
    assert call[1]["track_type"] == "regular"


def test_load_instrument_forwards_master(monkeypatch):
    conn = _RecordingConn()
    monkeypatch.setattr(server, "get_ableton_connection", lambda: conn)
    server.load_instrument_or_effect(None, 0, "query:AudioFx#EQ%20Eight",
                                     track_type="master")
    call = next(c for c in conn.calls if c[0] == "load_browser_item")
    assert call[1]["track_type"] == "master"


def test_load_preset_forwards_return(monkeypatch):
    conn = _RecordingConn()
    monkeypatch.setattr(server, "get_ableton_connection", lambda: conn)
    out = json.loads(
        server.load_preset(None, 0, "audio_effects", name="Dark.adg",
                           track_type="return")
    )
    assert out["ok"] is True
    call = next(c for c in conn.calls if c[0] == "load_browser_item")
    assert call[1]["track_type"] == "return"
