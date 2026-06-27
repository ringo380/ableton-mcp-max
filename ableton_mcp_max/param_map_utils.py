"""Load/validate/derive third-party plugin parameter-map packs.

A "pack" is a committed JSON file under `param_maps/` describing a plugin's
Configure-able parameters: the VST3 `param_id` of each named knob plus a curated
`category` tag. `expose_plugin_parameters` consumes a pack (or a freshly derived
list) to fill the Configure slots encoded by `plugin_config_utils`.

Serum 2's id scheme is dense: a parameter's Configure-slot ParameterId is
`id_base + parameter_index` with `id_base = 2000000` (validated live - 2000007
resolved to "Filter 1 Stereo", the 8th parameter). `derive_serum_ids` applies
that hypothesis to a name list returned by the `probe_plugin_parameters` tool.

Pure logic - JSON/lists in, dicts out. No Live / no network.
"""
import json
import os

PACK_DIR = os.path.join(os.path.dirname(__file__), "param_maps")
SERUM_ID_BASE = 2000000


def derive_serum_ids(names, id_base=SERUM_ID_BASE):
    """[{param_id, name, index}] from a probed name list via id = id_base + index.

    The list index IS the plugin parameter index, so a name's id is positional.
    Blank/whitespace names (a plugin can report empty padding entries) are
    skipped but do NOT shift later indices.
    """
    out = []
    for i, name in enumerate(names):
        nm = (name or "").strip()
        if not nm:
            continue
        out.append({"param_id": id_base + i, "name": nm, "index": i})
    return out


def validate_pack(pack):
    """Raise ValueError if the pack is missing required structure; else return it.

    Required: a dict with non-empty str `plugin`, int `id_base`, and a non-empty
    list `params` whose entries are dicts with int `param_id` and non-empty str
    `name`. `param_id`s must be unique. `category` is optional.
    """
    if not isinstance(pack, dict):
        raise ValueError("pack must be a dict")
    if not isinstance(pack.get("plugin"), str) or not pack["plugin"]:
        raise ValueError("pack.plugin must be a non-empty string")
    if not isinstance(pack.get("id_base"), int):
        raise ValueError("pack.id_base must be an int")
    params = pack.get("params")
    if not isinstance(params, list) or not params:
        raise ValueError("pack.params must be a non-empty list")
    seen = set()
    for i, p in enumerate(params):
        if not isinstance(p, dict):
            raise ValueError("params[%d] must be a dict" % i)
        if not isinstance(p.get("param_id"), int):
            raise ValueError("params[%d].param_id must be an int" % i)
        if not isinstance(p.get("name"), str) or not p["name"]:
            raise ValueError("params[%d].name must be a non-empty string" % i)
        if p["param_id"] in seen:
            raise ValueError("duplicate param_id %d" % p["param_id"])
        seen.add(p["param_id"])
    return pack


def load_pack(name, pack_dir=PACK_DIR):
    """Load + validate a committed pack JSON by bare name (no `.json`)."""
    path = os.path.join(pack_dir, name + ".json")
    if not os.path.exists(path):
        raise FileNotFoundError("no param-map pack: %s" % path)
    with open(path) as f:
        pack = json.load(f)
    return validate_pack(pack)


def find_params(pack, query, category=None):
    """Params whose name contains `query` (case-insensitive), in pack order.

    Optional `category` filter (exact match). Empty query matches every param,
    so `find_params(pack, "", category="Filter")` returns the whole category.
    """
    q = (query or "").lower()
    out = []
    for p in pack["params"]:
        if category is not None and p.get("category") != category:
            continue
        if q in p["name"].lower():
            out.append(p)
    return out
