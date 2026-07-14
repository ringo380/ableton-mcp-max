import json
import os

import pytest

from ableton_mcp_max import server


class _FakeUI:
    """Records AX calls and answers reads from a scripted dialog state."""

    def __init__(self, toggles=None, popups=None, sliders=None, windows=None):
        self.toggles = dict(toggles or {})
        self.popups = dict(popups or {})
        self.sliders = dict(sliders or {})
        self.windows = windows if windows is not None else {}
        self.clicks = []
        self.menus = []
        self.pressed = []

        self.ops = []

    def read_toggle(self, desc):
        return self.toggles.get(desc, "Off")

    def click_toggle(self, desc):
        self.clicks.append(desc)
        self.ops.append(("toggle", desc))
        self.toggles[desc] = "On" if self.toggles.get(desc) == "Off" else "Off"

    def read_popup(self, desc):
        return self.popups.get(desc, "")

    def set_popup(self, desc, value):
        self.ops.append(("popup", desc))
        self.popups[desc] = value

    def read_slider(self, desc):
        return self.sliders.get(desc)

    def press(self, desc):
        self.pressed.append(desc)
        if desc == "Export":
            self.windows["Save"] = True
        if desc == "Cancel":
            self.windows["Export Audio/Video"] = False


class _FakeConn:
    def __init__(self, song_length=232.0, sig=4, windows=None):
        self.sent = []
        self.song_length = song_length
        self.sig = sig
        self.windows = windows if windows is not None else {}

    def send_command(self, cmd, params=None):
        # A modal export dialog stops Live pumping scheduled messages, so a
        # Remote Script command issued while one is up would block, then fail.
        if any(self.windows.values()):
            raise RuntimeError("Live is busy (a modal dialog is open)")
        self.sent.append((cmd, params or {}))
        if cmd == "get_transport":
            return {"song_length": self.song_length,
                    "signature_numerator": self.sig,
                    "loop": True, "loop_start": 0.0, "loop_length": 4.0}
        return {}

    def commands(self):
        return [c for c, _ in self.sent]


def _range_sliders(start_beats, length_beats, sig=4):
    """The six range boxes as Live seeds them: start is 1-based, length 0-based."""
    def split(beats, base):
        bars, rest = divmod(beats, sig)
        beat, rest = divmod(rest, 1.0)
        return [bars + base, beat + base, round(rest / 0.25) + base]

    s = split(float(start_beats), 1)
    ln = split(float(length_beats), 0)
    names = ("Bar", "Beat", "Sixteenths")
    out = {}
    for i, n in enumerate(names):
        out["Start of Rendered Sample (%s)" % n] = float(s[i])
        out["Length of Rendered Sample (%s)" % n] = float(ln[i])
    return out


def _correct_state(windows):
    """A dialog whose state already matches plan_export()'s defaults."""
    return _FakeUI(
        toggles={"Include Return and Main Effects": "On",
                 "Render as Loop": "Off",
                 "Convert to Mono": "Off",
                 "Normalize": "Off",
                 "Create Analysis File": "On",
                 "Encode PCM": "On",
                 "Encode MP3": "Off"},
        popups={"Rendered Track Chooser": "Main",
                "Sample Rate": "44100",
                "File Type": "WAV",
                "Recording Bit Depth": "24",
                "Dither Options": "No Dither"},
        sliders=_range_sliders(0.0, 8.0),      # bars 1..3
        windows=windows,
    )


@pytest.fixture
def wired(monkeypatch):
    """Fully monkeypatched UI + Live connection. Never touches a real Live."""
    windows = {"Export Audio/Video": False, "Save": False}
    ui = _correct_state(windows)
    conn = _FakeConn(windows=windows)

    monkeypatch.setattr(server, "_live_app_and_pid",
                        lambda: ("/Applications/Live.app", 123))
    monkeypatch.setattr(server, "_app_name", lambda app: "Ableton Live 12 Suite")
    monkeypatch.setattr(server, "_osa", lambda s: None)
    monkeypatch.setattr(server, "_keystroke", lambda s: None)
    monkeypatch.setattr(server, "_rsleep", lambda s: None)
    monkeypatch.setattr(server, "_export_ui", ui)
    monkeypatch.setattr(server, "get_ableton_connection", lambda: conn)
    monkeypatch.setattr(server, "_live_window_exists",
                        lambda title: bool(windows.get(title)))
    monkeypatch.setattr(server, "_click_edit_menu",
                        lambda item: ui.menus.append(("Edit", item)))

    def _escape():
        ui.pressed.append("Escape")
        windows["Save"] = False

    monkeypatch.setattr(server, "_live_press_escape", _escape)

    def _open():
        ui.menus.append(("File", "Export Audio/Video..."))
        windows["Export Audio/Video"] = True
        return True

    monkeypatch.setattr(server, "_open_export_dialog", _open)

    def _finish():
        windows["Export Audio/Video"] = False
        windows["Save"] = False

    monkeypatch.setattr(server, "_press_return", _finish)
    monkeypatch.setattr(server, "_resolve_render_path",
                        lambda base, exts, since: "/tmp/%s.%s" % (base, exts[0]))
    monkeypatch.setattr(server, "_file_stats", lambda path: (1234, 4.0))

    ui.conn = conn
    ui.windows = windows
    return ui


# --- the idempotency contract --------------------------------------------

def test_toggle_already_correct_is_not_clicked(wired):
    wired.toggles["Normalize"] = "Off"
    server._apply_toggles([{"description": "Normalize", "want": "Off"}], wired)
    assert wired.clicks == []


def test_toggle_mismatched_is_clicked_once(wired):
    wired.toggles["Normalize"] = "On"
    server._apply_toggles([{"description": "Normalize", "want": "Off"}], wired)
    assert wired.clicks == ["Normalize"]
    assert wired.toggles["Normalize"] == "Off"


def test_render_audio_does_not_churn_an_already_correct_dialog(wired):
    out = json.loads(server.render_audio(None, "track", start_bar=1, end_bar=3))
    assert out["ok"] is True
    assert wired.clicks == []


# --- validation happens before any UI ------------------------------------

def test_render_audio_rejects_bad_name_before_touching_the_ui(wired):
    out = json.loads(server.render_audio(None, "a/b"))
    assert out["ok"] is False
    assert wired.menus == [] and wired.pressed == []
    assert wired.conn.sent == []


def test_render_audio_rejects_bad_enum_before_touching_the_ui(wired):
    out = json.loads(server.render_audio(None, "track", file_type="OGG"))
    assert out["ok"] is False
    assert wired.menus == [] and wired.pressed == []
    assert wired.conn.sent == []


# --- failure paths --------------------------------------------------------

def test_render_audio_errors_when_dialog_never_appears(monkeypatch, wired):
    monkeypatch.setattr(server, "_open_export_dialog", lambda: False)
    out = json.loads(server.render_audio(None, "track"))
    assert out["ok"] is False
    assert "Export" in out["error"]
    assert "Export" not in wired.pressed


def test_verification_mismatch_cancels_and_never_exports(wired):
    # The dialog refuses a popup set (sticky state) -> post-set verify fails.
    def _stuck(desc, value):
        if desc == "File Type":
            return
        wired.popups[desc] = value

    wired.set_popup = _stuck
    wired.popups["File Type"] = "AIFF"
    out = json.loads(server.render_audio(None, "track", start_bar=1, end_bar=3))
    assert out["ok"] is False
    assert "Cancel" in wired.pressed
    assert "Export" not in wired.pressed


def test_range_mismatch_cancels_and_never_exports(wired):
    wired.sliders["Start of Rendered Sample (Bar)"] = 7.0
    out = json.loads(server.render_audio(None, "track", start_bar=1, end_bar=3))
    assert out["ok"] is False
    assert "Cancel" in wired.pressed
    assert "Export" not in wired.pressed


def test_completion_timeout_reports_rendered_false(monkeypatch, wired):
    monkeypatch.setattr(server, "_press_return", lambda: None)  # windows stay up
    out = json.loads(server.render_audio(None, "track", start_bar=1, end_bar=3,
                                         timeout=0.0))
    assert out["ok"] is False
    assert out["rendered"] is False
    assert "path" not in out


# --- plan_export's extra keys are consumed --------------------------------

def test_render_audio_returns_the_planned_format(wired):
    out = json.loads(server.render_audio(None, "track", start_bar=1, end_bar=3,
                                         file_type="FLAC", bit_depth=16,
                                         sample_rate=48000))
    data = out["data"]
    assert (data["file_type"], data["bit_depth"], data["sample_rate"]) == (
        "FLAC", 16, 48000)
    assert data["rendered"] is True
    assert data["path"] == "/tmp/track.flac"
    assert data["extra_paths"] == []
    assert data["range"] == {"start_bar": 1, "end_bar": 3}
    assert data["bytes"] == 1234


def test_mp3_alongside_wav_reports_both_files(wired):
    out = json.loads(server.render_audio(None, "track", start_bar=1, end_bar=3,
                                         mp3=True))
    data = out["data"]
    assert data["path"] == "/tmp/track.wav"
    assert data["extra_paths"] == ["/tmp/track.mp3"]
    assert wired.toggles["Encode MP3"] == "On"
    assert wired.toggles["Encode PCM"] == "On"


def test_mp3_only_renders_the_mp3(wired):
    out = json.loads(server.render_audio(None, "track", start_bar=1, end_bar=3,
                                         file_type="MP3"))
    data = out["data"]
    assert data["path"] == "/tmp/track.mp3"
    assert data["extra_paths"] == []
    assert data["pcm"] is False and data["mp3"] is True


# --- the render range is established BEFORE the dialog opens --------------

def test_range_is_seeded_via_loop_then_focus_then_select_loop(wired):
    wired.sliders.update(_range_sliders(16.0, 32.0))
    server.render_audio(None, "track", start_bar=5, end_bar=13)
    assert wired.conn.commands() == ["get_transport", "set_arrangement_loop",
                                     "focus_view", "set_arrangement_loop"]
    loop = dict(wired.conn.sent[1][1])
    assert loop["start"] == 16.0 and loop["length"] == 32.0
    assert wired.conn.sent[2][1] == {"view": "Arranger"}
    assert ("Edit", "Select Loop") in wired.menus


def test_no_range_renders_the_whole_song(wired):
    wired.sliders.update(_range_sliders(0.0, 232.0))
    out = json.loads(server.render_audio(None, "track"))
    assert out["ok"] is True
    loop = dict(wired.conn.sent[1][1])
    assert loop["start"] == 0.0 and loop["length"] == 232.0
    assert out["data"]["range"] == {"start_bar": None, "end_bar": None}


# --- range verification covers non-bar-aligned spans (the default path) ----

def test_whole_song_non_bar_aligned_range_is_verified(monkeypatch, wired):
    wired.conn.song_length = 230.5           # 57 bars + 2 beats + 2 sixteenths
    wired.sliders.update(_range_sliders(0.0, 230.5))
    out = json.loads(server.render_audio(None, "track"))
    assert out["ok"] is True
    check = out["data"]["range_check"]
    assert check["verified"] is True
    assert check["length_beats"] == 230.5


def test_whole_song_non_bar_aligned_mismatch_cancels(wired):
    wired.conn.song_length = 230.5
    wired.sliders.update(_range_sliders(0.0, 226.5))   # a bar short
    out = json.loads(server.render_audio(None, "track"))
    assert out["ok"] is False
    assert "Cancel" in wired.pressed
    assert "Export" not in wired.pressed


def test_unreadable_range_sliders_proceed_unverified(wired):
    wired.sliders["Length of Rendered Sample (Sixteenths)"] = None
    out = json.loads(server.render_audio(None, "track", start_bar=1, end_bar=3))
    assert out["ok"] is True
    assert out["data"]["range_check"]["verified"] is False


# --- toggles are applied BEFORE popups ------------------------------------

def test_toggles_are_applied_before_popups(wired):
    # Encode PCM Off disables the format popups in Live, so it must be fixed
    # before any popup is set.
    wired.toggles["Encode PCM"] = "Off"
    wired.popups["File Type"] = "AIFF"
    out = json.loads(server.render_audio(None, "track", start_bar=1, end_bar=3))
    assert out["ok"] is True
    kinds = [k for k, _ in wired.ops]
    assert kinds.index("toggle") < kinds.index("popup")
    assert ("toggle", "Encode PCM") in wired.ops
    assert wired.ops.index(("toggle", "Encode PCM")) < kinds.index("popup")


# --- the save panel's Replace? sheet --------------------------------------

def test_existing_file_replace_sheet_is_confirmed(monkeypatch, wired):
    state = {"returns": 0}

    def _return():
        state["returns"] += 1
        if state["returns"] >= 2:            # 1st Return raises the sheet
            wired.windows["Export Audio/Video"] = False
            wired.windows["Save"] = False

    monkeypatch.setattr(server, "_press_return", _return)
    out = json.loads(server.render_audio(None, "track", start_bar=1, end_bar=3))
    assert out["ok"] is True
    assert out["data"]["rendered"] is True
    assert state["returns"] == 2


def test_stuck_save_panel_still_times_out(monkeypatch, wired):
    monkeypatch.setattr(server, "_press_return", lambda: None)
    out = json.loads(server.render_audio(None, "track", start_bar=1, end_bar=3,
                                         timeout=0.0))
    assert out["ok"] is False
    assert out["rendered"] is False


# --- the user's arrangement loop is restored ------------------------------

def _loop_writes(conn):
    return [p for c, p in conn.sent if c == "set_arrangement_loop"]


def test_loop_is_restored_on_success(wired):
    wired.sliders.update(_range_sliders(16.0, 32.0))
    out = json.loads(server.render_audio(None, "track", start_bar=5, end_bar=13))
    assert out["ok"] is True
    writes = _loop_writes(wired.conn)
    assert writes[0]["start"] == 16.0 and writes[0]["length"] == 32.0
    assert writes[-1] == {"enabled": True, "start": 0.0, "length": 4.0}


def test_loop_is_restored_on_the_timeout_path(monkeypatch, wired):
    monkeypatch.setattr(server, "_press_return", lambda: None)
    out = json.loads(server.render_audio(None, "track", start_bar=1, end_bar=3,
                                         timeout=0.0))
    assert out["ok"] is False
    assert _loop_writes(wired.conn)[-1] == {"enabled": True, "start": 0.0,
                                            "length": 4.0}


def test_loop_is_restored_when_the_dialog_is_cancelled(wired):
    wired.sliders["Start of Rendered Sample (Bar)"] = 7.0
    out = json.loads(server.render_audio(None, "track", start_bar=1, end_bar=3))
    assert out["ok"] is False
    assert _loop_writes(wired.conn)[-1] == {"enabled": True, "start": 0.0,
                                            "length": 4.0}


# --- path resolution (mdfind + extension + mtime) -------------------------

def test_resolve_render_path_filters_by_extension_and_mtime(monkeypatch, tmp_path):
    fresh = tmp_path / "mix.wav"
    stale = tmp_path / "old" / "mix.wav"
    other = tmp_path / "mix.aif"
    stale.parent.mkdir()
    for p in (fresh, stale, other):
        p.write_bytes(b"x")
    os.utime(str(stale), (1000.0, 1000.0))
    os.utime(str(fresh), (5000.0, 5000.0))
    os.utime(str(other), (5000.0, 5000.0))

    found = [str(stale), str(fresh), str(other), str(tmp_path / "mix.txt")]
    monkeypatch.setattr(server, "_mdfind_named", lambda base: found)

    assert server._resolve_render_path("mix", ("wav",), 4000.0) == str(fresh)
    # the stale same-named file is never claimed
    assert server._resolve_render_path("mix", ("wav",), 6000.0) == ""
    # AIFF accepts either spelling
    assert server._resolve_render_path("mix", ("aif", "aiff"),
                                       4000.0) == str(other)
    assert server._resolve_render_path("mix", ("flac",), 0.0) == ""


def test_path_unresolved_still_reports_a_completed_render(monkeypatch, wired):
    monkeypatch.setattr(server, "_resolve_render_path",
                        lambda base, ext, since: "")
    out = json.loads(server.render_audio(None, "track", start_bar=1, end_bar=3))
    assert out["ok"] is True
    assert out["data"]["path"] is None
    assert out["data"]["rendered"] is True


def test_no_running_live_is_an_error(monkeypatch, wired):
    monkeypatch.setattr(server, "_live_app_and_pid", lambda: (None, None))
    out = json.loads(server.render_audio(None, "track"))
    assert out["ok"] is False
    assert wired.pressed == []


# --- the dropdown is a separate window; the selected item is check-marked ---

class _FakeAX:
    """AppleScript seam for the real _ExportUI (no fake dialog object)."""

    def __init__(self, items):
        self.items = list(items)
        self.scripts = []
        self.escapes = 0

    def osa(self, script):
        self.scripts.append(script)

    def osa_get(self, script):
        return "\n".join(self.items)

    def clicked_items(self):
        return [s for s in self.scripts if "menu item" in s]


@pytest.fixture
def ax(monkeypatch):
    fake = _FakeAX([])
    monkeypatch.setattr(server, "_osa", fake.osa)
    monkeypatch.setattr(server, "_osa_get", fake.osa_get)
    monkeypatch.setattr(server, "_rsleep", lambda s: None)

    def _esc():
        fake.escapes += 1

    monkeypatch.setattr(server, "_live_press_escape", _esc)
    return fake


CHECK = u"✔ "


def test_set_popup_matches_the_already_selected_checkmarked_item(ax):
    # The idempotent re-run: WAV is already selected, so Live names it
    # "<check> WAV" - an exact-name match would miss it.
    ax.items = [CHECK + "WAV", "AIFF", "FLAC"]
    server._ExportUI().set_popup("File Type", "WAV")
    assert ax.escapes == 0
    clicked = ax.clicked_items()
    assert len(clicked) == 1
    assert (CHECK + "WAV") in clicked[0]


def test_set_popup_clicks_an_unselected_item_by_its_plain_name(ax):
    ax.items = [CHECK + "WAV", "AIFF", "FLAC"]
    server._ExportUI().set_popup("File Type", "FLAC")
    clicked = ax.clicked_items()
    assert len(clicked) == 1 and '"FLAC"' in clicked[0]


def test_set_popup_fails_loudly_when_the_item_is_missing(ax):
    ax.items = [CHECK + "24", "16", "32"]
    with pytest.raises(RuntimeError) as e:
        server._ExportUI().set_popup("Recording Bit Depth", "8")
    assert "8" in str(e.value)
    assert ax.escapes == 1                 # the open dropdown is closed again
    assert ax.clicked_items() == []


def test_set_popup_accepts_the_live_11_master_naming(ax):
    ax.items = [CHECK + "Master", "All Individual Tracks", "Selected Tracks Only"]
    server._ExportUI().set_popup("Rendered Track Chooser", "Main")
    clicked = ax.clicked_items()
    assert len(clicked) == 1 and (CHECK + "Master") in clicked[0]
    assert ax.escapes == 0


def test_verify_dialog_state_accepts_master_for_main(wired):
    wired.popups["Rendered Track Chooser"] = "Master"      # Live 11
    plan = server.plan_export()
    assert server._verify_dialog_state(wired, plan) == []


def test_unknown_popup_option_cancels_and_never_exports(wired):
    def _boom(desc, value):
        if desc == "Sample Rate":
            raise RuntimeError("The 'Sample Rate' dropdown has no '44100' option")
        wired.popups[desc] = value

    wired.set_popup = _boom
    out = json.loads(server.render_audio(None, "track", start_bar=1, end_bar=3))
    assert out["ok"] is False
    assert "Cancel" in wired.pressed
    assert "Export" not in wired.pressed
    assert _loop_writes(wired.conn)[-1] == {"enabled": True, "start": 0.0,
                                            "length": 4.0}


# --- 32-bit float has no dither popup -------------------------------------

def test_32_bit_render_does_not_touch_the_disabled_dither_popup(wired):
    del wired.popups["Dither Options"]          # Live disables it at 32 bit
    out = json.loads(server.render_audio(None, "track", start_bar=1, end_bar=3,
                                         bit_depth=32))
    assert out["ok"] is True
    assert ("popup", "Dither Options") not in wired.ops
    assert out["data"]["bit_depth"] == 32


# --- a failure must not leave Live sitting in a modal dialog ---------------

def test_dialog_is_dismissed_and_the_loop_restored_on_the_timeout_path(
        monkeypatch, wired):
    monkeypatch.setattr(server, "_press_return", lambda: None)   # windows stay up
    out = json.loads(server.render_audio(None, "track", start_bar=1, end_bar=3,
                                         timeout=0.0))
    assert out["ok"] is False and out["rendered"] is False
    assert wired.windows == {"Export Audio/Video": False, "Save": False}
    # the restore only lands because the modal dialog was dismissed FIRST
    assert _loop_writes(wired.conn)[-1] == {"enabled": True, "start": 0.0,
                                            "length": 4.0}


def test_dialog_is_dismissed_when_the_save_panel_never_appears(wired):
    def _press(desc):
        wired.pressed.append(desc)
        if desc == "Cancel":
            wired.windows["Export Audio/Video"] = False

    wired.press = _press                     # Export never raises the Save panel
    out = json.loads(server.render_audio(None, "track", start_bar=1, end_bar=3))
    assert out["ok"] is False
    assert out["rendered"] is False
    assert "Save panel" in out["error"]
    assert wired.windows["Export Audio/Video"] is False
    assert "Cancel" in wired.pressed
    assert _loop_writes(wired.conn)[-1] == {"enabled": True, "start": 0.0,
                                            "length": 4.0}
