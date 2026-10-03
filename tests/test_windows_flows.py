"""Windows UI flows (save_set / save_set_as / restart_live) against a FAKE
win_ui - no real windows are touched. Runs on any OS."""
import os

import pytest

from ableton_mcp_max import server
from ableton_mcp_max.export_utils import clean_render_name, strip_menu_check, \
    choose_menu_item
from ableton_mcp_max.save_utils import clean_set_name

NOSLEEP = lambda s: None
EXE = r"C:\ProgramData\Ableton\Live 12 Suite\Program\Ableton Live 12 Suite.exe"


class FakeWin:
    LIVE_WINDOW_CLASS = "Ableton Live Window Class"
    IDOK, IDCANCEL, IDYES = 1, 2, 6

    def __init__(self, title="Untitled - Ableton Live 12 Suite", folder=""):
        self.pid = 4242
        self.main = 100
        self.title = title
        self.folder = folder
        self.dialog = None              # (hwnd, title) of an open dialog
        self.alive = True
        self.calls = []
        self.on_menu = {}               # item -> callable
        self.on_save = None             # name -> None
        self.on_close = None

    # process
    def listening_pid(self, port):
        return self.pid if self.alive else None

    def process_image(self, pid):
        return EXE

    def pid_alive(self, pid):
        return self.alive

    def launch(self, exe):
        self.calls.append(("launch", exe))
        self.alive = True

    # windows
    def main_window(self, pid):
        return self.main if self.alive and self.title is not None else None

    def window_title(self, hwnd):
        return self.title or ""

    def windows(self, pid):
        out = [(self.main, self.title, self.LIVE_WINDOW_CLASS)] if self.title else []
        if self.dialog:
            out.append((self.dialog[0], self.dialog[1], "#32770"))
        return out

    def find_window(self, pid, title):
        if self.dialog and self.dialog[1] == title:
            return self.dialog[0]
        return None

    def dialogs(self, pid):
        return [self.dialog] if self.dialog else []

    def close(self, hwnd):
        self.calls.append(("close", hwnd))
        if self.on_close:
            self.on_close()
        return True

    def post_menu(self, hwnd, top, item):
        self.calls.append(("menu", top, item))
        if item in self.on_menu:
            self.on_menu[item]()

    # file dialog
    def file_dialog_folder(self, dlg):
        return self.folder

    def file_dialog_save(self, dlg, name):
        self.calls.append(("type_save", name))
        if self.on_save:
            self.on_save(name)

    def dialog_click(self, dlg, ctrl):
        self.calls.append(("click", ctrl))
        self.dialog = None
        return True


@pytest.fixture
def fake(monkeypatch, windows_flow):
    f = FakeWin()
    monkeypatch.setattr(server, "_win", f, raising=False)
    monkeypatch.setattr(server, "_win_prompt", lambda pid: (None, {}))
    monkeypatch.setattr(server, "_win_confirm_overwrite", lambda pid: False)
    monkeypatch.setattr(server, "_SAVED_SET_PATHS", {})
    return f


# --- save_set_as -------------------------------------------------------------

def test_save_as_types_name_and_reports_exact_path(fake, tmp_path):
    fake.folder = str(tmp_path)
    (tmp_path / "Song A.als").write_bytes(b"x")
    fake.on_menu["Save Live Set As..."] = lambda: setattr(
        fake, "dialog", (500, "Save Live Set As:"))

    def saved(name):
        fake.dialog = None
        fake.title = "%s - Ableton Live 12 Suite" % name
    fake.on_save = saved

    out = server._save_as_impl("Song A", sleep=NOSLEEP)
    assert out["saved"] is True
    assert out["path"] == os.path.join(str(tmp_path), "Song A.als")
    assert ("type_save", "Song A") in fake.calls
    assert server._SAVED_SET_PATHS["Song A"] == out["path"]


def test_save_as_finds_project_wrapped_file(fake, tmp_path):
    fake.folder = str(tmp_path)
    proj = tmp_path / "B Project"
    proj.mkdir()
    (proj / "B.als").write_bytes(b"x")
    fake.on_menu["Save Live Set As..."] = lambda: setattr(
        fake, "dialog", (500, "Save Live Set As:"))
    fake.on_save = lambda n: (setattr(fake, "dialog", None),
                              setattr(fake, "title", n + " - Ableton Live 12 Suite"))
    out = server._save_as_impl("B", sleep=NOSLEEP)
    assert out["path"] == str(proj / "B.als")


def test_save_as_no_dialog_is_an_error(fake):
    out = server._save_as_impl("X", sleep=NOSLEEP)
    assert out["saved"] is False and "did not appear" in out["error"]
    assert not any(c[0] == "type_save" for c in fake.calls)


def test_save_as_title_never_settles_cancels_dialog(fake):
    fake.on_menu["Save Live Set As..."] = lambda: setattr(
        fake, "dialog", (500, "Save Live Set As:"))
    out = server._save_as_impl("Y", sleep=NOSLEEP)       # on_save does nothing
    assert out["saved"] is False
    assert ("click", FakeWin.IDCANCEL) in fake.calls


def test_save_as_rejects_windows_illegal_names(fake):
    for bad in ("a*b", "a?b", 'a"b', "a<b", "a|b"):
        with pytest.raises(ValueError):
            server._save_as_impl(bad, sleep=NOSLEEP)
    assert fake.calls == []


# --- save_set ------------------------------------------------------------------

def test_save_set_untitled_errors_without_touching_live(fake):
    fake.title = "Untitled* - Ableton Live 12 Suite"
    out = server._save_set_impl(sleep=NOSLEEP)
    assert out["saved"] is False and out["untitled"] is True
    assert fake.calls == []


def test_save_set_titled_saves_in_place(fake):
    fake.title = "Song* - Ableton Live 12 Suite"
    fake.on_menu["Save Live Set"] = lambda: setattr(
        fake, "title", "Song - Ableton Live 12 Suite")
    out = server._save_set_impl(sleep=NOSLEEP)
    assert out == {"app": EXE, "saved": True, "title": "Song"}
    assert ("menu", "File", "Save Live Set") in fake.calls


def test_save_set_unexpected_dialog_is_cancelled(fake):
    fake.title = "Song* - Ableton Live 12 Suite"
    fake.on_menu["Save Live Set"] = lambda: setattr(
        fake, "dialog", (500, "Save Live Set As:"))
    out = server._save_set_impl(sleep=NOSLEEP)
    assert out["saved"] is False and "untitled" in out["error"]
    assert ("click", FakeWin.IDCANCEL) in fake.calls


def test_save_set_with_name_routes_to_save_as(fake, monkeypatch):
    seen = []
    monkeypatch.setattr(server, "_win_save_as_impl",
                        lambda name, sleep=None: seen.append(name) or {"saved": True})
    server._save_set_impl(name="New", sleep=NOSLEEP)
    assert seen == ["New"]


# --- restart_live ---------------------------------------------------------------

def test_restart_refuses_to_save_a_dirty_untitled_set(fake):
    fake.title = "Untitled* - Ableton Live 12 Suite"
    out = server._restart_live_impl(save="save", sleep=NOSLEEP)
    assert out["quit"] is False and "save_set_as" in out["error"]
    assert not any(c[0] == "close" for c in fake.calls)


def test_restart_discard_answers_no_and_relaunches(fake, monkeypatch):
    fake.title = "Song* - Ableton Live 12 Suite"
    pressed = []
    state = {"prompt": False}
    fake.on_close = lambda: state.update(prompt=True)
    monkeypatch.setattr(server, "_win_prompt", lambda pid: (
        (700, {"Yes": "y", "No": "n", "Cancel": "c"}) if state["prompt"] else (None, {})))

    def press(buttons, name):
        pressed.append(name)
        state["prompt"] = False
        fake.alive = False
        fake.title = None
    monkeypatch.setattr(server, "_win_press_prompt", press)

    out = server._restart_live_impl(save="discard", sleep=NOSLEEP)
    assert pressed == ["No"]
    assert out["was_dirty"] is True and out["quit"] is True
    assert out["relaunched"] is True and out["surface_up"] is True
    assert ("launch", EXE) in fake.calls


def test_restart_save_answers_yes(fake, monkeypatch):
    fake.title = "Song* - Ableton Live 12 Suite"
    pressed = []
    monkeypatch.setattr(server, "_win_prompt",
                        lambda pid: (700, {"Yes": 1, "No": 2}) if fake.alive else (None, {}))

    def press(buttons, name):
        pressed.append(name)
        fake.alive = False
        fake.title = None
    monkeypatch.setattr(server, "_win_press_prompt", press)
    out = server._restart_live_impl(save="save", relaunch=False, sleep=NOSLEEP)
    assert pressed == ["Yes"] and out["quit"] is True
    assert "relaunched" not in out


def test_restart_stuck_exit_is_reported_and_not_relaunched(fake):
    fake.title = "Song - Ableton Live 12 Suite"

    def closes_window_but_hangs():
        fake.title = None           # window gone, process still alive
    fake.on_close = closes_window_but_hangs
    out = server._restart_live_impl(save="discard", sleep=NOSLEEP)
    assert out["quit"] is False and "still exiting" in out["error"]
    assert not any(c[0] == "launch" for c in fake.calls)


def test_restart_bad_policy(fake):
    with pytest.raises(ValueError):
        server._restart_live_impl(save="maybe", sleep=NOSLEEP)


def test_no_live_raises(fake):
    fake.alive = False
    with pytest.raises(RuntimeError):
        server._save_as_impl("x", sleep=NOSLEEP)


# --- other Live windows open (Settings, plugin editors) ---------------------------

def test_render_finished_ignores_windows_open_before_render(fake, monkeypatch):
    monkeypatch.setattr(server, "_live_window_exists", lambda t: False)
    handles = {"now": {100, 300}}                 # 300 = a plugin editor
    monkeypatch.setattr(server, "_live_window_handles", lambda: handles["now"])
    baseline = {100, 300}
    assert server._render_finished(baseline) is True
    handles["now"] = {100, 300, 900}              # a render progress box
    assert server._render_finished(baseline) is False


@pytest.mark.skipif(not server.plat.is_windows(__import__("sys").platform),
                    reason="win_ui loads user32 (Windows only)")
def test_main_window_is_the_one_with_the_menu_bar(monkeypatch):
    from types import SimpleNamespace
    from ableton_mcp_max import win_ui
    cls = win_ui.LIVE_WINDOW_CLASS
    monkeypatch.setattr(win_ui, "windows", lambda pid: [
        (7, "Settings", cls), (8, "", cls), (9, "Song - Ableton Live 12 Suite", cls)])
    monkeypatch.setattr(win_ui, "user32", SimpleNamespace(GetMenu=lambda h: h == 9))
    assert win_ui.main_window(1) == 9
    # no menu readable: fall back to the title suffix, never 'first window'
    monkeypatch.setattr(win_ui, "user32", SimpleNamespace(GetMenu=lambda h: 0))
    assert win_ui.main_window(1) == 9


# --- pure name / menu helpers -----------------------------------------------------

def test_clean_names_default_is_macos_rule():
    assert clean_set_name("a*b") == "a*b"            # legal on macOS
    assert clean_render_name("a?b") == "a?b"
    with pytest.raises(ValueError):
        clean_set_name("a*b", illegal='\\/:*?"<>|')
    with pytest.raises(ValueError):
        clean_render_name("a?b", illegal='\\/:*?"<>|')


def test_strip_menu_check_windows_suffix():
    assert strip_menu_check("WAV, checked") == "WAV"
    assert choose_menu_item(["WAV, checked", "AIFF"], "WAV") == "WAV, checked"
    assert choose_menu_item(["Main, checked"], "Master") == "Main, checked"
