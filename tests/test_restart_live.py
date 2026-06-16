"""Tests for the graceful Live quit/restart orchestration (_restart_live_impl).
All OS seams (osascript, lsof/ps, open, port poll) are stubbed so the logic is
exercised without touching real apps. sleep is a no-op."""
import json
import pytest

from ableton_mcp_max import server

NOSLEEP = lambda *a, **k: None


def _stub_os(monkeypatch, *, app="/Applications/Ableton Live 12 Suite.app",
             pid=4242, alive_sequence=None, port_up=True):
    """Wire up the OS seams. alive_sequence: list of bools _pid_alive returns in
    order (then sticks on the last). osa calls are recorded."""
    calls = {"async": [], "osa": [], "opened": []}
    monkeypatch.setattr(server, "_live_app_and_pid", lambda port=9877: (app, pid))
    monkeypatch.setattr(server, "_osa_async", lambda s: calls["async"].append(s))
    monkeypatch.setattr(server, "_osa", lambda s: calls["osa"].append(s))
    monkeypatch.setattr(server, "_open_app", lambda a: calls["opened"].append(a))
    monkeypatch.setattr(server, "_port_listening", lambda port=9877: port_up)
    seq = list(alive_sequence or [])
    def _alive(p):
        if not seq:
            return False
        return seq.pop(0) if len(seq) > 1 else seq[0]
    monkeypatch.setattr(server, "_pid_alive", _alive)
    return calls


def test_clean_quit_and_relaunch(monkeypatch):
    # Clean set: dead right after the quit, port comes back up.
    calls = _stub_os(monkeypatch, alive_sequence=[False], port_up=True)
    data = server._restart_live_impl(sleep=NOSLEEP)
    assert data["was_dirty"] is False
    assert data["quit"] is True
    assert data["relaunched"] is True and data["surface_up"] is True
    assert calls["async"] and "to quit" in calls["async"][0]
    assert calls["osa"] == []          # no dialog keystroke for a clean set
    assert calls["opened"] == [data["app"]]


def test_dirty_discard_answers_dialog(monkeypatch):
    # Alive after quit (dialog up), then dies once we answer Don't Save.
    calls = _stub_os(monkeypatch, alive_sequence=[True, True, False])
    data = server._restart_live_impl(save="discard", sleep=NOSLEEP)
    assert data["was_dirty"] is True
    assert data["dialog_answered"] == "discard"
    assert data["quit"] is True
    # Cmd+D (Don't Save) keystroke was sent, and Live was activated first.
    assert any('keystroke "d" using {command down}' in s for s in calls["osa"])
    assert any("to activate" in s for s in calls["osa"])


def test_dirty_save_uses_return(monkeypatch):
    calls = _stub_os(monkeypatch, alive_sequence=[True, True, False])
    data = server._restart_live_impl(save="save", sleep=NOSLEEP)
    assert data["dialog_answered"] == "save"
    assert any("keystroke return" in s for s in calls["osa"])


def test_save_on_untitled_set_reports_failure(monkeypatch):
    # 'save' but the process never dies (Save-As path dialog blocks) -> quit False.
    _stub_os(monkeypatch, alive_sequence=[True])  # always alive
    data = server._restart_live_impl(save="save", sleep=NOSLEEP)
    assert data["quit"] is False
    assert "Untitled" in data["error"] or "file path" in data["error"]


def test_no_relaunch_skips_open(monkeypatch):
    calls = _stub_os(monkeypatch, alive_sequence=[False])
    data = server._restart_live_impl(relaunch=False, sleep=NOSLEEP)
    assert "relaunched" not in data and "surface_up" not in data
    assert calls["opened"] == []


def test_no_running_live_raises(monkeypatch):
    monkeypatch.setattr(server, "_live_app_and_pid", lambda port=9877: (None, None))
    with pytest.raises(RuntimeError):
        server._restart_live_impl(sleep=NOSLEEP)


def test_bad_save_policy_raises(monkeypatch):
    _stub_os(monkeypatch, alive_sequence=[False])
    with pytest.raises(ValueError):
        server._restart_live_impl(save="maybe", sleep=NOSLEEP)


def test_tool_wrapper_reports_error_cleanly(monkeypatch):
    monkeypatch.setattr(server, "_live_app_and_pid", lambda port=9877: (None, None))
    out = json.loads(server.restart_live(None))
    assert out["ok"] is False
    assert "No running Ableton Live" in out["error"]


def test_app_name_strips_suffix():
    assert server._app_name("/Applications/Ableton Live 12 Suite.app") == \
        "Ableton Live 12 Suite"
