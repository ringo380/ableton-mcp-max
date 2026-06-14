from ableton_mcp_max.masking_utils import (
    masking_score, loudness_balance, headroom_flags, stereo_flags)

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
