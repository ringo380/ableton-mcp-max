import pytest
import ableton_mcp_max.server as server


def test_resolve_sample_uri_returns_uri(monkeypatch):
    class _Conn:
        def send_command(self, cmd, params=None):
            assert cmd == "find_sample_uri"
            assert params["name"] == "Kick.wav"
            assert params["category"] == "samples"
            return {"uri": "query:Samples#FileId_1", "matches": 1}
    monkeypatch.setattr(server, "get_ableton_connection", lambda: _Conn())
    assert server._resolve_sample_uri("/x/Kick.wav") == "query:Samples#FileId_1"


def test_resolve_sample_uri_not_found_raises(monkeypatch):
    class _Conn:
        def send_command(self, cmd, params=None):
            return {"uri": None, "matches": 0}
    monkeypatch.setattr(server, "get_ableton_connection", lambda: _Conn())
    with pytest.raises(RuntimeError):
        server._resolve_sample_uri("/x/Ghost.wav")
