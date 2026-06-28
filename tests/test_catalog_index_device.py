from ableton_mcp_max import catalog_db, catalog_index


def test_index_device_presets_with_fake_reader(tmp_path):
    conn = catalog_db.open_db(str(tmp_path / "c.db"))

    def reader(path):
        if path == "instruments":
            return {"presets": [
                {"name": "Dark Pad.adg", "relative_path": "Pads/Dark Pad.adg",
                 "uri": "library://Wavetable/Pads/Dark Pad"}],
                "count": 1}
        if path == "broken":
            raise RuntimeError("no such category")
        return {"error": "empty", "presets": [], "count": 0}

    n = catalog_index.index_device_presets(
        conn, reader, ["instruments", "broken", "audio_effects"])
    assert n == 1
    row = conn.execute(
        "SELECT name,uri,folder,domain FROM items WHERE domain='device_preset'"
    ).fetchone()
    assert row["uri"] == "library://Wavetable/Pads/Dark Pad"
    assert row["folder"] == "Pads"


def test_device_reindex_replaces(tmp_path):
    conn = catalog_db.open_db(str(tmp_path / "c.db"))
    catalog_index.index_device_presets(
        conn, lambda p: {"presets": [
            {"name": "A.adg", "relative_path": "X/A.adg", "uri": "u://A"}],
            "count": 1}, ["instruments"])
    catalog_index.index_device_presets(
        conn, lambda p: {"presets": [
            {"name": "B.adg", "relative_path": "X/B.adg", "uri": "u://B"}],
            "count": 1}, ["instruments"])
    names = {r[0] for r in conn.execute(
        "SELECT name FROM items WHERE domain='device_preset'")}
    assert names == {"B"}
