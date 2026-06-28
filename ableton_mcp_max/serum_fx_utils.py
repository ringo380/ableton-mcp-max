"""Pure mutation helpers over a decoded Serum CBOR state tree's FX racks.
No IO. Each FX entry is {type:int, <WrapperKey>:{plainParams:{kParam*:native}}}
plus an optional sibling kUIParamMixOrGain. plainParams is sparse (absent key =
Serum default). kParamEnable 0.0/1.0 toggles bypass."""
from ableton_mcp_max import serum_fx_catalog as cat

RACK_KEYS = ("FXRack0", "FXRack1", "FXRack2")


def _rack_list(tree, rack, create=False):
    if rack < 0 or rack >= len(RACK_KEYS):
        raise ValueError("rack must be 0..2, got %r" % (rack,))
    node = tree.get(RACK_KEYS[rack]) if hasattr(tree, "get") else None
    if not node:
        if not create:
            raise ValueError("rack %d (FXRack%d) not present in state"
                             % (rack, rack))
        node = {"FX": [], "displayName": "", "plainParams": {}}
        tree[RACK_KEYS[rack]] = node
    return node["FX"]


def _fx_at(tree, rack, slot):
    fxs = _rack_list(tree, rack)
    if slot < 0 or slot >= len(fxs):
        raise ValueError("slot %r out of range (rack %d has %d FX)"
                         % (slot, rack, len(fxs)))
    return fxs[slot]


def _fx_wrapper(fx):
    for k, v in fx.items():
        if k != "type" and isinstance(v, dict):
            return k, v
    return None, None


def _plain_params(fx, create_wrapper=None):
    wk, wrapper = _fx_wrapper(fx)
    if wrapper is None:
        if not create_wrapper:
            raise ValueError("fx entry has no wrapper dict")
        wrapper = {}
        fx[create_wrapper] = wrapper
    pp = wrapper.get("plainParams")
    if pp is None:
        pp = {}
        wrapper["plainParams"] = pp
    return pp


def list_fx(tree):
    out = []
    for ri, rk in enumerate(RACK_KEYS):
        node = tree.get(rk) if hasattr(tree, "get") else None
        if not node:
            continue
        for si, fx in enumerate(node.get("FX", [])):
            fx_type = fx.get("type")
            if fx_type is None:
                continue  # skip empty/unoccupied slots
            wk, wrapper = _fx_wrapper(fx)
            pp = wrapper.get("plainParams", {}) if wrapper else {}
            out.append({"rack": ri, "slot": si, "type": int(fx_type),
                        "name": wk or "", "enabled": pp.get("kParamEnable", 1.0) != 0.0,
                        "params": dict(pp)})
    return out


def get_fx_params(tree, rack, slot):
    return dict(_plain_params(_fx_at(tree, rack, slot)))


def set_fx_param(catalog, tree, rack, slot, kparam, native):
    fx = _fx_at(tree, rack, slot)
    info = cat.param_info(catalog, int(fx.get("type")), kparam)
    val = float(native)
    if val < info["native_min"] or val > info["native_max"]:
        raise ValueError("%s=%s out of observed range [%s, %s]"
                         % (kparam, val, info["native_min"], info["native_max"]))
    _plain_params(fx)[kparam] = val


def set_fx_enabled(tree, rack, slot, on):
    _plain_params(_fx_at(tree, rack, slot))["kParamEnable"] = 1.0 if on else 0.0


def insert_fx(catalog, tree, rack, index, fx_type):
    info = cat.fx_type_info(catalog, fx_type)
    wk = info["wrapper_key"]
    if not wk:
        raise ValueError("fx_type %s has no wrapper_key in catalog" % fx_type)
    entry = {"type": int(fx_type), wk: {"plainParams": dict(info.get("default_template") or {})}}
    fxs = _rack_list(tree, rack, create=True)
    if index < 0 or index > len(fxs):
        raise ValueError("index %r out of range (0..%d)" % (index, len(fxs)))
    fxs.insert(index, entry)


def remove_fx(tree, rack, slot):
    fxs = _rack_list(tree, rack)
    if slot < 0 or slot >= len(fxs):
        raise ValueError("slot %r out of range" % (slot,))
    fxs.pop(slot)


def reorder_fx(tree, rack, from_index, to_index):
    fxs = _rack_list(tree, rack)
    n = len(fxs)
    if not (0 <= from_index < n) or not (0 <= to_index < n):
        raise ValueError("indices out of range (rack has %d FX)" % n)
    fxs.insert(to_index, fxs.pop(from_index))
