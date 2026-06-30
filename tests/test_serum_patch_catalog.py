import pytest
from ableton_mcp_max import serum_patch_catalog as pc

def _cat():
    return {"plugin": "Serum2", "modules": {
        "oscillator": {"count": 5, "node": "Oscillator{n}",
                       "params": {"Volume": {"kparam": "kParamVolume", "native_min": 0.0, "native_max": 1.0}},
                       "modes": {"wavetable": None, "multisample": "kOsc_MultiSample"}},
        "macro": {"count": 8, "node": "Macro{n}"}},
        "mod_dest_types": {"filter": "VoiceFilter"},
        "mod_dest_params": {"VoiceFilter": {"kParamFreq": 3}},
        "mod_sources": {}}

def test_module_info_ok():
    assert pc.module_info(_cat(), "oscillator")["count"] == 5

def test_module_info_unknown_raises():
    with pytest.raises(ValueError):
        pc.module_info(_cat(), "nope")

def test_param_info_by_friendly_and_kparam():
    c = _cat()
    assert pc.param_info(c, "oscillator", "Volume")["kparam"] == "kParamVolume"
    assert pc.param_info(c, "oscillator", "kParamVolume")["kparam"] == "kParamVolume"

def test_param_info_unknown_raises():
    with pytest.raises(ValueError):
        pc.param_info(_cat(), "oscillator", "Bogus")

def test_node_key_and_bounds():
    assert pc.node_key(_cat(), "oscillator", 2) == "Oscillator2"
    with pytest.raises(ValueError):
        pc.node_key(_cat(), "oscillator", 5)

def test_dest_type_string():
    assert pc.dest_type_string(_cat(), "filter") == "VoiceFilter"
    with pytest.raises(ValueError):
        pc.dest_type_string(_cat(), "nope")

def test_dest_param_id_by_kparam_and_friendly():
    c = _cat()
    assert pc.dest_param_id(c, "VoiceFilter", "kParamFreq") == 3
    assert pc.dest_param_id(c, "VoiceFilter", "Freq") == 3
    with pytest.raises(ValueError):
        pc.dest_param_id(c, "VoiceFilter", "Nope")

def test_real_catalog_loads():
    cat = pc.load_catalog()
    assert cat["plugin"] == "Serum2"
    assert set(["oscillator", "filter", "envelope", "lfo", "macro"]).issubset(cat["modules"])
    assert "VoiceFilter" in cat["mod_dest_params"]

def test_real_catalog_mod_sources_oracle():
    # The 16 mod-source ids harvested via the Task 7 live GUI oracle (Live 12.4).
    expected = {
        "env1": 2, "env2": 3, "env3": 4, "env4": 5,
        "lfo1": 6, "lfo2": 7, "lfo3": 8, "lfo4": 9,
        "macro1": 25, "macro2": 26, "macro3": 27, "macro4": 28,
        "macro5": 29, "macro6": 30, "macro7": 31, "macro8": 32,
    }
    assert pc.load_catalog()["mod_sources"] == expected
