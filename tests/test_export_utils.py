import pytest
from ableton_mcp_max import export_utils as eu
from ableton_mcp_max.export_utils import (
    plan_export, clean_render_name, loop_range_for,
)


def _toggle(plan, desc):
    return next(t["want"] for t in plan["toggles"] if t["description"] == desc)


def _popup(plan, desc):
    return next(p["value"] for p in plan["popups"] if p["description"] == desc)


def test_default_plan_is_wav_24_44100_pcm_on_mp3_off():
    p = plan_export()
    assert _popup(p, "File Type") == "WAV"
    assert _popup(p, "Recording Bit Depth") == "24"
    assert _popup(p, "Sample Rate") == "44100"
    assert _toggle(p, "Encode PCM") == "On"
    assert _toggle(p, "Encode MP3") == "Off"
    assert _toggle(p, "Normalize") == "Off"


def test_file_type_mp3_turns_pcm_off_and_mp3_on():
    p = plan_export(file_type="MP3")
    assert _toggle(p, "Encode PCM") == "Off"
    assert _toggle(p, "Encode MP3") == "On"


def test_mp3_flag_alongside_wav_emits_both():
    p = plan_export(file_type="WAV", mp3=True)
    assert _toggle(p, "Encode PCM") == "On"
    assert _toggle(p, "Encode MP3") == "On"


def test_every_managed_toggle_has_an_explicit_want():
    # The executor reads-then-clicks, so a missing want would mean "unknown".
    p = plan_export()
    wants = {t["description"]: t["want"] for t in p["toggles"]}
    for d in ("Include Return and Main Effects", "Render as Loop",
              "Convert to Mono", "Normalize", "Create Analysis File",
              "Encode PCM", "Encode MP3"):
        assert wants[d] in ("On", "Off")


@pytest.mark.parametrize("kw", [
    {"file_type": "OGG"}, {"bit_depth": 12}, {"sample_rate": 12345},
    {"dither": "Loud"},
])
def test_unknown_enum_values_are_rejected(kw):
    with pytest.raises(ValueError):
        plan_export(**kw)


@pytest.mark.parametrize("bad", ["", "a/b", "a:b", "   "])
def test_clean_render_name_rejects(bad):
    with pytest.raises(ValueError):
        clean_render_name(bad)


def test_clean_render_name_passes_and_strips():
    assert clean_render_name("  my track  ") == "my track"


def test_loop_range_bar_math_is_one_based():
    assert loop_range_for(1, 5, 232.0, 4) == (0.0, 16.0)
    assert loop_range_for(5, 13, 232.0, 4) == (16.0, 32.0)


def test_loop_range_honors_time_signature():
    assert loop_range_for(5, 9, 232.0, 3) == (12.0, 12.0)


def test_loop_range_defaults_to_whole_song():
    assert loop_range_for(None, None, 232.0, 4) == (0.0, 232.0)


@pytest.mark.parametrize("args", [(5, 5, 232.0, 4), (9, 5, 232.0, 4),
                                  (None, None, 0.0, 4)])
def test_loop_range_rejects_empty_spans(args):
    with pytest.raises(ValueError):
        loop_range_for(*args)


# --- dropdown item matching (Live check-marks the SELECTED item) -----------

CHECK = u"✔ "


def test_choose_menu_item_matches_the_checkmarked_selected_item():
    names = [CHECK + "WAV", "AIFF", "FLAC"]
    assert eu.choose_menu_item(names, "WAV") == CHECK + "WAV"
    assert eu.choose_menu_item(names, "FLAC") == "FLAC"


def test_choose_menu_item_returns_none_for_a_missing_option():
    assert eu.choose_menu_item(["16", CHECK + "24", "32"], "8") is None
    assert eu.choose_menu_item([], "WAV") is None


def test_choose_menu_item_falls_back_to_live_11_master():
    assert eu.choose_menu_item([CHECK + "Master", "All Individual Tracks"],
                               "Main") == CHECK + "Master"
    assert eu.choose_menu_item([CHECK + "Main"], "Main") == CHECK + "Main"


def test_popup_matches_is_alias_and_checkmark_tolerant():
    assert eu.popup_matches("Main", "Main")
    assert eu.popup_matches("Master", "Main")        # Live 11
    assert eu.popup_matches(CHECK + "WAV", "WAV")
    assert not eu.popup_matches("AIFF", "WAV")


def test_plan_export_drops_the_dither_popup_at_32_bit():
    # Live disables Dither Options at 32-bit float; setting it would no-op and
    # the post-set verify would cancel the render.
    descs = [p["description"] for p in eu.plan_export(bit_depth=32)["popups"]]
    assert "Dither Options" not in descs
    assert "Recording Bit Depth" in descs
    assert "Dither Options" in [
        p["description"] for p in eu.plan_export(bit_depth=24)["popups"]]
