import json
import ableton_mcp_max.server as server
from ableton_mcp_max.analysis_utils import live_volume_to_db
from ableton_mcp_max.remediation_utils import db_to_live_volume


class _FakeConn:
    def __init__(self, mixer_vol=0.85):
        self._mixer_vol = mixer_vol
        self.last_set = None

    def send_command(self, cmd, params=None):
        if cmd == "get_mixer":
            return {"volume": self._mixer_vol}
        if cmd == "set_mixer_property":
            self.last_set = params
            return {"ok": True}
        return {}


def test_adjust_track_gain_down():
    conn = _FakeConn(mixer_vol=0.85)  # 0.85 = 0 dB
    monkeypatch_conn = lambda: conn
    import ableton_mcp_max.server as s
    orig = s.get_ableton_connection
    s.get_ableton_connection = monkeypatch_conn
    try:
        out = json.loads(s.adjust_track_gain(ctx=None, track_index=0, delta_db=-3.0))
        assert out["ok"] is True
        d = out["data"]
        assert abs(d["db_before"] - 0.0) < 0.1
        assert abs(d["db_after"] - (-3.0)) < 0.2
        assert d["volume_after"] < d["volume_before"]
        # verify set_mixer_property was called with the new volume
        assert conn.last_set is not None
        assert abs(conn.last_set["value"] - db_to_live_volume(-3.0)) < 0.001
    finally:
        s.get_ableton_connection = orig


def test_adjust_track_gain_up():
    conn = _FakeConn(mixer_vol=0.70)  # below unity
    import ableton_mcp_max.server as s
    orig = s.get_ableton_connection
    s.get_ableton_connection = lambda: conn
    try:
        out = json.loads(s.adjust_track_gain(ctx=None, track_index=1, delta_db=3.0))
        d = out["data"]
        assert d["volume_after"] > d["volume_before"]
    finally:
        s.get_ableton_connection = orig


def test_adjust_track_gain_clamps_at_floor():
    conn = _FakeConn(mixer_vol=0.1)
    import ableton_mcp_max.server as s
    orig = s.get_ableton_connection
    s.get_ableton_connection = lambda: conn
    try:
        out = json.loads(s.adjust_track_gain(ctx=None, track_index=0, delta_db=-200.0))
        d = out["data"]
        assert d["volume_after"] == 0.0
        assert d["db_after"] == -70.0
    finally:
        s.get_ableton_connection = orig


def test_adjust_track_gain_no_volume_returns_error():
    class NoVolConn:
        def send_command(self, cmd, params=None):
            return {}  # no "volume" key
    import ableton_mcp_max.server as s
    orig = s.get_ableton_connection
    s.get_ableton_connection = lambda: NoVolConn()
    try:
        out = json.loads(s.adjust_track_gain(ctx=None, track_index=0, delta_db=-3.0))
        assert out["ok"] is False
    finally:
        s.get_ableton_connection = orig
