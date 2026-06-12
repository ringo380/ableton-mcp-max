import pytest
from ableton_mcp_max.analysis_utils import resolve_path


SNAP = {
    "transport": {"tempo": 120.0},
    "master": {"device_names": ["EQ Eight", "Limiter"]},
    "tracks": [
        {"name": "Bass", "mixer": {"volume_db": -6.0}, "devices": [{"class": "Eq8"}]},
        {"name": "Lead", "mixer": {"volume_db": 2.0}, "devices": [{"class": "Compressor2"}]},
    ],
}


def test_resolve_scalar():
    assert resolve_path(SNAP, "transport.tempo") == 120.0


def test_resolve_missing_is_none():
    assert resolve_path(SNAP, "transport.nope") is None
    assert resolve_path(SNAP, "nope.deep.path") is None


def test_resolve_list_projection():
    assert resolve_path(SNAP, "tracks[*].name") == ["Bass", "Lead"]


def test_resolve_nested_list_projection_flattens():
    assert resolve_path(SNAP, "tracks[*].devices[*].class") == ["Eq8", "Compressor2"]


def test_resolve_plain_list():
    assert resolve_path(SNAP, "master.device_names") == ["EQ Eight", "Limiter"]


from ableton_mcp_max.analysis_utils import evaluate_check


def test_op_includes():
    assert evaluate_check({"field": "master.device_names", "op": "includes", "value": "Limiter"}, SNAP) is True
    assert evaluate_check({"field": "master.device_names", "op": "includes", "value": "Saturator"}, SNAP) is False


def test_op_numeric():
    assert evaluate_check({"field": "transport.tempo", "op": "gt", "value": 100}, SNAP) is True
    assert evaluate_check({"field": "transport.tempo", "op": "lte", "value": 120}, SNAP) is True
    assert evaluate_check({"field": "transport.tempo", "op": "equals", "value": 120.0}, SNAP) is True


def test_op_exists_and_missing():
    assert evaluate_check({"field": "master", "op": "exists"}, SNAP) is True
    assert evaluate_check({"field": "nope", "op": "exists"}, SNAP) is False
    # numeric op on a missing field is False, never raises
    assert evaluate_check({"field": "nope", "op": "gt", "value": 0}, SNAP) is False


def test_op_matches_list_any():
    assert evaluate_check({"field": "tracks[*].devices[*].class", "op": "matches", "value": "^Eq"}, SNAP) is True
    assert evaluate_check({"field": "tracks[*].name", "op": "matches", "value": "^Drum"}, SNAP) is False


def test_op_count():
    assert evaluate_check({"field": "tracks[*].name", "op": "count_gt", "value": 1}, SNAP) is True
    assert evaluate_check({"field": "tracks[*].name", "op": "count_lt", "value": 5}, SNAP) is True


def test_composition_all_any_not():
    chk = {"all": [
        {"field": "transport.tempo", "op": "gt", "value": 100},
        {"any": [
            {"field": "master.device_names", "op": "includes", "value": "Limiter"},
            {"field": "master.device_names", "op": "includes", "value": "Saturator"},
        ]},
        {"not": {"field": "tracks[*].name", "op": "includes", "value": "Vocals"}},
    ]}
    assert evaluate_check(chk, SNAP) is True
from ableton_mcp_max.analysis_utils import evaluate_rules


RULES = [
    {"id": "master.limiter_present", "domain": "mastering", "severity": "fail",
     "mode": "auto", "scope": "master",
     "check": {"field": "device_names", "op": "includes", "value": "Limiter"},
     "evidence_template": "Master chain: {device_names}",
     "remediation": "Add a Limiter as the last master device."},
    {"id": "track.fader_headroom", "domain": "mixing", "severity": "warn",
     "mode": "auto", "scope": "track",
     "check": {"field": "mixer.volume_db", "op": "lte", "value": 0.0},
     "evidence_template": "{name} fader at {mixer.volume_db} dB",
     "remediation": "Gain-stage below 0 dB."},
    {"id": "sound.reverb_tail_taste", "domain": "sound_design", "severity": "info",
     "mode": "manual", "title": "Reverb tails sit in the groove",
     "rationale": "Long tails at fast tempos can wash the mix."},
    {"id": "master.loudness_target", "domain": "mastering", "severity": "warn",
     "mode": "deferred", "signal_required": True,
     "title": "Integrated loudness in target range"},
]


def test_evaluate_rules_master_pass():
    snap = {"master": {"device_names": ["EQ Eight", "Limiter"]}, "tracks": [], "returns": []}
    out = evaluate_rules(RULES, snap)
    f = [x for x in out["findings"] if x["id"] == "master.limiter_present"][0]
    assert f["status"] == "pass"
    assert f["evidence"] == "Master chain: ['EQ Eight', 'Limiter']"


def test_evaluate_rules_master_fail_and_evidence():
    snap = {"master": {"device_names": ["EQ Eight"]}, "tracks": [], "returns": []}
    out = evaluate_rules(RULES, snap)
    f = [x for x in out["findings"] if x["id"] == "master.limiter_present"][0]
    assert f["status"] == "fail"
    assert f["remediation"] == "Add a Limiter as the last master device."


def test_evaluate_rules_track_scope_emits_per_offender():
    snap = {"master": {"device_names": ["Limiter"]}, "returns": [], "tracks": [
        {"name": "Bass", "mixer": {"volume_db": -6.0}},
        {"name": "Lead", "mixer": {"volume_db": 2.1}},
    ]}
    out = evaluate_rules(RULES, snap)
    fader = [x for x in out["findings"] if x["id"] == "track.fader_headroom"]
    assert len(fader) == 1
    assert fader[0]["status"] == "warn"
    assert fader[0]["entity"] == "Lead"


def test_evaluate_rules_track_scope_all_pass_single_finding():
    snap = {"master": {"device_names": ["Limiter"]}, "returns": [], "tracks": [
        {"name": "Bass", "mixer": {"volume_db": -6.0}},
    ]}
    out = evaluate_rules(RULES, snap)
    fader = [x for x in out["findings"] if x["id"] == "track.fader_headroom"]
    assert len(fader) == 1 and fader[0]["status"] == "pass"


def test_evaluate_rules_routes_manual_and_deferred():
    snap = {"master": {"device_names": ["Limiter"]}, "tracks": [], "returns": []}
    out = evaluate_rules(RULES, snap)
    assert [m["id"] for m in out["manual_rules"]] == ["sound.reverb_tail_taste"]
    assert [d["id"] for d in out["deferred_rules"]] == ["master.loudness_target"]
    assert out["deferred_rules"][0]["reason"] == "needs metering"


def test_summary_counts():
    snap = {"master": {"device_names": ["EQ Eight"]}, "returns": [], "tracks": [
        {"name": "Lead", "mixer": {"volume_db": 2.1}},
    ]}
    out = evaluate_rules(RULES, snap)
    s = out["summary"]
    assert s["fail"] == 1 and s["warn"] == 1
    assert s["manual"] == 1 and s["deferred"] == 1
