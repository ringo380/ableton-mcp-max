"""Generate param_maps/ozone12.json from scripts/ozone_probe_data.json.

param_id = id_base + index (index-based Configure scheme, confirmed live).
Each param is enriched via ozone_utils.parse_param_name. Run:
  uv run python scripts/build_ozone_catalog.py
"""
import json
import os

from ableton_mcp_max import ozone_utils as oz

HERE = os.path.dirname(__file__)
SRC = os.path.join(HERE, "ozone_probe_data.json")
OUT = os.path.join(HERE, "..", "ableton_mcp_max", "param_maps", "ozone12.json")


def build():
    data = json.load(open(SRC))
    id_base = data["id_base"]
    params = []
    for p in data["params"]:
        info = oz.parse_param_name(p["name"])
        params.append({
            "param_id": id_base + p["index"],
            "name": p["name"],
            "category": info["module_name"] or "Global",
            "module": info["module"],
            "section": info["section"],
            "role": info["role"],
            "band": info["band"],
            "min": p.get("min"),
            "max": p.get("max"),
            "is_quantized": p.get("is_quantized", False),
            "value_items": p.get("value_items", []),
        })
    pack = {"plugin": "Ozone12", "id_base": id_base, "params": params}
    with open(OUT, "w") as f:
        json.dump(pack, f, indent=1)
        f.write("\n")
    print("wrote %d params to %s" % (len(params), OUT))


if __name__ == "__main__":
    build()
