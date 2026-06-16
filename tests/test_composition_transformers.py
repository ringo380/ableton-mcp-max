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
