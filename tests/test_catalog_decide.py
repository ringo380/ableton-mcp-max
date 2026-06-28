import pytest
from ableton_mcp_max import catalog_db, catalog_decide


def _seed_serum(conn, names):
    for n in names:
        conn.execute(
            "INSERT INTO items(domain,name,path,source,folder,loadable,tags,"
            "indexed_at) VALUES('serum',?,?,'user','Bass',1,?,1.0)",
            (n, "/s/%s.SerumPreset" % n, "bass"))
    conn.commit()


def test_recommend_reuse_when_strong_match(tmp_path):
    conn = catalog_db.open_db(str(tmp_path / "c.db"))
    _seed_serum(conn, ["Deep Sub Bass"])
    r = catalog_decide.recommend(conn, "deep sub bass", "serum")
    assert r["decision"] == "reuse"
    assert r["create_plan"] is None
    assert r["top_matches"][0]["name"] == "Deep Sub Bass"


def test_recommend_create_when_no_match_serum(tmp_path):
    conn = catalog_db.open_db(str(tmp_path / "c.db"))
    _seed_serum(conn, ["Bright Lead"])
    r = catalog_decide.recommend(conn, "wobble reese growl", "serum")
    assert r["decision"] == "create"
    assert r["create_plan"]["tool"] == "serum_clone"


def test_recommend_gap_for_samples(tmp_path):
    conn = catalog_db.open_db(str(tmp_path / "c.db"))
    r = catalog_decide.recommend(conn, "vinyl crackle texture", "sample")
    assert r["decision"] == "gap"
    assert r["create_plan"] is None


def test_resolve_dispatch():
    d = catalog_decide.resolve_dispatch(
        {"tool": "create_wavetable_preset", "params": {"name": "X", "table1": "Basics"}})
    assert d["creator"] == "create_wavetable_preset"
    assert d["kwargs"]["name"] == "X"
    with pytest.raises(ValueError):
        catalog_decide.resolve_dispatch({"tool": "nope", "params": {}})
