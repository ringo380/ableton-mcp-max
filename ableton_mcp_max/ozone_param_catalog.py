"""Load/validate the committed Ozone 12 catalog (param_maps/ozone12.json)."""
import os

from ableton_mcp_max import param_map_utils as pmu

_PACK = "ozone12"


def load():
    """Load + validate the Ozone 12 catalog pack."""
    return pmu.load_pack(_PACK)


def catalog_by_module(pack):
    """Group params by module key (params with module None -> key 'GLOBAL')."""
    out = {}
    for p in pack["params"]:
        out.setdefault(p.get("module") or "GLOBAL", []).append(p)
    return out


def find_param(pack, module, role, band=None, section=None):
    """First param matching module + role (+ optional band/section), else None."""
    for p in pack["params"]:
        if p.get("module") != module:
            continue
        if p.get("role") != role:
            continue
        if band is not None and p.get("band") != band:
            continue
        if section is not None and p.get("section") != section:
            continue
        return p
    return None
