import json
import ableton_mcp_max.server as server


def test_load_audio_clip_resolves_and_loads(tmp_path, monkeypatch):
    sample = tmp_path / "Loop 120 bpm.wav"
    sample.write_bytes(b"RIFF")

    calls = {"ensure": [], "sent": []}
    monkeypatch.setattr(server, "_ensure_local",
                        lambda p, timeout=30: (calls["ensure"].append(p) or str(sample)))
    monkeypatch.setattr(server, "_read_audio_meta", lambda p: (1000, 2 * 48000, 48000))
    monkeypatch.setattr(server, "_resolve_sample_uri",
                        lambda p, category="samples": "query:Samples#FileId_9")

    class _Conn:
        def send_command(self, cmd, params=None):
            calls["sent"].append((cmd, params))
            if cmd == "get_transport":
                return {"tempo": 120.0}
            if cmd == "load_browser_item":
                return {"loaded": True}
            return {}

    monkeypatch.setattr(server, "get_ableton_connection", lambda: _Conn())

    out = json.loads(server.load_audio_clip(
        ctx=None, track_index=3, clip_index=0, sample_path=str(sample)))
    assert out["ok"] is True
    assert calls["ensure"], "expected _ensure_local before load"
    cmds = [c for c, _ in calls["sent"]]
    assert "set_highlighted_clip_slot" in cmds
    assert "load_browser_item" in cmds
    # the resolved URI was passed to load_browser_item
    lbi = next(p for c, p in calls["sent"] if c == "load_browser_item")
    assert lbi["item_uri"] == "query:Samples#FileId_9"
    d = out["data"]
    assert d["track_index"] == 3
    assert d["clip_index"] == 0
    assert d["kind"] == "loop"   # 2-beat sample at 120 bpm refines to loop
    assert d["loaded"] is True


def test_load_audio_clip_placeholder_error(monkeypatch):
    def boom(p, timeout=30):
        raise RuntimeError("undownloaded iCloud placeholder after 30s")
    monkeypatch.setattr(server, "_ensure_local", boom)
    out = json.loads(server.load_audio_clip(
        ctx=None, track_index=0, clip_index=0, sample_path="/x/Ghost.wav"))
    assert out["ok"] is False
    assert "placeholder" in out["error"].lower()


def test_load_audio_clip_unresolvable_uri_error(tmp_path, monkeypatch):
    sample = tmp_path / "Mystery.wav"
    sample.write_bytes(b"RIFF")
    monkeypatch.setattr(server, "_ensure_local", lambda p, timeout=30: str(sample))
    monkeypatch.setattr(server, "_read_audio_meta", lambda p: (10, 48000, 48000))
    def boom(p, category="samples"):
        raise RuntimeError("Could not resolve 'Mystery.wav' to a browser item.")
    monkeypatch.setattr(server, "_resolve_sample_uri", boom)
    out = json.loads(server.load_audio_clip(
        ctx=None, track_index=0, clip_index=0, sample_path=str(sample)))
    assert out["ok"] is False
    assert "resolve" in out["error"].lower()
