import ableton_mcp_max.master_select as ms


def test_parse_bucket_loud_club():
    p = ms.parse_intent("loud club master for a festival")
    assert p["bucket"] == "loud_club"


def test_parse_bucket_defaults_transparent():
    assert ms.parse_intent("just finish it")["bucket"] == "transparent"


def test_platform_target_spotify():
    p = ms.parse_intent("warm master for spotify")
    lufs, src = ms.resolve_target(p, None)
    assert lufs == -14.0 and src.startswith("platform")


def test_platform_target_apple():
    p = ms.parse_intent("clean apple music master")
    assert ms.resolve_target(p, None)[0] == -16.0


def test_explicit_target_overrides_platform():
    p = ms.parse_intent("club master for spotify")  # club + spotify both present
    lufs, src = ms.resolve_target(p, -9.0)
    assert lufs == -9.0 and src == "explicit"


def test_default_target_when_no_signal():
    p = ms.parse_intent("master this")
    assert ms.resolve_target(p, None) == (-14.0, "default")


def test_recommend_shape():
    out = ms.recommend("warm vinyl-style master", target=None)
    assert out["decision"] == "create"
    assert out["parsed"]["bucket"] == "warm"
    assert out["target"] == -14.0
    assert out["true_peak"] == -1.0
    assert isinstance(out["chain"], dict) and "MAX" in out["chain"]


def test_recommend_explicit_target_flows_into_chain():
    out = ms.recommend("loud club", target=-8.0)
    assert out["target"] == -8.0
    from ableton_mcp_max.master_profiles import PARAM_KEYS
    a, p = PARAM_KEYS["max_target"]
    assert out["chain"][a][p] == -8.0
