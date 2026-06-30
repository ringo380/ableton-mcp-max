"""Load + query the Serum patch catalog (param_maps/serum2_patch.json)."""
import json
import os

_DEFAULT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "param_maps", "serum2_patch.json")


def load_catalog(path=None):
    with open(path or _DEFAULT) as fh:
        return json.load(fh)


def module_info(catalog, module_type):
    mods = catalog["modules"]
    if module_type not in mods:
        raise ValueError("unknown module type %r; valid: %s"
                         % (module_type, ", ".join(sorted(mods))))
    return mods[module_type]


def node_key(catalog, module_type, index):
    info = module_info(catalog, module_type)
    count = info["count"]
    if index < 0 or index >= count:
        raise ValueError("%s index %r out of range (0..%d)"
                         % (module_type, index, count - 1))
    return info["node"].replace("{n}", str(index))


def param_info(catalog, module_type, name):
    params = module_info(catalog, module_type).get("params", {})
    if name in params:
        return params[name]
    for _friendly, p in params.items():
        if p["kparam"] == name:
            return p
    raise ValueError("unknown param %r for %s; valid: %s"
                     % (name, module_type, ", ".join(sorted(params))))


def dest_type_string(catalog, module_type):
    types = catalog.get("mod_dest_types", {})
    if module_type not in types:
        raise ValueError("unknown mod dest module %r; valid: %s"
                         % (module_type, ", ".join(sorted(types))))
    return types[module_type]


def dest_param_id(catalog, type_string, name):
    table = catalog.get("mod_dest_params", {}).get(type_string)
    if not table:
        raise ValueError("no dest params for type %r" % type_string)
    if name in table:
        return table[name]
    cand = "kParam" + name
    if cand in table:
        return table[cand]
    raise ValueError("unknown dest param %r for %s; valid: %s"
                     % (name, type_string, ", ".join(sorted(table))))
