"""Preferences.cfg bool read/write against a synthetic file laid out like Live
12.4.7's (class declaration first, value record later). The real file holds
account secrets, so it is never used as a fixture."""
import struct

import pytest

from ableton_mcp_max import live_prefs_utils as lp
from ableton_mcp_max import server

CLS, KEY = lp.AUTO_WARP_LONG_SAMPLES

FIELDS = [("BrowserIsFullHeight", "RemoteableBool"),
          ("RecordDirectory", "FileRef"),
          ("ClipUpdateRate", "RemoteableEnum"),
          ("SelectOnLaunch", "RemoteableBool"),
          ("MetronomePreset", "RemoteableString"),
          ("Follow", "RemoteableBool"),
          ("ClipDefaultHiQ", "RemoteableBool"),
          (KEY, "RemoteableBool"),
          ("DeviceBreakoutViewHeight", "RemoteableInt")]


def _hdr(name):
    return bytes([len(name)]) + name.encode("ascii")


def _s16(text):
    return struct.pack("<I", len(text)) + text.encode("utf-16-le")


def _declaration(fields):
    out = _hdr(CLS) + struct.pack("<I", len(fields))
    for name, typ in fields:
        out += _s16(name) + b"\x00" + _hdr(typ)
    return out


def build(auto_warp=1, metronome="Classic.adg", follow=0):
    values = (_hdr(CLS) + struct.pack("<I", 9)
              + b"\x01"                                  # BrowserIsFullHeight
              + _s16("C:/Users/x/Live Recordings")       # RecordDirectory
              + struct.pack("<I", 4)                     # ClipUpdateRate
              + b"\x00"                                  # SelectOnLaunch
              + _s16(metronome)                          # MetronomePreset
              + bytes([follow, 1, auto_warp])            # Follow, HiQ, KEY
              + struct.pack("<I", 245))                  # DeviceBreakoutViewHeight
    return b"\xab\x1eVx" + _declaration(FIELDS) + b"\x00" * 37 + values + b"\x07tail"


def test_reads_the_declared_fields_in_order():
    assert lp.class_fields(build(), CLS) == FIELDS


def test_reads_and_flips_only_the_one_byte():
    data = build(auto_warp=1)
    assert lp.get_bool(data, CLS, KEY) is True
    off = lp.set_bool(data, CLS, KEY, False)
    assert lp.get_bool(off, CLS, KEY) is False
    changed = [i for i in range(len(data)) if data[i] != off[i]]
    assert changed == [lp.locate_bool(data, CLS, KEY)]
    assert len(off) == len(data)


def test_empty_metronome_string_still_locates():
    data = build(metronome="")
    assert lp.get_bool(lp.set_bool(data, CLS, KEY, False), CLS, KEY) is False


def test_unrecognized_layout_is_refused():
    # a non-bool byte where Follow should be: no offset fits, nothing written
    with pytest.raises(ValueError, match="not recognized"):
        lp.locate_bool(build(follow=7), CLS, KEY)


def test_two_matching_spots_are_refused():
    data = build()
    record = data[data.rfind(_hdr(CLS)) + len(_hdr(CLS)) + 4:-len(b"\x07tail")]
    with pytest.raises(ValueError, match="2 candidate"):
        lp.locate_bool(data + record, CLS, KEY)     # a decoy copy, no header


def test_missing_class_or_field_or_wrong_type_is_refused():
    with pytest.raises(ValueError):
        lp.locate_bool(b"nothing here", CLS, KEY)
    with pytest.raises(ValueError):
        lp.locate_bool(build(), CLS, "NoSuchField")
    with pytest.raises(ValueError):
        lp.locate_bool(build(), CLS, "DeviceBreakoutViewHeight")


def test_a_third_copy_of_the_record_is_refused():
    data = build()
    with pytest.raises(ValueError, match="twice"):
        lp.locate_bool(data + _hdr(CLS), CLS, KEY)


def test_write_backs_up_then_writes(tmp_path):
    cfg = tmp_path / "Preferences.cfg"
    original = build(auto_warp=1)
    cfg.write_bytes(original)
    out = server._write_pref_bool(str(cfg), CLS, KEY, False, stamp="T")
    assert out == {"path": str(cfg), "backup": str(cfg) + ".bak-T",
                   "was": True, "now": False}
    assert (tmp_path / "Preferences.cfg.bak-T").read_bytes() == original
    assert lp.get_bool(cfg.read_bytes(), CLS, KEY) is False
    assert not (tmp_path / "Preferences.cfg.tmp").exists()


def test_write_refuses_an_unknown_layout_without_touching_the_file(tmp_path):
    cfg = tmp_path / "Preferences.cfg"
    cfg.write_bytes(build(follow=7))
    with pytest.raises(ValueError):
        server._write_pref_bool(str(cfg), CLS, KEY, False, stamp="T")
    assert cfg.read_bytes() == build(follow=7)
    assert not (tmp_path / "Preferences.cfg.bak-T").exists()


@pytest.fixture
def prefs(tmp_path, monkeypatch):
    cfg = tmp_path / "Preferences.cfg"
    cfg.write_bytes(build(auto_warp=1))
    monkeypatch.setattr(server, "_live_prefs_cfg", lambda: str(cfg))
    monkeypatch.setattr(server, "_live_window_title", lambda *a: "Song")
    monkeypatch.setattr(server, "_current_set_path",
                        lambda title=None: r"C:\P\Song Project\Song.als")
    return cfg


def test_set_pref_quits_writes_while_closed_relaunches_and_reopens(prefs):
    events, reopened = [], []

    def restart(save, before_relaunch):
        events.append(("quit", save))
        written = before_relaunch()
        events.append(("hook", written["now"]))
        events.append(("relaunch",))
        return {"quit": True, "surface_up": True, "before_relaunch": written}

    out = server._set_live_pref_bool_impl(
        CLS, KEY, False, restart=restart,
        reload=lambda p, n: reopened.append((p, n)) or {"reloaded": True})
    assert events == [("quit", "save"), ("hook", False), ("relaunch",)]
    assert out["backup"].startswith(str(prefs) + ".bak-")
    assert lp.get_bool(prefs.read_bytes(), CLS, KEY) is False
    assert out["was"] is True and out["now"] is False and out["changed"] is True
    assert reopened == [(r"C:\P\Song Project\Song.als", "Song")]
    assert "error" not in out


def test_set_pref_already_set_does_not_restart(prefs):
    called = []
    out = server._set_live_pref_bool_impl(
        CLS, KEY, True, restart=lambda **k: called.append(k))
    assert called == [] and out["changed"] is False and "not restarted" in out["note"]


def test_set_pref_reports_a_failed_quit(prefs):
    out = server._set_live_pref_bool_impl(
        CLS, KEY, False,
        restart=lambda save, before_relaunch: {"quit": False, "error": "dialog open"},
        reload=lambda p, n: pytest.fail("must not reopen"))
    assert out["error"] == "dialog open" and out["changed"] is False
    assert lp.get_bool(prefs.read_bytes(), CLS, KEY) is True


def test_set_pref_refuses_unknown_layout_before_quitting(prefs):
    prefs.write_bytes(build(follow=7))
    with pytest.raises(ValueError):
        server._set_live_pref_bool_impl(
            CLS, KEY, False, restart=lambda **k: pytest.fail("must not quit"))
