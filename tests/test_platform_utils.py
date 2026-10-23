"""platform_utils: per-OS path rules. The darwin cases pin the exact values the
server used before Windows support - they must not drift."""
from ableton_mcp_max import platform_utils as plat

MAC, WIN = plat.MAC, plat.WIN
HOME_MAC = "/Users/me"
HOME_WIN = r"C:\Users\me"


def test_is_windows():
    assert plat.is_windows("win32") and not plat.is_windows("darwin")


def test_core_library_glob_mac_unchanged():
    assert plat.core_library_glob(MAC) == \
        "/Applications/Ableton*Live*.app/Contents/App-Resources/Core Library"
    assert plat.core_library_glob(MAC, 12) == \
        "/Applications/Ableton*Live*12*.app/Contents/App-Resources/Core Library"


def test_core_library_glob_windows():
    assert plat.core_library_glob(WIN) == \
        r"C:\ProgramData\Ableton\Live*\Resources\Core Library"
    assert plat.core_library_glob(WIN, 12) == \
        r"C:\ProgramData\Ableton\Live 12*\Resources\Core Library"


def test_remote_scripts_glob():
    assert plat.remote_scripts_glob(WIN) == \
        r"C:\ProgramData\Ableton\Live*\Resources\MIDI Remote Scripts"
    assert plat.remote_scripts_glob(MAC).startswith("/Applications/")


def test_prefs_base():
    assert plat.prefs_base(MAC, HOME_MAC) == "/Users/me/Library/Preferences/Ableton"
    assert plat.prefs_base(WIN, HOME_WIN, r"C:\Users\me\AppData\Roaming") == \
        r"C:\Users\me\AppData\Roaming\Ableton"
    assert plat.prefs_base(WIN, HOME_WIN) == r"C:\Users\me\AppData\Roaming\Ableton"


def test_version_key_is_numeric():
    dirs = [r"X\Live 12.4.6", r"X\Live 12.4.10", r"X\Live 12.4.3", r"X\Live Reports"]
    assert sorted(dirs, key=plat.version_key) == \
        [r"X\Live Reports", r"X\Live 12.4.3", r"X\Live 12.4.6", r"X\Live 12.4.10"]


def test_order_pref_dirs_mac_is_lexical():
    dirs = ["/p/Live 12.4.10", "/p/Live 12.4.6"]
    assert plat.order_pref_dirs(MAC, dirs) == sorted(dirs)


def test_order_pref_dirs_windows_running_version_last():
    dirs = [r"A\Live 12.4.6", r"A\Live 12.4.10", r"A\Live 12.4.3"]
    assert plat.order_pref_dirs(WIN, dirs)[-1] == r"A\Live 12.4.10"
    assert plat.order_pref_dirs(WIN, dirs, "12.4.6")[-1] == r"A\Live 12.4.6"
    # an unknown running version leaves the numeric order alone
    assert plat.order_pref_dirs(WIN, dirs, "11.0.0")[-1] == r"A\Live 12.4.10"


def test_user_library_fallback():
    assert plat.user_library_fallback(MAC, HOME_MAC) == \
        "/Users/me/Music/Ableton/User Library"
    assert plat.user_library_fallback(WIN, HOME_WIN) == \
        r"C:\Users\me\Documents\Ableton\User Library"


def test_is_factory_set_path():
    assert plat.is_factory_set_path(
        MAC, "/Applications/Ableton Live 12 Suite.app/Contents/x.als")
    assert not plat.is_factory_set_path(MAC, "/Users/me/Music/song.als")
    assert plat.is_factory_set_path(
        WIN, r"C:\ProgramData\Ableton\Live 12 Suite\Resources\Builtin"
             r"\Templates\DefaultLiveSet.als")
    assert not plat.is_factory_set_path(WIN, r"C:\Users\me\Music\song.als")


def test_save_search_roots_mac_unchanged():
    assert plat.save_search_roots(MAC, HOME_MAC) == [
        "/Users/me/Desktop", "/Users/me/Music", "/Users/me/Documents",
        "/Users/me/Music/Ableton", "/Users/me/Documents/Ableton"]


def test_save_search_roots_windows_adds_known_documents():
    roots = plat.save_search_roots(WIN, HOME_WIN, r"C:\Users\me\OneDrive\Documents")
    assert r"C:\Users\me\Documents\Ableton" in roots
    assert r"C:\Users\me\OneDrive\Documents\Ableton" in roots
    assert len(roots) == len(set(r.lower() for r in roots))


def test_serum_roots_mac_unchanged():
    assert plat.serum_preset_roots(MAC, HOME_MAC) == [
        ("/Library/Audio/Presets/Xfer Records/Serum 2 Presets/Presets", "factory"),
        ("/Users/me/Music/Serum/Presets", "user")]


def test_serum_roots_windows():
    roots = plat.serum_preset_roots(WIN, HOME_WIN, r"D:\Docs")
    assert roots[:2] == [
        (r"D:\Docs\Xfer\Serum 2 Presets\Presets\Factory", "factory"),
        (r"D:\Docs\Xfer\Serum 2 Presets\Presets\User", "user")]
    assert (r"C:\Users\me\Documents\Xfer\Serum 2 Presets\Presets\User", "user") in roots


def test_serum_user_preset_dir():
    assert plat.serum_user_preset_dir(
        MAC, HOME_MAC, isdir=lambda p: p == "/Users/me/Music/Serum/Presets") == \
        "/Users/me/Music/Serum/Presets/User"
    assert plat.serum_user_preset_dir(MAC, HOME_MAC, isdir=lambda p: False) is None
    base = r"D:\Docs\Xfer\Serum 2 Presets\Presets"
    assert plat.serum_user_preset_dir(WIN, HOME_WIN, r"D:\Docs",
                                      isdir=lambda p: p == base) == base + r"\User"
    assert plat.serum_user_preset_dir(WIN, HOME_WIN, r"D:\Docs",
                                      isdir=lambda p: False) is None


def test_serum_install_candidates():
    mac = plat.serum_install_candidates(MAC, HOME_MAC)
    assert mac[0] == "/Library/Audio/Plug-Ins/VST3/Serum2.vst3"
    assert "/Users/me/Library/Audio/Plug-Ins/Components/Serum.component" in mac
    assert len(mac) == 9
    win = plat.serum_install_candidates(WIN, HOME_WIN, r"C:\Program Files\Common Files")
    assert win[0] == r"C:\Program Files\Common Files\VST3\Serum2.vst3"


def test_set_title_from_window_title():
    t = plat.set_title_from_window_title
    assert t(WIN, "Untitled* - Ableton Live 12 Suite") == "Untitled"
    assert t(WIN, "My - Song - Ableton Live 12 Suite") == "My - Song"
    assert t(WIN, "") == ""
    assert t(MAC, "My Song") == "My Song"          # macOS untouched


def test_window_title_dirty():
    assert plat.window_title_dirty(WIN, "Song* - Ableton Live 12 Suite") is True
    assert plat.window_title_dirty(WIN, "Song - Ableton Live 12 Suite") is False
    assert plat.window_title_dirty(MAC, "Song") is None


def test_illegal_name_chars():
    assert plat.illegal_name_chars(MAC) == "/:"
    assert set('\\/:*?"<>|') == set(plat.illegal_name_chars(WIN))


def test_menu_label():
    assert plat.menu_label("&Save Live Set\tCtrl+S") == "Save Live Set"
    assert plat.menu_label("Export Audio/Video...\tCtrl+Shift+R") == \
        "Export Audio/Video..."
    assert plat.menu_label("Tom && Jerry") == "Tom & Jerry"
