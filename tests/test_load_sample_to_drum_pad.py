import json
import ableton_mcp_max.server as server


def test_load_sample_to_drum_pad_happy(tmp_path, monkeypatch):
    sample = tmp_path / "Kick.wav"
    sample.write_bytes(b"RIFF")
    monkeypatch.setattr(server, "_ensure_local", lambda p, timeout=30: str(sample))
    monkeypatch.setattr(server, "_resolve_sample_uri",
                        lambda p, category="samples": "query:Samples#FileId_2")

    calls = []

    class _Conn:
        def send_command(self, cmd, params=None):
            calls.append((cmd, params))
            if cmd == "select_drum_pad":
                return {"selected": True}
            if cmd == "load_browser_item":
                return {"loaded": True}
            return {}

    monkeypatch.setattr(server, "get_ableton_connection", lambda: _Conn())

    out = json.loads(server.load_sample_to_drum_pad(
        ctx=None, track_index=2, pad_note=36, sample_path=str(sample)))
    assert out["ok"] is True
    cmds = [c for c, _ in calls]
    assert "select_drum_pad" in cmds
    assert "load_browser_item" in cmds
    sp = next(p for c, p in calls if c == "select_drum_pad")
    assert sp["pad_note"] == 36
    d = out["data"]
    assert d["track_index"] == 2
    assert d["pad_note"] == 36
    assert d["uri"] == "query:Samples#FileId_2"
    assert d["loaded"] is True


def test_load_sample_to_drum_pad_no_rack_error(tmp_path, monkeypatch):
    sample = tmp_path / "Kick.wav"
    sample.write_bytes(b"RIFF")
    monkeypatch.setattr(server, "_ensure_local", lambda p, timeout=30: str(sample))
    monkeypatch.setattr(server, "_resolve_sample_uri",
                        lambda p, category="samples": "query:Samples#FileId_2")

    class _Conn:
        def send_command(self, cmd, params=None):
            if cmd == "select_drum_pad":
                return {"selected": False, "error": "no drum rack"}
            return {}

    monkeypatch.setattr(server, "get_ableton_connection", lambda: _Conn())
    out = json.loads(server.load_sample_to_drum_pad(
        ctx=None, track_index=2, pad_note=36, sample_path=str(sample)))
    assert out["ok"] is False
    assert "drum rack" in out["error"].lower()


def test_load_sample_to_drum_pad_placeholder_error(monkeypatch):
    def boom(p, timeout=30):
        raise RuntimeError("undownloaded iCloud placeholder after 30s")
    monkeypatch.setattr(server, "_ensure_local", boom)
    out = json.loads(server.load_sample_to_drum_pad(
        ctx=None, track_index=0, pad_note=36, sample_path="/x/Ghost.wav"))
    assert out["ok"] is False
    assert "placeholder" in out["error"].lower()
