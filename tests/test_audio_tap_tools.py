"""Tool-level tests for the audio-tap tools, faking the tap connection."""
import json

import ableton_mcp_max.server as server


class FakeTap:
    def __init__(self, responses=None, fail=False):
        self.responses = responses or {}
        self.fail = fail
        self.calls = []

    def send(self, command, params=None):
        self.calls.append((command, params))
        if self.fail:
            raise ConnectionError("audio tap not connected")
        return self.responses.get(command, {})


def _install(monkeypatch, tap):
    monkeypatch.setattr(server, "get_audio_tap_connection", lambda: tap)


# NOTE: get_audio_tap_status / read_meter / reset_meter / measure_loudness were
# reimplemented against the in-process tap registry (see tests/test_taps_tools.py).
# get_audio_tap_connection / AudioTapConnection survive only for analyze_set, so
# its FakeTap/_install helpers remain here for any future analyze_set coverage.


def test_reset_meter(monkeypatch):
    out = json.loads(server.reset_meter(None))
    assert out["ok"] is True and out["data"]["reset"] is True


def test_measure_loudness_integrated_from_registry(monkeypatch):
    # measure_loudness resets the master buffer, runs the playback seam, then
    # integrates whatever the seam captured. Stub the seam to "play" by feeding
    # blocks that integrate to -23.0 LUFS (no Live transport touched).
    reg = server._tap_registry
    reg.state.reset()
    reg.feed("m", '{"type":"hello","track":{"uuid":"master","index":-1,"kind":"master"},"sample_rate":48000}\n')

    def fake_play(*_a, **_k):
        for _ in range(50):
            reg.feed("m", json.dumps({"type": "block",
                                      "data": {"ms_k_l": 0.0029377, "ms_k_r": 0.0029377,
                                               "peak": 0.5, "rms": 0.1}}) + "\n")
        return True

    monkeypatch.setattr(server, "_run_measure_playback", fake_play)
    out = json.loads(server.measure_loudness(None, seconds=2))
    assert out["ok"] is True
    assert out["data"]["integrated_lufs"] == -23.0
    assert out["data"]["played"] is True
