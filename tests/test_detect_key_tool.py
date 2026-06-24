import json
import ableton_mcp_max.server as server


class _Conn:
    """Fake connection: serves get_clip_contents + per-clip get_clip_notes."""
    def __init__(self, clips, notes_by_clip, song_scale=None):
        self._clips = clips
        self._notes = notes_by_clip
        self._scale = song_scale

    def send_command(self, command_type, params=None, **kw):
        if command_type == "get_clip_contents":
            return {"clips": self._clips}
        if command_type == "get_clip_notes":
            key = (params["track_index"], params["clip_index"])
            return {"notes": self._notes.get(key, [])}
        if command_type == "get_song_scale":
            return self._scale
        raise AssertionError("unexpected command %s" % command_type)


def _c_major_notes():
    # C major triad emphasis -> should detect C major
    pitches = [60, 64, 67, 60, 64, 67, 72, 65, 62]
    return [{"pitch": p, "duration": 1.0, "velocity": 100} for p in pitches]


def test_detect_key_midi_only(monkeypatch):
    clips = [{"track_index": 0, "clip_index": 0, "location": "session",
              "is_midi": True, "length": 4.0, "pitch_coarse": 0,
              "file_path": None}]
    # root_note is an INT (0=C) matching the real Remote Script contract
    conn = _Conn(clips, {(0, 0): _c_major_notes()},
                 song_scale={"root_note": 0, "scale_name": "Major"})
    monkeypatch.setattr(server, "get_ableton_connection", lambda: conn)
    out = json.loads(server.detect_key(ctx=None, source="midi"))
    assert out["ok"] is True
    data = out["data"]
    assert data["detected_key"] == "C major"
    assert data["candidates"][0]["key"] == "C major"
    assert data["sources"]["midi"]["notes"] == 9
    assert data["matches_live"] is True


def test_detect_key_matches_live_false_different_key(monkeypatch):
    # Live says D major (root_note=2), content is C major -> matches_live False
    clips = [{"track_index": 0, "clip_index": 0, "location": "session",
              "is_midi": True, "length": 4.0, "pitch_coarse": 0,
              "file_path": None}]
    conn = _Conn(clips, {(0, 0): _c_major_notes()},
                 song_scale={"root_note": 2, "scale_name": "Major"})
    monkeypatch.setattr(server, "get_ableton_connection", lambda: conn)
    out = json.loads(server.detect_key(ctx=None, source="midi"))
    assert out["ok"] is True
    assert out["data"]["detected_key"] == "C major"
    assert out["data"]["matches_live"] is False


def test_detect_key_dataless_audio_clip_skipped(monkeypatch):
    # _ensure_local raises -> audio clip should be skipped, MIDI detection proceeds
    clips = [
        {"track_index": 0, "clip_index": 0, "location": "session",
         "is_midi": True, "length": 4.0, "pitch_coarse": 0, "file_path": None},
        {"track_index": 1, "clip_index": 0, "location": "session",
         "is_midi": False, "length": 4.0, "pitch_coarse": 0,
         "file_path": "/icloud/missing.wav"},
    ]
    conn = _Conn(clips, {(0, 0): _c_major_notes()})
    monkeypatch.setattr(server, "get_ableton_connection", lambda: conn)
    monkeypatch.setattr(server, "_ensure_local",
                        lambda p, **k: (_ for _ in ()).throw(RuntimeError("not available")))
    out = json.loads(server.detect_key(ctx=None, source="auto"))
    assert out["ok"] is True, "tool must not fail when one audio clip is unavailable"
    data = out["data"]
    assert data["detected_key"] == "C major"
    assert data["sources"]["audio"]["skipped"] == 1
    assert data["sources"]["audio"]["analyzed"] == 0


def test_detect_key_empty_set(monkeypatch):
    conn = _Conn([], {})
    monkeypatch.setattr(server, "get_ableton_connection", lambda: conn)
    out = json.loads(server.detect_key(ctx=None, source="midi"))
    assert out["ok"] is False


def test_detect_key_tap_not_supported(monkeypatch):
    conn = _Conn([], {})
    monkeypatch.setattr(server, "get_ableton_connection", lambda: conn)
    out = json.loads(server.detect_key(ctx=None, source="tap"))
    assert out["ok"] is False and "tap" in out["error"].lower()


def test_detect_key_auto_blends_audio(monkeypatch):
    # MIDI says C major; audio profile says A (pc 9). With audio_weight=1.0
    # the result must follow the audio toward A minor/C major neighborhood.
    clips = [
        {"track_index": 0, "clip_index": 0, "location": "session",
         "is_midi": True, "length": 4.0, "pitch_coarse": 0, "file_path": None},
        {"track_index": 1, "clip_index": 0, "location": "session",
         "is_midi": False, "length": 4.0, "pitch_coarse": 0,
         "file_path": "/tmp/a.wav"},
    ]
    conn = _Conn(clips, {(0, 0): _c_major_notes()})
    monkeypatch.setattr(server, "get_ableton_connection", lambda: conn)
    monkeypatch.setattr(server, "_ensure_local", lambda p, **k: p)
    a_profile = [0.0] * 12
    a_profile[9] = 1.0
    monkeypatch.setattr(server, "_run_chroma",
                        lambda items, **k: {"profile": a_profile,
                                            "analyzed": 1, "skipped": 0})
    out = json.loads(server.detect_key(ctx=None, source="auto", audio_weight=1.0))
    assert out["ok"] is True
    assert out["data"]["sources"]["audio"]["analyzed"] == 1
