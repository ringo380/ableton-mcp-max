"""Per-domain indexers + directory-mtime freshness for the catalog.

Imported by server.py only. Filesystem indexers (serum/sample/groove) are pure;
the device-preset indexer takes an injected browser_reader callable so this
module never imports the Ableton connection.
"""
import hashlib
import os
import time


def fingerprint_root(root):
    """Cheap signature of a directory tree: hash over (dirpath, dir_mtime) for
    every directory under root. Stats directories only, never files - adding or
    removing any file bumps its parent dir's mtime, so content changes are still
    caught."""
    h = hashlib.sha1()
    if not os.path.isdir(root):
        return ""
    entries = []
    for dirpath, dirnames, _files in os.walk(root):
        dirnames.sort()
        try:
            mt = os.stat(dirpath).st_mtime
        except OSError:
            mt = 0.0
        entries.append("%s\t%r" % (dirpath, mt))
    for e in entries:
        h.update(e.encode("utf-8", "ignore"))
        h.update(b"\n")
    return h.hexdigest()


def root_changed(conn, root, domain, source):
    row = conn.execute(
        "SELECT fingerprint FROM roots WHERE root_path=? AND domain=? AND source=?",
        (root, domain, source)).fetchone()
    if row is None or row[0] is None:
        return True
    return row[0] != fingerprint_root(root)


def record_root(conn, root, domain, source, fingerprint):
    conn.execute(
        "INSERT INTO roots(root_path,domain,source,fingerprint,last_indexed)"
        " VALUES(?,?,?,?,?)"
        " ON CONFLICT(root_path,domain,source) DO UPDATE SET"
        " fingerprint=excluded.fingerprint, last_indexed=excluded.last_indexed",
        (root, domain, source, fingerprint, time.time()))
    conn.commit()


import json as _json
import re as _re

from ableton_mcp_max import serum_state_codec as _ssc
from ableton_mcp_max import serum_fx_utils as _sfx
from ableton_mcp_max import groove_preset_utils as _groovep
from ableton_mcp_max.sample_utils import classify_sample as _classify

SAMPLE_EXTS = (".wav", ".aif", ".aiff", ".aifc", ".flac", ".mp3", ".ogg",
               ".adv", ".adg")


def _folder_words(folder):
    return " ".join(w for w in _re.split(r"[\W_]+", folder or "") if w)


def _delete_subtree(conn, domain, source, root):
    conn.execute(
        "DELETE FROM items WHERE domain=? AND source=? AND path LIKE ?",
        (domain, source, root.rstrip("/") + os.sep + "%"))


def _upsert_fs(conn, domain, name, path, source, folder, kind, loadable,
               tags, extra):
    try:
        mt = os.stat(path).st_mtime
    except OSError:
        mt = None
    # INSERT OR REPLACE handles the partial unique index (domain,source,path)
    # correctly; the ON CONFLICT(...) upsert syntax requires a non-partial index.
    # _delete_subtree always clears stale rows first, so replace is a no-op in
    # practice, but keeps the function safe against duplicate paths.
    conn.execute(
        "INSERT OR REPLACE INTO items(domain,name,path,uri,source,folder,kind,"
        "loadable,mtime,tags,extra,indexed_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (domain, name, path, None, source, folder, kind, loadable, mt, tags,
         extra, time.time()))


def index_serum(conn, roots):
    count = 0
    for root, source in roots:
        if not os.path.isdir(root):
            continue
        _delete_subtree(conn, "serum", source, root)
        for dirpath, _d, files in os.walk(root):
            for fn in files:
                if not fn.endswith(".SerumPreset"):
                    continue
                path = os.path.join(dirpath, fn)
                name = os.path.splitext(fn)[0]
                folder = os.path.relpath(dirpath, root)
                fx_types, loadable = [], 1
                try:
                    tree = _ssc.decode(open(path, "rb").read()).tree
                    for fx in _sfx.list_fx(tree):
                        if fx.get("type") is not None:
                            fx_types.append(fx["type"])
                except Exception:
                    loadable = 0
                tags = (_folder_words(folder) + " "
                        + " ".join("fx%d" % t for t in fx_types)).strip()
                _upsert_fs(conn, "serum", name, path, source, folder, None,
                           loadable, tags, _json.dumps({"fx_types": fx_types}))
                count += 1
        record_root(conn, root, "serum", source, fingerprint_root(root))
    conn.commit()
    return count


def index_samples(conn, roots):
    count = 0
    for root, source in roots:
        if not os.path.isdir(root):
            continue
        _delete_subtree(conn, "sample", source, root)
        for dirpath, _d, files in os.walk(root):
            for fn in files:
                is_stub = fn.startswith(".") and fn.endswith(".icloud")
                real = fn[1:-len(".icloud")] if is_stub else fn
                if os.path.splitext(real)[1].lower() not in SAMPLE_EXTS:
                    continue
                path = os.path.join(dirpath, real)
                folder = os.path.relpath(dirpath, root)
                kind = _classify(real, os.path.join(folder, real))
                tags = (kind + " " + _folder_words(folder)).strip()
                _upsert_fs(conn, "sample", real, path, source, folder, kind, 1,
                           tags, None)
                count += 1
        record_root(conn, root, "sample", source, fingerprint_root(root))
    conn.commit()
    return count


def index_grooves(conn, roots):
    count = 0
    for root, source in roots:
        if not os.path.isdir(root):
            continue
        _delete_subtree(conn, "groove", source, root)
        for dirpath, _d, files in os.walk(root):
            for fn in files:
                if not fn.lower().endswith(".agr"):
                    continue
                path = os.path.join(dirpath, fn)
                name = os.path.splitext(fn)[0]
                category = os.path.basename(dirpath)
                loadable = 1 if _groovep.is_xml_agr(path) else 0
                _upsert_fs(conn, "groove", name, path, source, category, None,
                           loadable, category, None)
                count += 1
        record_root(conn, root, "groove", source, fingerprint_root(root))
    conn.commit()
    return count


class DeviceLiveUnavailable(Exception):
    """Raised when no browser path was reachable (Live likely disconnected)."""


def index_device_presets(conn, browser_reader, paths):
    """Index device presets from Live's browser via an injected reader callable.

    browser_reader(path) -> {"presets": [{"name","relative_path","uri"}], "count":int}
    A reader call that raises or returns {"error":...} is skipped silently.
    Accumulates rows across all paths, then only deletes + inserts when at
    least one path was reachable. Raises DeviceLiveUnavailable when every
    path raised (so the caller can preserve an existing cache). Returns the
    number of presets indexed.
    """
    collected = []
    reachable = False
    for path in paths:
        try:
            result = browser_reader(path)
        except Exception:
            continue
        reachable = True
        if not result or result.get("error"):
            continue
        for p in result.get("presets", []):
            uri = p.get("uri")
            if not uri:
                continue
            rel = p.get("relative_path", "") or ""
            name = os.path.splitext(os.path.basename(p.get("name", "")))[0]
            folder = os.path.dirname(rel)
            collected.append((name, uri, folder, _folder_words(folder)))
    if not reachable:
        raise DeviceLiveUnavailable(
            "no browser path reachable (Live connected?)")
    conn.execute("DELETE FROM items WHERE domain='device_preset'")
    for name, uri, folder, tags in collected:
        # INSERT OR REPLACE: the unique index on (domain,uri) is partial
        # (WHERE uri IS NOT NULL), which SQLite forbids as an ON CONFLICT
        # target; INSERT OR REPLACE handles it correctly (same pattern as
        # _upsert_fs).
        conn.execute(
            "INSERT OR REPLACE INTO items(domain,name,path,uri,source,folder,"
            "kind,loadable,mtime,tags,extra,indexed_at)"
            " VALUES('device_preset',?,?,?,?,?,?,1,?,?,?,?)",
            (name, None, uri, "factory", folder, None, None, tags, None,
             time.time()))
    record_root(conn, "lom:device_presets", "device_preset", "factory", "live")
    conn.commit()
    return len(collected)
