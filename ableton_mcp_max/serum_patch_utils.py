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


_MOD_SLOTS = 64


def _is_free_slot(node):
    if not isinstance(node, dict):
        return True
    return "source" not in node and "destModuleTypeString" not in node


def resolve_source(catalog, source):
    if isinstance(source, bool):
        raise ValueError("mod source must be an int id or a name, not a bool")
    if isinstance(source, int):
        return [int(source), 0]
    if isinstance(source, str) and source.lstrip("-").isdigit():
        return [int(source), 0]
    srcs = catalog.get("mod_sources", {})
    if source not in srcs:
        raise ValueError("unknown mod source %r; pass a raw int id, or one of: %s"
                         % (source, ", ".join(sorted(srcs)) or "(none configured yet)"))
    return [int(srcs[source]), 0]


def _dest_fields(catalog, dest_module, dest_index, dest_param):
    ts = pc.dest_type_string(catalog, dest_module)
    has_params = dest_module in catalog["modules"] and "params" in catalog["modules"][dest_module]
    info = pc.param_info(catalog, dest_module, dest_param) if has_params else None
    kparam = info["kparam"] if info else (dest_param if dest_param.startswith("kParam") else "kParam" + dest_param)
    pid = pc.dest_param_id(catalog, ts, kparam)
    return ts, int(dest_index), kparam, pid


def add_mod_route(catalog, tree, source, dest_module, dest_index, dest_param, amount):
    src = resolve_source(catalog, source)
    ts, did, kparam, pid = _dest_fields(catalog, dest_module, dest_index, dest_param)
    for n in range(_MOD_SLOTS):
        key = "ModSlot%d" % n
        node = tree.get(key)
        if node is None or _is_free_slot(node):
            tree[key] = {"source": src, "destModuleID": did, "destModuleParamID": pid,
                         "destModuleParamName": kparam, "destModuleTypeString": ts,
                         "plainParams": {"kParamAmount": float(amount)}}
            return n
    raise ValueError("no free ModSlot (all %d used)" % _MOD_SLOTS)


def clear_mod_route(catalog, tree, dest_module, dest_index, dest_param):
    ts, did, kparam, pid = _dest_fields(catalog, dest_module, dest_index, dest_param)
    for n in range(_MOD_SLOTS):
        node = tree.get("ModSlot%d" % n)
        if (isinstance(node, dict) and node.get("destModuleTypeString") == ts
                and node.get("destModuleID") == did
                and node.get("destModuleParamID") == pid):
            tree["ModSlot%d" % n] = {"plainParams": {}}
            return n
    raise ValueError("no mod route to %s[%d].%s found" % (dest_module, dest_index, dest_param))


def set_wavetable(catalog, tree, osc, table):
    node = _node(tree, pc.node_key(catalog, "oscillator", osc), create=True)
    node["plainParams"].pop("kParamType", None)   # WT is the default mode
    wtkey = "WTOsc%d" % osc
    wt = node.get(wtkey)
    if not isinstance(wt, dict):
        wt = {"plainParams": "default"}
        node[wtkey] = wt
    wt["relativePathToWT"] = table
