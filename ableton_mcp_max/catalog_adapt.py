"""Convert catalog rows back to the exact legacy search_samples/search_grooves
item shapes so those tools can delegate without changing their contract."""
import os


def rows_to_sample_items(rows):
    out = []
    for r in rows:
        path = r["path"] if not isinstance(r, dict) else r.get("path")
        is_ph = False
        if path:
            try:
                is_ph = not os.path.exists(path) and os.path.exists(
                    os.path.join(os.path.dirname(path),
                                 "." + os.path.basename(path) + ".icloud"))
            except OSError:
                is_ph = False
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
