import json
import ableton_mcp_max.server as server


def _install(monkeypatch, devices, load_appends=None, saves=None,
             ozone_ok=True):
    """devices: mutable list of {"index","name","is_on"} the fake master holds.
    load_appends: dict to append on load (or None -> append Ozone 12).
    saves: list of save_set data dicts to return in sequence (cycled/last).
    """
    monkeypatch.setattr(server, "get_ableton_connection", lambda: object())

    def fake_get_device_info(ctx, track_index, device_index, track_type="regular"):
        for d in devices:
            if d["index"] == device_index:
                return json.dumps({"ok": True, "data": {
                    "device_index": device_index, "name": d["name"],
                    "is_on": d["is_on"]}})
        return json.dumps({"ok": False, "error": "no device at index %d" % device_index})

    def fake_set_device_on(ctx, track_index, device_index, on, track_type="regular"):
        for d in devices:
            if d["index"] == device_index:
                d["is_on"] = bool(on)
        return json.dumps({"ok": True, "data": {"device_index": device_index,
                                                "is_on": bool(on)}})

    def fake_load(ctx, track_index, uri, track_type="regular"):
        new = load_appends or {"index": len(devices), "name": "Ozone 12",
                               "is_on": True}
        new = dict(new)
        new["index"] = max([d["index"] for d in devices], default=-1) + 1
        devices.append(new)
        return json.dumps({"ok": True, "data": "loaded"})

    save_seq = list(saves or [{"saved": True, "title": "myset", "untitled": False}])

    def fake_save_set(ctx, name=""):
        data = save_seq[0] if len(save_seq) == 1 else save_seq.pop(0)
        return json.dumps({"ok": True, "data": data})

    def fake_get_ozone_state(ctx, track_index, device_index=0,
                             track_type="master", module=None):
        if ozone_ok:
            return json.dumps({"ok": True, "data": {"module": "Maximizer",
                                                    "params": []}})
        return json.dumps({"ok": False,
                           "error": "Could not resolve the current set's .als path."})

    monkeypatch.setattr(server, "get_device_info", fake_get_device_info)
    monkeypatch.setattr(server, "set_device_on", fake_set_device_on)
    monkeypatch.setattr(server, "load_instrument_or_effect", fake_load)
    monkeypatch.setattr(server, "save_set", fake_save_set)
    monkeypatch.setattr(server, "get_ozone_state", fake_get_ozone_state)
    # Make the retry loop instant.
    monkeypatch.setattr(server.time, "sleep", lambda *_a, **_k: None)
    return devices


def test_reuse_existing_ozone12(monkeypatch):
    _install(monkeypatch, [{"index": 0, "name": "Ozone 12", "is_on": True},
                           {"index": 1, "name": "MCP Tap", "is_on": True}])
    out = json.loads(server.ensure_ozone_master(ctx=None))
    assert out["ok"] is True
    d = out["data"]
    assert d["device_index"] == 0
    assert d["action"] == "reused"
    assert d["disabled_indices"] == []
    assert d["blob_ready"] is True


def test_reenable_disabled_ozone12(monkeypatch):
    devs = _install(monkeypatch, [{"index": 0, "name": "Ozone 12", "is_on": False}])
    out = json.loads(server.ensure_ozone_master(ctx=None))
    d = out["data"]
    assert d["action"] == "reused_reenabled"
    assert d["device_index"] == 0
    assert devs[0]["is_on"] is True  # executor re-enabled it


def test_disable_older_and_load_fresh(monkeypatch):
    devs = _install(monkeypatch, [{"index": 0, "name": "Ozone 10", "is_on": True},
                                  {"index": 1, "name": "MCP Tap", "is_on": True}])
    out = json.loads(server.ensure_ozone_master(ctx=None))
    d = out["data"]
    assert d["action"] == "loaded"
    assert d["disabled_indices"] == [0]
    assert d["device_index"] == 2   # appended after 0,1
    assert devs[0]["is_on"] is False


def test_untitled_set_precondition_errors(monkeypatch):
    _install(monkeypatch, [{"index": 0, "name": "Ozone 12", "is_on": True}],
             saves=[{"saved": False, "untitled": True, "title": ""}])
    out = json.loads(server.ensure_ozone_master(ctx=None))
    assert out["ok"] is False
    assert "untitled" in out["error"].lower()


def test_transient_untitled_then_recovers(monkeypatch):
    # First save reports transient empty title; retry succeeds. Precondition
    # save (call 1) is titled, loop save (call 2) transient, (call 3) good.
    _install(monkeypatch, [{"index": 0, "name": "Ozone 12", "is_on": True}],
             saves=[{"saved": True, "title": "myset", "untitled": False},
                    {"saved": False, "untitled": True, "title": ""},
                    {"saved": True, "title": "myset", "untitled": False}])
    out = json.loads(server.ensure_ozone_master(ctx=None))
    assert out["ok"] is True
    assert out["data"]["blob_ready"] is True


def test_blob_never_ready_returns_error(monkeypatch):
    _install(monkeypatch, [{"index": 0, "name": "Ozone 12", "is_on": True}],
             ozone_ok=False)
    out = json.loads(server.ensure_ozone_master(ctx=None))
    assert out["ok"] is False
    assert "blob" in out["error"].lower()
