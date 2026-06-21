# tests/test_clipping_utils.py
from ableton_mcp_max.clipping_utils import (
    peak_to_dbfs,
    annotate_meters,
    clipping_flags,
)


def test_peak_to_dbfs_full_scale():
    assert peak_to_dbfs(1.0) == 0.0


def test_peak_to_dbfs_half():
    # 0.5 linear == -6.02 dBFS
    assert abs(peak_to_dbfs(0.5) - (-6.0)) < 0.1


def test_peak_to_dbfs_over_full_scale():
    # a peak above 1.0 reads positive dBFS (clipped)
    assert peak_to_dbfs(2.0) > 0.0


def test_peak_to_dbfs_silence_floor():
    assert peak_to_dbfs(0.0) <= -100.0
    assert peak_to_dbfs(None) <= -100.0


def test_annotate_meters_marks_clipping():
    meters = [
        {"name": "Bass", "index": 0, "track_type": "regular", "peak": 0.5},
        {"name": "Drums", "index": 1, "track_type": "regular", "peak": 1.1},
    ]
    out = annotate_meters(meters)
    by_name = {m["name"]: m for m in out}
    assert by_name["Bass"]["is_clipping"] is False
    assert by_name["Bass"]["overshoot_db"] == 0.0
    assert by_name["Drums"]["is_clipping"] is True
    assert by_name["Drums"]["overshoot_db"] > 0.0


def test_annotate_meters_returns_all_entities():
    meters = [{"name": "A", "index": 0, "peak": 0.1},
              {"name": "B", "index": 1, "peak": 0.2}]
    assert len(annotate_meters(meters)) == 2


def test_annotate_meters_at_exactly_zero_dbfs_clips():
    # peak == 1.0 -> 0.0 dBFS, ceiling default 0.0, >= so clipping
    out = annotate_meters([{"name": "M", "index": -1, "peak": 1.0}])
    assert out[0]["is_clipping"] is True


def test_clipping_flags_filters_and_sorts():
    meters = [
        {"name": "Bass", "index": 0, "peak": 0.5},       # ok
        {"name": "Drums", "index": 1, "peak": 1.1},      # clip ~+0.8
        {"name": "Lead", "index": 2, "peak": 2.0},       # clip ~+6
    ]
    out = clipping_flags(meters)
    assert [m["name"] for m in out] == ["Lead", "Drums"]
    assert all(m["is_clipping"] for m in out)


def test_clipping_flags_custom_ceiling():
    # ceiling -3 dBFS: 0.5 (-6) ok, 0.8 (~-1.9) clips
    meters = [{"name": "A", "index": 0, "peak": 0.5},
              {"name": "B", "index": 1, "peak": 0.8}]
    out = clipping_flags(meters, ceiling_db=-3.0)
    assert [m["name"] for m in out] == ["B"]


def test_clipping_flags_empty_when_clean():
    assert clipping_flags([{"name": "A", "index": 0, "peak": 0.3}]) == []
