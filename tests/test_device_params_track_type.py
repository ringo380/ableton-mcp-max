"""Server-side tests: get_device_parameters / set_device_parameter forward
track_type into the command payload (incl. the name-resolution pre-fetch in
set_device_parameter). Connection is mocked - no Live needed."""
import json

from ableton_mcp_max import server


class _RecordingConn:
    """Records every send_command call. Returns a one-parameter device list
    for get_device_parameters so name->index resolution works."""

    def __init__(self):
        self.calls = []

    def send_command(self, cmd, params=None):
        self.calls.append((cmd, params or {}))
        if cmd == "get_device_parameters":
            return {
                "device_name": "Reverb",
                "parameters": [
                    {"index": 0, "name": "Device On", "value": 1.0,
                     "min": 0.0, "max": 1.0, "is_quantized": True},
                    {"index": 1, "name": "Decay Time", "value": 0.5,
                     "min": 0.0, "max": 1.0, "is_quantized": False},
                ],
            }
        return {"ok": True}


def test_get_device_parameters_defaults_to_regular(monkeypatch):
    conn = _RecordingConn()
    monkeypatch.setattr(server, "get_ableton_connection", lambda: conn)
    out = json.loads(server.get_device_parameters(None, 0, 0))
    assert out["ok"] is True
    cmd, params = conn.calls[0]
    assert cmd == "get_device_parameters"
    assert params["track_type"] == "regular"


def test_get_device_parameters_forwards_master(monkeypatch):
    conn = _RecordingConn()
    monkeypatch.setattr(server, "get_ableton_connection", lambda: conn)
    server.get_device_parameters(None, 0, 0, track_type="master")
    assert conn.calls[0][1]["track_type"] == "master"


def test_set_device_parameter_forwards_track_type_to_both_calls(monkeypatch):
    conn = _RecordingConn()
    monkeypatch.setattr(server, "get_ableton_connection", lambda: conn)
    out = json.loads(
        server.set_device_parameter(None, 0, 0, "Decay Time", 0.8,
                                    track_type="return")
    )
    assert out["ok"] is True
    prefetch = next(c for c in conn.calls if c[0] == "get_device_parameters")
    setcall = next(c for c in conn.calls if c[0] == "set_device_parameter")
    assert prefetch[1]["track_type"] == "return"
    assert setcall[1]["track_type"] == "return"
    assert setcall[1]["parameter_index"] == 1
