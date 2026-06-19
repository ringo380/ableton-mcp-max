import json
import ableton_mcp_max.server as server


# A realistic enriched findings list (as returned by the enhanced analyze_set)
_ACTION_SOLO = {"tool": "set_mixer_property",
                "params": {"track_index": 1, "property": "solo", "value": 0.0,
                           "track_type": "regular"},
                "reason": "Lead solo cleared"}
_ACTION_VOL  = {"tool": "set_mixer_property",
                "params": {"track_index": 0, "property": "volume", "value": 0.76,
                           "track_type": "regular"},
                "reason": "Bass fader -> -3.0 dB"}

_FINDINGS = [
    {"id": "health.no_leftover_solo", "status": "fail", "severity": "fail",
     "entity": "Lead", "action": _ACTION_SOLO},
    {"id": "mixing.fader_headroom", "status": "warn", "severity": "warn",
     "entity": "Bass", "action": _ACTION_VOL},
    {"id": "mixing.spectral_masking", "status": "warn", "severity": "warn",
     "items": []},  # no action
]


def test_apply_findings_dry_run_returns_plan_only():
    """dry_run=True should never call set_mixer_property."""
    set_calls = []

    class _FakeConn:
        def send_command(self, cmd, params=None):
            if cmd == "set_mixer_property":
                set_calls.append(params)
            return {}

    orig = server.get_ableton_connection
    server.get_ableton_connection = lambda: _FakeConn()
    try:
        out = json.loads(server.apply_findings(
            ctx=None, findings=_FINDINGS, dry_run=True, severity_filter=["fail", "warn"]
        ))
        assert out["ok"] is True
        d = out["data"]
        assert d["dry_run"] is True
        assert d["planned_count"] >= 2
        assert all(p["status"] == "planned" for p in d["plan"])
        assert set_calls == []  # no mutations
    finally:
        server.get_ableton_connection = orig


def test_apply_findings_applies_when_not_dry_run():
    set_calls = []

    class _FakeConn:
        def send_command(self, cmd, params=None):
            if cmd == "set_mixer_property":
                set_calls.append(params)
            return {}

    orig = server.get_ableton_connection
    server.get_ableton_connection = lambda: _FakeConn()
    try:
        out = json.loads(server.apply_findings(
            ctx=None, findings=_FINDINGS, dry_run=False, severity_filter=["fail", "warn"]
        ))
        assert out["ok"] is True
        d = out["data"]
        assert d["dry_run"] is False
        applied = [p for p in d["plan"] if p["status"] == "applied"]
        assert len(applied) >= 2
        assert len(set_calls) >= 2
    finally:
        server.get_ableton_connection = orig


def test_apply_findings_skips_no_action():
    orig = server.get_ableton_connection
    server.get_ableton_connection = lambda: type("C", (), {"send_command": lambda s, c, p=None: {}})()
    try:
        out = json.loads(server.apply_findings(
            ctx=None, findings=_FINDINGS, dry_run=True, severity_filter=["fail", "warn"]
        ))
        d = out["data"]
        skipped = d["skipped_reasons"]
        assert "mixing.spectral_masking" in skipped
    finally:
        server.get_ableton_connection = orig


def test_apply_findings_severity_filter():
    orig = server.get_ableton_connection
    server.get_ableton_connection = lambda: type("C", (), {"send_command": lambda s, c, p=None: {}})()
    try:
        out = json.loads(server.apply_findings(
            ctx=None, findings=_FINDINGS, dry_run=True, severity_filter=["fail"]
        ))
        d = out["data"]
        ids = [p["finding_id"] for p in d["plan"]]
        assert "mixing.fader_headroom" not in ids   # warn only
        assert "health.no_leftover_solo" in ids      # fail
    finally:
        server.get_ableton_connection = orig


def test_analyze_set_enriches_findings(monkeypatch):
    """analyze_set should add action fields to fixable findings."""
    _RAW = {
        "transport": {"tempo": 120.0, "is_playing": False,
                      "signature_numerator": 4, "signature_denominator": 4},
        "tracks": [
            {"name": "Lead", "index": 0, "type": "midi", "volume": 0.95, "panning": 0.0,
             "sends": [0.0], "mute": False, "solo": True, "arm": False,
             "has_instrument": True, "is_grouped": False,
             "devices": [{"index": 0, "name": "Wavetable", "class_name": "InstrumentVector",
                          "on": True, "is_instrument": True}],
             "clips": {"count": 0, "named": 0, "warped": 0, "empty_slots": 8},
             "routing": {"audio_to": "Master", "audio_from": "No Input"}},
        ],
        "returns": [],
        "master": {"name": "Master", "volume": 0.85, "panning": 0.0, "devices": []},
    }

    class _FakeConn:
        def send_command(self, cmd, params=None):
            return _RAW

    monkeypatch.setattr(server, "get_ableton_connection", lambda: _FakeConn())
    out = json.loads(server.analyze_set(ctx=None, focus="health"))
    assert out["ok"] is True
    findings = out["data"]["findings"]
    solo_f = next((f for f in findings if f["id"] == "health.no_leftover_solo"
                   and f["status"] == "fail"), None)
    assert solo_f is not None
    assert "action" in solo_f
    assert solo_f["action"]["tool"] == "set_mixer_property"
    assert solo_f["action"]["params"]["property"] == "solo"
