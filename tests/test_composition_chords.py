import pytest
from ableton_mcp_max.composition_utils import build_chord


C_MAJOR = [0, 2, 4, 5, 7, 9, 11]


def test_roman_triads_are_diatonic():
    # C major, octave 3 (C3=60): I = C E G
    assert build_chord("I", 0, C_MAJOR, 3) == [60, 64, 67]
    # ii = D F A (minor, derived from the scale, not hardcoded)
    assert build_chord("ii", 0, C_MAJOR, 3) == [62, 65, 69]
    # V = G B D
    assert build_chord("V", 0, C_MAJOR, 3) == [67, 71, 74]


def test_roman_seventh_adds_fourth_tone():
    # V7 in C major = G B D F
    assert build_chord("V7", 0, C_MAJOR, 3) == [67, 71, 74, 77]


def test_literal_symbol_independent_of_key():
    # Am7 regardless of the song key: A C E G
    assert build_chord("Am7", 0, C_MAJOR, 3) == [69, 72, 76, 79]
    # Cmaj7 = C E G B
    assert build_chord("Cmaj7", 0, C_MAJOR, 3) == [60, 64, 67, 71]


def test_unknown_symbol_raises():
    with pytest.raises(ValueError):
        build_chord("Zsus", 0, C_MAJOR, 3)
