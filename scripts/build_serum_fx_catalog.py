"""Decode every factory .SerumPreset and union all FX types/wrappers/params into
ableton_mcp_max/param_maps/serum2_fx.json. Rerunnable. Native ranges are observed
across the factory corpus (approximate; native is source of truth at runtime)."""
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ableton_mcp_max import serum_state_codec as sc

FACTORY = "/Library/Audio/Presets/Xfer Records/Serum 2 Presets/Presets"
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "ableton_mcp_max", "param_maps", "serum2_fx.json")


def _fx_entries(tree):
    for rk in ("FXRack0", "FXRack1", "FXRack2"):
        rack = tree.get(rk) if hasattr(tree, "get") else None
        if not rack:
            continue
        for fx in rack.get("FX", []):
            yield fx


def _wrapper_and_params(fx):
    wrapper = None
    params = {}
    for k, v in fx.items():
        if k == "type":
            continue
        if isinstance(v, dict):
            wrapper = wrapper or k
            pp = v.get("plainParams")
            if isinstance(pp, dict):
                params.update(pp)
    return wrapper, params


def main():
    files = glob.glob(FACTORY + "/**/*.SerumPreset", recursive=True)
    if not files:
        raise SystemExit("no factory presets found at %s" % FACTORY)
    types = {}
    for f in files:
        try:
            tree = sc.decode(open(f, "rb").read()).tree
        except Exception:
            continue
        for fx in _fx_entries(tree):
            t = int(fx.get("type"))
            wrapper, params = _wrapper_and_params(fx)
            slot = types.setdefault(t, {"name": (wrapper or "FX%d" % t).replace("FX", "", 1) or "FX%d" % t,
                                        "wrapper_key": wrapper, "params": {}, "default_template": {}})
            if wrapper and not slot["wrapper_key"]:
                slot["wrapper_key"] = wrapper
            for kp, val in params.items():
                if not isinstance(val, (int, float)):
                    continue
                rng = slot["params"].setdefault(kp, [float(val), float(val)])
                rng[0] = min(rng[0], float(val))
                rng[1] = max(rng[1], float(val))
    out = {"plugin": "Serum2", "fx_types": {}}
    for t, slot in sorted(types.items()):
        out["fx_types"][str(t)] = {
            "name": slot["name"],
            "wrapper_key": slot["wrapper_key"],
            "params": [{"kparam": kp, "native_min": lo, "native_max": hi}
                       for kp, (lo, hi) in sorted(slot["params"].items())],
            "default_template": {},
        }
    with open(OUT, "w") as fh:
        json.dump(out, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print("wrote %s: %d fx types" % (OUT, len(out["fx_types"])))


if __name__ == "__main__":
    main()
