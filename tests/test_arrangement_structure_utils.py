import pytest
from ableton_mcp_max.arrangement_structure_utils import (
    bars_to_beats,
    compute_section_starts,
    validate_section_map,
    tiling_plan,
    sections_from_cues,
    infer_sections,
    section_facts,
    normalize_energy,
)


# --- bars_to_beats --------------------------------------------------------

def test_bars_to_beats_4_4():
    assert bars_to_beats(4, 4, 4) == 16.0

def test_bars_to_beats_6_8():
    # 6/8: beats_per_bar = 6 * (4/8) = 3.0
    assert bars_to_beats(2, 6, 8) == 6.0

def test_bars_to_beats_3_4():
    assert bars_to_beats(1, 3, 4) == 3.0

def test_bars_to_beats_fractional():
    assert bars_to_beats(0.5, 4, 4) == 2.0

def test_bars_to_beats_invalid_num():
    with pytest.raises(ValueError):
        bars_to_beats(4, 0, 4)

def test_bars_to_beats_invalid_den():
    with pytest.raises(ValueError):
        bars_to_beats(4, 4, 0)


# --- compute_section_starts -----------------------------------------------

def test_compute_section_starts_basic_4_4():
    sections = [{"name": "Intro", "length_bars": 4},
                {"name": "Verse", "length_bars": 8}]
    result = compute_section_starts(sections, start_bar=1, num=4, den=4)
    assert result[0]["start_beat"] == 0.0
    assert result[0]["length_beats"] == 16.0
    assert result[1]["start_beat"] == 16.0
    assert result[1]["length_beats"] == 32.0

def test_compute_section_starts_start_bar_offset():
    # start_bar=3 means bar 3 = beat 8.0 in 4/4
    sections = [{"name": "A", "length_bars": 4}]
    result = compute_section_starts(sections, start_bar=3, num=4, den=4)
    assert result[0]["start_beat"] == 8.0

def test_compute_section_starts_6_8():
    sections = [{"name": "A", "length_bars": 2}]
    result = compute_section_starts(sections, start_bar=1, num=6, den=8)
    assert result[0]["length_beats"] == 6.0

def test_compute_section_starts_preserves_original_keys():
    sections = [{"name": "Intro", "length_bars": 4, "clips": []}]
    result = compute_section_starts(sections, start_bar=1, num=4, den=4)
    assert result[0]["clips"] == []
    assert result[0]["name"] == "Intro"

def test_compute_section_starts_does_not_mutate_input():
    sections = [{"length_bars": 4}]
    compute_section_starts(sections, start_bar=1, num=4, den=4)
    assert "start_beat" not in sections[0]


# --- validate_section_map -------------------------------------------------

def test_validate_section_map_valid_minimal():
    validate_section_map([{"name": "A", "length_bars": 4}])  # no error

def test_validate_section_map_valid_with_clips():
    validate_section_map([{
        "name": "A", "length_bars": 4,
        "clips": [{"track_index": 0, "source_slot_index": 0, "repeat": "fill"}]
    }])

def test_validate_section_map_valid_repeat_int():
    validate_section_map([{
        "name": "A", "length_bars": 4,
        "clips": [{"track_index": 0, "source_slot_index": 0, "repeat": 2}]
    }])

def test_validate_section_map_empty_raises():
    with pytest.raises(ValueError, match="non-empty"):
        validate_section_map([])

def test_validate_section_map_not_list_raises():
    with pytest.raises(ValueError):
        validate_section_map("oops")

def test_validate_section_map_missing_name_raises():
    with pytest.raises(ValueError, match="name"):
        validate_section_map([{"length_bars": 4}])

def test_validate_section_map_empty_name_raises():
    with pytest.raises(ValueError, match="name"):
        validate_section_map([{"name": "  ", "length_bars": 4}])

def test_validate_section_map_missing_length_bars_raises():
    with pytest.raises(ValueError, match="length_bars"):
        validate_section_map([{"name": "A"}])

def test_validate_section_map_zero_length_bars_raises():
    with pytest.raises(ValueError, match="positive"):
        validate_section_map([{"name": "A", "length_bars": 0}])

def test_validate_section_map_negative_length_bars_raises():
    with pytest.raises(ValueError, match="positive"):
        validate_section_map([{"name": "A", "length_bars": -4}])

def test_validate_section_map_non_numeric_length_bars_raises():
    with pytest.raises(ValueError, match="number"):
        validate_section_map([{"name": "A", "length_bars": "eight"}])

def test_validate_section_map_clips_not_list_raises():
    with pytest.raises(ValueError, match="clips.*list"):
        validate_section_map([{"name": "A", "length_bars": 4, "clips": "nope"}])

def test_validate_section_map_clip_missing_track_index_raises():
    with pytest.raises(ValueError, match="track_index"):
        validate_section_map([{
            "name": "A", "length_bars": 4,
            "clips": [{"source_slot_index": 0}]
        }])

def test_validate_section_map_clip_negative_track_index_raises():
    with pytest.raises(ValueError, match="track_index"):
        validate_section_map([{
            "name": "A", "length_bars": 4,
            "clips": [{"track_index": -1, "source_slot_index": 0}]
        }])

def test_validate_section_map_bad_repeat_raises():
    with pytest.raises(ValueError, match="repeat"):
        validate_section_map([{
            "name": "A", "length_bars": 4,
            "clips": [{"track_index": 0, "source_slot_index": 0, "repeat": 0}]
        }])

def test_validate_section_map_repeat_float_raises():
    with pytest.raises(ValueError, match="repeat"):
        validate_section_map([{
            "name": "A", "length_bars": 4,
            "clips": [{"track_index": 0, "source_slot_index": 0, "repeat": 1.5}]
        }])


# --- tiling_plan ----------------------------------------------------------

def test_tiling_plan_fill_exact():
    # section = 16 beats, clip = 4 beats -> 4 copies
    assert tiling_plan(16.0, 4.0, "fill") == [0.0, 4.0, 8.0, 12.0]

def test_tiling_plan_fill_partial_no_trailing():
    # section = 10 beats, clip = 4 beats -> 2 copies (floor(10/4)=2)
    assert tiling_plan(10.0, 4.0, "fill") == [0.0, 4.0]

def test_tiling_plan_fill_clip_longer_than_section_one_copy():
    assert tiling_plan(4.0, 16.0, "fill") == [0.0]

def test_tiling_plan_fill_zero_section_still_one_copy():
    # edge: section_beats=0 -> max(1, floor(0/4))=1
    assert tiling_plan(0.0, 4.0, "fill") == [0.0]

def test_tiling_plan_integer_repeat():
    assert tiling_plan(16.0, 4.0, 3) == [0.0, 4.0, 8.0]

def test_tiling_plan_integer_repeat_overrun():
    # repeat=4, clip=8, section=16 -> 4 offsets even though last overruns
    assert tiling_plan(16.0, 8.0, 4) == [0.0, 8.0, 16.0, 24.0]

def test_tiling_plan_zero_clip_length_raises():
    with pytest.raises(ValueError, match="positive"):
        tiling_plan(16.0, 0.0, "fill")

def test_tiling_plan_negative_clip_length_raises():
    with pytest.raises(ValueError, match="positive"):
        tiling_plan(16.0, -4.0, "fill")

def test_tiling_plan_bad_repeat_raises():
    with pytest.raises(ValueError, match="repeat"):
        tiling_plan(16.0, 4.0, "half")


# --- sections_from_cues ---------------------------------------------------

def test_sections_from_cues_two_cues():
    cues = [{"name": "Intro", "time": 0.0},
            {"name": "Verse", "time": 16.0}]
    sections = sections_from_cues(cues, song_end=48.0)
    assert len(sections) == 2
    assert sections[0] == {"name": "Intro", "start_time": 0.0, "end_time": 16.0}
    assert sections[1] == {"name": "Verse", "start_time": 16.0, "end_time": 48.0}

def test_sections_from_cues_single_cue():
    cues = [{"name": "A", "time": 8.0}]
    sections = sections_from_cues(cues, song_end=32.0)
    assert len(sections) == 1
    assert sections[0]["start_time"] == 8.0
    assert sections[0]["end_time"] == 32.0

def test_sections_from_cues_cue_at_zero():
    cues = [{"name": "Start", "time": 0.0}, {"name": "End", "time": 32.0}]
    sections = sections_from_cues(cues, song_end=64.0)
    assert sections[0]["start_time"] == 0.0

def test_sections_from_cues_empty_returns_empty():
    assert sections_from_cues([], song_end=32.0) == []

def test_sections_from_cues_song_end_equals_last_cue_time():
    # song_end == last cue's time means the final section would be zero-length
    # This tests the boundary condition; the fix is in get_arrangement_structure
    # which now adds 4 bars past the last cue before calling sections_from_cues
    cues = [{"name": "Intro", "time": 0.0}, {"name": "Outro", "time": 16.0}]
    sections = sections_from_cues(cues, song_end=16.0)
    # With song_end == last cue time, final section is zero-length - this is the
    # raw behavior that get_arrangement_structure guards against
    assert len(sections) == 2
    assert sections[1]["start_time"] == 16.0
    assert sections[1]["end_time"] == 16.0  # zero-length - confirmed


# --- infer_sections -------------------------------------------------------

def test_infer_sections_two_tracks_same_boundary():
    # Both tracks change at beat 16: two sections [0,16) [16,32)
    clips_by_track = [
        [{"start_time": 0.0, "end_time": 16.0},
         {"start_time": 16.0, "end_time": 32.0}],
        [{"start_time": 0.0, "end_time": 16.0},
         {"start_time": 16.0, "end_time": 32.0}],
    ]
    sections = infer_sections(clips_by_track, song_end=32.0)
    assert len(sections) == 2
    assert sections[0]["start_time"] == 0.0
    assert sections[0]["end_time"] == 16.0
    assert sections[1]["start_time"] == 16.0
    assert sections[1]["name"] == "Section 2"

def test_infer_sections_naming():
    clips_by_track = [
        [{"start_time": 0.0, "end_time": 8.0},
         {"start_time": 8.0, "end_time": 16.0},
         {"start_time": 16.0, "end_time": 24.0}],
    ]
    sections = infer_sections(clips_by_track, song_end=24.0)
    names = [s["name"] for s in sections]
    assert names == ["Section 1", "Section 2", "Section 3"]

def test_infer_sections_empty_arrangement():
    assert infer_sections([], song_end=0.0) == []

def test_infer_sections_no_clips():
    assert infer_sections([[]], song_end=0.0) == []

def test_infer_sections_density_label_present():
    clips_by_track = [
        [{"start_time": 0.0, "end_time": 16.0}],
        [{"start_time": 0.0, "end_time": 16.0}],
    ]
    sections = infer_sections(clips_by_track, song_end=16.0)
    assert "density_label" in sections[0]
    assert sections[0]["density_label"] in ("sparse", "medium", "dense")


# --- section_facts --------------------------------------------------------

def test_section_facts_all_tracks_active():
    span = {"start_time": 0.0, "end_time": 16.0}
    clips_by_track = [
        [{"start_time": 0.0, "end_time": 16.0}],
        [{"start_time": 0.0, "end_time": 8.0}],
    ]
    facts = section_facts(span, clips_by_track)
    assert facts["active_tracks"] == [0, 1]
    assert facts["clip_count"] == 2
    # coverage: track 0 = 16/16=1.0, track 1 = 8/16=0.5, avg=0.75
    assert abs(facts["coverage"] - 0.75) < 1e-6

def test_section_facts_no_overlap():
    span = {"start_time": 32.0, "end_time": 48.0}
    clips_by_track = [
        [{"start_time": 0.0, "end_time": 16.0}],
    ]
    facts = section_facts(span, clips_by_track)
    assert facts["active_tracks"] == []
    assert facts["clip_count"] == 0
    assert facts["coverage"] == 0.0

def test_section_facts_coverage_capped_at_1():
    # Overlapping clips on same track could exceed 1.0 - must cap
    span = {"start_time": 0.0, "end_time": 8.0}
    clips_by_track = [
        [{"start_time": 0.0, "end_time": 8.0},
         {"start_time": 4.0, "end_time": 12.0}],
    ]
    facts = section_facts(span, clips_by_track)
    assert facts["coverage"] <= 1.0


# --- normalize_energy -----------------------------------------------------

def test_normalize_energy_range():
    sections = [
        {"active_tracks": [0, 1], "coverage": 0.5},
        {"active_tracks": [0], "coverage": 1.0},
        {"active_tracks": [], "coverage": 0.0},
    ]
    # Assign raw energy first (active_tracks * coverage)
    for s in sections:
        s["_raw_energy"] = len(s["active_tracks"]) * s["coverage"]
    result = normalize_energy(sections)
    energies = [s["energy"] for s in result]
    assert min(energies) == pytest.approx(0.0)
    assert max(energies) == pytest.approx(1.0)

def test_normalize_energy_single_section():
    sections = [{"active_tracks": [0], "coverage": 0.8}]
    sections[0]["_raw_energy"] = 0.8
    result = normalize_energy(sections)
    # Single section: all-equal -> uniform energy 0.0
    assert result[0]["energy"] == 0.0

def test_normalize_energy_all_equal():
    sections = [{"_raw_energy": 1.0}, {"_raw_energy": 1.0}]
    result = normalize_energy(sections)
    assert result[0]["energy"] == 0.0
    assert result[1]["energy"] == 0.0
