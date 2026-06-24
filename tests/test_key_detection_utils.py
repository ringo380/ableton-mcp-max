import ableton_mcp_max.key_detection_utils as kd


def test_pitch_names_and_profiles():
    assert kd.PITCH_NAMES[0] == "C" and kd.PITCH_NAMES[9] == "A"
    assert len(kd.KS_MAJOR) == 12 and len(kd.KS_MINOR) == 12


def test_correlation_constant_is_zero():
    assert kd.correlation([1, 1, 1], [1, 2, 3]) == 0.0


def test_detect_key_c_major_profile_ranks_c_major_first():
    # A histogram shaped like the C-major profile must detect C major.
    top = kd.detect_key(kd.KS_MAJOR, top_n=3)
    assert top[0]["key"] == "C major"
    assert top[0]["root_pc"] == 0 and top[0]["mode"] == "major"
    assert 0.0 <= top[0]["confidence"] <= 1.0


def test_detect_key_a_minor_profile_ranks_a_minor_first():
    # Rotate the minor profile so tonic A (pc 9) sits at bin 9.
    hist = kd.KS_MINOR[-9:] + kd.KS_MINOR[:-9]
    top = kd.detect_key(hist, top_n=5)
    assert top[0]["key"] == "A minor"


def test_detect_key_flat_histogram_low_confidence():
    top = kd.detect_key([1.0] * 12, top_n=5)
    assert top[0]["confidence"] < 0.2


def test_naming_and_relative():
    assert kd.key_name(9, "minor") == "A minor"
    assert kd.relative_key(0, "major") == (9, "minor")
    assert kd.relative_key(9, "minor") == (0, "major")
