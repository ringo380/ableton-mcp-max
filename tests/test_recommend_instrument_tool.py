import json
import ableton_mcp_max.server as server
import ableton_mcp_max.instrument_select as isel


class _Conn:
    """Fake connection: get_session_info + per-track get_track_info."""
    def __init__(self, tracks):
        self._tracks = tracks  # list of device-lists

    def send_command(self, command_type, params=None, **kw):
        if command_type == "get_session_info":
            return {"track_count": len(self._tracks)}
        if command_type == "get_track_info":
            i = params["track_index"]
            return {"index": i, "devices": self._tracks[i]}
        raise AssertionError("unexpected command %s" % command_type)


def test_recommend_instrument_connected_reese(monkeypatch):
    conn = _Conn([[{"name": "Wavetable", "class_name": "InstrumentVector"}]])
    monkeypatch.setattr(server, "get_ableton_connection", lambda: conn)
    monkeypatch.setattr(isel, "serum_installed", lambda candidates=None: True)
    out = json.loads(server.recommend_instrument(ctx=None,
                                                 intent="gritty reese bass dnb"))
    assert out["ok"] is True
    d = out["data"]
    assert d["top"]["engine"] == "serum"
    assert d["environment"]["live_connected"] is True
    assert d["environment"]["serum_instances"] == 0
    assert "recommend_asset" in d["next"]


def test_recommend_instrument_serum_absent(monkeypatch):
    conn = _Conn([[]])
    monkeypatch.setattr(server, "get_ableton_connection", lambda: conn)
    monkeypatch.setattr(isel, "serum_installed", lambda candidates=None: False)
    out = json.loads(server.recommend_instrument(ctx=None,
                                                 intent="gritty reese bass dnb"))
    assert out["ok"] is True
    assert all(r["engine"] != "serum" for r in out["data"]["ranked"])
    assert out["data"]["environment"]["serum_installed"] is False


def test_recommend_instrument_disconnected(monkeypatch):
    def _boom():
        raise RuntimeError("Could not connect to Ableton")
    monkeypatch.setattr(server, "get_ableton_connection", _boom)
    monkeypatch.setattr(isel, "serum_installed", lambda candidates=None: True)
    out = json.loads(server.recommend_instrument(ctx=None, intent="a pad"))
    assert out["ok"] is True
    assert out["data"]["environment"]["live_connected"] is False
    assert out["data"]["top"] is not None  # still ranks intent-only
