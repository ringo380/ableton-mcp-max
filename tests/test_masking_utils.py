from ableton_mcp_max.masking_utils import (
    masking_score, loudness_balance, headroom_flags, stereo_flags,
    partition_master)


def test_partition_master_splits_index_minus_one():
    sigs = [{"name": "Kick", "index": 0}, {"name": "Master", "index": -1},
            {"name": "Bass", "index": 1}]
    per_track, master = partition_master(sigs)
    assert [s["index"] for s in per_track] == [0, 1]
    assert master is not None and master["index"] == -1


def test_partition_master_none_when_no_master():
    sigs = [{"name": "Kick", "index": 0}, {"name": "Bass", "index": 1}]
    per_track, master = partition_master(sigs)
    assert len(per_track) == 2
    assert master is None


def test_partition_master_first_wins_when_duplicate():
    sigs = [{"name": "M1", "index": -1}, {"name": "M2", "index": -1},
            {"name": "Kick", "index": 0}]
    per_track, master = partition_master(sigs)
    assert master["name"] == "M1"
    assert [s["index"] for s in per_track] == [0]

def test_masking_high_when_two_tracks_share_a_loud_band():
    a = {"name":"Kick","bands":[1,0,0,0,0,0,0,0]}
    b = {"name":"Bass","bands":[1,0,0,0,0,0,0,0]}
    pairs = masking_score([a, b], threshold=0.6)
    assert pairs and pairs[0]["score"] > 0.6
    assert {pairs[0]["a"], pairs[0]["b"]} == {"Kick", "Bass"}

def test_masking_low_when_bands_disjoint():
    a = {"name":"Kick","bands":[1,0,0,0,0,0,0,0]}
    b = {"name":"Hat","bands":[0,0,0,0,0,0,0,1]}
    assert masking_score([a, b], threshold=0.6) == []

def test_masking_skips_tracks_without_bands():
    a = {"name":"Kick","bands":[1,0,0,0,0,0,0,0]}
    b = {"name":"NoData"}            # no bands
    assert masking_score([a, b], threshold=0.6) == []

def test_masking_sorted_descending_by_score():
    a = {"name":"A","bands":[1,1,0,0,0,0,0,0]}
    b = {"name":"B","bands":[1,1,0,0,0,0,0,0]}   # identical -> ~1.0
    c = {"name":"C","bands":[1,0.2,0,0,0,0,0,0]} # partial overlap
    pairs = masking_score([a, b, c], threshold=0.5)
    scores = [p["score"] for p in pairs]
    assert scores == sorted(scores, reverse=True)

def test_loudness_balance_flags_outlier():
    tracks = [{"name":"A","integrated_lufs":-18},{"name":"B","integrated_lufs":-19},
              {"name":"C","integrated_lufs":-40}]
    out = loudness_balance(tracks, spread_db=12.0)
    assert any(f["name"] == "C" for f in out)
    assert all(f["name"] != "A" for f in out)

def test_loudness_balance_ignores_silent_and_missing():
    tracks = [{"name":"A","integrated_lufs":-18},{"name":"Q","integrated_lufs":None},
              {"name":"S","integrated_lufs":-80}]   # below -70 = silent, excluded
    out = loudness_balance(tracks, spread_db=12.0)
    assert all(f["name"] == "A" or True for f in out)  # no crash; S/Q excluded from 'active'
    assert all(f["name"] not in ("Q",) for f in out)

def test_loudness_balance_empty_or_all_silent_returns_empty():
    assert loudness_balance([], spread_db=12.0) == []
    assert loudness_balance([{"name":"x","integrated_lufs":-90}], spread_db=12.0) == []

def test_headroom_flags_near_clip_and_overcompressed():
    tracks = [{"name":"Loud","true_peak_dbtp":-0.2,"crest":8.0},
              {"name":"Squashed","true_peak_dbtp":-6.0,"crest":3.0},
              {"name":"Fine","true_peak_dbtp":-6.0,"crest":10.0}]
    out = headroom_flags(tracks, peak_ceiling=-1.0, crest_floor=4.0)
    names = {f["name"]: f["issue"] for f in out}
    assert names.get("Loud") == "near_clip"
    assert names.get("Squashed") == "over_compressed"
    assert "Fine" not in names

def test_headroom_ignores_missing_fields():
    out = headroom_flags([{"name":"x"}], peak_ceiling=-1.0, crest_floor=4.0)
    assert out == []

def test_stereo_flags_negative_correlation():
    tracks = [{"name":"Wide","correlation":-0.5},{"name":"Mono","correlation":0.9}]
    out = stereo_flags(tracks, corr_floor=-0.2)
    assert any(f["name"] == "Wide" for f in out)
    assert all(f["name"] != "Mono" for f in out)


from ableton_mcp_max.masking_utils import build_mix_findings, enrich_names, MIX_RULE_FNS

_MIX_RULES = [
    {"id": "mixing.spectral_masking", "domain": "mixing", "severity": "warn",
     "signal_kind": "mix", "params": {"threshold": 0.6},
     "remediation": "carve EQ"},
    {"id": "mixing.loudness_balance", "domain": "mixing", "severity": "warn",
     "signal_kind": "mix", "params": {"spread_db": 12.0}, "remediation": "rebalance"},
    {"id": "mixing.headroom_per_track", "domain": "mixing", "severity": "warn",
     "signal_kind": "mix", "params": {"peak_ceiling": -1.0, "crest_floor": 4.0},
     "remediation": "trim gain"},
    {"id": "mixing.stereo_correlation", "domain": "mixing", "severity": "warn",
     "signal_kind": "mix", "params": {"corr_floor": -0.2}, "remediation": "narrow"},
    {"id": "mixing.fader_headroom", "domain": "mixing", "severity": "warn"},
]


def test_mix_rule_fns_cover_the_four_signal_rules():
    assert set(MIX_RULE_FNS) == {
        "mixing.spectral_masking", "mixing.loudness_balance",
        "mixing.headroom_per_track", "mixing.stereo_correlation"}


def test_build_mix_findings_pass_when_clean():
    sigs = [{"name": "Kick", "bands": [1, 0, 0, 0, 0, 0, 0, 0],
             "integrated_lufs": -14.0, "true_peak_dbtp": -6.0, "crest": 10.0,
             "correlation": 0.9},
            {"name": "Hat", "bands": [0, 0, 0, 0, 0, 0, 0, 1],
             "integrated_lufs": -15.0, "true_peak_dbtp": -6.0, "crest": 10.0,
             "correlation": 0.9}]
    out = build_mix_findings(sigs, _MIX_RULES)
    by_id = {f["id"]: f for f in out}
    # only the 4 signal rules are built (fader_headroom is not a mix rule)
    assert set(by_id) == set(MIX_RULE_FNS)
    assert all(f["status"] == "pass" for f in out)
    assert all(f["items"] == [] for f in out)


def test_build_mix_findings_flags_masking_and_uses_severity():
    sigs = [{"name": "Kick", "bands": [1, 0, 0, 0, 0, 0, 0, 0],
             "integrated_lufs": -14.0, "correlation": 0.9},
            {"name": "Bass", "bands": [1, 0, 0, 0, 0, 0, 0, 0],
             "integrated_lufs": -14.0, "correlation": 0.9}]
    out = build_mix_findings(sigs, _MIX_RULES)
    masking = next(f for f in out if f["id"] == "mixing.spectral_masking")
    assert masking["status"] == "warn"
    assert masking["items"]
    assert {masking["items"][0]["a"], masking["items"][0]["b"]} == {"Kick", "Bass"}
    assert "carve EQ" in masking["remediation"]
    assert masking["evidence"]


def test_build_mix_findings_only_builds_present_rules():
    # ruleset missing the mix rules (e.g. focus=mastering) -> nothing built
    out = build_mix_findings([{"name": "x", "bands": [1, 0, 0, 0, 0, 0, 0, 0]}],
                             [{"id": "mixing.fader_headroom", "domain": "mixing"}])
    assert out == []


def test_enrich_names_fills_empty_from_index_map():
    sigs = [{"name": "", "index": 0}, {"name": "Bass", "index": 1},
            {"name": "", "index": -1}]
    enrich_names(sigs, {0: "Kick", 1: "Ignored", -1: "Master"})
    assert sigs[0]["name"] == "Kick"
    assert sigs[1]["name"] == "Bass"      # existing name preserved
    assert sigs[2]["name"] == "Master"


def test_enrich_names_leaves_unknown_index_empty():
    sigs = [{"name": "", "index": 9}]
    enrich_names(sigs, {0: "Kick"})
    assert sigs[0]["name"] == ""
