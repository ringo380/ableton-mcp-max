"""Load + query the Serum FX catalog (param_maps/serum2_fx.json)."""
import json
import os

_DEFAULT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "param_maps", "serum2_fx.json")


def load_catalog(path=None):
    with open(path or _DEFAULT) as fh:
        return json.load(fh)


def fx_type_info(catalog, fx_type):
    key = str(int(fx_type))
    types = catalog["fx_types"]
    if key not in types:
        raise ValueError("unknown fx_type %s; valid: %s"
                         % (key, ", ".join(sorted(types, key=int))))
    return types[key]


def wrapper_key(catalog, fx_type):
    return fx_type_info(catalog, fx_type)["wrapper_key"]


def param_info(catalog, fx_type, kparam):
    info = fx_type_info(catalog, fx_type)
    for p in info["params"]:
        if p["kparam"] == kparam:
            return p
    raise ValueError("unknown param %s for fx_type %s; valid: %s"
                     % (kparam, fx_type, ", ".join(p["kparam"] for p in info["params"])))
