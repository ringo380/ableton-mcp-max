import pytest
from ableton_mcp_max.composition_utils import (
    parse_key, parse_scale, resolve_key_scale, scale_pitches,
    degree_to_pitch, snap_to_scale, SCALE_INTERVALS,
    resolve_live_scale_name, resolve_song_scale, LIVE_SCALE_NAMES,
)


def test_parse_key_accepts_sharps_flats_case():
    assert parse_key("C") == 0
    assert parse_key("c#") == 1
    assert parse_key("Db") == 1
    assert parse_key("B") == 11
    assert parse_key("eb") == 3


def test_parse_key_unknown_raises():
    with pytest.raises(ValueError):
        parse_key("H")


def test_parse_scale_named_and_aliases():
    assert parse_scale("major") == [0, 2, 4, 5, 7, 9, 11]
    assert parse_scale("minor") == [0, 2, 3, 5, 7, 8, 10]   # alias -> natural_minor
    assert parse_scale("Dorian") == [0, 2, 3, 5, 7, 9, 10]


def test_resolve_explicit_params_win():
    root, intervals = resolve_key_scale(key="D", scale="dorian", song_scale=None)
    assert root == 2
    assert intervals == [0, 2, 3, 5, 7, 9, 10]


def test_resolve_reads_set_when_omitted():
    song = {"root_note": 7, "scale_intervals": [0, 2, 4, 5, 7, 9, 11], "scale_name": "Major"}
    root, intervals = resolve_key_scale(key=None, scale=None, song_scale=song)
    assert root == 7
    assert intervals == [0, 2, 4, 5, 7, 9, 11]


def test_resolve_falls_back_to_c_minor():
    root, intervals = resolve_key_scale(key=None, scale=None, song_scale=None)
    assert root == 0
    assert intervals == SCALE_INTERVALS["natural_minor"]


def test_scale_pitches_filters_to_members_in_range():
    pitches = scale_pitches(0, [0, 4, 7], 60, 72)   # C, E, G
    assert pitches == [60, 64, 67, 72]


def test_degree_to_pitch_wraps_octaves():
    # C major, octave 3 -> C3 = 60
    assert degree_to_pitch(0, [0, 2, 4, 5, 7, 9, 11], 0, 3) == 60
    assert degree_to_pitch(0, [0, 2, 4, 5, 7, 9, 11], 7, 3) == 72  # next octave root


def test_snap_to_scale_moves_to_nearest_member():
    # C major: C#(61) -> C(60), prefer lower on tie
    assert snap_to_scale(61, 0, [0, 2, 4, 5, 7, 9, 11]) == 60
    assert snap_to_scale(60, 0, [0, 2, 4, 5, 7, 9, 11]) == 60


def test_parse_scale_unknown_raises():
    with pytest.raises(ValueError):
        parse_scale("nope")


def test_snap_to_scale_nearest_above():
    # C major: D#(63) -> E(64) is the nearest in-scale tone above; D(62) is also
    # distance 1 below, and downward is preferred on a tie -> D
    assert snap_to_scale(63, 0, [0, 2, 4, 5, 7, 9, 11]) == 62


def test_snap_to_scale_pure_above_when_below_farther():
    # C major: F#(66) -> G(67) (dist 1 above) vs F(65) (dist 1 below) -> tie -> F
    # Use A#(70): nearest are A(69, below dist1) and B(71, above dist1) -> tie -> A
    assert snap_to_scale(70, 0, [0, 2, 4, 5, 7, 9, 11]) == 69


def test_degree_to_pitch_non_root_degree():
    # C major octave 3: degree 2 -> E3 = 64
    assert degree_to_pitch(0, [0, 2, 4, 5, 7, 9, 11], 2, 3) == 64


def test_degree_to_pitch_empty_intervals_raises():
    with pytest.raises(ValueError):
        degree_to_pitch(0, [], 0, 3)


def test_snap_to_scale_empty_intervals_raises():
    with pytest.raises(ValueError):
        snap_to_scale(60, 0, [])


def test_resolve_key_only_defaults_major():
    root, intervals = resolve_key_scale(key="D", scale=None, song_scale=None)
    assert root == 2
    assert intervals == [0, 2, 4, 5, 7, 9, 11]


def test_resolve_scale_only_defaults_root_c():
    root, intervals = resolve_key_scale(key=None, scale="dorian", song_scale=None)
    assert root == 0
    assert intervals == [0, 2, 3, 5, 7, 9, 10]


def test_resolve_live_scale_name_display_names_pass_through():
    assert resolve_live_scale_name("Major") == "Major"
    assert resolve_live_scale_name("Minor Blues") == "Minor Blues"
    assert resolve_live_scale_name("Harmonic Minor") == "Harmonic Minor"
    assert resolve_live_scale_name("Dorian #4") == "Dorian #4"
    assert resolve_live_scale_name("8-Tone Spanish") == "8-Tone Spanish"


def test_resolve_live_scale_name_aliases_and_normalization():
    # composition vocabulary + synonyms map to Live's display names
    assert resolve_live_scale_name("minor") == "Minor"
    assert resolve_live_scale_name("natural_minor") == "Minor"
    assert resolve_live_scale_name("aeolian") == "Minor"
    assert resolve_live_scale_name("ionian") == "Major"
    assert resolve_live_scale_name("blues") == "Minor Blues"
    assert resolve_live_scale_name("minor_pent") == "Minor Pentatonic"
    assert resolve_live_scale_name("pentatonic") == "Major Pentatonic"
    # punctuation / case / separators are ignored
    assert resolve_live_scale_name("whole tone") == "Whole Tone"
    assert resolve_live_scale_name("HALF-WHOLE DIM.") == "Half-whole Dim."


def test_resolve_live_scale_name_unknown_raises():
    with pytest.raises(ValueError):
        resolve_live_scale_name("chromatic")  # no Live scale equivalent
    with pytest.raises(ValueError):
        resolve_live_scale_name("bogus")


def test_resolve_song_scale_returns_root_and_live_name():
    assert resolve_song_scale("A", "minor") == (9, "Minor")
    assert resolve_song_scale("c#", "Dorian") == (1, "Dorian")
    assert resolve_song_scale("Eb", "major") == (3, "Major")


def test_live_scale_names_self_resolve():
    # every advertised Live name must resolve back to itself
    for n in LIVE_SCALE_NAMES:
        assert resolve_live_scale_name(n) == n
