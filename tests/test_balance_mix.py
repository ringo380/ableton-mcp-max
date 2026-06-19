import json
import ableton_mcp_max.server as server


def test_balance_mix_applies_corrections(monkeypatch):
    """Two tracks: ref at -14, other at -22 (delta +8). Should call set_mixer_property."""
    set_calls = []

    class _FakeConn:
        def send_command(self, cmd, params=None):
            if cmd == "set_mixer_property":
                set_calls.append(params)
            if cmd == "get_mixer":
                return {"volume": 0.75}
            return {}

    TRACKS_OUT = [
        {"name": "Kick", "index": 0, "kind": "regular",
         "signal": {"integrated_lufs": -14.0}},
        {"name": "Bass", "index": 1, "kind": "regular",
         "signal": {"integrated_lufs": -22.0}},
    ]
    SIGS = [
        {"index": 0, "name": "Kick", "integrated_lufs": -14.0},
        {"index": 1, "name": "Bass", "integrated_lufs": -22.0},
    ]

    monkeypatch.setattr(server, "_measure_pass",
                        lambda w, region=None, name_by_index=None: (TRACKS_OUT, SIGS))
    monkeypatch.setattr(server, "get_ableton_connection", lambda: _FakeConn())

    out = json.loads(server.balance_mix(ctx=None, reference_track_index=0))
    assert out["ok"] is True
    d = out["data"]
    assert d["reference_track_index"] == 0
    assert d["reference_db"] == -14.0
    adj = {a["track_index"]: a for a in d["adjustments"]}
    assert adj[0]["skipped"] is True       # reference is always skipped
    assert adj[1]["skipped"] is False
    assert abs(adj[1]["delta_db"] - 8.0) < 0.1
    # set_mixer_property was called for Bass
    assert any(c["track_index"] == 1 for c in set_calls)


def test_balance_mix_within_tolerance_skips(monkeypatch):
    """Tracks already within 1 dB of reference should be skipped."""
    class _FakeConn:
        def send_command(self, cmd, params=None): return {}

    TRACKS_OUT = [
        {"name": "A", "index": 0, "kind": "regular", "signal": {"integrated_lufs": -14.0}},
        {"name": "B", "index": 1, "kind": "regular", "signal": {"integrated_lufs": -14.5}},
    ]
    SIGS = [
        {"index": 0, "name": "A", "integrated_lufs": -14.0},
        {"index": 1, "name": "B", "integrated_lufs": -14.5},
    ]
    monkeypatch.setattr(server, "_measure_pass",
                        lambda w, region=None, name_by_index=None: (TRACKS_OUT, SIGS))
    monkeypatch.setattr(server, "get_ableton_connection", lambda: _FakeConn())

    out = json.loads(server.balance_mix(ctx=None, reference_track_index=0))
    d = out["data"]
    adj = {a["track_index"]: a for a in d["adjustments"]}
    assert adj[1]["skipped"] is True


def test_balance_mix_custom_offsets(monkeypatch):
    """Bass should sit 3 dB below Kick via target_offsets."""
    set_calls = []

    class _FakeConn:
        def send_command(self, cmd, params=None):
            if cmd == "set_mixer_property":
                set_calls.append(params)
            if cmd == "get_mixer":
                return {"volume": 0.85}
            return {}

    SIGS = [
        {"index": 0, "name": "Kick", "integrated_lufs": -14.0},
        {"index": 1, "name": "Bass", "integrated_lufs": -14.0},  # same as ref
    ]
    TRACKS_OUT = [{"name": s["name"], "index": s["index"], "kind": "regular",
                   "signal": {"integrated_lufs": s["integrated_lufs"]}} for s in SIGS]

    monkeypatch.setattr(server, "_measure_pass",
                        lambda w, region=None, name_by_index=None: (TRACKS_OUT, SIGS))
    monkeypatch.setattr(server, "get_ableton_connection", lambda: _FakeConn())

    out = json.loads(server.balance_mix(
        ctx=None, reference_track_index=0,
        target_offsets=[{"track_index": 1, "offset_db": -3.0}]
    ))
    d = out["data"]
    adj = {a["track_index"]: a for a in d["adjustments"]}
    assert adj[1]["skipped"] is False
    assert abs(adj[1]["delta_db"] - (-3.0)) < 0.1
