import os
from ableton_mcp_max import server
from ableton_mcp_max import ozone_state_utils as osu

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "ozone_processor_state.bin")
BLOB = open(FIXTURE, "rb").read()
HEX = osu.to_hex(BLOB)

# Minimal Live 12 master-track XML embedding the real Ozone ProcessorState.
XML = (
    '<Ableton><LiveSet><Tracks></Tracks>'
    '<MainTrack Id="9" SelectedToolPanel="7"><DeviceChain>'
    '<ProcessorState>' + HEX + '</ProcessorState>'
    '<ControllerState />'
    '</DeviceChain></MainTrack>'
    '</LiveSet></Ableton>'
)


def test_read_impl_returns_module_leaves():
    res = server._ozone_state_read_impl(
        0, 0, "master", "MAX",
        save_impl=lambda: {"saved": True},
        read_als=lambda p: XML,
        resolve_path=lambda: "/x.als",
        title_fn=lambda: "x")
    assert res["ok"] is True
    assert res["module"] == "Maximizer"
    names = {p["name"]: p for p in res["params"]}
    assert names["Character"]["value"] == 2
    assert names["Target Loudness [dB]"]["type"] == "Float"


def test_read_impl_rejects_non_ozone():
    bad = XML.replace(HEX, "DEADBEEF")
    res = server._ozone_state_read_impl(
        0, 0, "master", "MAX",
        save_impl=lambda: {"saved": True},
        read_als=lambda p: bad,
        resolve_path=lambda: "/x.als", title_fn=lambda: "x")
    assert res["ok"] is False
    assert "Ozone" in res["error"]


def test_mutate_impl_writes_native_value_and_reports_skips():
    written = {}
    res = server._ozone_state_mutate_impl(
        0, 0, "master",
        {"MAX": {"Target Loudness [dB]": -9.0, "NoParam": 1}}, reload=False,
        save_impl=lambda: {"saved": True},
        reload_impl=lambda p, n: {"reloaded": True},
        read_als=lambda p: XML,
        write_als=lambda p, x: written.update(xml=x),
        resolve_path=lambda: "/x.als", title_fn=lambda: "x")
    assert res["ok"] is True
    assert {"module": "Maximizer", "param": "Target Loudness [dB]", "value": -9.0} in res["applied"]
    assert any(s["param"] == "NoParam" for s in res["skipped"])
    # the written .als carries the native value in the re-encoded blob
    import re
    m = re.search(r"<ProcessorState>([0-9A-F]+)</ProcessorState>", written["xml"])
    tree = osu.decode(osu.from_hex(m.group(1))).tree
    assert tree["DSP State"]["Value"]["DSP Elements"]["Value"]["Maximizer"]["Value"]["Target Loudness [dB]"]["Value"] == -9.0


def test_mutate_impl_merges_aliased_modules():
    written = {}
    res = server._ozone_state_mutate_impl(
        0, 0, "master",
        {"MAX": {"Target Loudness [dB]": -9.0}, "Maximizer": {"Character": 1}},
        reload=False,
        save_impl=lambda: {"saved": True},
        reload_impl=lambda p, n: {"reloaded": True},
        read_als=lambda p: XML,
        write_als=lambda p, x: written.update(xml=x),
        resolve_path=lambda: "/x.als", title_fn=lambda: "x")
    assert res["ok"] is True
    got = {(a["module"], a["param"]) for a in res["applied"]}
    # both aliased entries survived the merge - neither silently dropped
    assert ("Maximizer", "Target Loudness [dB]") in got
    assert ("Maximizer", "Character") in got


def test_read_impl_summary_lists_modules():
    res = server._ozone_state_read_impl(
        0, 0, "master", None,
        save_impl=lambda: {"saved": True},
        read_als=lambda p: XML,
        resolve_path=lambda: "/x.als", title_fn=lambda: "x")
    assert res["ok"] is True
    names = {m["name"]: m for m in res["modules"]}
    assert "Maximizer" in names
    assert names["Maximizer"]["param_count"] > 0
