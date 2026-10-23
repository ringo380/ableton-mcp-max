import json
import ableton_mcp_max.server as server


def _install_stubs(monkeypatch, sos_ok=True, tap_ok=True):
    monkeypatch.setattr(server, "get_ableton_connection", lambda: object())
    def fake_sos(ctx, track_index, changes, device_index=0,
                 track_type="master", reload=True):
        if not sos_ok:
            return json.dumps({"ok": False,
                               "error": "device 0 on track 0 is not an Ozone 12 plugin"})
        return json.dumps({"ok": True, "data": {"reloaded": True,
                          "applied": [{"module": "Maximizer",
                                       "param": "Target Loudness [dB]",
                                       "value": -9.0}], "skipped": []}})
    def fake_expose(ctx, track_index, modules, device_index=0,
                    track_type="master", reload=True):
        return json.dumps({"ok": True, "data": {"exposed_count": 128,
                                                "overflow": []}})
    def fake_taps(ctx, track_indices=None, include_master=True):
        if not tap_ok:
            return json.dumps({"ok": True, "data": {"deployed": [],
                              "failed": [{"track_index": -1, "error": "no device"}]}})
        return json.dumps({"ok": True, "data": {"deployed": [
            {"track_index": -1, "device": "MCP Tap"}], "failed": []}})
    monkeypatch.setattr(server, "set_ozone_state", fake_sos)
    monkeypatch.setattr(server, "expose_ozone_modules", fake_expose)
    monkeypatch.setattr(server, "deploy_taps", fake_taps)


def test_apply_master_happy_path(monkeypatch):
    _install_stubs(monkeypatch)
    out = json.loads(server.apply_master(ctx=None,
                     chain={"MAX": {"Target Loudness [dB]": -9.0}}))
    assert out["ok"] is True
    d = out["data"]
    assert d["reloaded"] is True
    assert d["applied"][0]["value"] == -9.0
    assert d["exposed"]["exposed_count"] == 128
    assert d["tap"]["status"] == "deployed"
    assert "render" in d["next"] and "input_gain_db" in d["next"]


def test_apply_master_not_ozone(monkeypatch):
    _install_stubs(monkeypatch, sos_ok=False)
    out = json.loads(server.apply_master(ctx=None, chain={"MAX": {}}))
    assert out["ok"] is False
    assert "not an Ozone 12 plugin" in out["error"]


def test_apply_master_tap_failure_is_nonfatal(monkeypatch):
    _install_stubs(monkeypatch, tap_ok=False)
    out = json.loads(server.apply_master(ctx=None,
                     chain={"MAX": {"Target Loudness [dB]": -9.0}}))
    assert out["ok"] is True  # write still counts
    assert out["data"]["tap"]["status"] == "failed"


def test_apply_master_input_gain_writes_locked_and_sides(monkeypatch):
    _install_stubs(monkeypatch)
    seen = {}
    real = server.set_ozone_state
    def capture(ctx, track_index, changes, device_index=0,
                track_type="master", reload=True):
        seen["changes"] = changes
        return real(ctx, track_index, changes, device_index, track_type, reload)
    monkeypatch.setattr(server, "set_ozone_state", capture)
    chain = {"MAX": {"Margin": -1.0}}
    out = json.loads(server.apply_master(ctx=None, chain=chain,
                                         input_gain_db=-6))
    assert out["ok"] is True
    gi = seen["changes"]["Gain Input"]
    assert gi == {"Gain Input Locked": -6.0, "Gain Input Left": -6.0,
                  "Gain Input Right": -6.0}
    assert seen["changes"]["MAX"] == {"Margin": -1.0}
    assert "Gain Input" not in chain  # caller's dict is not mutated


def test_apply_master_without_input_gain_leaves_trim_alone(monkeypatch):
    _install_stubs(monkeypatch)
    seen = {}
    real = server.set_ozone_state
    def capture(ctx, track_index, changes, device_index=0,
                track_type="master", reload=True):
        seen["changes"] = changes
        return real(ctx, track_index, changes, device_index, track_type, reload)
    monkeypatch.setattr(server, "set_ozone_state", capture)
    server.apply_master(ctx=None, chain={"MAX": {"Margin": -1.0}})
    assert "Gain Input" not in seen["changes"]


def test_apply_master_errors_when_an_enabled_module_is_not_in_the_chain(monkeypatch):
    _install_stubs(monkeypatch)        # fake write reports no chain at all
    out = json.loads(server.apply_master(ctx=None, chain={"MAX": {"Bypass": False}}))
    assert out["ok"] is False and "Maximizer" in out["error"] and "chain" in out["error"]


def test_apply_master_passes_when_the_chain_holds_the_module(monkeypatch):
    _install_stubs(monkeypatch)
    real = server.set_ozone_state
    def with_chain(*a, **k):
        d = json.loads(real(*a, **k)); d["data"]["chain"] = ["Maximizer"]
        return json.dumps(d)
    monkeypatch.setattr(server, "set_ozone_state", with_chain)
    out = json.loads(server.apply_master(ctx=None, chain={"MAX": {"Bypass": False}}))
    assert out["ok"] is True
