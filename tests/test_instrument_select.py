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


def test_parse_intent_reese_bass_dnb():
    p = isel.load_profiles()
    r = isel.parse_intent("gritty evolving reese bass for dnb", p)
    assert r["role"] == "bass"
    assert r["genre"] == "dnb"
    # reese -> growl character; gritty, evolving present
    assert set(["gritty", "evolving", "growl"]).issubset(set(r["character"]))


def test_parse_intent_multiword_genre():
    p = isel.load_profiles()
    r = isel.parse_intent("warm pad for deep house", p)
    assert r["role"] == "pad"
    assert r["genre"] == "house"
    assert "warm" in r["character"]


def test_parse_intent_word_boundary_no_false_match():
    p = isel.load_profiles()
    # "harp" must NOT match the "arp" lead synonym
    r = isel.parse_intent("a harp sound", p)
    assert r["role"] != "lead" or "arp" not in p["role_vocab"]["lead"]  # arp not falsely triggered
    r2 = isel.parse_intent("harp", p)
    assert r2["role"] is None


def test_parse_intent_empty():
    p = isel.load_profiles()
    r = isel.parse_intent("", p)
    assert r == {"role": None, "genre": None, "character": []}
