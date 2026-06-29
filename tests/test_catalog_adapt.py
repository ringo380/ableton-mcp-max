from ableton_mcp_max import catalog_adapt


def test_rows_to_sample_items():
    rows = [{"name": "Kick.wav", "path": "/x/Kick.wav", "kind": "one_shot",
             "source": "user", "folder": "Drums"}]
    out = catalog_adapt.rows_to_sample_items(rows)
    assert out[0] == {"name": "Kick.wav", "path": "/x/Kick.wav", "uri": None,
                      "kind": "one_shot", "source": "user", "folder": "Drums",
                      "is_icloud_placeholder": False}


def test_rows_to_groove_items():
    rows = [{"name": "Swing", "path": "/g/Funk/Swing.agr", "folder": "Funk",
             "source": "factory", "loadable": 1}]
    out = catalog_adapt.rows_to_groove_items(rows)
    assert out[0] == {"name": "Swing", "file": "Swing.agr", "category": "Funk",
                      "path": "/g/Funk/Swing.agr", "source": "factory",
                      "loadable": True}
