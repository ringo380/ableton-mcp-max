import json
from ableton_mcp_max import server


class _FakeConn:
    def __init__(self):
        self.sent = []

    def send_command(self, cmd, params=None):
        self.sent.append((cmd, params or {}))
        return {"view": (params or {}).get("view"), "focused": True}


def test_focus_view_sends_the_command(monkeypatch):
    conn = _FakeConn()
    monkeypatch.setattr(server, "get_ableton_connection", lambda: conn)
    out = json.loads(server.focus_view(None, "Arranger"))
    assert out["ok"] is True
    assert conn.sent == [("focus_view", {"view": "Arranger"})]


def test_focus_view_rejects_unknown_view(monkeypatch):
    conn = _FakeConn()
    monkeypatch.setattr(server, "get_ableton_connection", lambda: conn)
    out = json.loads(server.focus_view(None, "Mixer"))
    assert out["ok"] is False
    assert conn.sent == []      # validated before the socket call
