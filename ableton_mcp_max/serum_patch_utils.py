"""Pure read/set helpers over a decoded Serum CBOR state tree's instrument
modules (oscillators, filters, envelopes, LFOs, macros) and mod matrix. No IO.
plainParams is sparse (absent key = Serum default); setting a value inserts/updates
a kParam*. FX live in serum_fx_utils. kParamType (oscillator mode) is a STRING; WT
mode is the default = absence of the key."""
from ableton_mcp_max import serum_patch_catalog as pc

_PLAIN_MODULES = ("oscillator", "filter", "envelope", "lfo")


def _node(tree, key, create=False):
    node = tree.get(key) if hasattr(tree, "get") else None
    if node is None:
        if not create:
            return None
        node = {"plainParams": {}}
        tree[key] = node
    if "plainParams" not in node or not isinstance(node["plainParams"], dict):
        node["plainParams"] = {}
    return node


def set_module_params(catalog, tree, module_type, index, params):
    if module_type not in _PLAIN_MODULES:
        raise ValueError("set_module_params: module_type must be one of %s, got %r"
                         % (", ".join(_PLAIN_MODULES), module_type))
    node = _node(tree, pc.node_key(catalog, module_type, index), create=True)
    for name, native in params.items():
        info = pc.param_info(catalog, module_type, name)
        val = float(native)
        if val < info["native_min"] or val > info["native_max"]:
            raise ValueError("%s.%s=%s out of observed range [%s, %s]"
                             % (module_type, name, val, info["native_min"], info["native_max"]))
        node["plainParams"][info["kparam"]] = val


def set_oscillator_mode(catalog, tree, index, mode):
    modes = pc.module_info(catalog, "oscillator").get("modes", {})
    if mode not in modes:
        raise ValueError("unknown oscillator mode %r; valid: %s"
                         % (mode, ", ".join(sorted(modes))))
    node = _node(tree, pc.node_key(catalog, "oscillator", index), create=True)
    value = modes[mode]
    if value is None:               # wavetable = default => remove the key
        node["plainParams"].pop("kParamType", None)
    else:
        node["plainParams"]["kParamType"] = value


def set_macro(catalog, tree, index, value, name=None):
    key = pc.node_key(catalog, "macro", index)
    val = float(value)
    if val < 0.0 or val > 100.0:
        raise ValueError("macro value %s out of range [0, 100]" % val)
    node = _node(tree, key, create=True)
    node["plainParams"]["kParamValue"] = val
    if name is not None:
        node["name"] = name


def summarize(catalog, tree):
    out = {"oscillators": [], "filters": [], "envelopes": [], "lfos": [], "macros": []}
    plural = {"oscillator": "oscillators", "filter": "filters",
              "envelope": "envelopes", "lfo": "lfos"}
    for mtype, bucket in plural.items():
        info = pc.module_info(catalog, mtype)
        for n in range(info["count"]):
            node = tree.get(info["node"].replace("{n}", str(n)))
            if not isinstance(node, dict):
                continue
            pp = node.get("plainParams", {})
            pp = pp if isinstance(pp, dict) else {}
            entry = {"index": n, "params": dict(pp)}
            if mtype == "oscillator":
                entry["mode"] = pp.get("kParamType")
            out[bucket].append(entry)
    minfo = pc.module_info(catalog, "macro")
    for n in range(minfo["count"]):
        node = tree.get("Macro%d" % n)
        if not isinstance(node, dict):
            continue
        pp = node.get("plainParams", {})
        pp = pp if isinstance(pp, dict) else {}
        out["macros"].append({"index": n, "name": node.get("name", ""),
                              "value": pp.get("kParamValue")})
    return out
