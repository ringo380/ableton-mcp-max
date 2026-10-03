"""Pure helpers for the save tools (save_set / save_set_as). No Live deps.

Saving an Ableton set is UI-only — the LOM exposes no save API and Song has no
file_path/is_modified — so the tools drive the macOS save UI via System Events.
This module holds only the value logic the server resolves BEFORE touching the
UI: detecting an Untitled set from its window title, and normalizing a target
path to the absolute ``.als`` form the Save-As sheet expects.
"""
import os
import re

# Live auto-names an unsaved set "Untitled", then "Untitled 2", "Untitled 3"...
# (a number only). A set a user literally named "Untitled Symphony" is titled.
_UNTITLED_RE = re.compile(r"^untitled( \d+)?$")


def is_untitled_title(title):
    """True if a Live window title denotes a set with no file on disk.

    Matches Live's auto-naming ("Untitled" / "Untitled 2"), tolerating a
    trailing "*" macOS edited marker. An empty/unreadable title is treated as
    untitled so callers demand an explicit path rather than blind-saving.
    """
    t = (title or "").strip()
    if not t:
        return True
    t = t.rstrip("*").strip().lower()
    return bool(_UNTITLED_RE.match(t))


def clean_set_name(value, illegal="/:"):
    """Reduce a user-supplied value to a bare Live set NAME (no directory, no
    ``.als``). Ableton's Save-As panel saves to its last-used location and wraps
    the set in a ``<name> Project`` folder, so the tools take a name, not a path
    (arbitrary-directory navigation through Live's panel is not reliably
    scriptable). Accepts a name or a path-like value (basename is used). Rejects
    empty / path-separator-only / names with characters illegal in a filename.
    """
    if value is None or not str(value).strip():
        raise ValueError("name is required (the set name to save as).")
    base = str(value).strip()
    root, ext = os.path.splitext(base)
    if ext.lower() == ".als":
        base = root.strip()
    if not base or base in (".", ".."):
        raise ValueError("name has no usable component: %r" % value)
    # ':' is the HFS path separator and '/' can't appear in a filename; both
    # corrupt Live's save panel (a stray '/' hijacks Go-to-Folder). Reject a
    # path here rather than silently taking its basename — the tool wants a name.
    if "/" in base or ":" in base:
        raise ValueError("name must not contain '/' or ':' (pass a name, not a "
                         "path): %r" % base)
    bad = [ch for ch in illegal if ch in base]
    if bad:
        raise ValueError("name must not contain %s (pass a name, not a path): %r"
                         % (" ".join(repr(c) for c in illegal), base))
    return base


def set_name_from_path(path):
    """The set name a saved window title should show: basename without ``.als``."""
    base = os.path.basename(str(path))
    root, _ = os.path.splitext(base)
    return root
