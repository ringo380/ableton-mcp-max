from ableton_mcp_max import instrument_select as isel

# valid recommend_asset domains (server.py recommend_asset accepts these)
_VALID_DOMAINS = {"serum", "sample", "groove", "device_preset", "wavetable", "simpler"}
_ROLES = {"bass", "lead", "pad", "pluck", "fx", "drums"}


def test_load_profiles_shape():
    p = isel.load_profiles()
    assert set(["engines", "role_vocab", "genre_vocab", "character_vocab"]).issubset(p)
    assert "serum" in p["engines"] and "wavetable" in p["engines"]


def test_matrix_integrity():
    p = isel.load_profiles()
    for key, eng in p["engines"].items():
        assert eng["domain"] in _VALID_DOMAINS, key
        assert set(eng["roles"]) == _ROLES, key
        assert isinstance(eng["native"], bool) and isinstance(eng["creatable"], bool)
        for c in eng["character"]:
            assert isinstance(c, str)
    # every scored character token category is a real dict entry
    assert "growl" in p["character_vocab"]
    assert "growl" in p["engines"]["serum"]["character"]
