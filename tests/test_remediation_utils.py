# tests/test_remediation_utils.py
import math
from ableton_mcp_max.remediation_utils import db_to_live_volume
from ableton_mcp_max.analysis_utils import live_volume_to_db

_UNITY = 0.85

def test_db_to_live_volume_unity():
    assert abs(db_to_live_volume(0.0) - _UNITY) < 0.001

def test_db_to_live_volume_floor_clamp():
    assert db_to_live_volume(-999.0) == 0.0

def test_db_to_live_volume_ceil_clamp():
    assert db_to_live_volume(999.0) == 1.0

def test_db_to_live_volume_roundtrip():
    # live_volume_to_db rounds to 1 decimal place, so max quantization error
    # at the taper extremes is ~0.002 linear (< 0.05 dB). Tolerance = 0.002.
    for v in [0.2, 0.5, 0.85, 0.95, 1.0]:
        db = live_volume_to_db(v)
        assert abs(db_to_live_volume(db) - v) < 0.002, f"roundtrip failed for v={v}"

def test_db_to_live_volume_negative_3():
    v = db_to_live_volume(-3.0)
    assert 0.0 < v < _UNITY
    # must round-trip within 0.1 dB
    assert abs(live_volume_to_db(v) - (-3.0)) < 0.1


from ableton_mcp_max.remediation_utils import generate_actions

# Minimal snapshot with one regular track (index 0) and master
_SNAPSHOT = {
    "tracks": [
        {"index": 0, "name": "Bass", "type": "regular",
         "mixer": {"volume_db": 1.5, "solo": False}},
        {"index": 1, "name": "Lead", "type": "regular",
         "mixer": {"volume_db": 0.5, "solo": True}},
    ],
    "returns": [],
    "master": {
        "volume_db": 0.0,
        "signal": {"true_peak_dbtp": 0.2, "integrated_lufs": -11.0},
    },
}

def test_generate_actions_solo_finding():
    findings = [
        {"id": "health.no_leftover_solo", "status": "fail", "severity": "fail",
         "entity": "Lead", "remediation": "Clear the solo."},
    ]
    result = generate_actions(findings, _SNAPSHOT)
    assert len(result) == 1
    action = result[0].get("action")
    assert action is not None
    assert action["tool"] == "set_mixer_property"
    assert action["params"]["track_index"] == 1
    assert action["params"]["property"] == "solo"
    assert action["params"]["value"] == 0.0

def test_generate_actions_fader_headroom():
    findings = [
        {"id": "mixing.fader_headroom", "status": "warn", "severity": "warn",
         "entity": "Bass", "remediation": "Gain-stage below 0 dB."},
    ]
    result = generate_actions(findings, _SNAPSHOT)
    action = result[0].get("action")
    assert action is not None
    assert action["tool"] == "set_mixer_property"
    assert action["params"]["track_index"] == 0
    assert action["params"]["property"] == "volume"
    assert action["params"]["value"] < _UNITY   # below unity = lower than current

def test_generate_actions_true_peak():
    findings = [
        {"id": "mastering.true_peak", "status": "fail", "severity": "fail",
         "entity": None, "remediation": "Lower the ceiling."},
    ]
    result = generate_actions(findings, _SNAPSHOT)
    action = result[0].get("action")
    assert action is not None
    assert action["tool"] == "set_mixer_property"
    assert action["params"]["track_type"] == "master"
    assert action["params"]["value"] < _UNITY   # lowered from 0.85

def test_generate_actions_true_peak_no_signal():
    snapshot_no_sig = dict(_SNAPSHOT)
    snapshot_no_sig["master"] = {"volume_db": 0.0, "signal": None}
    findings = [
        {"id": "mastering.true_peak", "status": "fail", "severity": "fail",
         "entity": None, "remediation": "Lower the ceiling."},
    ]
    result = generate_actions(findings, snapshot_no_sig)
    assert result[0].get("action") is None

def test_generate_actions_no_fix_passes_through():
    findings = [
        {"id": "mixing.spectral_masking", "status": "warn", "severity": "warn",
         "items": [], "remediation": "EQ-carve."},
    ]
    result = generate_actions(findings, _SNAPSHOT)
    assert result[0].get("action") is None

def test_generate_actions_pass_status_unchanged():
    findings = [
        {"id": "health.no_leftover_solo", "status": "pass", "severity": "fail",
         "entity": "Bass"},
    ]
    result = generate_actions(findings, _SNAPSHOT)
    # pass-status findings don't get an action even if the id is fixable
    assert result[0].get("action") is None

def test_generate_actions_unknown_entity_skipped():
    findings = [
        {"id": "health.no_leftover_solo", "status": "fail", "severity": "fail",
         "entity": "GhostTrack"},  # not in snapshot
    ]
    result = generate_actions(findings, _SNAPSHOT)
    assert result[0].get("action") is None


def test_generate_actions_no_clipping_track():
    findings = [
        {"id": "health.no_clipping", "status": "fail", "severity": "fail",
         "entity": "Drums", "track_index": 3, "track_type": "regular",
         "peak_dbfs": 2.0, "current_volume_db": 1.5,
         "remediation": "Trim track gain."},
    ]
    result = generate_actions(findings, _SNAPSHOT)
    action = result[0].get("action")
    assert action is not None
    assert action["tool"] == "set_mixer_property"
    assert action["params"]["track_index"] == 3
    assert action["params"]["track_type"] == "regular"
    assert action["params"]["property"] == "volume"
    # target peak -3 dBFS: drop fader by (2.0 - (-3.0)) = 5 dB, 1.5 -> -3.5 dB
    from ableton_mcp_max.remediation_utils import db_to_live_volume
    assert abs(action["params"]["value"] - db_to_live_volume(-3.5)) < 0.001


def test_generate_actions_no_clipping_master():
    findings = [
        {"id": "health.no_clipping", "status": "fail", "severity": "fail",
         "entity": "Master", "track_index": 0, "track_type": "master",
         "peak_dbfs": 1.0, "current_volume_db": 0.0,
         "remediation": "Trim master."},
    ]
    result = generate_actions(findings, _SNAPSHOT)
    action = result[0].get("action")
    assert action is not None
    assert action["params"]["track_type"] == "master"
    assert action["params"]["value"] < _UNITY


def test_generate_actions_no_clipping_missing_data_skipped():
    findings = [
        {"id": "health.no_clipping", "status": "fail", "severity": "fail",
         "entity": "Drums", "track_index": 3, "track_type": "regular"},
    ]  # no peak_dbfs / current_volume_db
    result = generate_actions(findings, _SNAPSHOT)
    assert result[0].get("action") is None


from ableton_mcp_max.remediation_utils import build_correction_plan

_ACTION_SOLO = {
    "tool": "set_mixer_property",
    "params": {"track_index": 1, "property": "solo", "value": 0.0, "track_type": "regular"},
}
_ACTION_VOL = {
    "tool": "set_mixer_property",
    "params": {"track_index": 0, "property": "volume", "value": 0.7, "track_type": "regular"},
}
_ACTION_MASTER = {
    "tool": "set_mixer_property",
    "params": {"track_index": 0, "property": "volume", "value": 0.8, "track_type": "master"},
}

_ENRICHED = [
    {"id": "health.no_leftover_solo", "status": "fail", "severity": "fail",
     "entity": "Lead", "action": _ACTION_SOLO},
    {"id": "mixing.fader_headroom", "status": "warn", "severity": "warn",
     "entity": "Bass", "action": _ACTION_VOL},
    {"id": "mastering.true_peak", "status": "fail", "severity": "fail",
     "action": _ACTION_MASTER},
    {"id": "mixing.spectral_masking", "status": "warn", "severity": "warn",
     "items": []},   # no action
    {"id": "health.track_named", "status": "info", "severity": "info",
     "entity": "1-MIDI"},  # filtered by severity
]

def test_build_plan_basic():
    plan = build_correction_plan(_ENRICHED, severity_filter=["fail", "warn"], focus=None)
    ids = [p["finding_id"] for p in plan["plan"]]
    assert "health.no_leftover_solo" in ids
    assert "mixing.fader_headroom" in ids
    assert "mastering.true_peak" in ids

def test_build_plan_skips_no_action():
    plan = build_correction_plan(_ENRICHED, severity_filter=["fail", "warn"], focus=None)
    ids = [p["finding_id"] for p in plan["plan"]]
    assert "mixing.spectral_masking" not in ids
    assert plan["skipped_count"] >= 1
    assert "mixing.spectral_masking" in plan["skipped_reasons"]

def test_build_plan_severity_filter():
    plan = build_correction_plan(_ENRICHED, severity_filter=["fail"], focus=None)
    ids = [p["finding_id"] for p in plan["plan"]]
    assert "mixing.fader_headroom" not in ids   # warn, not fail

def test_build_plan_focus_filter():
    plan = build_correction_plan(_ENRICHED, severity_filter=["fail", "warn"],
                                  focus=["health.no_leftover_solo"])
    ids = [p["finding_id"] for p in plan["plan"]]
    assert ids == ["health.no_leftover_solo"]

def test_build_plan_sequence_health_first():
    plan = build_correction_plan(_ENRICHED, severity_filter=["fail", "warn"], focus=None)
    ids = [p["finding_id"] for p in plan["plan"]]
    # health findings must come before mixing/mastering
    health_pos = next(i for i, x in enumerate(ids) if x.startswith("health."))
    other_pos = [i for i, x in enumerate(ids) if not x.startswith("health.")]
    assert all(health_pos < op for op in other_pos)

def test_build_plan_dedup_same_target():
    # Two findings targeting same track_index + property -> keep last
    dup = [
        {"id": "mixing.fader_headroom", "status": "warn", "severity": "warn",
         "entity": "A", "action": {
             "tool": "set_mixer_property",
             "params": {"track_index": 0, "property": "volume", "value": 0.6, "track_type": "regular"}}},
        {"id": "mixing.fader_headroom", "status": "warn", "severity": "warn",
         "entity": "A", "action": {
             "tool": "set_mixer_property",
             "params": {"track_index": 0, "property": "volume", "value": 0.7, "track_type": "regular"}}},
    ]
    plan = build_correction_plan(dup, severity_filter=["warn"], focus=None)
    assert plan["planned_count"] == 1
    assert plan["plan"][0]["action"]["params"]["value"] == 0.7  # last wins

def test_build_plan_counts():
    plan = build_correction_plan(_ENRICHED, severity_filter=["fail", "warn"], focus=None)
    assert plan["planned_count"] == len(plan["plan"])
    assert plan["planned_count"] + plan["skipped_count"] == len(_ENRICHED)


from ableton_mcp_max.remediation_utils import compute_balance_deltas

def test_compute_balance_deltas_basic():
    signals = [
        {"index": 0, "name": "Kick", "integrated_lufs": -14.0},
        {"index": 1, "name": "Bass", "integrated_lufs": -22.0},
        {"index": 2, "name": "Lead", "integrated_lufs": -14.5},
    ]
    deltas = compute_balance_deltas(signals, reference_idx=0, target_offsets=None)
    # reference (idx 0) should be skipped or have delta 0
    ref = next(d for d in deltas if d["track_index"] == 0)
    assert ref["skipped"] is True
    # Bass is 8 dB below ref, default spread 12 dB -> within spread -> skipped? No...
    # Actually it should NOT be skipped -- default behavior is match to ref with offset 0
    bass = next(d for d in deltas if d["track_index"] == 1)
    assert abs(bass["delta_db"] - 8.0) < 0.1   # -22 + 8 = -14 = reference

def test_compute_balance_deltas_within_tolerance():
    signals = [
        {"index": 0, "name": "A", "integrated_lufs": -14.0},
        {"index": 1, "name": "B", "integrated_lufs": -14.4},  # within 1 dB
    ]
    deltas = compute_balance_deltas(signals, reference_idx=0, target_offsets=None)
    b = next(d for d in deltas if d["track_index"] == 1)
    assert b["skipped"] is True  # within tolerance

def test_compute_balance_deltas_custom_offset():
    signals = [
        {"index": 0, "name": "Kick", "integrated_lufs": -14.0},
        {"index": 1, "name": "Bass", "integrated_lufs": -14.0},
    ]
    # Bass should sit 3 dB below Kick
    offsets = [{"track_index": 1, "offset_db": -3.0}]
    deltas = compute_balance_deltas(signals, reference_idx=0, target_offsets=offsets)
    bass = next(d for d in deltas if d["track_index"] == 1)
    assert abs(bass["delta_db"] - (-3.0)) < 0.1   # needs to go down 3 dB

def test_compute_balance_deltas_missing_lufs_skipped():
    signals = [
        {"index": 0, "name": "A", "integrated_lufs": -14.0},
        {"index": 1, "name": "B", "integrated_lufs": None},
    ]
    deltas = compute_balance_deltas(signals, reference_idx=0, target_offsets=None)
    b = next(d for d in deltas if d["track_index"] == 1)
    assert b["skipped"] is True
