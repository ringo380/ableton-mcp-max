"""Tool-level tests for the per-track tap tools, driven through the in-process
tap registry singleton hosted in server.py (no real socket needed - feed frames
straight into the registry via its testable ingest seam)."""
import json
import pytest

from ableton_mcp_max import server


def _seed_registry():
    reg = server._tap_registry
    reg.state.reset()
    # master + one regular track identity, each with one block frame
    reg.feed("c1", '{"type":"hello","track":{"uuid":"master","name":"Master","index":-1,"kind":"master"}}\n')
    reg.feed("c1", '{"type":"block","data":{"ms_k_l":0.01,"ms_k_r":0.01,"peak":0.5,"rms":0.1}}\n')
    reg.feed("c2", '{"type":"hello","track":{"uuid":"u-bass","name":"Bass","index":2,"kind":"midi"}}\n')


def test_get_audio_tap_status_reports_connected():
    _seed_registry()
    out = json.loads(server.get_audio_tap_status(None))
    assert out["ok"] is True
    assert out["data"]["connected"] is True
    assert any(t["uuid"] == "master" for t in out["data"]["tracks"])


def test_list_taps_lists_tracks():
    _seed_registry()
    out = json.loads(server.list_taps(None))
    assert out["ok"] is True
    assert out["data"]["count"] >= 2


def test_uuid_for_index_matches_master_and_track():
    _seed_registry()
    assert server._uuid_for_index(-1) == "master"
    assert server._uuid_for_index(2) == "u-bass"
    assert server._uuid_for_index(99) is None


def test_reset_meter_all_and_one():
    _seed_registry()
    assert json.loads(server.reset_meter(None))["ok"] is True
    assert json.loads(server.reset_meter(None, track_index=-1))["ok"] is True


def test_read_meter_master_snapshot():
    _seed_registry()
    out = json.loads(server.read_meter(None))
    assert out["ok"] is True
    assert out["data"]["block_count"] == 1
    # read_meter now delegates to read_track_meter(-1): a signal summary.
    assert out["data"]["peak"] == 0.5
    assert "integrated_lufs" in out["data"]


def test_read_meter_no_master(monkeypatch):
    # Fresh registry (port=0 = no bind) so no master identity lingers from
    # the shared singleton seeded by other tests.
    from ableton_mcp_max.tap_registry import TapRegistry
    reg = TapRegistry(port=0)
    reg.feed("c9", '{"type":"hello","track":{"uuid":"u-only","name":"Only","index":0,"kind":"midi"}}\n')
    monkeypatch.setattr(server, "_tap_registry", reg)
    out = json.loads(server.read_meter(None))
    assert out["ok"] is False
    assert "tap" in out["error"].lower()


def _seed_master(blocks):
    reg = server._tap_registry
    reg.state.reset()
    reg.feed("m", '{"type":"hello","track":{"uuid":"master","name":"Master","index":-1,"kind":"master"},"sample_rate":48000}\n')
    for b in blocks:
        reg.feed("m", json.dumps({"type": "block", "data": b}) + "\n")


def test_read_track_meter_integrates_master_blocks():
    _seed_master([{"ms_k_l": 0.01, "ms_k_r": 0.01, "peak": 0.5, "rms": 0.1}] * 30)
    out = json.loads(server.read_track_meter(None, track_index=-1))
    assert out["ok"] is True
    d = out["data"]
    for k in ("integrated_lufs", "momentary_lufs", "short_term_lufs",
              "true_peak_dbtp", "peak", "rms", "crest", "block_count",
              "sample_rate"):
        assert k in d
    assert d["block_count"] == 30


def test_read_track_meter_empty_buffer_is_ok_with_zero_count():
    reg = server._tap_registry
    reg.state.reset()
    reg.feed("m", '{"type":"hello","track":{"uuid":"master","index":-1,"kind":"master"}}\n')
    out = json.loads(server.read_track_meter(None, track_index=-1))
    assert out["ok"] is True
    assert out["data"]["block_count"] == 0


def test_read_track_meter_unknown_track_errors():
    server._tap_registry.state.reset()
    out = json.loads(server.read_track_meter(None, track_index=99))
    assert out["ok"] is False


def test_read_meter_delegates_to_track_meter():
    _seed_master([{"ms_k_l": 0.01, "ms_k_r": 0.01, "peak": 0.5, "rms": 0.1}] * 30)
    out = json.loads(server.read_meter(None))
    assert out["ok"] is True
    assert "integrated_lufs" in out["data"]


def test_measure_loudness_reads_master_after_playback(monkeypatch):
    _seed_master([{"ms_k_l": 0.02, "ms_k_r": 0.02, "peak": 0.7, "rms": 0.2}] * 40)
    monkeypatch.setattr(server, "_run_measure_playback", lambda *a, **k: None)
    out = json.loads(server.measure_loudness(None))
    assert out["ok"] is True
    assert "integrated_lufs" in out["data"]


def test_measure_mix_returns_per_track_signal_and_findings(monkeypatch):
    reg = server._tap_registry
    reg.state.reset()
    # identities registered up front (hello); blocks arrive DURING the simulated playback window
    reg.feed("ck", '{"type":"hello","track":{"uuid":"ck","name":"Kick","index":0,"kind":"regular"},"sample_rate":48000}\n')
    reg.feed("bs", '{"type":"hello","track":{"uuid":"bs","name":"Bass","index":1,"kind":"regular"},"sample_rate":48000}\n')
    blk = lambda: '{"type":"block","data":{"ms_k_l":0.02,"ms_k_r":0.02,"peak":0.5,"rms":0.2,"bands":[1,0,0,0,0,0,0,0],"mid":1,"side":0}}\n'

    def fake_play(*a, **k):
        # measure_mix has already reset buffers; the "playback window" streams fresh blocks
        for _ in range(40):
            reg.feed("ck", blk()); reg.feed("bs", blk())
    monkeypatch.setattr(server, "_run_measure_playback", fake_play)

    out = json.loads(server.measure_mix(None, window_s=0))
    assert out["ok"] is True
    names = {t["name"] for t in out["data"]["tracks"]}
    assert {"Kick", "Bass"} <= names
    # both share band 0 -> masking finding present
    assert out["data"]["findings"]["masking"]
    # buffers were captured fresh during the window
    ck = next(t for t in out["data"]["tracks"] if t["name"] == "Kick")
    assert ck["signal"]["block_count"] == 40


def test_measure_mix_resets_stale_buffer_before_capture(monkeypatch):
    # Pre-existing stale blocks must NOT leak into the measured window.
    reg = server._tap_registry
    reg.state.reset()
    reg.feed("ck", '{"type":"hello","track":{"uuid":"ck","name":"Kick","index":0,"kind":"regular"},"sample_rate":48000}\n')
    stale = '{"type":"block","data":{"ms_k_l":0.9,"ms_k_r":0.9,"peak":0.99,"rms":0.9,"bands":[0,0,0,0,0,0,0,1],"mid":1,"side":0}}\n'
    for _ in range(100):
        reg.feed("ck", stale)   # stale history before the pass

    def fake_play(*a, **k):
        reg.feed("ck", '{"type":"block","data":{"ms_k_l":0.01,"ms_k_r":0.01,"peak":0.1,"rms":0.05,"bands":[1,0,0,0,0,0,0,0],"mid":1,"side":0}}\n')
    monkeypatch.setattr(server, "_run_measure_playback", fake_play)

    out = json.loads(server.measure_mix(None, window_s=0))
    ck = next(t for t in out["data"]["tracks"] if t["name"] == "Kick")
    # only the 1 fresh block from the window, not the 100 stale ones
    assert ck["signal"]["block_count"] == 1


def test_measure_mix_separates_master_from_per_track(monkeypatch):
    # The master tap (index -1) is post-fader: it must appear under data.master,
    # NOT in data.tracks, and must NOT skew the cross-track findings.
    reg = server._tap_registry
    reg.state.reset()
    reg.state._by_conn.clear()
    reg.state._identity.clear()
    reg.feed("ck", '{"type":"hello","track":{"uuid":"ck","name":"Kick","index":0,"kind":"regular"},"sample_rate":48000}\n')
    reg.feed("ms", '{"type":"hello","track":{"uuid":"ms","name":"Master","index":-1,"kind":"master"},"sample_rate":48000}\n')
    blk = lambda: '{"type":"block","data":{"ms_k_l":0.02,"ms_k_r":0.02,"peak":0.5,"rms":0.2,"bands":[1,0,0,0,0,0,0,0],"mid":1,"side":0}}\n'

    def fake_play(*a, **k):
        for _ in range(40):
            reg.feed("ck", blk()); reg.feed("ms", blk())
    monkeypatch.setattr(server, "_run_measure_playback", fake_play)

    out = json.loads(server.measure_mix(None, window_s=0))
    assert out["ok"] is True
    track_indices = {t["index"] for t in out["data"]["tracks"]}
    assert track_indices == {0}                       # master excluded from tracks
    assert out["data"]["master"] is not None
    assert out["data"]["master"]["index"] == -1
    assert out["data"]["master"]["signal"]["block_count"] == 40
    # balance compares per-track only -> a single instrument has no balance gap
    assert out["data"]["findings"]["balance"] == []


def test_measure_mix_master_null_when_no_master_tap(monkeypatch):
    reg = server._tap_registry
    reg.state.reset()
    reg.state._by_conn.clear()
    reg.state._identity.clear()
    reg.feed("ck", '{"type":"hello","track":{"uuid":"ck","name":"Kick","index":0,"kind":"regular"},"sample_rate":48000}\n')
    monkeypatch.setattr(server, "_run_measure_playback", lambda *a, **k: None)
    out = json.loads(server.measure_mix(None, window_s=0))
    assert out["ok"] is True
    assert out["data"]["master"] is None


def test_measure_mix_no_taps_is_ok_empty(monkeypatch):
    server._tap_registry.state.reset()
    monkeypatch.setattr(server, "_run_measure_playback", lambda *a, **k: None)
    out = json.loads(server.measure_mix(None, window_s=0))
    assert out["ok"] is True
    assert isinstance(out["data"]["tracks"], list)


# --- deploy_taps / remove_taps (Live calls stubbed via the named seams) ---

def test_deploy_taps_targets_audio_and_instrument_tracks_plus_master(monkeypatch):
    monkeypatch.setattr(server, "_find_taps", lambda: [])
    # Auto-target now also drops a master tap by default (include_master=True).
    calls = []
    monkeypatch.setattr(server, "_load_tap_on_track",
                        lambda i, tt="regular": calls.append((i, tt)) or "MCP Tap")
    monkeypatch.setattr(server, "_audio_instrument_track_indices", lambda: [0, 2, 3])
    out = json.loads(server.deploy_taps(None))
    assert out["ok"] is True
    assert calls == [(0, "regular"), (2, "regular"), (3, "regular"), (-1, "master")]
    assert [d["track_index"] for d in out["data"]["deployed"]] == [0, 2, 3, -1]
    assert out["data"]["failed"] == []


def test_deploy_taps_include_master_false_skips_master(monkeypatch):
    monkeypatch.setattr(server, "_find_taps", lambda: [])
    calls = []
    monkeypatch.setattr(server, "_load_tap_on_track",
                        lambda i, tt="regular": calls.append((i, tt)) or "MCP Tap")
    monkeypatch.setattr(server, "_audio_instrument_track_indices", lambda: [0, 2])
    out = json.loads(server.deploy_taps(None, include_master=False))
    assert out["ok"] is True
    assert calls == [(0, "regular"), (2, "regular")]
    assert -1 not in [d["track_index"] for d in out["data"]["deployed"]]


def test_deploy_taps_master_only_via_explicit_minus_one(monkeypatch):
    monkeypatch.setattr(server, "_find_taps", lambda: [])
    calls = []
    monkeypatch.setattr(server, "_load_tap_on_track",
                        lambda i, tt="regular": calls.append((i, tt)) or "MCP Tap")
    out = json.loads(server.deploy_taps(None, track_indices=[-1]))
    assert out["ok"] is True
    assert calls == [(-1, "master")]


def test_deploy_taps_explicit_indices_ignore_include_master(monkeypatch):
    monkeypatch.setattr(server, "_find_taps", lambda: [])
    # Explicit track_indices is used verbatim; include_master does not append -1.
    calls = []
    monkeypatch.setattr(server, "_load_tap_on_track",
                        lambda i, tt="regular": calls.append((i, tt)) or "MCP Tap")
    out = json.loads(server.deploy_taps(None, track_indices=[1]))
    assert out["ok"] is True
    assert calls == [(1, "regular")]


def test_deploy_taps_falls_back_to_manual_when_all_fail(monkeypatch):
    monkeypatch.setattr(server, "_find_taps", lambda: [])
    def boom(i, tt="regular"):
        raise RuntimeError("not in browser")
    monkeypatch.setattr(server, "_load_tap_on_track", boom)
    out = json.loads(server.deploy_taps(None, track_indices=[0, 1]))
    assert out["ok"] is True
    assert out["data"]["manual"] is True
    assert [f["track_index"] for f in out["data"]["failed"]] == [0, 1]
    assert out["data"]["deployed"] == []


def test_deploy_taps_confirms_via_registry_on_lost_reply(monkeypatch):
    monkeypatch.setattr(server, "_find_taps", lambda: [])
    # A slow M4L boot drops the load reply, but the device DID connect to the
    # registry -> deploy_taps should confirm it instead of failing.
    reg = server._tap_registry
    reg.state.reset()

    def slow_boom(i, tt="regular"):
        reg.feed("late", '{"type":"hello","track":{"uuid":"u-late","name":"X","index":0,"kind":"midi"}}\n')
        raise Exception("Communication error with Ableton: No data received")

    monkeypatch.setattr(server, "_load_tap_on_track", slow_boom)
    out = json.loads(server.deploy_taps(None, track_indices=[0]))
    assert out["ok"] is True
    assert out["data"]["failed"] == []
    dep = out["data"]["deployed"]
    assert dep and dep[0]["track_index"] == 0
    assert dep[0]["confirmed_via"] == "registry"


def test_deploy_taps_timeout_with_no_connection_still_fails(monkeypatch):
    monkeypatch.setattr(server, "_find_taps", lambda: [])
    # Timeout signature but nothing connects -> genuine failure (poll exhausts).
    server._tap_registry.state.reset()
    monkeypatch.setattr(server, "TAP_CONFIRM_ATTEMPTS", 1)  # don't sleep in tests

    def boom(i, tt="regular"):
        raise Exception("Communication error with Ableton: No data received")

    monkeypatch.setattr(server, "_load_tap_on_track", boom)
    out = json.loads(server.deploy_taps(None, track_indices=[0]))
    assert out["data"]["deployed"] == []
    assert out["data"]["failed"][0]["track_index"] == 0


def test_deploy_taps_does_not_false_confirm_on_preexisting_tap(monkeypatch):
    monkeypatch.setattr(server, "_find_taps", lambda: [])
    # A tap already on index 0 before the load must NOT be mistaken for the
    # (failed) new load's device.
    reg = server._tap_registry
    reg.state.reset()
    reg.feed("old", '{"type":"hello","track":{"uuid":"u-old","name":"Old","index":0,"kind":"midi"}}\n')
    monkeypatch.setattr(server, "TAP_CONFIRM_ATTEMPTS", 1)

    def boom(i, tt="regular"):
        raise Exception("Communication error with Ableton: No data received")

    monkeypatch.setattr(server, "_load_tap_on_track", boom)
    out = json.loads(server.deploy_taps(None, track_indices=[0]))
    assert out["data"]["deployed"] == []
    assert out["data"]["failed"][0]["track_index"] == 0


def test_deploy_taps_non_timeout_error_fails_fast_without_polling(monkeypatch):
    monkeypatch.setattr(server, "_find_taps", lambda: [])
    # A clean 'not in browser' error must not trigger the registry poll.
    polled = []
    monkeypatch.setattr(server, "_confirm_tap_via_registry",
                        lambda *a, **k: polled.append(True))

    def boom(i, tt="regular"):
        raise RuntimeError("MCP Tap device has no loadable URI")

    monkeypatch.setattr(server, "_load_tap_on_track", boom)
    out = json.loads(server.deploy_taps(None, track_indices=[0]))
    assert out["data"]["failed"][0]["track_index"] == 0
    assert polled == []  # fast path: no registry confirm attempted


def test_remove_taps_deletes_matched_devices(monkeypatch):
    found = [("regular", 0, 1), ("regular", 2, 0)]
    monkeypatch.setattr(server, "_find_taps", lambda: list(found))
    deleted = []
    monkeypatch.setattr(server, "_delete_device_raw",
                        lambda tt, ti, di: deleted.append((tt, ti, di)))
    out = json.loads(server.remove_taps(None))
    assert out["ok"] is True
    assert set(deleted) == set(found)
    assert out["data"]["removed_count"] == 2


def test_remove_taps_deletes_master_tap(monkeypatch):
    # A tap on the master bus is found + deleted via track_type='master'.
    found = [("regular", 0, 0), ("master", 0, 1)]
    monkeypatch.setattr(server, "_find_taps", lambda: list(found))
    deleted = []
    monkeypatch.setattr(server, "_delete_device_raw",
                        lambda tt, ti, di: deleted.append((tt, ti, di)))
    out = json.loads(server.remove_taps(None))
    assert out["ok"] is True
    assert ("master", 0, 1) in deleted
    types = {r["track_type"] for r in out["data"]["removed"]}
    assert "master" in types


def test_remove_taps_none_found_is_ok(monkeypatch):
    monkeypatch.setattr(server, "_find_taps", lambda: [])
    out = json.loads(server.remove_taps(None))
    assert out["ok"] is True
    assert out["data"]["removed_count"] == 0


# --- deploy_taps is idempotent: never stack a duplicate tap -------------------
# apply_master always taps the master, so without this every mastering pass
# appended another MCP Tap to it (observed live: [0]Ozone, [1]Tap, [2]Tap).

def test_deploy_taps_skips_track_that_already_has_a_tap(monkeypatch):
    calls = []
    monkeypatch.setattr(server, "_find_taps", lambda: [("master", 0, 1)])
    monkeypatch.setattr(server, "_load_tap_on_track",
                        lambda i, tt="regular": calls.append((i, tt)) or "MCP Tap")
    out = json.loads(server.deploy_taps(None, track_indices=[-1]))
    assert out["ok"] is True
    assert calls == []                                    # no second load
    assert out["data"]["deployed"] == []
    assert [a["track_index"] for a in out["data"]["already_present"]] == [-1]
    assert out["data"]["failed"] == []
    assert "manual" not in out["data"]                    # skipping is success


def test_deploy_taps_deploys_only_the_untapped_tracks(monkeypatch):
    calls = []
    monkeypatch.setattr(server, "_find_taps", lambda: [("regular", 2, 0)])
    monkeypatch.setattr(server, "_load_tap_on_track",
                        lambda i, tt="regular": calls.append((i, tt)) or "MCP Tap")
    out = json.loads(server.deploy_taps(None, track_indices=[0, 2, -1]))
    assert calls == [(0, "regular"), (-1, "master")]      # track 2 skipped
    assert [d["track_index"] for d in out["data"]["deployed"]] == [0, -1]
    assert [a["track_index"] for a in out["data"]["already_present"]] == [2]


def test_apply_master_reports_present_when_master_already_tapped(monkeypatch):
    monkeypatch.setattr(server, "get_ableton_connection", lambda: object())
    monkeypatch.setattr(server, "set_ozone_state",
                        lambda *a, **k: json.dumps({"ok": True, "data": {
                            "reloaded": True, "applied": [], "skipped": []}}))
    monkeypatch.setattr(server, "expose_ozone_modules",
                        lambda *a, **k: json.dumps({"ok": True, "data": {}}))
    monkeypatch.setattr(server, "_find_taps", lambda: [("master", 0, 1)])
    monkeypatch.setattr(server, "_load_tap_on_track",
                        lambda i, tt="regular": pytest.fail("must not re-tap"))
    out = json.loads(server.apply_master(ctx=None, chain={"MAX": {}}))
    assert out["ok"] is True
    assert out["data"]["tap"]["status"] == "present"
