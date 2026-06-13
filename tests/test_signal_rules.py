"""evaluate_rules treats a signal_required rule as auto when signal is present."""
from ableton_mcp_max.analysis_utils import evaluate_rules

_LOUDNESS = {
    "id": "mastering.loudness_target", "domain": "mastering",
    "title": "Integrated loudness in target range", "severity": "warn",
    "mode": "auto", "signal_required": True, "scope": "master",
    "check": {"all": [
        {"field": "signal.integrated_lufs", "op": "gte", "value": -16.0},
        {"field": "signal.integrated_lufs", "op": "lte", "value": -8.0},
    ]},
}


def _snapshot(signal):
    return {"tracks": [], "returns": [],
            "master": {"name": "Master", "device_names": [], "signal": signal}}


def test_deferred_when_signal_absent():
    res = evaluate_rules([_LOUDNESS], _snapshot(None))
    assert res["findings"] == []
    assert any(d["id"] == "mastering.loudness_target" for d in res["deferred_rules"])


def test_evaluated_pass_when_signal_in_range():
    res = evaluate_rules([_LOUDNESS], _snapshot({"integrated_lufs": -14.0}))
    assert res["deferred_rules"] == []
    f = next(f for f in res["findings"] if f["id"] == "mastering.loudness_target")
    assert f["status"] == "pass"


def test_evaluated_warn_when_signal_out_of_range():
    res = evaluate_rules([_LOUDNESS], _snapshot({"integrated_lufs": -5.0}))
    f = next(f for f in res["findings"] if f["id"] == "mastering.loudness_target")
    assert f["status"] == "warn"
