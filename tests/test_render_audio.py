import json

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

    def read_toggle(self, desc):
        return self.toggles.get(desc, "Off")

    def click_toggle(self, desc):
        self.clicks.append(desc)
        self.toggles[desc] = "On" if self.toggles.get(desc) == "Off" else "Off"

    def read_popup(self, desc):
        return self.popups.get(desc, "")

    def set_popup(self, desc, value):
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
    def __init__(self, song_length=232.0, sig=4):
        self.sent = []
        self.song_length = song_length
        self.sig = sig

    def send_command(self, cmd, params=None):
        self.sent.append((cmd, params or {}))
        if cmd == "get_transport":
            return {"song_length": self.song_length,
                    "signature_numerator": self.sig,
                    "loop": True, "loop_start": 0.0, "loop_length": 4.0}
        return {}

    def commands(self):
        return [c for c, _ in self.sent]


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
        sliders={"Start of Rendered Sample (Bar)": 1.0,
                 "Length of Rendered Sample (Bar)": 2.0},
        windows=windows,
    )


@pytest.fixture
def wired(monkeypatch):
    """Fully monkeypatched UI + Live connection. Never touches a real Live."""
    windows = {"Export Audio/Video": False, "Save": False}
    ui = _correct_state(windows)
    conn = _FakeConn()

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
                        lambda base, ext, since: "/tmp/%s.%s" % (base, ext))
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
        "FLAC", "16", "48000")
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
    server.render_audio(None, "track", start_bar=5, end_bar=13)
    assert wired.conn.commands() == ["get_transport", "set_arrangement_loop",
                                     "focus_view"]
    loop = dict(wired.conn.sent[1][1])
    assert loop["start"] == 16.0 and loop["length"] == 32.0
    assert wired.conn.sent[2][1] == {"view": "Arranger"}
    assert ("Edit", "Select Loop") in wired.menus


def test_no_range_renders_the_whole_song(wired):
    wired.sliders["Length of Rendered Sample (Bar)"] = 58.0
    out = json.loads(server.render_audio(None, "track"))
    assert out["ok"] is True
    loop = dict(wired.conn.sent[1][1])
    assert loop["start"] == 0.0 and loop["length"] == 232.0
    assert out["data"]["range"] == {"start_bar": None, "end_bar": None}


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
