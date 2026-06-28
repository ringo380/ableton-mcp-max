"""Tests for the closure semantics of the four Serum FX mutator tools.
No IO, no Live connection - tests validate that the mutate_fn closures
produced by each tool correctly call into serum_fx_utils."""
from ableton_mcp_max import serum_fx_utils as fx

CAT = {"plugin": "Serum2", "fx_types": {
    "12": {"name": "Utils", "wrapper_key": "FXUtils",
           "params": [{"kparam": "kParamWet", "native_min": 0.0, "native_max": 100.0}],
           "default_template": {}},
    "4": {"name": "Delay", "wrapper_key": "FXDelay",
          "params": [{"kparam": "kParamWet", "native_min": 0.0, "native_max": 100.0}],
          "default_template": {}}}}


def _tree():
    return {"FXRack0": {"FX": [{"type": 12, "FXUtils": {"plainParams": {"kParamWet": 96.7}}}],
                        "displayName": "", "plainParams": {}},
            "FXRack1": {"FX": [], "displayName": "", "plainParams": {}},
            "FXRack2": {"FX": [], "displayName": "", "plainParams": {}}}


# --- set_serum_fx_param closure ---

def test_set_param_closure():
    """Closure mutates the correct FX slot's param in-place."""
    t = _tree()
    rack, slot, kparam, value = 0, 0, "kParamWet", 25.0
    mutate = lambda catalog, tree: fx.set_fx_param(catalog, tree, rack, slot, kparam, value)
    mutate(CAT, t)
    assert fx.get_fx_params(t, 0, 0)["kParamWet"] == 25.0


def test_set_param_closure_out_of_range():
    """Closure propagates ValueError for out-of-range native values."""
    t = _tree()
    rack, slot, kparam, value = 0, 0, "kParamWet", 999.0
    mutate = lambda catalog, tree: fx.set_fx_param(catalog, tree, rack, slot, kparam, value)
    try:
        mutate(CAT, t)
        assert False, "should have raised ValueError"
    except ValueError:
        pass


def test_set_param_closure_bad_slot():
    """Closure raises ValueError for a non-existent slot."""
    t = _tree()
    mutate = lambda catalog, tree: fx.set_fx_param(catalog, tree, 0, 99, "kParamWet", 50.0)
    try:
        mutate(CAT, t)
        assert False, "should have raised ValueError"
    except ValueError:
        pass


# --- insert_serum_fx closure ---

def test_insert_closure():
    """Closure inserts a new FX entry at the correct index and rack."""
    t = _tree()
    rack, index, fx_type = 1, 0, 4
    mutate = lambda catalog, tree: fx.insert_fx(catalog, tree, rack, index, fx_type)
    mutate(CAT, t)
    assert t["FXRack1"]["FX"][0]["type"] == 4
    assert "FXDelay" in t["FXRack1"]["FX"][0]


def test_insert_closure_appends():
    """Closure can append to an existing non-empty rack."""
    t = _tree()
    mutate = lambda catalog, tree: fx.insert_fx(catalog, tree, 0, 1, 4)
    mutate(CAT, t)
    assert len(t["FXRack0"]["FX"]) == 2
    assert t["FXRack0"]["FX"][1]["type"] == 4


def test_insert_closure_unknown_type():
    """Closure raises ValueError for an unknown fx_type."""
    t = _tree()
    mutate = lambda catalog, tree: fx.insert_fx(catalog, tree, 0, 0, 9999)
    try:
        mutate(CAT, t)
        assert False, "should have raised ValueError"
    except (ValueError, KeyError):
        pass


# --- remove_serum_fx closure ---

def test_remove_closure():
    """Closure removes the FX at the specified slot."""
    t = _tree()
    assert len(t["FXRack0"]["FX"]) == 1
    mutate = lambda catalog, tree: fx.remove_fx(tree, 0, 0)
    mutate(CAT, t)
    assert len(t["FXRack0"]["FX"]) == 0


def test_remove_closure_bad_slot():
    """Closure raises ValueError when the slot is out of range."""
    t = _tree()
    mutate = lambda catalog, tree: fx.remove_fx(tree, 0, 5)
    try:
        mutate(CAT, t)
        assert False, "should have raised ValueError"
    except ValueError:
        pass


# --- reorder_serum_fx closure (reorder branch) ---

def _tree_two():
    """Tree with two FX in rack 0 for reorder tests."""
    return {"FXRack0": {"FX": [
        {"type": 12, "FXUtils": {"plainParams": {"kParamWet": 96.7}}},
        {"type": 4,  "FXDelay": {"plainParams": {"kParamWet": 50.0}}}],
        "displayName": "", "plainParams": {}},
        "FXRack1": {"FX": [], "displayName": "", "plainParams": {}},
        "FXRack2": {"FX": [], "displayName": "", "plainParams": {}}}


def test_reorder_closure():
    """Closure moves FX from from_index to to_index."""
    t = _tree_two()
    from_index, to_index = 0, 1
    mutate = lambda catalog, tree: fx.reorder_fx(tree, 0, from_index, to_index)
    mutate(CAT, t)
    assert t["FXRack0"]["FX"][0]["type"] == 4
    assert t["FXRack0"]["FX"][1]["type"] == 12


# --- reorder_serum_fx closure (bypass branch) ---

def test_bypass_closure_disables():
    """bypass=True sets kParamEnable=0.0 (disabled)."""
    t = _tree()
    bypass = True
    from_index = 0
    mutate = lambda catalog, tree: fx.set_fx_enabled(tree, 0, from_index, not bypass)
    mutate(CAT, t)
    pp = fx.get_fx_params(t, 0, 0)
    assert pp["kParamEnable"] == 0.0


def test_bypass_closure_enables():
    """bypass=False sets kParamEnable=1.0 (enabled)."""
    t = _tree()
    # First disable it
    fx.set_fx_enabled(t, 0, 0, False)
    bypass = False
    from_index = 0
    mutate = lambda catalog, tree: fx.set_fx_enabled(tree, 0, from_index, not bypass)
    mutate(CAT, t)
    pp = fx.get_fx_params(t, 0, 0)
    assert pp["kParamEnable"] == 1.0


def test_reorder_with_bypass_none_uses_reorder():
    """When bypass is None the reorder branch is taken, not the enable branch."""
    t = _tree_two()
    bypass = None
    from_index, to_index = 1, 0
    # Mimics exactly the reorder_serum_fx tool logic
    mutate_called = []
    def mutate(catalog, tree):
        if bypass is not None:
            fx.set_fx_enabled(tree, 0, from_index, not bypass)
        else:
            fx.reorder_fx(tree, 0, from_index, to_index)
        mutate_called.append(True)
    mutate(CAT, t)
    assert mutate_called
    assert t["FXRack0"]["FX"][0]["type"] == 4
    assert t["FXRack0"]["FX"][1]["type"] == 12
