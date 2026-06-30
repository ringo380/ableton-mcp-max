import pytest
from ableton_mcp_max import serum_patch_utils as pu

CAT = {"plugin": "Serum2", "modules": {
    "oscillator": {"count": 5, "node": "Oscillator{n}",
                   "params": {"Volume": {"kparam": "kParamVolume", "native_min": 0.0, "native_max": 1.0},
                              "Pan": {"kparam": "kParamPan", "native_min": -1.0, "native_max": 1.0}},
                   "modes": {"wavetable": None, "multisample": "kOsc_MultiSample"}},
    "filter": {"count": 2, "node": "VoiceFilter{n}",
               "params": {"Freq": {"kparam": "kParamFreq", "native_min": 0.0, "native_max": 1.0}}},
    "envelope": {"count": 4, "node": "Env{n}",
                 "params": {"Attack": {"kparam": "kParamAttack", "native_min": 0.0, "native_max": 16.0}}},
    "lfo": {"count": 10, "node": "LFO{n}",
            "params": {"Rate": {"kparam": "kParamRate", "native_min": 0.0, "native_max": 1.0}}},
    "macro": {"count": 8, "node": "Macro{n}"}},
    "mod_dest_types": {}, "mod_dest_params": {}, "mod_sources": {}}

def _tree():
    return {"Oscillator0": {"plainParams": {"kParamVolume": 0.5, "kParamType": "kOsc_Sample"}},
            "VoiceFilter0": {"plainParams": {}},
            "Env0": {"plainParams": {}},
            "LFO0": {"plainParams": {}},
            "Macro0": {"name": "HIGH", "plainParams": {"kParamValue": 56.0}}}

def test_set_param_friendly_name():
    t = _tree()
    pu.set_module_params(CAT, t, "oscillator", 0, {"Volume": 0.8})
    assert t["Oscillator0"]["plainParams"]["kParamVolume"] == 0.8

def test_set_param_kparam_name():
    t = _tree()
    pu.set_module_params(CAT, t, "oscillator", 0, {"kParamPan": -0.5})
    assert t["Oscillator0"]["plainParams"]["kParamPan"] == -0.5

def test_set_param_out_of_range_raises():
    t = _tree()
    with pytest.raises(ValueError):
        pu.set_module_params(CAT, t, "oscillator", 0, {"Volume": 9.0})

def test_set_param_creates_node_when_absent():
    t = _tree()
    pu.set_module_params(CAT, t, "filter", 1, {"Freq": 0.3})
    assert t["VoiceFilter1"]["plainParams"]["kParamFreq"] == 0.3

def test_set_oscillator_mode_string():
    t = _tree()
    pu.set_oscillator_mode(CAT, t, 0, "multisample")
    assert t["Oscillator0"]["plainParams"]["kParamType"] == "kOsc_MultiSample"

def test_set_oscillator_mode_wavetable_deletes_key():
    t = _tree()  # starts as kOsc_Sample
    pu.set_oscillator_mode(CAT, t, 0, "wavetable")
    assert "kParamType" not in t["Oscillator0"]["plainParams"]

def test_set_oscillator_mode_unknown_raises():
    t = _tree()
    with pytest.raises(ValueError):
        pu.set_oscillator_mode(CAT, t, 0, "bogus")

def test_set_macro_value_and_name():
    t = _tree()
    pu.set_macro(CAT, t, 0, 25.0, name="CUTOFF")
    assert t["Macro0"]["plainParams"]["kParamValue"] == 25.0
    assert t["Macro0"]["name"] == "CUTOFF"

def test_set_macro_out_of_range_raises():
    with pytest.raises(ValueError):
        pu.set_macro(CAT, _tree(), 0, 250.0)

def test_summarize_reports_present_modules():
    s = pu.summarize(CAT, _tree())
    osc0 = [o for o in s["oscillators"] if o["index"] == 0][0]
    assert osc0["params"].get("kParamVolume") == 0.5
    assert osc0["mode"] == "kOsc_Sample"
    mac0 = [m for m in s["macros"] if m["index"] == 0][0]
    assert mac0["name"] == "HIGH" and mac0["value"] == 56.0


import glob, os
from ableton_mcp_max import serum_state_codec as ssc
from ableton_mcp_max import serum_patch_catalog as realpc

_ROOT = "/Library/Audio/Presets/Xfer Records/Serum 2 Presets/Presets"

@pytest.mark.skipif(not glob.glob(os.path.join(_ROOT, "**", "*.SerumPreset"), recursive=True),
                    reason="factory presets absent")
def test_roundtrip_setting_macro_only_changes_that_node():
    cat = realpc.load_catalog()
    files = glob.glob(os.path.join(_ROOT, "**", "*.SerumPreset"), recursive=True)
    for p in files[:50]:
        st = ssc.decode(open(p, "rb").read())
        before = {k: v for k, v in st.tree.items() if k != "Macro0"}
        pu.set_macro(cat, st.tree, 0, 42.0)
        re = ssc.decode(ssc.encode(st, st.tree)).tree
        after = {k: v for k, v in re.items() if k != "Macro0"}
        assert after == before, "patch perturbed an unrelated node in %s" % p
        assert re["Macro0"]["plainParams"]["kParamValue"] == 42.0
