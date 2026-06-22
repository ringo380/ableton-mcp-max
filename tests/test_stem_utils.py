import json
import pytest
from ableton_mcp_max import stem_utils as su


def test_validate_model_default_4stem():
    spec = su.validate_model("htdemucs")
    assert spec["demucs_model"] == "htdemucs"
    assert spec["two_stems"] is None
    assert spec["stems"] == ["drums", "bass", "other", "vocals"]


def test_validate_model_6stem_order():
    spec = su.validate_model("htdemucs_6s")
    assert spec["demucs_model"] == "htdemucs_6s"
    assert spec["stems"] == ["drums", "bass", "other", "vocals", "guitar", "piano"]


def test_validate_model_two_stems():
    spec = su.validate_model("two_stems")
    assert spec["demucs_model"] == "htdemucs"
    assert spec["two_stems"] == "vocals"
    assert spec["stems"] == ["vocals", "no_vocals"]


def test_validate_model_aliases_and_case():
    assert su.validate_model("HTDemucs")["demucs_model"] == "htdemucs"
    assert su.validate_model("4")["stems"] == ["drums", "bass", "other", "vocals"]
    assert su.validate_model("6")["demucs_model"] == "htdemucs_6s"


def test_validate_model_unknown_raises():
    with pytest.raises(ValueError):
        su.validate_model("spleeter")


def test_build_demucs_cmd_4stem():
    cmd = su.build_demucs_cmd("/x/song.wav", "htdemucs", "/tmp/out", "cpu")
    assert cmd[0] == "demucs"
    assert "-n" in cmd and "htdemucs" in cmd
    assert "-o" in cmd and "/tmp/out" in cmd
    assert "-d" in cmd and "cpu" in cmd
    assert "--two-stems" not in " ".join(cmd)
    assert cmd[-1] == "/x/song.wav"


def test_build_demucs_cmd_two_stems_flag():
    cmd = su.build_demucs_cmd("/x/song.wav", "two_stems", "/tmp/out", "mps")
    joined = " ".join(cmd)
    assert "--two-stems=vocals" in joined
    assert "-n htdemucs" in joined


def test_expected_stem_paths_layout_and_location():
    paths = su.expected_stem_paths("/tmp/out", "htdemucs", "song")
    names = [n for n, _ in paths]
    assert names == ["drums", "bass", "other", "vocals"]
    assert paths[0][1] == "/tmp/out/htdemucs/song/drums.wav"


def test_expected_stem_paths_two_stems():
    paths = su.expected_stem_paths("/tmp/out", "two_stems", "song")
    assert [n for n, _ in paths] == ["vocals", "no_vocals"]
    assert paths[1][1] == "/tmp/out/htdemucs/song/no_vocals.wav"


def test_key_to_scale_args():
    assert su.key_to_scale_args("C#", "minor") == ("C#", "minor")
    assert su.key_to_scale_args("A", "major") == ("A", "major")


def test_parse_analysis_full():
    blob = json.dumps({"tempo": 128.4, "key_pitch_class": "F#", "mode": "minor"})
    tempo, key, scale = su.parse_analysis(blob)
    assert tempo == pytest.approx(128.4)
    assert (key, scale) == ("F#", "minor")


def test_parse_analysis_missing_fields_returns_none():
    tempo, key, scale = su.parse_analysis(json.dumps({"tempo": None}))
    assert tempo is None and key is None and scale is None


def test_parse_analysis_bad_json_returns_none_tuple():
    assert su.parse_analysis("not json") == (None, None, None)


def test_parse_analysis_null_json_returns_none_tuple():
    assert su.parse_analysis("null") == (None, None, None)


def test_parse_analysis_array_json_returns_none_tuple():
    assert su.parse_analysis("[1, 2, 3]") == (None, None, None)


def test_resolve_device_auto():
    assert su.resolve_device("auto", "arm64") == "mps"
    assert su.resolve_device("auto", "x86_64") == "cpu"
    assert su.resolve_device("cpu", "arm64") == "cpu"
