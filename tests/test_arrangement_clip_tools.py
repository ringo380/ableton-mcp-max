import json

import ableton_mcp_max.server as server


class _Conn:
    def __init__(self, reply):
        self.calls = []
        self.reply = reply

    def send_command(self, cmd, params=None):
        self.calls.append((cmd, params))
        return self.reply


def test_set_clip_property_passes_arrangement_location(monkeypatch):
    conn = _Conn({"property": "start_marker", "value": 0.1875})
    monkeypatch.setattr(server, "get_ableton_connection", lambda: conn)
    out = json.loads(server.set_clip_property(None, 11, 0, "start_marker", 0.1875,
                                              clip_location="arrangement"))
    assert out["ok"]
    cmd, params = conn.calls[0]
    assert cmd == "set_clip_property"
    assert params["clip_location"] == "arrangement"
    assert params["property"] == "start_marker"


def test_set_clip_property_defaults_to_session(monkeypatch):
    conn = _Conn({})
    monkeypatch.setattr(server, "get_ableton_connection", lambda: conn)
    server.set_clip_property(None, 0, 0, "looping", True)
    assert conn.calls[0][1]["clip_location"] == "session"


def test_set_clip_property_rejects_bad_location(monkeypatch):
    conn = _Conn({})
    monkeypatch.setattr(server, "get_ableton_connection", lambda: conn)
    out = json.loads(server.set_clip_property(None, 0, 0, "looping", True,
                                              clip_location="nowhere"))
    assert not out["ok"]
    assert conn.calls == []


def test_move_arrangement_clip_sends_command(monkeypatch):
    conn = _Conn({"removed": 1, "clip": {"index": 0, "start_time": 0.0}})
    monkeypatch.setattr(server, "get_ableton_connection", lambda: conn)
    out = json.loads(server.move_arrangement_clip(None, 5, 0, 0.0))
    assert out["ok"]
    assert conn.calls == [("move_arrangement_clip",
                           {"track_index": 5, "clip_index": 0,
                            "destination_time": 0.0})]


def test_move_arrangement_clip_is_a_mutation():
    assert "move_arrangement_clip" in server.MUTATING_COMMANDS
