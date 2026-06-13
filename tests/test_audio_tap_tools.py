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


def test_status_connected(monkeypatch):
    tap = FakeTap({"ping": {"device": "mcp-audio-tap", "sample_rate": 48000, "channels": 2}})
    _install(monkeypatch, tap)
    out = json.loads(server.get_audio_tap_status(None))
    assert out["ok"] is True
    assert out["data"]["connected"] is True
    assert out["data"]["sample_rate"] == 48000


def test_status_not_connected(monkeypatch):
    _install(monkeypatch, FakeTap(fail=True))
    out = json.loads(server.get_audio_tap_status(None))
    assert out["ok"] is True
    assert out["data"]["connected"] is False
    assert "Master" in out["data"]["hint"]


def test_read_meter_computes_metrics(monkeypatch):
    blocks = [{"ms_k_l": 0.0029377, "ms_k_r": 0.0029377, "tp": 0.0} for _ in range(50)]
    tap = FakeTap({"read": {"sample_rate": 48000, "since_reset_s": 5.0,
                            "block_count": 50, "blocks": blocks, "peak": 0.5, "rms": 0.1}})
    _install(monkeypatch, tap)
    out = json.loads(server.read_meter(None))
    assert out["ok"] is True
    assert out["data"]["integrated_lufs"] == -23.0


def test_read_meter_not_connected(monkeypatch):
    _install(monkeypatch, FakeTap(fail=True))
    out = json.loads(server.read_meter(None))
    assert out["ok"] is False
    assert "not connected" in out["error"]


def test_reset_meter(monkeypatch):
    tap = FakeTap({"reset": {"reset": True}})
    _install(monkeypatch, tap)
    out = json.loads(server.reset_meter(None))
    assert out["ok"] is True and out["data"]["reset"] is True


def test_measure_loudness_orchestrates(monkeypatch):
    blocks = [{"ms_k_l": 0.0029377, "ms_k_r": 0.0029377, "tp": 0.5} for _ in range(50)]
    tap = FakeTap({"reset": {"reset": True},
                   "read": {"sample_rate": 48000, "since_reset_s": 2.0,
                            "block_count": 50, "blocks": blocks, "peak": 0.5, "rms": 0.1}})
    _install(monkeypatch, tap)

    class FakeAbleton:
        def __init__(self):
            self.t = 0.0
            self.commands = []

        def send_command(self, ctype, params=None):
            self.commands.append(ctype)
            if ctype == "get_transport":
                self.t += 4.0
                return {"current_song_time": self.t}
            return {}

    monkeypatch.setattr(server, "get_ableton_connection", FakeAbleton)
    monkeypatch.setattr(server.time, "sleep", lambda _s: None)
    out = json.loads(server.measure_loudness(None, seconds=2))
    assert out["ok"] is True
    assert out["data"]["integrated_lufs"] == -23.0
    assert out["data"]["played"] is True
    assert tap.calls[0][0] == "reset"
