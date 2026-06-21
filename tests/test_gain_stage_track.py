# tests/test_gain_stage_track.py
import json
import ableton_mcp_max.server as server


class _FakeTapState:
    def __init__(self, tracks, lufs_sequence):
        self._tracks = tracks
        self._seq = iter(lufs_sequence)
        self._buf = []

    def tracks(self):
        return self._tracks

    def reset(self, uuid=None):
        pass

    def buffer(self, uuid):
        return self._buf


class _FakeConn:
    def __init__(self, vol=0.85):
        self._vol = vol
        self.set_calls = []

    def send_command(self, cmd, params=None):
        if cmd == "get_mixer":
            # Mirror the real Remote Script: volume is a {value,min,max} dict.
            return {"volume": {"value": self._vol, "min": 0.0, "max": 1.0}}
        if cmd == "set_mixer_property":
            self.set_calls.append(params)
            # simulate the volume update
            self._vol = params.get("value", self._vol)
            return {}
        return {}


def _make_buf_for_lufs(lufs):
    """Fake buffer that produces the given integrated LUFS from _integrate_buffer.
    We monkeypatch _integrate_buffer directly so the buf content doesn't matter.
    """
    return [{"ms_k_l": 1e-5, "ms_k_r": 1e-5, "peak": 0.1, "rms": 0.05}] * 50


def test_gain_stage_track_no_tap_error():
    import ableton_mcp_max.server as s

    class _EmptyReg:
        class state:
            @staticmethod
            def tracks(): return []
            @staticmethod
            def reset(uuid=None): pass

    orig_reg = s._tap_registry
    s._tap_registry = _EmptyReg()
    try:
        out = json.loads(s.gain_stage_track(ctx=None, track_index=0))
        assert out["ok"] is False
        assert "No tap" in out["error"]
    finally:
        s._tap_registry = orig_reg


def test_gain_stage_track_converges_in_one_iteration(monkeypatch):
    """Track measures -21 dBLUFS, target -18: delta +3, should converge after 1 iter."""
    TRACK_IDX = 2
    UUID = "abc"

    class _FakeReg:
        class state:
            @staticmethod
            def tracks():
                return [{"uuid": UUID, "index": TRACK_IDX, "kind": "regular",
                         "sample_rate": 48000}]
            @staticmethod
            def reset(uuid=None): pass
            @staticmethod
            def buffer(uuid): return []

    conn = _FakeConn(vol=0.75)  # some starting volume
    monkeypatch.setattr(server, "_tap_registry", _FakeReg())
    monkeypatch.setattr(server, "get_ableton_connection", lambda: conn)

    # First measure: -21 dBLUFS; after correction re-measure: -18.1 (converged)
    call_count = [0]
    def fake_integrate(buf, sr):
        call_count[0] += 1
        if call_count[0] == 1:
            return {"integrated_lufs": -21.0, "momentary_lufs": None,
                    "short_term_lufs": None, "true_peak_dbtp": None,
                    "peak": 0.1, "rms": 0.05, "crest": None,
                    "bands": None, "width": None, "correlation": None,
                    "block_count": 50, "sample_rate": 48000}
        return {"integrated_lufs": -18.1, "momentary_lufs": None,
                "short_term_lufs": None, "true_peak_dbtp": None,
                "peak": 0.1, "rms": 0.05, "crest": None,
                "bands": None, "width": None, "correlation": None,
                "block_count": 50, "sample_rate": 48000}

    monkeypatch.setattr(server, "_integrate_buffer", fake_integrate)
    monkeypatch.setattr(server, "_run_measure_playback", lambda s, r=None: True)

    out = json.loads(server.gain_stage_track(
        ctx=None, track_index=TRACK_IDX, target_db=-18.0, window_s=4.0, max_iterations=3
    ))
    assert out["ok"] is True
    d = out["data"]
    assert d["before_db"] == -21.0
    assert d["converged"] is True
    assert d["iterations"] == 2
    assert len(conn.set_calls) >= 1  # fader was adjusted


def test_gain_stage_track_does_not_converge(monkeypatch):
    """Simulate a track that never converges (oscillates)."""
    TRACK_IDX = 3
    UUID = "xyz"

    class _FakeReg:
        class state:
            @staticmethod
            def tracks():
                return [{"uuid": UUID, "index": TRACK_IDX, "kind": "regular",
                         "sample_rate": 48000}]
            @staticmethod
            def reset(uuid=None): pass
            @staticmethod
            def buffer(uuid): return []

    monkeypatch.setattr(server, "_tap_registry", _FakeReg())
    monkeypatch.setattr(server, "get_ableton_connection", lambda: _FakeConn(0.85))
    monkeypatch.setattr(server, "_run_measure_playback", lambda s, r=None: True)

    call_count = [0]
    def fake_integrate(buf, sr):
        call_count[0] += 1
        return {"integrated_lufs": -21.0, "momentary_lufs": None,
                "short_term_lufs": None, "true_peak_dbtp": None,
                "peak": 0.1, "rms": 0.05, "crest": None,
                "bands": None, "width": None, "correlation": None,
                "block_count": 50, "sample_rate": 48000}

    monkeypatch.setattr(server, "_integrate_buffer", fake_integrate)
    out = json.loads(server.gain_stage_track(
        ctx=None, track_index=TRACK_IDX, target_db=-18.0, window_s=4.0, max_iterations=2
    ))
    assert out["ok"] is True
    d = out["data"]
    assert d["converged"] is False
    assert d["iterations"] == 2
