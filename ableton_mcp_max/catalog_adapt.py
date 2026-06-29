"""Convert catalog rows back to the exact legacy search_samples/search_grooves
item shapes so those tools can delegate without changing their contract."""
import os

from ableton_mcp_max.sample_utils import icloud_placeholder_path


def rows_to_sample_items(rows):
    out = []
    for r in rows:
        path = r.get("path")
        is_ph = False
        if path:
            is_ph = bool(path) and icloud_placeholder_path(path) is not None
        out.append({
            "name": r["name"], "path": path, "uri": None, "kind": r["kind"],
            "source": r["source"], "folder": r["folder"],
            "is_icloud_placeholder": is_ph,
        })
    return out


def rows_to_groove_items(rows):
    out = []
    for r in rows:
        path = r.get("path")
        out.append({
            "name": r["name"],
            "file": (os.path.basename(path) if path else r["name"] + ".agr"),
            "category": r["folder"], "path": path, "source": r["source"],
            "loadable": bool(r["loadable"]),
        })
    return out
