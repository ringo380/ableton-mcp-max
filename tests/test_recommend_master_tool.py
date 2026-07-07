import json
import ableton_mcp_max.server as server


def test_recommend_master_create_no_catalog(monkeypatch):
    # Catalog unavailable -> profile chain still returned, top_matches empty.
    def _boom():
        raise RuntimeError("catalog offline")
    monkeypatch.setattr(server, "_catalog_conn", _boom)
    out = json.loads(server.recommend_master(ctx=None,
                                             intent="warm master for spotify"))
    assert out["ok"] is True
    d = out["data"]
    assert d["decision"] == "create"
    assert d["parsed"]["bucket"] == "warm"
    assert d["target"] == -14.0
    assert "MAX" in d["chain"]
    assert d["top_matches"] == []
    assert "apply_master" in d["next"]


def test_recommend_master_explicit_target(monkeypatch):
    monkeypatch.setattr(server, "_catalog_conn",
                        lambda: (_ for _ in ()).throw(RuntimeError("off")))
    out = json.loads(server.recommend_master(ctx=None, intent="loud club",
                                             target=-8.0))
    assert out["ok"] is True
    assert out["data"]["target"] == -8.0


def test_recommend_master_reuse_when_catalog_matches(monkeypatch):
    class _Conn:
        pass
    monkeypatch.setattr(server, "_catalog_conn", lambda: _Conn())
    monkeypatch.setattr(server, "_ensure_device_index", lambda conn: None)
    monkeypatch.setattr(server.catalog_query, "find_similar",
                        lambda conn, intent, domain, limit=5: [
                            {"name": "Ozone Master Loud", "path": "/x/ozone.adv",
                             "score": 3}])
    out = json.loads(server.recommend_master(ctx=None, intent="loud club master"))
    assert out["ok"] is True
    assert out["data"]["decision"] == "reuse"
    assert out["data"]["top_matches"][0]["score"] == 3
