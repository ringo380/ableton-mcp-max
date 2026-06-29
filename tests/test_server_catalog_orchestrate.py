import json
import importlib


def _server(tmp_path, monkeypatch):
    monkeypatch.setenv("ABLETON_MCP_CATALOG_DB", str(tmp_path / "c.db"))
    import ableton_mcp_max.server as server
    importlib.reload(server)
    server._catalog_db_conn = None
    return server


def test_create_from_plan_dry_run_does_not_write(tmp_path, monkeypatch):
    server = _server(tmp_path, monkeypatch)
    plan = {"tool": "create_wavetable_preset",
            "params": {"name": "Test", "table1": "Basics"}}
    out = json.loads(server.create_from_plan(None, plan, confirm=False))
    assert out["ok"] is True
    assert out["data"]["dry_run"] is True
    assert out["data"]["would_call"] == "create_wavetable_preset"


def test_create_from_plan_bad_plan(tmp_path, monkeypatch):
    server = _server(tmp_path, monkeypatch)
    out = json.loads(server.create_from_plan(None, {"tool": "nope"}, confirm=True))
    assert out["ok"] is False


def test_serum_clone_impl_copies(tmp_path, monkeypatch):
    server = _server(tmp_path, monkeypatch)
    base = tmp_path / "base.SerumPreset"
    base.write_bytes(b"XferJson-bytes")
    monkeypatch.setattr(server, "_user_serum_presets_dir",
                        lambda: str(tmp_path / "out"))
    res = server._serum_clone_impl(str(base), "My Clone")
    assert res["written"] is True
    with open(res["path"], "rb") as f:
        assert f.read() == b"XferJson-bytes"
