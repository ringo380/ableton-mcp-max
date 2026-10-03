"""Pure per-OS path rules (host-side only).

Every function takes the platform (and any home/known-folder roots) as
arguments, so the macOS and Windows answers are both unit-testable on either
machine. server.py supplies the real values. The macOS results are exactly the
paths the server used before Windows support existed - do not change them
without a Mac live check.

Windows facts (verified on Live 12.4.6 Suite, Windows 11):
  * install root      C:\\ProgramData\\Ableton\\Live 12 Suite
  * Core Library      <install>\\Resources\\Core Library
  * Remote Scripts    <install>\\Resources\\MIDI Remote Scripts
  * prefs             %APPDATA%\\Ableton\\Live 12.4.6\\Preferences (Library.cfg, Log.txt)
  * factory sets      <install>\\Resources\\Builtin\\Templates\\DefaultLiveSet.als
  * Serum 2 presets   <Documents>\\Xfer\\Serum 2 Presets\\Presets\\{Factory,User}
  * Serum 2 plugin    C:\\Program Files\\Common Files\\VST3\\Serum2.vst3
"""
import ntpath
import posixpath
import re

MAC = "darwin"
WIN = "win32"

_WIN_ABLETON_ROOT = r"C:\ProgramData\Ableton"


def is_windows(platform):
    return str(platform).startswith("win")


def _join(platform, *parts):
    return (ntpath if is_windows(platform) else posixpath).join(*parts)


def core_library_glob(platform, major=None):
    """Glob for an installed Live's Core Library. `major` narrows it to one
    version; None matches any installed Live (the multi-version fallback)."""
    if is_windows(platform):
        live = "Live %d*" % major if major is not None else "Live*"
        return _join(platform, _WIN_ABLETON_ROOT, live, "Resources", "Core Library")
    if major is not None:
        return ("/Applications/Ableton*Live*%d*.app/Contents/App-Resources/"
                "Core Library" % major)
    return "/Applications/Ableton*Live*.app/Contents/App-Resources/Core Library"


def remote_scripts_glob(platform):
    """Glob for every installed Live's MIDI Remote Scripts dir."""
    if is_windows(platform):
        return _join(platform, _WIN_ABLETON_ROOT, "Live*", "Resources",
                     "MIDI Remote Scripts")
    return "/Applications/Ableton*Live*.app/Contents/App-Resources/MIDI Remote Scripts"


def prefs_base(platform, home, appdata=None):
    """Parent of the per-version 'Live x.y.z' preference dirs."""
    if is_windows(platform):
        base = appdata or _join(platform, home, "AppData", "Roaming")
        return _join(platform, base, "Ableton")
    return posixpath.join(home, "Library", "Preferences", "Ableton")


def version_key(path):
    """Sort key for a 'Live 12.4.10' style dir: numeric, so 12.4.10 sorts after
    12.4.6 (a plain string sort gets that backwards). Non-matching names sort
    first."""
    name = re.split(r"[\\/]", str(path).rstrip("\\/"))[-1]
    m = re.match(r"Live (\d+(?:\.\d+)*)", name)
    if not m:
        return (0,)
    return (1,) + tuple(int(x) for x in m.group(1).split("."))


def order_pref_dirs(platform, dirs, running_version=None):
    """Pref dirs, best LAST (callers walk them in reverse). macOS keeps its
    historic lexical order. Windows sorts by version and, when the running
    Live's 'x.y.z' is known, moves that exact dir to the end."""
    if not is_windows(platform):
        return sorted(dirs)
    out = sorted(dirs, key=version_key)
    if running_version:
        exact = [d for d in out
                 if re.split(r"[\\/]", d.rstrip("\\/"))[-1] == "Live %s" % running_version]
        out = [d for d in out if d not in exact] + exact
    return out


def user_library_fallback(platform, home):
    """Live's default User Library when Library.cfg can't be read."""
    if is_windows(platform):
        return _join(platform, home, "Documents", "Ableton", "User Library")
    return posixpath.join(home, "Music", "Ableton", "User Library")


def is_factory_set_path(platform, path):
    """True for a set that ships inside the Live install (the blank default
    set Live loads on launch) - never a user's set."""
    p = str(path)
    if is_windows(platform):
        low = p.replace("/", "\\").lower()
        return "\\programdata\\ableton\\" in low or "\\resources\\builtin\\" in low
    return "/Applications/" in p


def save_search_roots(platform, home, documents=None):
    """Folders Live may have dropped a '<name> Project' folder into."""
    if is_windows(platform):
        roots = [_join(platform, home, "Desktop"),
                 _join(platform, home, "Music"),
                 _join(platform, home, "Documents"),
                 _join(platform, home, "Documents", "Ableton")]
        if documents:
            roots += [documents, _join(platform, documents, "Ableton")]
        return _dedupe(roots)
    return [posixpath.join(home, r) for r in
            ("Desktop", "Music", "Documents", "Music/Ableton", "Documents/Ableton")]


def render_search_roots(platform, home, documents=None):
    """Folders to walk for a just-rendered file where there is no Spotlight
    (Windows). Live renders into its last-used export dir, which on a fresh
    install defaults under the user's Documents/Music."""
    roots = save_search_roots(platform, home, documents)
    if is_windows(platform):
        roots.append(_join(platform, home, "Downloads"))
    return _dedupe(roots)


def serum_preset_roots(platform, home, documents=None):
    """[(dir, 'factory'|'user')] candidates for Serum 2 presets, in priority
    order. Callers keep only the ones that exist."""
    if is_windows(platform):
        out = []
        for docs in _dedupe([documents, _join(platform, home, "Documents")]):
            if not docs:
                continue
            base = _join(platform, docs, "Xfer", "Serum 2 Presets", "Presets")
            out.append((_join(platform, base, "Factory"), "factory"))
            out.append((_join(platform, base, "User"), "user"))
        return out
    return [("/Library/Audio/Presets/Xfer Records/Serum 2 Presets/Presets", "factory"),
            (posixpath.join(home, "Music", "Serum", "Presets"), "user")]


def serum_user_preset_dir(platform, home, documents=None, isdir=None):
    """Where a cloned Serum preset is written, or None to fall back to the
    User Library. `isdir` is the existence check (injected for tests)."""
    isdir = isdir or (lambda p: False)
    if is_windows(platform):
        for path, label in serum_preset_roots(platform, home, documents):
            if label == "user" and isdir(ntpath.dirname(path)):
                return path
        return None
    base = posixpath.join(home, "Music", "Serum", "Presets")
    return posixpath.join(base, "User") if isdir(base) else None


def serum_install_candidates(platform, home, common_files=None):
    """Paths whose existence means Serum is installed."""
    if is_windows(platform):
        common = common_files or r"C:\Program Files\Common Files"
        return [_join(platform, common, "VST3", "Serum2.vst3"),
                _join(platform, common, "VST3", "Serum.vst3"),
                _join(platform, home, "AppData", "Roaming", "Xfer", "Serum 2")]
    return [
        "/Library/Audio/Plug-Ins/VST3/Serum2.vst3",
        posixpath.join(home, "Library/Audio/Plug-Ins/VST3/Serum2.vst3"),
        "/Library/Audio/Plug-Ins/VST3/Serum.vst3",
        posixpath.join(home, "Library/Audio/Plug-Ins/VST3/Serum.vst3"),
        "/Library/Audio/Plug-Ins/Components/Serum2.component",
        posixpath.join(home, "Library/Audio/Plug-Ins/Components/Serum2.component"),
        "/Library/Audio/Plug-Ins/Components/Serum.component",
        posixpath.join(home, "Library/Audio/Plug-Ins/Components/Serum.component"),
        "/Library/Audio/Presets/Xfer Records/Serum 2 Presets",
    ]


_WIN_TITLE_SUFFIX = re.compile(r"\s+-\s+Ableton Live\b.*$")


def set_title_from_window_title(platform, title):
    """The set name from Live's main window title. Windows titles carry the
    app name ('My Song - Ableton Live 12 Suite') and mark unsaved edits with
    '*'; the macOS title is already the bare set name, returned unchanged."""
    t = title or ""
    if not is_windows(platform):
        return t
    t = _WIN_TITLE_SUFFIX.sub("", t.strip())
    return t.rstrip("*").strip()


def window_title_dirty(platform, title):
    """True if Live's raw main-window title marks unsaved changes. Only
    Windows titles carry the marker ('Untitled* - Ableton Live 12 Suite');
    on macOS this returns None (unknown)."""
    if not is_windows(platform):
        return None
    t = _WIN_TITLE_SUFFIX.sub("", (title or "").strip())
    return t.endswith("*")


# Characters Windows forbids in a file name (plus the macOS panel's '/' ':').
WIN_ILLEGAL_NAME_CHARS = '\\/:*?"<>|'


def illegal_name_chars(platform):
    return WIN_ILLEGAL_NAME_CHARS if is_windows(platform) else "/:"


def menu_label(text):
    """A Win32 menu item's text without its '&' accelerator marker and its
    tab-separated shortcut: '&Save Live Set\\tCtrl+S' -> 'Save Live Set'."""
    t = (text or "").split("\t", 1)[0]
    return t.replace("&&", "\0").replace("&", "").replace("\0", "&").strip()


def _dedupe(items):
    seen, out = set(), []
    for x in items:
        key = str(x).lower() if x else x
        if key in seen:
            continue
        seen.add(key)
        out.append(x)
    return out
