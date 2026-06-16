import random
import pytest
from ableton_mcp_max.composition_utils import (
    build_chord_progression, build_bassline, scale_pitches,
)

C_MAJOR = [0, 2, 4, 5, 7, 9, 11]


def test_chord_progression_exact_layout():
    notes = build_chord_progression(["I", "V"], 0, C_MAJOR, bars=2, octave=3)
    # 2 bars / 2 chords -> 4 beats each; I=C E G at t0, V=G B D at t4
    assert notes == [
        {"pitch": 60, "start_time": 0.0, "duration": 4.0, "velocity": 100},
        {"pitch": 64, "start_time": 0.0, "duration": 4.0, "velocity": 100},
        {"pitch": 67, "start_time": 0.0, "duration": 4.0, "velocity": 100},
        {"pitch": 67, "start_time": 4.0, "duration": 4.0, "velocity": 100},
        {"pitch": 71, "start_time": 4.0, "duration": 4.0, "velocity": 100},
        {"pitch": 74, "start_time": 4.0, "duration": 4.0, "velocity": 100},
    ]


def test_chord_progression_empty_raises():
    with pytest.raises(ValueError):
        build_chord_progression([], 0, C_MAJOR, bars=4, octave=3)


def test_bassline_root_follows_progression():
    notes = build_bassline(progression=["I", "IV"], style="root", root=0,
                           intervals=C_MAJOR, bars=2, octave=1)
    assert [n["pitch"] for n in notes] == [36, 41]   # C1, F1
    assert [n["start_time"] for n in notes] == [0.0, 4.0]


def test_bassline_no_progression_one_root_per_bar():
    notes = build_bassline(progression=None, style="root", root=0,
                           intervals=C_MAJOR, bars=2, octave=1)
    assert [n["pitch"] for n in notes] == [36, 36]
    assert [n["start_time"] for n in notes] == [0.0, 4.0]


def test_bassline_arp_in_chord():
    notes = build_bassline(progression=["I"], style="arp", root=0,
                           intervals=C_MAJOR, bars=1, octave=1, rng=random.Random(1))
    allowed = set(scale_pitches(0, C_MAJOR, 0, 127))
    assert all(n["pitch"] in allowed for n in notes)
    assert len(notes) == 3   # triad arpeggiated


def test_chord_progression_durations_mismatch_raises():
    with pytest.raises(ValueError):
        build_chord_progression(["I", "V"], 0, C_MAJOR, bars=2, octave=3,
                                durations=[4.0])   # wrong length


def test_bassline_walking_quarter_notes():
    notes = build_bassline(progression=["I", "V"], style="walking", root=0,
                           intervals=C_MAJOR, bars=2, octave=1)
    # seg = 4 beats per chord -> 4 quarter notes each = 8 total
    assert len(notes) == 8
    assert [n["start_time"] for n in notes] == [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0]
    # each chord's downbeat is its root: I->C1=36, V->G1=43
    assert notes[0]["pitch"] == 36
    assert notes[4]["pitch"] == 43
    allowed = set(scale_pitches(0, C_MAJOR, 0, 127))
    assert all(n["pitch"] in allowed for n in notes)


def test_bassline_arp_seventh_count():
    # A diatonic seventh chord arpeggiates to 4 notes.
    notes = build_bassline(progression=["V7"], style="arp", root=0,
                           intervals=C_MAJOR, bars=1, octave=1)
    assert len(notes) == 4
