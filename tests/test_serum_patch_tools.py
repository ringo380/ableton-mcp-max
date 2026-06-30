import json
from ableton_mcp_max import server

def test_set_serum_oscillator_writes_param(monkeypatch):
    captured = {}
    def fake_mutate(track_index, device_index, mutate_fn, **kw):
        cat = kw["catalog_loader"]()
        tree = {"Oscillator0": {"plainParams": {}}}
        mutate_fn(cat, tree)
        captured["tree"] = tree
        return {"ok": True, "reloaded": False, "set_path": "/x.als"}
    monkeypatch.setattr(server, "_serum_fx_mutate_impl", fake_mutate)
    monkeypatch.setattr(server, "get_ableton_connection", lambda: object())
    out = json.loads(server.set_serum_oscillator(None, 1, 0, {"Volume": 0.8}))
    assert out["ok"] is True
    assert captured["tree"]["Oscillator0"]["plainParams"].get("kParamVolume") == 0.8

def test_set_serum_macro_writes_value_and_name(monkeypatch):
    captured = {}
    def fake_mutate(track_index, device_index, mutate_fn, **kw):
        cat = kw["catalog_loader"]()
        tree = {"Macro0": {"plainParams": {}}}
        mutate_fn(cat, tree)
        captured["tree"] = tree
        return {"ok": True, "reloaded": True, "set_path": "/x.als"}
    monkeypatch.setattr(server, "_serum_fx_mutate_impl", fake_mutate)
    monkeypatch.setattr(server, "get_ableton_connection", lambda: object())
    out = json.loads(server.set_serum_macro(None, 1, 0, 30.0, name="CUTOFF"))
    assert out["ok"] is True
    assert captured["tree"]["Macro0"]["name"] == "CUTOFF"
    assert captured["tree"]["Macro0"]["plainParams"]["kParamValue"] == 30.0

def test_add_serum_mod_route(monkeypatch):
    captured = {}
    def fake_mutate(track_index, device_index, mutate_fn, **kw):
        cat = kw["catalog_loader"]()
        tree = {"ModSlot%d" % n: {"plainParams": {}} for n in range(64)}
        mutate_fn(cat, tree)
        captured["tree"] = tree
        return {"ok": True, "reloaded": True, "set_path": "/x.als"}
    monkeypatch.setattr(server, "_serum_fx_mutate_impl", fake_mutate)
    monkeypatch.setattr(server, "get_ableton_connection", lambda: object())
    out = json.loads(server.add_serum_mod_route(None, 1, 26, "filter", 0, "Freq", 40.0))
    assert out["ok"] is True
    assert captured["tree"]["ModSlot0"]["destModuleTypeString"] == "VoiceFilter"
    assert captured["tree"]["ModSlot0"]["source"] == [26, 0]

def test_get_serum_patch_projects_summary(monkeypatch):
    def fake_read(track_index, device_index, **kw):
        tree = {"Oscillator0": {"plainParams": {"kParamVolume": 0.5}}}
        payload = {"ok": True, "set_path": "/x.als"}
        payload.update(kw["project_fn"](tree))
        return payload
    monkeypatch.setattr(server, "_serum_fx_read_impl", fake_read)
    monkeypatch.setattr(server, "get_ableton_connection", lambda: object())
    out = json.loads(server.get_serum_patch(None, 1))
    assert out["ok"] is True
    assert any(o["index"] == 0 for o in out["data"]["oscillators"])

def test_create_serum_patch_applies_sections(monkeypatch):
    captured = {}
    def fake_mutate(track_index, device_index, mutate_fn, **kw):
        cat = kw["catalog_loader"]()
        tree = {"Oscillator0": {"plainParams": {}}, "Macro0": {"plainParams": {}}}
        for n in range(64):
            tree["ModSlot%d" % n] = {"plainParams": {}}
        mutate_fn(cat, tree)
        captured["tree"] = tree
        return {"ok": True, "reloaded": True, "set_path": "/x.als"}
    monkeypatch.setattr(server, "_serum_fx_mutate_impl", fake_mutate)
    monkeypatch.setattr(server, "get_ableton_connection", lambda: object())
    spec = {"oscillators": [{"index": 0, "params": {"Volume": 0.7}}],
            "macros": [{"index": 0, "value": 30.0, "name": "X"}],
            "mod_routes": [{"source": 26, "dest_module": "filter", "dest_index": 0,
                            "dest_param": "Freq", "amount": 40.0}]}
    out = json.loads(server.create_serum_patch(None, 1, spec))
    assert out["ok"] is True
    assert captured["tree"]["Macro0"]["name"] == "X"
    assert captured["tree"]["ModSlot0"]["destModuleTypeString"] == "VoiceFilter"
    assert out["data"]["applied"]["mod_routes"] == 1
