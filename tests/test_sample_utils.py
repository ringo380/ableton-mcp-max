from ableton_mcp_max.sample_utils import (
    classify_sample, name_match, icloud_placeholder_path, refine_kind_by_length,
)


def test_classify_kit_adg_under_drums():
    assert classify_sample("Acoustic Kit.adg", "drums/Kits/Acoustic Kit.adg") == "kit"

def test_classify_instrument_adv():
    assert classify_sample("Dark Pad.adv", "instruments/Wavetable/Dark Pad.adv") == "instrument"

def test_classify_one_shot_by_folder_token():
    assert classify_sample("Hit 03.wav", "Samples/One Shots/Hit 03.wav") == "one_shot"

def test_classify_one_shot_by_name_token():
    assert classify_sample("Kick Deep.wav", "Samples/Drums/Kick Deep.wav") == "one_shot"
    assert classify_sample("Snare Tight.wav", "x/Snare Tight.wav") == "one_shot"
    assert classify_sample("Closed Hat.wav", "x/Closed Hat.wav") == "one_shot"
    assert classify_sample("Clap.wav", "x/Clap.wav") == "one_shot"
    assert classify_sample("Vox Stab.wav", "x/Vox Stab.wav") == "one_shot"

def test_classify_loop_by_folder_token():
    assert classify_sample("Groove.wav", "Samples/Loops/Groove.wav") == "loop"

def test_classify_loop_by_bpm_in_name():
    assert classify_sample("Drums 120 bpm.wav", "x/Drums 120 bpm.wav") == "loop"
    assert classify_sample("Beat 90bpm.wav", "x/Beat 90bpm.wav") == "loop"
    assert classify_sample("Top_128.wav", "x/Top_128.wav") == "loop"

def test_classify_loop_by_loop_token():
    assert classify_sample("Perc Loop.wav", "x/Perc Loop.wav") == "loop"

def test_classify_kit_beats_one_shot_priority():
    # a .adg under drums is a kit even if the name says "Kick"
    assert classify_sample("Kick Rack.adg", "drums/Kits/Kick Rack.adg") == "kit"

def test_classify_fallback_by_extension():
    # plain audio file, no tokens -> loop is too strong a guess; default to one_shot
    assert classify_sample("Untitled.wav", "x/Untitled.wav") == "one_shot"
    # non-audio, non-preset extension still returns a valid kind
    assert classify_sample("Notes.txt", "x/Notes.txt") in {"loop", "one_shot", "kit", "instrument"}


def test_name_match_single_term_hit():
    matched, score = name_match("kick", "Kick Deep 01.wav", "Samples/Drums")
    assert matched is True
    assert score >= 1

def test_name_match_or_semantics():
    # any term hitting => matched
    matched, _ = name_match("kick snare", "Snare Tight.wav", "x")
    assert matched is True

def test_name_match_folder_hit():
    matched, _ = name_match("drums", "Untitled.wav", "Samples/Drums/Kicks")
    assert matched is True

def test_name_match_no_hit():
    matched, score = name_match("piano", "Kick.wav", "Samples/Drums")
    assert matched is False
    assert score == 0

def test_name_match_whole_word_bonus_ranks_higher():
    _, exact = name_match("kick", "Kick.wav", "x")
    _, partial = name_match("kick", "Kickstarter Pad.wav", "x")
    assert exact > partial

def test_name_match_case_insensitive():
    matched, _ = name_match("KICK", "kick deep.wav", "x")
    assert matched is True


def test_icloud_placeholder_real_file_returns_none(tmp_path):
    real = tmp_path / "Kick.wav"
    real.write_bytes(b"RIFF....")
    assert icloud_placeholder_path(str(real)) is None

def test_icloud_placeholder_stub_present(tmp_path):
    # dataless: only the .Kick.wav.icloud stub exists, no real file
    stub = tmp_path / ".Kick.wav.icloud"
    stub.write_bytes(b"")
    result = icloud_placeholder_path(str(tmp_path / "Kick.wav"))
    assert result == str(stub)

def test_icloud_placeholder_neither_returns_none(tmp_path):
    # no real file and no stub -> not a known placeholder
    assert icloud_placeholder_path(str(tmp_path / "Ghost.wav")) is None

def test_refine_one_shot_to_loop_when_long():
    # 4 seconds at 120 bpm = 8 beats -> loop
    assert refine_kind_by_length("one_shot", frames=4 * 48000, sample_rate=48000, tempo=120.0) == "loop"

def test_refine_keeps_short_one_shot():
    # 0.25 s at 120 bpm = 0.5 beats -> stays one_shot
    assert refine_kind_by_length("one_shot", frames=12000, sample_rate=48000, tempo=120.0) == "one_shot"

def test_refine_boundary_just_over_two_beats():
    # exactly > 2 beats upgrades; 2 beats at 120 bpm = 1.0 s = 48000 frames
    assert refine_kind_by_length("one_shot", frames=48001, sample_rate=48000, tempo=120.0) == "loop"
    assert refine_kind_by_length("one_shot", frames=48000, sample_rate=48000, tempo=120.0) == "one_shot"

def test_refine_non_one_shot_unchanged():
    assert refine_kind_by_length("kit", frames=4 * 48000, sample_rate=48000, tempo=120.0) == "kit"

def test_refine_zero_sample_rate_unchanged():
    assert refine_kind_by_length("one_shot", frames=48000, sample_rate=0, tempo=120.0) == "one_shot"
