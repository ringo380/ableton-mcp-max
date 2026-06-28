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
