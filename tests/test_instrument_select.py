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


def test_serum_installed_candidates(tmp_path):
    fake = tmp_path / "Serum2.vst3"
    fake.write_text("x")
    assert isel.serum_installed([str(fake)]) is True
    assert isel.serum_installed([str(tmp_path / "nope.vst3")]) is False


def test_classify_device():
    assert isel.classify_device("Serum2", "PluginDevice") == "serum"
    assert isel.classify_device("Serum", "AuPluginDevice") == "serum"
    assert isel.classify_device("Massive X", "PluginDevice") == "plugin"
    assert isel.classify_device("Wavetable", "InstrumentVector") == "native"
    assert isel.classify_device("", "Operator") == "native"


def test_summarize_environment_counts_and_autonative():
    # one native instrument, no 3rd-party -> auto prefer_native True
    devs = [[{"name": "Wavetable", "class_name": "InstrumentVector"}]]
    env = isel.summarize_environment(devs, True, None)
    assert env == {"serum_installed": True, "serum_instances": 0, "prefer_native": True}


def test_summarize_environment_serum_present_blocks_autonative():
    devs = [[{"name": "Serum2", "class_name": "PluginDevice"}],
            [{"name": "Serum2", "class_name": "PluginDevice"}]]
    env = isel.summarize_environment(devs, True, None)
    assert env["serum_instances"] == 2
    assert env["prefer_native"] is False  # a 3rd-party plugin is present


def test_summarize_environment_explicit_prefer_native_overrides():
    devs = [[{"name": "Serum2", "class_name": "PluginDevice"}]]
    env = isel.summarize_environment(devs, True, True)
    assert env["prefer_native"] is True


def test_summarize_environment_empty_set_not_autonative():
    env = isel.summarize_environment([], True, None)
    assert env["prefer_native"] is False


_ENV_OK = {"serum_installed": True, "serum_instances": 0, "prefer_native": False}


def test_score_reese_bass_serum_wins():
    p = isel.load_profiles()
    parsed = isel.parse_intent("gritty evolving reese bass for dnb", p)
    ranked = isel.score(parsed, p, _ENV_OK)
    assert ranked[0]["engine"] == "serum"
    assert ranked[0]["domain"] == "serum"
    assert ranked[0]["creatable"] is True


def test_score_generic_pad_native_wins_over_serum():
    # no genre, generic "pad", no serum-only character -> native bias decides
    p = isel.load_profiles()
    parsed = isel.parse_intent("a pad", p)
    ranked = isel.score(parsed, p, _ENV_OK)
    assert ranked[0]["engine"] != "serum"
    assert p["engines"][ranked[0]["engine"]]["native"] is True


def test_score_acoustic_pluck_simpler():
    p = isel.load_profiles()
    parsed = isel.parse_intent("realistic acoustic pluck", p)
    ranked = isel.score(parsed, p, _ENV_OK)
    assert ranked[0]["engine"] == "simpler"
    assert ranked[0]["domain"] == "simpler"


def test_score_serum_excluded_when_not_installed():
    p = isel.load_profiles()
    parsed = isel.parse_intent("gritty reese bass dnb", p)
    env = {"serum_installed": False, "serum_instances": 0, "prefer_native": False}
    ranked = isel.score(parsed, p, env)
    assert all(r["engine"] != "serum" for r in ranked)


def test_score_serum_busy_penalty_demotes():
    p = isel.load_profiles()
    parsed = isel.parse_intent("gritty reese bass dnb", p)
    top_free = isel.score(parsed, p, _ENV_OK)[0]["engine"]
    busy = {"serum_installed": True, "serum_instances": 5, "prefer_native": False}
    serum_score_busy = [r for r in isel.score(parsed, p, busy) if r["engine"] == "serum"][0]["score"]
    serum_score_free = [r for r in isel.score(parsed, p, _ENV_OK) if r["engine"] == "serum"][0]["score"]
    assert top_free == "serum"
    assert serum_score_busy == serum_score_free - 3.0


def test_score_prefer_native_penalizes_non_native():
    p = isel.load_profiles()
    parsed = isel.parse_intent("gritty reese bass dnb", p)
    pn = {"serum_installed": True, "serum_instances": 0, "prefer_native": True}
    serum_pn = [r for r in isel.score(parsed, p, pn) if r["engine"] == "serum"][0]["score"]
    serum_free = [r for r in isel.score(parsed, p, _ENV_OK) if r["engine"] == "serum"][0]["score"]
    assert serum_pn == serum_free - 3.0


def test_recommend_shape():
    p = isel.load_profiles()
    out = isel.recommend("gritty reese bass dnb", _ENV_OK, profiles=p)
    assert set(["intent", "parsed", "ranked", "top", "reason"]).issubset(out)
    assert out["top"]["engine"] == out["ranked"][0]["engine"]
    assert out["top"]["domain"] == out["ranked"][0]["domain"]


def test_recommend_operator_routes_to_device_preset():
    p = isel.load_profiles()
    # FM bell pluck favors operator; operator is non-creatable -> device_preset
    out = isel.recommend("metallic fm bell pluck", _ENV_OK, profiles=p)
    op = [r for r in out["ranked"] if r["engine"] == "operator"][0]
    assert op["domain"] == "device_preset"
    assert op["creatable"] is False
