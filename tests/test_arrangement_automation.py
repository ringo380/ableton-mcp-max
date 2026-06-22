"""Tests for the arrangement-automation server orchestration (_current_set_path,
_reload_set, _arr_auto_impl). All OS/UI/connection seams are stubbed so the
probe -> save -> patch -> reload choreography runs without a real Live."""
import os

import pytest

from ableton_mcp_max import server
from ableton_mcp_max import als_automation_utils as als

NOSLEEP = lambda *a, **k: None


# --------------------------------------------------------------------------- #
# _current_set_path
# --------------------------------------------------------------------------- #
def test_current_set_path_parses_last_loading_line(monkeypatch, tmp_path):
    real = tmp_path / "my_set Project" / "my_set.als"
    real.parent.mkdir(parents=True)
    real.write_text("x")
    log = tmp_path / "Log.txt"
    log.write_text(
        'info: Loading document "/Applications/Ableton Live 12 Suite.app/x.als"\n'
        'info: Loading document "%s"\n' % real)
    monkeypatch.setattr(server, "_live_log_path", lambda: str(log))
    assert server._current_set_path("my_set") == str(real)


def test_current_set_path_skips_factory_and_missing(monkeypatch, tmp_path):
    log = tmp_path / "Log.txt"
    log.write_text(
        'Loading document "/Applications/Ableton Live 12 Suite.app/Default.als"\n'
        'Loading document "/tmp/does_not_exist.als"\n')
    monkeypatch.setattr(server, "_live_log_path", lambda: str(log))
    assert server._current_set_path() == ""


def test_current_set_path_title_mismatch(monkeypatch, tmp_path):
    real = tmp_path / "a.als"
    real.write_text("x")
    log = tmp_path / "Log.txt"
    log.write_text('Loading document "%s"\n' % real)
    monkeypatch.setattr(server, "_live_log_path", lambda: str(log))
    assert server._current_set_path("different") == ""
    assert server._current_set_path("a") == str(real)


# --------------------------------------------------------------------------- #
# _reload_set
# --------------------------------------------------------------------------- #
def test_reload_set_new_then_open_then_ready(monkeypatch):
    calls = {"osa": [], "open": []}
    monkeypatch.setattr(server, "_live_app_and_pid",
                        lambda port=9877: ("/Applications/Ableton Live 12 Suite.app", 1))
    monkeypatch.setattr(server, "_osa", lambda s: calls["osa"].append(s))
    monkeypatch.setattr(server, "_live_window_count", lambda proc="Live": 1)
    monkeypatch.setattr(server, "_open_file", lambda p: calls["open"].append(p))
    monkeypatch.setattr(server, "_live_window_title", lambda proc="Live": "my_set")
    res = server._reload_set("/tmp/my_set Project/my_set.als", "my_set",
                             sleep=NOSLEEP, probe=lambda: True)
    assert res["reloaded"] is True
    assert calls["open"] == ["/tmp/my_set Project/my_set.als"]
    assert any('keystroke "n"' in s for s in calls["osa"])


def test_reload_set_answers_save_dialog(monkeypatch):
    calls = {"osa": []}
    state = {"wins": 1}
    monkeypatch.setattr(server, "_live_app_and_pid",
                        lambda port=9877: ("/Applications/Ableton Live 12 Suite.app", 1))
    def _osa(s):
        calls["osa"].append(s)
        if 'keystroke "n"' in s:
            state["wins"] = 2          # ⌘N popped a save dialog
        if 'keystroke "d"' in s:
            state["wins"] = 1
    monkeypatch.setattr(server, "_osa", _osa)
    monkeypatch.setattr(server, "_live_window_count", lambda proc="Live": state["wins"])
    monkeypatch.setattr(server, "_open_file", lambda p: None)
    monkeypatch.setattr(server, "_live_window_title", lambda proc="Live": "s")
    res = server._reload_set("/tmp/s.als", "s", sleep=NOSLEEP, probe=lambda: True)
    assert res["reloaded"] is True
    assert any('keystroke "d"' in s for s in calls["osa"])  # Don't Save


def test_reload_set_times_out_when_title_never_matches(monkeypatch):
    monkeypatch.setattr(server, "_live_app_and_pid",
                        lambda port=9877: ("/Applications/Ableton Live 12 Suite.app", 1))
    monkeypatch.setattr(server, "_osa", lambda s: None)
    monkeypatch.setattr(server, "_live_window_count", lambda proc="Live": 1)
    monkeypatch.setattr(server, "_open_file", lambda p: None)
    monkeypatch.setattr(server, "_live_window_title", lambda proc="Live": "wrong")
    res = server._reload_set("/tmp/s.als", "s", timeout=2.0, sleep=NOSLEEP,
                             probe=lambda: True)
    assert res["reloaded"] is False


# --------------------------------------------------------------------------- #
# _arr_auto_impl
# --------------------------------------------------------------------------- #
class FakeAbleton:
    """Minimal stand-in: get_device_parameters returns a fixed param list whose
    `value` reflects the last set_device_parameter (so the readback matches)."""
    def __init__(self, params):
        self.params = [dict(p) for p in params]
        self.sets = []

    def send_command(self, cmd, payload=None):
        payload = payload or {}
        if cmd == "get_device_parameters":
            return {"parameters": [dict(p) for p in self.params]}
        if cmd == "set_device_parameter":
            self.sets.append(payload)
            self.params[payload["parameter_index"]]["value"] = payload["value"]
            return {"ok": True}
        if cmd == "get_session_info":
            return {"ok": True}
        return {}


def _xml_with_manual(value, env="<Envelopes />"):
    """A one-track set whose only device param has <Manual Value=value> followed
    by its AutomationTarget Id, so find_target_after_manual resolves it."""
    return (
        '<Ableton><LiveSet><Tracks>'
        '<MidiTrack Id="8" SelectedToolPanel="2">'
        '<AutomationEnvelopes><Envelopes>%s</Envelopes></AutomationEnvelopes>'
        '<DeviceChain><DeviceChain><Devices><Foo>'
        '<Cutoff><Manual Value="%s" />'
        '<MidiControllerRange><Min Value="0" /><Max Value="1" /></MidiControllerRange>'
        '<AutomationTarget Id="4242" /></Cutoff>'
        '</Foo></Devices></DeviceChain></DeviceChain>'
        '</MidiTrack></Tracks></LiveSet></Ableton>'
        % (env.replace("<Envelopes />", "") or "", als._fmt(value))
    )


def _run_impl(monkeypatch, lanes, reload=False, saved=True, title="my_set",
              xml=None, params=None):
    if params is None:
        params = [{"index": 0, "name": "Cutoff", "value": 0.5, "min": 0.0,
                   "max": 1.0, "is_quantized": False}]
    ab = FakeAbleton(params)
    sentinel = 0.0 + server._probe_fraction(0) * (1.0 - 0.0)
    if xml is None:
        xml = _xml_with_manual(sentinel)
    written = {}
    monkeypatch.setattr(server, "_live_window_title", lambda proc="Live": title)
    monkeypatch.setattr(server, "_current_set_path",
                        lambda t=None: "/tmp/my_set Project/my_set.als")
    data = server._arr_auto_impl(
        ab, lanes, reload,
        save_impl=lambda: {"saved": saved},
        reload_impl=lambda p, n: {"reloaded": True, "title": n},
        read_als=lambda p: xml,
        write_als=lambda p, x: written.__setitem__("xml", x),
    )
    return data, ab, written


def test_arr_auto_impl_writes_envelope(monkeypatch):
    lanes = [{"track_index": 0, "device_index": 0, "parameter": "Cutoff",
              "points": [{"time": 0, "value": 0.2}, {"time": 16, "value": 0.9}]}]
    data, ab, written = _run_impl(monkeypatch, lanes)
    assert data["lanes"][0]["ok"] is True
    assert data["lanes"][0]["pointee_id"] == "4242"
    assert data["lanes"][0]["points_written"] == 2
    assert '<PointeeId Value="4242" />' in written["xml"]
    # the probed Manual is patched back to the first point value (0.2)
    assert '<Manual Value="0.2" />' in written["xml"]


def test_arr_auto_impl_untitled_raises(monkeypatch):
    with pytest.raises(ValueError):
        _run_impl(monkeypatch, [{"track_index": 0, "parameter": "Cutoff",
                                 "points": [{"time": 0, "value": 0.2}]}],
                  title="Untitled")


def test_arr_auto_impl_quantized_lane_skipped(monkeypatch):
    params = [{"index": 0, "name": "Cutoff", "value": 0.5, "min": 0.0,
               "max": 1.0, "is_quantized": True}]
    data, ab, written = _run_impl(
        monkeypatch,
        [{"track_index": 0, "parameter": "Cutoff",
          "points": [{"time": 0, "value": 0.2}]}],
        params=params)
    assert data["lanes"][0]["ok"] is False
    assert "quantized" in data["lanes"][0]["error"]
    assert "no resolvable lanes" in data.get("error", "")


def test_arr_auto_impl_save_failure_reports(monkeypatch):
    lanes = [{"track_index": 0, "parameter": "Cutoff",
              "points": [{"time": 0, "value": 0.2}]}]
    data, ab, written = _run_impl(monkeypatch, lanes, saved=False)
    assert "save_set failed" in data["error"]
    assert "xml" not in written


def test_arr_auto_impl_reload_false_restores_live_param(monkeypatch):
    lanes = [{"track_index": 0, "device_index": 0, "parameter": "Cutoff",
              "points": [{"time": 0, "value": 0.33}, {"time": 8, "value": 0.7}]}]
    data, ab, written = _run_impl(monkeypatch, lanes, reload=False)
    assert data["reloaded"] is False
    # the LAST set_device_parameter restores the knob to the first point (0.33),
    # not the probe sentinel.
    assert ab.sets[-1]["value"] == 0.33
