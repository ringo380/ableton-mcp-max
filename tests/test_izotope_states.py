import base64
import json

import ableton_mcp_max.server as server
from ableton_mcp_max import als_automation_utils as als
from ableton_mcp_max import ozone_state_utils as osu
from ableton_mcp_max.analysis_utils import (attach_plugin_states, evaluate_rules,
                                            normalize_snapshot)
from ableton_mcp_max.ruleset_utils import load_rulesets

# Element Chain payloads captured from a real Live 12.4.6 set.
_OZONE_CHAIN = ("ABAAAABNYXN0ZXIgUmViYWxhbmNlAAkAAABFcXVhbGl6ZXIABgAAAEltcGFjdAANAAAAU3RlcmVv"
                "IEltYWdlcgAHAAAAQ2xhcml0eQAKAAAAU3RhYmlsaXplcgAKAAAARHluYW1pYyBFUQAJAAAATWF4aW1pemVy")
_NEUTRON_CHAIN = "EQAAAEh5YnJpZCBEeW5hbWljIEVRBwAAAEV4Y2l0ZXIKAAAARHluYW1pY3MgMAoAAABEeW5hbWljcyAx"
_NECTAR_CHAIN = "BAAAAEVRIDAMAAAAQ29tcHJlc3NvciAwBwAAAERlRXNzZXI="


def test_parse_chain_bytes_ozone_prefix_form():
    assert osu.parse_chain_bytes(base64.b64decode(_OZONE_CHAIN)) == [
        "Master Rebalance", "Equalizer", "Impact", "Stereo Imager", "Clarity",
        "Stabilizer", "Dynamic EQ", "Maximizer"]


def test_parse_chain_bytes_neutron_and_nectar_plain_form():
    assert osu.parse_chain_bytes(base64.b64decode(_NEUTRON_CHAIN)) == [
        "Hybrid Dynamic EQ", "Exciter", "Dynamics 0", "Dynamics 1"]
    assert osu.parse_chain_bytes(base64.b64decode(_NECTAR_CHAIN)) == [
        "EQ 0", "Compressor 0", "DeEsser"]
    assert osu.parse_chain_bytes(b"") == []


def _leaf(t, v):
    return {"Type": t, "Value": v}


def _ozone_tree(chain_b64, max_bypass=False, global_bypass=False):
    elems = {
        "Global": _leaf("Dictionary", {"Global Bypass": _leaf("Bool", global_bypass)}),
        "Maximizer": _leaf("Dictionary", {
            "Bypass": _leaf("Bool", max_bypass),
            "Target Loudness [dB]": _leaf("Float", -8.5),
            "Margin": _leaf("Float", -0.1),
            "Prevent Intersample Clipping": _leaf("Bool", False),
            "Mode": _leaf("UInt", 3),
            "Character": _leaf("Float", 2.5),
            "Gain": _leaf("Float", 0.0)}),
        "Gain Input": _leaf("Dictionary", {
            "Input Lock": _leaf("Bool", True),
            "Gain Input Locked": _leaf("Float", -6.0),
            "Gain Input Left": _leaf("Float", 0.0),
            "Gain Input Right": _leaf("Float", 0.0)}),
        "Equalizer": _leaf("Dictionary", {"Bypass": _leaf("Bool", False)}),
    }
    ec = {"Element Name": _leaf("String", "ElementChain")}
    if chain_b64:
        ec["Extra Bytes"] = _leaf("Base64", chain_b64)
    elems["ElementChain"] = _leaf("Dictionary", ec)
    return {"DSP State": _leaf("Dictionary", {"DSP Elements": _leaf("Dictionary", elems)})}


def test_summarize_family_reads_maximizer_in_chain():
    s = osu.summarize_family(_ozone_tree(_OZONE_CHAIN), "Ozone 12")
    assert [c["module"] for c in s["chain"]][-1] == "Maximizer"
    assert s["limiter"] == {"module": "Maximizer", "target_lufs": -8.5,
                            "ceiling_db": -0.1, "true_peak_safe": False,
                            "mode": 3, "character": 2.5,
                            "gain_db": 0.0, "input_gain_db": -6.0}


def test_input_gain_follows_the_lock():
    tree = _ozone_tree(_OZONE_CHAIN)
    elems = tree["DSP State"]["Value"]["DSP Elements"]["Value"]
    gi = elems["Gain Input"]["Value"]
    # Locked: Ozone ignores Left/Right (render-verified), so report Locked.
    gi["Gain Input Left"]["Value"] = -3
    assert osu.ozone_input_gain(elems) == -6.0
    # Unlocked: the per-side values apply.
    gi["Input Lock"]["Value"] = False
    gi["Gain Input Right"]["Value"] = -1
    assert osu.ozone_input_gain(elems) == -2.0
    del elems["Gain Input"]
    assert osu.ozone_input_gain(elems) is None


def test_chain_entry_resolves_by_element_name_and_ceiling_rounds():
    tree = _ozone_tree(_NEUTRON_CHAIN)
    elems = tree["DSP State"]["Value"]["DSP Elements"]["Value"]
    elems["Dynamic EQ"] = _leaf("Dictionary", {
        "Element Name": _leaf("String", "Hybrid Dynamic EQ"),
        "Bypass": _leaf("Bool", True)})
    s = osu.summarize_family(tree, "Neutron 5")
    assert s["chain"][0] == {"module": "Hybrid Dynamic EQ", "bypass": True}
    oz_tree = _ozone_tree(_OZONE_CHAIN)
    oz_max = oz_tree["DSP State"]["Value"]["DSP Elements"]["Value"]["Maximizer"]["Value"]
    oz_max["Margin"]["Value"] = -0.10000038146972656
    oz = osu.summarize_family(oz_tree, "Ozone 12")
    assert oz["limiter"]["ceiling_db"] == -0.1


def test_summarize_family_bypassed_or_unchained_maximizer_is_no_limiter():
    assert osu.summarize_family(_ozone_tree(_OZONE_CHAIN, max_bypass=True),
                                "Ozone 12")["limiter"] is None
    empty = osu.summarize_family(_ozone_tree(None), "Ozone 12")
    assert empty["chain"] == [] and empty["limiter"] is None


def _blob_hex(tree, magic=osu.MAGIC):
    st = osu.DecodedState(1, tree)
    blob = osu.encode(st, tree)
    return osu.to_hex(magic + blob[4:])


def _set_xml():
    oz = _blob_hex(_ozone_tree(_OZONE_CHAIN))
    oz_empty = _blob_hex(_ozone_tree(None))
    return ('<Ableton><Tracks>'
            '<GroupTrack Id="1"><DeviceChain/></GroupTrack>'
            '<AudioTrack Id="2"><ProcessorState>00FF</ProcessorState>'
            '<ProcessorState />'
            '<ProcessorState>%s</ProcessorState></AudioTrack>'
            '<ReturnTrack Id="3"><DeviceChain/></ReturnTrack>'
            '</Tracks><MainTrack><ProcessorState>%s</ProcessorState></MainTrack>'
            '</Ableton>') % (oz_empty, oz)


def test_iter_track_spans_and_scan_family_states():
    xml = _set_xml()
    spans = list(als.iter_track_spans(xml))
    assert [(t, i) for t, i, _, _ in spans] == [
        ("regular", 0), ("regular", 1), ("return", 0), ("master", 0)]
    states = osu.scan_family_states(xml, spans)
    track = states[("regular", 1)]
    assert len(track) == 1
    # ordinal counts the non-iZotope and self-closing states before it
    assert track[0]["plugin_ordinal"] == 2
    assert track[0]["chain"] == []
    master = states[("master", 0)][0]
    assert master["product"] == "Ozone 12"
    assert master["limiter"]["ceiling_db"] == -0.1
    assert ("regular", 0) not in states


def test_scan_reads_neutron_magic():
    neu = _blob_hex(_ozone_tree(_NEUTRON_CHAIN), magic=b"\x83\xFB\x80\x00")
    xml = '<Tracks><AudioTrack Id="1"><ProcessorState>%s</ProcessorState></AudioTrack></Tracks>' % neu
    states = osu.scan_family_states(xml, als.iter_track_spans(xml))
    assert states[("regular", 0)][0]["product"] == "Neutron 5"


_RAW = {
    "transport": {"tempo": 116.0, "is_playing": False,
                  "signature_numerator": 4, "signature_denominator": 4},
    "tracks": [
        {"index": 0, "name": "Ref MIDI", "type": "midi", "volume": 0.85,
         "panning": 0.0, "sends": [], "mute": False, "solo": False, "arm": False,
         "has_instrument": False, "devices": [],
         "routing": {"audio_to": "No Output", "audio_from": "All Ins"}},
        {"index": 1, "name": "FX", "type": "audio", "volume": 0.85,
         "volume_display": "-3.0 dB", "panning": 0.0, "sends": [0.0],
         "sends_detail": [{"return": "A-Reverb", "value": 0.0, "display": "-inf dB"}],
         "mute": False, "solo": False, "arm": False, "has_instrument": False,
         "group_track": "DRUM", "is_grouped": True,
         "arrangement": {"count": 1, "audio": 1, "midi": 0, "warped": 1, "warp_markers": 2},
         "devices": [{"index": 0, "name": "Ozone 12", "class_name": "PluginDevice",
                      "on": True, "is_instrument": False}],
         "routing": {"audio_to": "Main", "audio_from": "Ext. In"}},
    ],
    "returns": [],
    "master": {"name": "Master", "volume": 0.85, "panning": 0.0,
               "devices": [{"index": 0, "name": "Ozone 12", "class_name": "PluginDevice",
                            "on": True, "is_instrument": False}]},
}


def _by_id(result):
    return {f["id"]: f for f in result["findings"] if f.get("entity") is None}


def test_snapshot_normalizes_new_remote_fields():
    snap = normalize_snapshot(_RAW)
    fx = snap["tracks"][1]
    assert fx["mixer"]["volume_db"] == -3.0
    assert fx["mixer"]["sends_detail"][0] == {"return": "A-Reverb", "value": 0.0,
                                              "display": "-inf dB", "db": -70.0}
    assert fx["group_track"] == "DRUM"
    assert fx["arrangement"]["warp_markers"] == 2
    assert snap["master"]["limiting"]["present"] is None  # Ozone not read yet


def test_unread_ozone_defers_limiter_rules():
    res = evaluate_rules(load_rulesets("mastering"), normalize_snapshot(_RAW))
    deferred = {d["id"]: d for d in res["deferred_rules"]}
    assert "mastering.limiter_present" in deferred
    assert "plugin_state=True" in deferred["mastering.limiter_present"]["reason"]
    assert "mastering.limiter_ceiling" in deferred


def test_read_ozone_passes_limiter_and_flags_ceiling_and_empty_chain():
    snap = normalize_snapshot(_RAW)
    full = osu.summarize_family(_ozone_tree(_OZONE_CHAIN), "Ozone 12")
    full["plugin_ordinal"] = 0
    empty = osu.summarize_family(_ozone_tree(None), "Ozone 12")
    empty["plugin_ordinal"] = 0
    attach_plugin_states(snap, {("master", 0): [full], ("regular", 1): [empty]})
    assert snap["master"]["devices"][0]["izotope"]["limiter"]["target_lufs"] == -8.5
    res = evaluate_rules(load_rulesets("all"), snap)
    ids = _by_id(res)
    assert ids["mastering.limiter_present"]["status"] == "pass"
    ceiling = ids["mastering.limiter_ceiling"]
    assert ceiling["status"] == "warn"
    assert "-0.1" in ceiling["evidence"] and "-8.5" in ceiling["evidence"]
    empty_f = [f for f in res["findings"] if f["id"] == "health.izotope_empty_chain"]
    assert [f["entity"] for f in empty_f] == ["FX"]
    assert empty_f[0]["status"] == "warn"


def test_safe_ceiling_passes():
    snap = normalize_snapshot(_RAW)
    tree = _ozone_tree(_OZONE_CHAIN)
    mx = tree["DSP State"]["Value"]["DSP Elements"]["Value"]["Maximizer"]["Value"]
    mx["Margin"]["Value"] = -1.0
    mx["Prevent Intersample Clipping"]["Value"] = True
    attach_plugin_states(snap, {("master", 0): [osu.summarize_family(tree, "Ozone 12")]})
    ids = _by_id(evaluate_rules(load_rulesets("mastering"), snap))
    assert ids["mastering.limiter_ceiling"]["status"] == "pass"


def test_no_output_midi_track_is_not_missing_an_instrument():
    res = evaluate_rules(load_rulesets("sound_design"), normalize_snapshot(_RAW))
    flagged = [f for f in res["findings"]
               if f["id"] == "sound_design.has_instrument" and f["status"] != "pass"]
    assert flagged == []


def test_native_limiter_ceiling_from_key_params():
    raw = dict(_RAW)
    raw["master"] = {"name": "Master", "volume": 0.85, "panning": 0.0, "devices": [
        {"index": 0, "name": "Limiter", "class_name": "Limiter", "on": True,
         "is_instrument": False, "key_params": {"Ceiling": "-0.30 dB"}}]}
    ids = _by_id(evaluate_rules(load_rulesets("mastering"), normalize_snapshot(raw)))
    assert ids["mastering.limiter_present"]["status"] == "pass"
    assert ids["mastering.limiter_ceiling"]["status"] == "warn"


def test_compact_snapshot_keeps_judgment_fields_and_zero_db():
    from ableton_mcp_max.analysis_utils import compact_snapshot
    raw = json.loads(json.dumps(_RAW))
    raw["tracks"][1]["sends_detail"].append(
        {"return": "B-Delay", "value": 0.5, "display": "-12.0 dB"})
    raw["tracks"][1]["devices"][0]["key_params"] = {}
    raw["tracks"][0]["devices"] = [{"index": 0, "name": "Auto Filter",
                                    "class_name": "AutoFilter2", "on": True,
                                    "key_params": {"LFO Amount": "0.0 %"},
                                    "automated_params": 1, "automated": ["Frequency"]}]
    c = compact_snapshot(normalize_snapshot(raw))
    fx = c["tracks"][1]
    assert fx["mixer"]["volume_db"] == -3.0
    assert fx["mixer"]["sends"] == [{"return": "B-Delay", "db": -12.0}]  # -inf send dropped
    assert fx["group_track"] == "DRUM" and fx["arrangement"]["warp_markers"] == 2
    assert fx["devices"] == [{"name": "Ozone 12", "class": "PluginDevice"}]
    ref = c["tracks"][0]
    assert ref["mixer"]["volume_db"] == 0.0         # a 0 dB fader is kept, not pruned
    assert ref["audio_to"] == "No Output"
    assert ref["devices"][0]["key_params"] == {"LFO Amount": "0.0 %"}
    assert ref["devices"][0]["automated"] == ["Frequency"]
    assert c["master"]["limiting"]["present"] is None


class _Conn:
    def send_command(self, cmd, params=None, **kw):
        assert cmd == "get_analysis_snapshot"
        return _RAW


def test_analyze_set_plugin_state_and_compact(monkeypatch):
    monkeypatch.setattr(server, "get_ableton_connection", lambda: _Conn())
    xml = ('<Tracks><MidiTrack Id="1"></MidiTrack><AudioTrack Id="2"></AudioTrack>'
           '</Tracks><MainTrack><ProcessorState>%s</ProcessorState></MainTrack>'
           % _blob_hex(_ozone_tree(_OZONE_CHAIN)))
    calls = []

    def fake_read(**kw):
        calls.append(kw)
        return {"ok": True, "set_path": "x.als",
                "states": osu.scan_family_states(xml, als.iter_track_spans(xml))}
    monkeypatch.setattr(server, "_plugin_states_read_impl", fake_read)

    out = json.loads(server.analyze_set(ctx=None, plugin_state=True,
                                        include_snapshot=False))
    assert out["ok"] is True and "snapshot" not in out["data"]
    ids = _by_id(out["data"])
    assert ids["mastering.limiter_present"]["status"] == "pass"
    assert ids["mastering.limiter_ceiling"]["status"] == "warn"
    assert len(calls) == 1

    calls.clear()
    out = json.loads(server.analyze_set(ctx=None))
    assert "snapshot" in out["data"] and calls == []   # default stays read-only
