"""Tests for the save orchestration (_save_set_impl / _save_as_impl). All OS/UI
seams are stubbed so the menu-click + keystroke choreography is exercised without
touching a real Live or the macOS save UI."""
import json
import pytest

from ableton_mcp_max import server

NOSLEEP = lambda *a, **k: None


def _stub(monkeypatch, *, app="/Applications/Ableton Live 12 Suite.app", pid=4242,
         title="Untitled", panel=True, final_title=None, found_path=""):
    """Wire seams. title = window title before save; panel = whether clicking a
    save menu item opens a panel (window count 1->2); final_title = title the
    window settles to after Save (defaults to nothing changing); found_path = what
    _find_saved_set returns."""
    calls = {"osa": []}
    monkeypatch.setattr(server, "_live_app_and_pid", lambda port=9877: (app, pid))
    monkeypatch.setattr(server, "_find_saved_set", lambda b: found_path)
    # 1 window until a save menu item opens the panel; a Return then saves
    # (title settles, panel closes back to 1 window).
    state = {"title": title, "wins": 1}
    def _osa(s):
        calls["osa"].append(s)
        if panel and "click menu item" in s and "Save Live Set" in s:
            state["wins"] = 2
        elif "keystroke return" in s and final_title is not None and state["wins"] > 1:
            state["title"] = final_title
            state["wins"] = 1
    monkeypatch.setattr(server, "_osa", _osa)
    monkeypatch.setattr(server, "_live_window_count", lambda proc="Live": state["wins"])
    monkeypatch.setattr(server, "_live_window_title",
                        lambda proc="Live": state["title"])
    return calls


def test_untitled_no_name_errors(monkeypatch):
    _stub(monkeypatch, title="Untitled", panel=False)
    data = server._save_set_impl(name="", sleep=NOSLEEP)
    assert data["saved"] is False and data["untitled"] is True
    assert "untitled" in data["error"].lower()


def test_titled_save_in_place_via_menu(monkeypatch):
    calls = _stub(monkeypatch, title="MyTrack", panel=False)
    data = server._save_set_impl(name="", sleep=NOSLEEP)
    assert data["saved"] is True and data["title"] == "MyTrack"
    assert any('click menu item "Save Live Set"' in s for s in calls["osa"])


def test_titled_unexpected_panel_escapes(monkeypatch):
    calls = _stub(monkeypatch, title="MyTrack", panel=True)
    data = server._save_set_impl(name="", sleep=NOSLEEP)
    assert data["saved"] is False
    assert any("key code 53" in s for s in calls["osa"])


def test_untitled_with_name_routes_to_save_as(monkeypatch):
    calls = _stub(monkeypatch, title="Untitled", panel=True, final_title="Song",
                  found_path="/Users/me/Music/Song Project/Song.als")
    data = server._save_set_impl(name="Song", sleep=NOSLEEP)
    assert data["saved"] is True and data["name"] == "Song"
    assert data["path"] == "/Users/me/Music/Song Project/Song.als"
    assert any('click menu item "Save Live Set As..."' in s for s in calls["osa"])


def test_save_as_panel_never_appears(monkeypatch):
    _stub(monkeypatch, title="Untitled", panel=False)
    data = server._save_as_impl("Song", sleep=NOSLEEP)
    assert data["saved"] is False
    assert "Accessibility" in data["error"] or "did not appear" in data["error"]


def test_save_as_no_path_found_still_saved(monkeypatch):
    _stub(monkeypatch, title="Untitled", panel=True, final_title="Song", found_path="")
    data = server._save_as_impl("Song", sleep=NOSLEEP)
    assert data["saved"] is True and "path" not in data


def test_save_as_bad_name_raises(monkeypatch):
    _stub(monkeypatch, title="Untitled")
    with pytest.raises(ValueError):
        server._save_as_impl("", sleep=NOSLEEP)
    with pytest.raises(ValueError):
        server._save_as_impl("bad/name", sleep=NOSLEEP)


def test_save_no_running_live_raises(monkeypatch):
    monkeypatch.setattr(server, "_live_app_and_pid", lambda port=9877: (None, None))
    with pytest.raises(RuntimeError):
        server._save_set_impl(sleep=NOSLEEP)


def test_tool_wrapper_untitled_error_clean(monkeypatch):
    _stub(monkeypatch, title="Untitled", panel=False)
    out = json.loads(server.save_set(None))
    assert out["ok"] is True and out["data"]["saved"] is False


def test_tool_wrapper_bad_name_clean(monkeypatch):
    _stub(monkeypatch, title="Untitled")
    out = json.loads(server.save_set_as(None, "a/b"))
    assert out["ok"] is False and "/" in out["error"]


# --- _live_window_title: ignore a plugin's floating editor window -------------
# A freshly loaded VST3 (e.g. Ozone 12) opens an AXFloatingWindow that sits on
# top of the set window and persists, so `window 1` returns the PLUGIN's title.
# _live_window_title must read the main AXStandardWindow instead, or the .als
# path resolver and the untitled check both get a bogus title.

def test_live_window_title_prefers_standard_window(monkeypatch):
    def _osa_get(script):
        if "AXStandardWindow" in script:
            return "ozone_idbase_probe"
        return "Ozone 12/1-Serum 2"          # window 1 = plugin editor
    monkeypatch.setattr(server, "_osa_get", _osa_get)
    assert server._live_window_title() == "ozone_idbase_probe"


def test_live_window_title_falls_back_to_window_1(monkeypatch):
    def _osa_get(script):
        if "AXStandardWindow" in script:
            return ""                        # no standard window readable
        return "SomeSet"
    monkeypatch.setattr(server, "_osa_get", _osa_get)
    assert server._live_window_title() == "SomeSet"
