"""Tests for running-Live version detection + adaptive factory-asset selection
(_app_core), so preset/table reads match the Live version the user is actually
running when several versions are installed. Live seams are stubbed."""
from ableton_mcp_max import server


def test_app_core_uses_running_version_bundle(monkeypatch):
    monkeypatch.setattr(server, "_running_live_major", lambda: 12)
    monkeypatch.setattr(server, "_core_for_major",
                        lambda m: "/Applications/Ableton Live %d Suite.app/Core" % m)
    assert server._app_core() == "/Applications/Ableton Live 12 Suite.app/Core"


def test_app_core_falls_back_to_glob_when_version_unknown(monkeypatch):
    monkeypatch.setattr(server, "_running_live_major", lambda: None)
    assert server._app_core() == server._APP_CORE


def test_app_core_falls_back_when_bundle_missing(monkeypatch):
    # Version resolves but no matching bundle on disk -> multi-version glob.
    monkeypatch.setattr(server, "_running_live_major", lambda: 13)
    monkeypatch.setattr(server, "_core_for_major", lambda m: None)
    assert server._app_core() == server._APP_CORE


def test_running_live_major_parses_remote_reply(monkeypatch):
    class _Conn:
        def send_command(self, cmd, params=None):
            assert cmd == "get_application_version"
            return {"major": 11, "minor": 3, "bugfix": 43}
    monkeypatch.setattr(server, "get_ableton_connection", lambda: _Conn())
    assert server._running_live_major() == 11


def test_running_live_major_none_on_error(monkeypatch):
    def boom():
        raise RuntimeError("not connected")
    monkeypatch.setattr(server, "get_ableton_connection", boom)
    assert server._running_live_major() is None
