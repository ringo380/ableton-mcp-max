import json
import os
import importlib


def _fresh_server(tmp_path, monkeypatch):
    monkeypatch.setenv("ABLETON_MCP_CATALOG_DB", str(tmp_path / "c.db"))
    import ableton_mcp_max.server as server
    importlib.reload(server)
    # reset cached connection so the env-var path is picked up
    server._catalog_db_conn = None
    server._catalog_device_indexed = False
    server._catalog_live_disconnected = False
    # prevent freshness checks from indexing real filesystem content during tests
    monkeypatch.setattr(server, "_serum_roots", lambda: [])
    monkeypatch.setattr(server, "_sample_search_roots", lambda sources: [])
    monkeypatch.setattr(server, "_groove_search_roots", lambda sources: [])
    return server


def test_search_catalog_tool_reads_db(tmp_path, monkeypatch):
    server = _fresh_server(tmp_path, monkeypatch)
    conn = server._catalog_conn()
    conn.execute(
        "INSERT INTO items(domain,name,path,source,folder,loadable,tags,"
        "indexed_at) VALUES('serum','Deep Sub','/s/Deep Sub.SerumPreset','user',"
        "'Bass',1,'bass',1.0)")
    conn.commit()
    # FastMCP in this project returns the plain function from @mcp.tool(),
    # so search_catalog IS the callable directly (no .fn wrapper).
    out = json.loads(server.search_catalog(None, "deep", domains=["serum"]))
    assert out["ok"] is True
    assert out["data"]["items"][0]["name"] == "Deep Sub"


def test_catalog_stats_tool(tmp_path, monkeypatch):
    server = _fresh_server(tmp_path, monkeypatch)
    out = json.loads(server.catalog_stats(None))
    assert out["ok"] is True
    assert "by_domain" in out["data"]


def test_search_catalog_device_live_disconnected(tmp_path, monkeypatch):
    server = _fresh_server(tmp_path, monkeypatch)

    def dead(_path):
        raise RuntimeError("Live not connected")

    monkeypatch.setattr(server, "_browser_reader", dead)
    out = json.loads(server.search_catalog(None, "pad", domains=["device_preset"]))
    assert out["ok"] is True
    assert out["data"]["live_disconnected"] is True
