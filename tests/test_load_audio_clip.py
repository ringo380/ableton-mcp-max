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
            if cmd == "get_track_info":
                return {"clip_slots": [{"has_clip": True}]}
            return {}

    monkeypatch.setattr(server, "get_ableton_connection", lambda: _Conn())

    out = json.loads(server.load_audio_clip(
        ctx=None, track_index=3, clip_index=0, sample_path=str(sample)))
    assert out["ok"] is True
    assert calls["ensure"], "expected _ensure_local before load"
    cmds = [c for c, _ in calls["sent"]]
    assert "set_highlighted_clip_slot" in cmds
    assert "load_browser_item" in cmds
    # Session view comes to the front before the load (issue #63)
    assert cmds.index("focus_view") < cmds.index("load_browser_item")
    assert dict(calls["sent"])["focus_view"] == {"view": "Session"}
    # the resolved URI was passed to load_browser_item
    lbi = next(p for c, p in calls["sent"] if c == "load_browser_item")
    assert lbi["item_uri"] == "query:Samples#FileId_9"
    d = out["data"]
    assert d["track_index"] == 3
    assert d["clip_index"] == 0
    assert d["kind"] == "loop"   # 2-beat sample at 120 bpm refines to loop
    assert d["loaded"] is True


def test_load_audio_clip_errors_when_no_clip_lands(tmp_path, monkeypatch):
    # issue #63: load_browser_item said loaded, the slot stayed empty
    sample = tmp_path / "0 Lead Vocals.wav"
    sample.write_bytes(b"RIFF")
    monkeypatch.setattr(server, "_ensure_local", lambda p, timeout=30: str(sample))
    monkeypatch.setattr(server, "_read_audio_meta", lambda p: (10, 48000, 48000))
    monkeypatch.setattr(server, "_resolve_sample_uri",
                        lambda p, category="samples": "query:Samples#FileId_9")
    monkeypatch.setattr(server, "_wait_for_clip", lambda *a, **k: False)

    class _Conn:
        def send_command(self, cmd, params=None):
            return {"loaded": True} if cmd == "load_browser_item" else {}
    monkeypatch.setattr(server, "get_ableton_connection", lambda: _Conn())

    out = json.loads(server.load_audio_clip(
        ctx=None, track_index=0, clip_index=0, sample_path=str(sample)))
    assert out["ok"] is False
    assert "no clip appeared" in out["error"]


def test_wait_for_clip_polls_until_the_slot_fills():
    seen = {"n": 0}

    class _Conn:
        def send_command(self, cmd, params=None):
            seen["n"] += 1
            return {"clip_slots": [{"has_clip": seen["n"] >= 3}]}
    assert server._wait_for_clip(_Conn(), 0, 0, timeout=5, sleep=lambda s: None)

    class _Empty:
        def send_command(self, cmd, params=None):
            return {"clip_slots": [{"has_clip": False}]}
    assert not server._wait_for_clip(_Empty(), 0, 0, timeout=2, sleep=lambda s: None)


def test_project_file_resolves_in_the_project_first(tmp_path, monkeypatch):
    proj = tmp_path / "Song Project"
    (proj / "Ableton Project Info").mkdir(parents=True)
    stems = proj / "Samples" / "Stems"
    stems.mkdir(parents=True)
    inside = stems / "1 Drums.wav"
    outside = tmp_path / "1 Drums.wav"
    assert server._in_live_project(str(inside))
    assert not server._in_live_project(str(outside))

    asked = []

    class _Conn:
        def send_command(self, cmd, params=None):
            asked.append(params)
            return {"uri": "u:%s" % params["category"]}
    monkeypatch.setattr(server, "get_ableton_connection", lambda: _Conn())
    assert server._resolve_sample_uri(str(inside)) == "u:current_project"
    assert asked[-1]["parents"][-2:] == ["Samples", "Stems"]
    assert server._resolve_sample_uri(str(outside)) == "u:samples"


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
