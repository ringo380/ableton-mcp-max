import random
import pytest
from ableton_mcp_max.composition_utils import (
    humanize, quantize_to_scale,
)

C_MAJOR = [0, 2, 4, 5, 7, 9, 11]


def _notes():
    return [
        {"pitch": 60, "start_time": 0.0, "duration": 1.0, "velocity": 100},
        {"pitch": 61, "start_time": 1.0, "duration": 1.0, "velocity": 100},
    ]


def test_humanize_bounds_and_reproducible():
    a = humanize(_notes(), timing=0.05, velocity=10, rng=random.Random(5))
    b = humanize(_notes(), timing=0.05, velocity=10, rng=random.Random(5))
    assert a == b
    for orig, h in zip(_notes(), a):
        assert abs(h["start_time"] - orig["start_time"]) <= 0.05 + 1e-9
        assert h["start_time"] >= 0.0
        assert 1.0 <= h["velocity"] <= 127.0


def test_humanize_does_not_mutate_input():
    orig = _notes()
    humanize(orig, timing=0.05, velocity=10, rng=random.Random(5))
    assert orig == _notes()   # input list/dicts untouched


def test_quantize_snaps_pitches_into_scale():
    out = quantize_to_scale(_notes(), 0, C_MAJOR)
    assert [n["pitch"] for n in out] == [60, 60]   # 61 (C#) -> 60 (C)
    # all non-pitch fields preserved
    assert out[1]["start_time"] == 1.0
    assert out[1]["duration"] == 1.0
    assert out[1]["velocity"] == 100


def test_quantize_does_not_mutate_input():
    orig = _notes()
    quantize_to_scale(orig, 0, C_MAJOR)
    assert orig == _notes()


from ableton_mcp_max.composition_utils import arpeggiate, harmonize


def _triad():
    # C E G all at t0 for 1 beat
    return [
        {"pitch": 60, "start_time": 0.0, "duration": 1.0, "velocity": 100},
        {"pitch": 64, "start_time": 0.0, "duration": 1.0, "velocity": 100},
        {"pitch": 67, "start_time": 0.0, "duration": 1.0, "velocity": 100},
    ]


def test_arpeggiate_up_sequences_pitches():
    out = arpeggiate(_triad(), mode="up", rate=0.25, gate=0.9)
    # span 1.0 / rate 0.25 = 4 steps cycling C E G C
    assert [n["pitch"] for n in out] == [60, 64, 67, 60]
    assert [n["start_time"] for n in out] == [0.0, 0.25, 0.5, 0.75]


def test_arpeggiate_down_reverses():
    out = arpeggiate(_triad(), mode="down", rate=0.5, gate=1.0)
    assert [n["pitch"] for n in out][:2] == [67, 64]


def test_harmonize_fixed_intervals_snapped_to_scale():
    src = [{"pitch": 60, "start_time": 0.0, "duration": 1.0, "velocity": 100}]
    out = harmonize(src, 0, C_MAJOR, intervals=[4])   # +4 semis = E (in scale)
    assert sorted(n["pitch"] for n in out) == [60, 64]


def test_harmonize_requires_exactly_one_mode():
    src = [{"pitch": 60, "start_time": 0.0, "duration": 1.0, "velocity": 100}]
    with pytest.raises(ValueError):
        harmonize(src, 0, C_MAJOR, intervals=[4], degrees=[2])
    with pytest.raises(ValueError):
        harmonize(src, 0, C_MAJOR)


def test_harmonize_scale_degrees_stay_diatonic():
    src = [{"pitch": 60, "start_time": 0.0, "duration": 1.0, "velocity": 100}]
    out = harmonize(src, 0, C_MAJOR, degrees=[2])   # a third up the scale = E
    assert sorted(n["pitch"] for n in out) == [60, 64]
