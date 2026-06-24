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


def test_histogram_from_notes_weights_and_transpose():
    notes = [
        {"pitch": 60, "duration": 1.0, "velocity": 127},  # C
        {"pitch": 64, "duration": 2.0, "velocity": 127},  # E, double weight
    ]
    h = kd.histogram_from_notes(notes)
    assert h[0] == 1.0 and h[4] == 2.0 and sum(h) == 3.0
    ht = kd.histogram_from_notes(notes, transpose=2)  # up a tone: C->D, E->F#
    assert ht[2] == 1.0 and ht[6] == 2.0


def test_histogram_from_chroma_rotates():
    prof = [0.0] * 12
    prof[0] = 1.0  # energy on C
    out = kd.histogram_from_chroma(prof, transpose=3)  # C -> D#
    assert out[3] == 1.0 and sum(out) == 1.0


def test_combine_weights():
    midi = [1.0] + [0.0] * 11        # all on C
    audio = [0.0] * 9 + [1.0, 0, 0]  # all on A (pc 9)
    only_midi = kd.combine(midi, audio, audio_weight=0.0)
    assert only_midi[0] == 1.0 and only_midi[9] == 0.0
    only_audio = kd.combine(midi, audio, audio_weight=1.0)
    assert only_audio[9] == 1.0 and only_audio[0] == 0.0
    blended = kd.combine(midi, audio, audio_weight=0.5)
    assert abs(blended[0] - 0.5) < 1e-9 and abs(blended[9] - 0.5) < 1e-9


def test_combine_empty_source_passthrough():
    midi = [2.0] + [0.0] * 11
    out = kd.combine(midi, [0.0] * 12, audio_weight=0.5)
    assert abs(out[0] - 1.0) < 1e-9  # normalized midi, audio ignored


def test_histogram_from_notes_skips_muted():
    notes = [
        {"pitch": 60, "duration": 1.0, "velocity": 127},          # C - active
        {"pitch": 64, "duration": 1.0, "velocity": 127, "mute": True},  # E - muted, skipped
        {"pitch": 67, "duration": 1.0, "velocity": 127, "mute": False}, # G - not muted
    ]
    h = kd.histogram_from_notes(notes)
    assert h[0] == 1.0   # C counted
    assert h[4] == 0.0   # E skipped (muted)
    assert h[7] == 1.0   # G counted
