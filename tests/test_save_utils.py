"""Tests for save_utils — pure path/title logic for the save tools. No Live,
no OS automation; just value normalization the server resolves before driving
the macOS save UI."""
import os
import pytest

from ableton_mcp_max import save_utils


# ---- is_untitled_title -------------------------------------------------------

@pytest.mark.parametrize("title,expected", [
    ("Untitled", True),
    ("Untitled*", True),          # macOS edited indicator
    ("  Untitled  ", True),
    ("untitled", True),           # case-insensitive
    ("Untitled 2", True),         # Live's fresh-set naming
    ("", True),                   # unreadable title -> treat as untitled (require a path)
    ("My Track", False),
    ("tester8", False),
    ("Untitled Symphony", False), # a real set literally named this is titled
])
def test_is_untitled_title(title, expected):
    assert save_utils.is_untitled_title(title) is expected


# ---- clean_set_name ----------------------------------------------------------

def test_clean_plain_name():
    assert save_utils.clean_set_name("My Track") == "My Track"


def test_clean_strips_als_extension():
    assert save_utils.clean_set_name("My Track.als") == "My Track"
    assert save_utils.clean_set_name("My Track.ALS") == "My Track"


def test_clean_rejects_a_path():
    # a path is rejected (not silently reduced to its basename) — the tool
    # controls the name only, and a '/' would hijack Live's save panel.
    with pytest.raises(ValueError):
        save_utils.clean_set_name("/tmp/foo/Deep House.als")


def test_clean_strips_whitespace():
    assert save_utils.clean_set_name("  Banger  ") == "Banger"


@pytest.mark.parametrize("bad", [None, "", "   ", "/", "   /"])
def test_clean_rejects_empty(bad):
    with pytest.raises(ValueError):
        save_utils.clean_set_name(bad)


@pytest.mark.parametrize("bad", ["a/b", "a:b", "x/y/z"])
def test_clean_rejects_separators_in_name(bad):
    # a stray '/' hijacks Live's save panel into Go-to-Folder; ':' is HFS sep.
    with pytest.raises(ValueError):
        save_utils.clean_set_name(bad)


# ---- set_name_from_path ------------------------------------------------------

def test_set_name_strips_dir_and_ext():
    assert save_utils.set_name_from_path("/a/b/MyTrack.als") == "MyTrack"


def test_set_name_from_path_without_ext():
    assert save_utils.set_name_from_path("/a/b/Deep House") == "Deep House"
