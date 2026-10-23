import pytest
import ableton_mcp_max.master_profiles as mp
from ableton_mcp_max.ozone_utils import ALIAS_TO_BLOB


def test_buckets_are_five():
    assert mp.BUCKETS == ("transparent", "warm", "loud_club", "punchy", "bright")


def test_build_chain_passes_target_through_to_maximizer():
    chain = mp.build_chain("transparent", -14.0, -1.0)
    alias, pname = mp.PARAM_KEYS["max_target"]
    assert chain[alias][pname] == -14.0


def test_build_chain_always_sets_ceiling_and_isc():
    chain = mp.build_chain("transparent", -14.0, -1.0)
    a, ck = mp.PARAM_KEYS["max_ceiling"]
    _, ik = mp.PARAM_KEYS["max_isc"]
    assert chain["MAX"][ck] == -1.0        # Margin = ceiling
    assert chain["MAX"][ik] is True        # Prevent Intersample Clipping


def test_build_chain_enables_maximizer():
    chain = mp.build_chain("transparent", -12.0, -1.0)
    _, bk = mp.PARAM_KEYS["max_bypass"]
    assert chain["MAX"][bk] is False       # bypass False == module on


def test_build_chain_louder_target_is_higher_value():
    quiet = mp.build_chain("transparent", -14.0, -1.0)
    loud = mp.build_chain("loud_club", -8.0, -1.0)
    a, p = mp.PARAM_KEYS["max_target"]
    assert loud[a][p] > quiet[a][p]  # -8 > -14


def test_build_chain_only_emits_known_aliases():
    for b in mp.BUCKETS:
        chain = mp.build_chain(b, -12.0, -1.0)
        for alias in chain:
            assert alias in ALIAS_TO_BLOB, "unknown module alias %s" % alias


def test_warm_bucket_lifts_low_and_enables_band():
    chain = mp.build_chain("warm", -14.0, -1.0)
    _, le = mp.PARAM_KEYS["eq_low_enable"]
    _, lg = mp.PARAM_KEYS["eq_low_gain"]
    # A nonzero shelf gain must be accompanied by enabling that band.
    assert chain["EQ"][lg] > 0
    assert chain["EQ"][le] is True


def test_transparent_bucket_has_no_eq_shaping():
    # Flat EQ (0/0) -> no EQ block emitted (nothing to enable).
    chain = mp.build_chain("transparent", -14.0, -1.0)
    assert "EQ" not in chain


def test_buckets_have_distinct_eq_fingerprints():
    shapes = {b: (mp.BUCKET_SHAPES[b]["eq_low_gain"],
                  mp.BUCKET_SHAPES[b]["eq_high_gain"]) for b in mp.BUCKETS}
    assert len(set(shapes.values())) == len(mp.BUCKETS)  # all five differ


def test_unknown_bucket_raises():
    with pytest.raises(KeyError):
        mp.build_chain("nonsense", -12.0, -1.0)


def test_input_trim_changes_writes_locked_and_both_sides():
    out = mp.input_trim_changes(-6)
    assert out == {"Gain Input": {"Gain Input Locked": -6.0,
                                  "Gain Input Left": -6.0,
                                  "Gain Input Right": -6.0}}
    merged = mp.input_trim_changes(-2.5, {"MAX": {"Margin": -1.0}})
    assert merged["MAX"] == {"Margin": -1.0}
    assert merged["Gain Input"]["Gain Input Locked"] == -2.5
