"""place_stems_to_arrangement / _lay_stem_on_track against a fake Live."""
import json

from ableton_mcp_max import server, stem_utils


def test_pack_order_and_track_names():
    names = ["10 Woodwinds.wav", "2 Bass.wav", "0 Lead Vocals.wav", "notes.txt",
             "1 Drums.WAV", "Extra.aif", "Demo.mp3"]
    assert stem_utils.order_stem_files(names) == [
        "0 Lead Vocals.wav", "1 Drums.WAV", "2 Bass.wav", "10 Woodwinds.wav",
        "Extra.aif"]
    assert stem_utils.stem_track_name("0 Lead Vocals.wav") == "Lead Vocals"
    assert stem_utils.stem_track_name("10_Woodwinds.wav") == "Woodwinds"
    assert stem_utils.stem_track_name("Extra.aif") == "Extra"
    assert stem_utils.stem_track_name("Waiting for Nothing (Bass).wav") == "Bass"
    assert stem_utils.stem_track_name("Inspector Horse (FX).mid") == "FX"


class FakeLive:
    def __init__(self, tracks=0, placed=None):
        self.sent = []
        self.tracks = tracks
        self.placed = placed or (lambda p: {
            "warping": False, "start_marker": p["start_offset"], "end_marker": 215.0})

    def send_command(self, cmd, params=None):
        self.sent.append((cmd, params))
        if cmd == "get_session_info":
            return {"track_count": self.tracks}
        if cmd == "load_browser_item":
            return {"loaded": True}
        if cmd == "duplicate_clip_to_arrangement":
            return {"placed": True, "new_clip": self.placed(params)}
        return {}


def _pack(tmp_path):
    for n in ("1 Drums.wav", "0 Lead Vocals.wav"):
        (tmp_path / n).write_bytes(b"RIFF")
    return tmp_path


def test_places_each_stem_with_one_shared_offset(tmp_path, monkeypatch):
    folder = _pack(tmp_path)
    monkeypatch.setattr(server, "_resolve_sample_uri", lambda p, category="samples": "u:" + p)
    monkeypatch.setattr(server, "_read_audio_meta", lambda p: (1, 215 * 48000, 48000))
    live = FakeLive(tracks=2)
    out = server._place_stems_impl(live, str(folder), start_offset=0.154, tempo=90,
                                   wait_clip=lambda *a: True)
    assert out["failed"] == []
    assert [(s["name"], s["track_index"]) for s in out["stems"]] == [
        ("Lead Vocals", 2), ("Drums", 3)]
    dups = [p for c, p in live.sent if c == "duplicate_clip_to_arrangement"]
    assert [d["start_offset"] for d in dups] == [0.154, 0.154]
    assert all(d["warp_off"] and d["clip_seconds"] == 215.0 for d in dups)
    cmds = [c for c, _ in live.sent]
    assert cmds[0] == "set_tempo"
    assert cmds.index("focus_view") < cmds.index("load_browser_item")
    assert live.sent[-1] == ("focus_view", {"view": "Arranger"})


def test_a_stem_that_never_lands_is_reported(tmp_path, monkeypatch):
    folder = _pack(tmp_path)
    monkeypatch.setattr(server, "_resolve_sample_uri", lambda p, category="samples": "u")
    monkeypatch.setattr(server, "_read_audio_meta", lambda p: (1, 48000, 48000))
    live = FakeLive()
    out = server._place_stems_impl(live, str(folder), wait_clip=lambda *a: False)
    assert out["failed"] == ["Lead Vocals", "Drums"]
    assert "no clip landed" in out["stems"][0]["error"]
    assert not any(c == "duplicate_clip_to_arrangement" for c, _ in live.sent)


def test_a_stem_left_warped_or_offset_is_reported(tmp_path, monkeypatch):
    folder = _pack(tmp_path)
    monkeypatch.setattr(server, "_resolve_sample_uri", lambda p, category="samples": "u")
    monkeypatch.setattr(server, "_read_audio_meta", lambda p: (1, 48000, 48000))
    live = FakeLive(placed=lambda p: {"warping": True, "start_marker": 3.37,
                                      "normalize_errors": ["markers: boom"]})
    out = server._place_stems_impl(live, str(folder), start_offset=0.154,
                                   wait_clip=lambda *a: True)
    err = out["stems"][0]["error"]
    assert "markers: boom" in err and "warp is still on" in err and "3.370" in err
    assert out["failed"] == ["Lead Vocals", "Drums"]


def test_tool_fails_loudly_on_partial_success(tmp_path, monkeypatch):
    folder = _pack(tmp_path)
    monkeypatch.setattr(server, "_place_stems_impl", lambda *a, **k: {
        "stems": [], "failed": ["Drums"]})
    monkeypatch.setattr(server, "get_ableton_connection", lambda: None)
    out = json.loads(server.place_stems_to_arrangement(None, str(folder)))
    assert out["ok"] is False and "Drums" in out["error"] and "data" in out


def test_tool_rejects_a_missing_folder(tmp_path):
    out = json.loads(server.place_stems_to_arrangement(None, str(tmp_path / "nope")))
    assert out["ok"] is False and "not found" in out["error"]
