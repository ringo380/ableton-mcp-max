from ableton_mcp_max import catalog_db, catalog_query


def _seed(conn):
    rows = [
        ("serum", "Deep Sub Bass", "/s/Deep Sub Bass.SerumPreset", None, "user",
         "Bass", None, 1, "bass fx0"),
        ("serum", "Bright Lead", "/s/Bright Lead.SerumPreset", None, "factory",
         "Lead", None, 1, "lead fx1"),
        ("sample", "Deep Kick.wav", "/x/Deep Kick.wav", None, "user", "Drums",
         "one_shot", 1, "one_shot drums"),
    ]
    for r in rows:
        conn.execute(
            "INSERT INTO items(domain,name,path,uri,source,folder,kind,loadable,"
            "tags,indexed_at) VALUES(?,?,?,?,?,?,?,?,?,1.0)", r)
    conn.commit()


def test_score_tokens():
    assert catalog_query.score_tokens("deep bass", "Deep Sub Bass", "Bass",
                                      "bass fx0") >= 2
    assert catalog_query.score_tokens("", "x", "y", "z") == 0


def test_search_catalog_filters_domain(tmp_path):
    conn = catalog_db.open_db(str(tmp_path / "c.db"))
    _seed(conn)
    res = catalog_query.search_catalog(conn, "deep", domains=["serum"])
    names = [i["name"] for i in res["items"]]
    assert "Deep Sub Bass" in names and "Deep Kick.wav" not in names
    assert res["count"] == len(res["items"])


def test_find_similar_scored(tmp_path):
    conn = catalog_db.open_db(str(tmp_path / "c.db"))
    _seed(conn)
    hits = catalog_query.find_similar(conn, "deep bass", "serum", limit=5)
    assert hits[0]["name"] == "Deep Sub Bass"
    assert hits[0]["score"] >= 2


def test_stats(tmp_path):
    conn = catalog_db.open_db(str(tmp_path / "c.db"))
    _seed(conn)
    s = catalog_query.catalog_stats(conn)
    assert s["total"] == 3
    assert s["by_domain"]["serum"] == 2
    assert s["by_kind"]["one_shot"] == 1
