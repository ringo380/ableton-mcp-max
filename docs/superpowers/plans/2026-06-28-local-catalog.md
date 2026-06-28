# Local Catalog + Decision Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the MCP server a persistent sqlite catalog of on-disk content (Serum presets, samples, grooves, device presets) plus query, decision, and create-orchestration tools so the LLM knows what exists and can reuse-or-create before acting.

**Architecture:** Four new pure host-side modules imported by `server.py` only - `catalog_db` (sqlite lifecycle + FTS5), `catalog_index` (per-domain indexers + dir-mtime freshness), `catalog_query` (search/similarity/stats), `catalog_decide` (reuse-vs-create + dispatch resolution). Six new MCP tools plus an internal orchestration dispatcher in `server.py`; `search_samples`/`search_grooves` delegate to the catalog with a live-walk fallback.

**Tech Stack:** Python 3.10+, stdlib `sqlite3` with FTS5 (no new third-party dependency), pytest, existing `serum_state_codec` / `serum_fx_utils` / `serum_fx_catalog` / `sample_utils` / `groove_preset_utils`.

## Global Constraints

- New code is host-side **pure modules imported by `server.py` only**; the Remote Script never imports them and gets no new handlers.
- **No new third-party dependency**: stdlib `sqlite3` ships FTS5 in CPython. Do NOT add anything to `pyproject.toml` dependencies.
- DB lives at `~/.ableton-mcp/catalog.db`: a **disposable cache** - created on first use, never shipped, safe to delete (rebuilds), never precious data.
- All new tools return the house envelope via `_ok(data)` / `_err(message)` from `server.py`.
- A catalog failure must always degrade (slower / cached / clear error), never break a tool. Where a live path exists (`search_samples`/`search_grooves`), fall back to it.
- ASCII only in all source, docs, commits, PR text. No AI attribution anywhere (public repo).
- Tests run with `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q`. Syntax-check server with `uv run python -c "import ableton_mcp_max.server"`. Do NOT reformat existing files.
- Embeddings/semantic search and full Serum tree synthesis are OUT of scope.
- `SCHEMA_VERSION = 1`. Decision values: `"reuse"` | `"create"` | `"gap"` (gap = no match in a non-creatable domain).
- `REUSE_MIN_SCORE = 2` (token-overlap score at/above which the top match is a reuse).

---

### Task 1: catalog_db.py - sqlite lifecycle, schema, FTS5, migrations

**Files:**
- Create: `ableton_mcp_max/catalog_db.py`
- Test: `tests/test_catalog_db.py`

**Interfaces:**
- Consumes: stdlib `sqlite3`, `os`, `time`.
- Produces:
  - `default_db_path() -> str` (override via `_DB_PATH_OVERRIDE` module global or env `ABLETON_MCP_CATALOG_DB`, else `~/.ableton-mcp/catalog.db`)
  - `open_db(path=None) -> sqlite3.Connection` (creates dir + schema, sets WAL, rebuilds on corruption/version mismatch; `row_factory = sqlite3.Row`)
  - `rebuild(conn) -> None` (drop + recreate all tables/triggers, set schema_version)
  - `SCHEMA_VERSION = 1`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_catalog_db.py
import os
import sqlite3
import pytest
from ableton_mcp_max import catalog_db


def test_open_creates_schema(tmp_path):
    db = str(tmp_path / "c.db")
    conn = catalog_db.open_db(db)
    names = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
    assert {"items", "items_fts", "roots", "meta"} <= names
    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    ver = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
    assert int(ver) == catalog_db.SCHEMA_VERSION


def test_fts_trigger_syncs_on_insert_and_delete(tmp_path):
    conn = catalog_db.open_db(str(tmp_path / "c.db"))
    conn.execute(
        "INSERT INTO items(domain,name,path,source,folder,tags,loadable,indexed_at)"
        " VALUES('sample','Deep Kick','/a/Deep Kick.wav','user','Drums','drums kick',1,1.0)")
    conn.commit()
    rows = conn.execute(
        "SELECT items.name FROM items_fts JOIN items ON items.id=items_fts.rowid"
        " WHERE items_fts MATCH 'kick'").fetchall()
    assert [r[0] for r in rows] == ["Deep Kick"]
    conn.execute("DELETE FROM items")
    conn.commit()
    rows = conn.execute("SELECT * FROM items_fts WHERE items_fts MATCH 'kick'").fetchall()
    assert rows == []


def test_rebuild_on_version_mismatch(tmp_path):
    db = str(tmp_path / "c.db")
    conn = catalog_db.open_db(db)
    conn.execute("UPDATE meta SET value='0' WHERE key='schema_version'")
    conn.commit()
    conn.close()
    conn2 = catalog_db.open_db(db)  # should detect stale version and rebuild
    ver = conn2.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
    assert int(ver) == catalog_db.SCHEMA_VERSION


def test_rebuild_on_corrupt_file(tmp_path):
    db = str(tmp_path / "c.db")
    with open(db, "wb") as f:
        f.write(b"not a sqlite database at all")
    conn = catalog_db.open_db(db)  # should wipe + recreate, not raise
    assert conn.execute("SELECT count(*) FROM items").fetchone()[0] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_catalog_db.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'ableton_mcp_max.catalog_db'`

- [ ] **Step 3: Write the implementation**

```python
# ableton_mcp_max/catalog_db.py
"""Disposable sqlite catalog cache: schema, FTS5, migrations, lifecycle.

Pure stdlib. Imported by server.py only. The DB at ~/.ableton-mcp/catalog.db is
a cache - any corruption or schema-version drift triggers a full rebuild rather
than an error.
"""
import os
import sqlite3
import time

SCHEMA_VERSION = 1
_DB_PATH_OVERRIDE = None

_SCHEMA = """
CREATE TABLE items (
  id INTEGER PRIMARY KEY,
  domain TEXT NOT NULL,
  name TEXT NOT NULL,
  path TEXT,
  uri TEXT,
  source TEXT NOT NULL,
  folder TEXT,
  kind TEXT,
  loadable INTEGER NOT NULL DEFAULT 1,
  mtime REAL,
  tags TEXT,
  extra TEXT,
  indexed_at REAL NOT NULL
);
CREATE UNIQUE INDEX idx_items_fs ON items(domain, source, path) WHERE path IS NOT NULL;
CREATE UNIQUE INDEX idx_items_uri ON items(domain, uri) WHERE uri IS NOT NULL;
CREATE INDEX idx_items_domain ON items(domain);

CREATE VIRTUAL TABLE items_fts USING fts5(
  name, folder, tags, content='items', content_rowid='id'
);
CREATE TRIGGER items_ai AFTER INSERT ON items BEGIN
  INSERT INTO items_fts(rowid, name, folder, tags)
    VALUES (new.id, new.name, new.folder, new.tags);
END;
CREATE TRIGGER items_ad AFTER DELETE ON items BEGIN
  INSERT INTO items_fts(items_fts, rowid, name, folder, tags)
    VALUES ('delete', old.id, old.name, old.folder, old.tags);
END;
CREATE TRIGGER items_au AFTER UPDATE ON items BEGIN
  INSERT INTO items_fts(items_fts, rowid, name, folder, tags)
    VALUES ('delete', old.id, old.name, old.folder, old.tags);
  INSERT INTO items_fts(rowid, name, folder, tags)
    VALUES (new.id, new.name, new.folder, new.tags);
END;

CREATE TABLE roots (
  root_path TEXT NOT NULL,
  domain TEXT NOT NULL,
  source TEXT NOT NULL,
  fingerprint TEXT,
  last_indexed REAL,
  PRIMARY KEY (root_path, domain, source)
);

CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
"""


def default_db_path():
    if _DB_PATH_OVERRIDE:
        return _DB_PATH_OVERRIDE
    env = os.environ.get("ABLETON_MCP_CATALOG_DB")
    if env:
        return env
    return os.path.expanduser("~/.ableton-mcp/catalog.db")


def _create(conn):
    conn.executescript(_SCHEMA)
    conn.execute("INSERT INTO meta(key,value) VALUES('schema_version',?)",
                 (str(SCHEMA_VERSION),))
    conn.execute("INSERT INTO meta(key,value) VALUES('last_run',?)",
                 (str(time.time()),))
    conn.commit()


def rebuild(conn):
    """Drop everything and recreate from scratch."""
    cur = conn.execute(
        "SELECT name,type FROM sqlite_master WHERE type IN ('table','trigger','view')")
    for name, _type in cur.fetchall():
        if name.startswith("sqlite_"):
            continue
        conn.execute("DROP TABLE IF EXISTS %s" % name) if _type == "table" \
            else conn.execute("DROP %s IF EXISTS %s" % (_type.upper(), name))
    conn.commit()
    _create(conn)


def _schema_ok(conn):
    try:
        row = conn.execute(
            "SELECT value FROM meta WHERE key='schema_version'").fetchone()
    except sqlite3.DatabaseError:
        return False
    return row is not None and int(row[0]) == SCHEMA_VERSION


def open_db(path=None):
    path = path or default_db_path()
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    try:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        if not _schema_ok(conn):
            rebuild(conn)
        return conn
    except sqlite3.DatabaseError:
        # Corrupt file: wipe and recreate.
        try:
            conn.close()
        except Exception:
            pass
        if os.path.exists(path):
            os.remove(path)
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        _create(conn)
        return conn
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_catalog_db.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/catalog_db.py tests/test_catalog_db.py
git commit -m "feat: catalog_db - sqlite schema, FTS5, migrations"
```

---

### Task 2: catalog_index.py - directory fingerprint + freshness

**Files:**
- Create: `ableton_mcp_max/catalog_index.py`
- Test: `tests/test_catalog_index_fingerprint.py`

**Interfaces:**
- Consumes: stdlib `os`, `hashlib`.
- Produces:
  - `fingerprint_root(root: str) -> str` (hash over dirs-only `(dirpath, dir_mtime)`; statting directories not files)
  - `root_changed(conn, root: str, domain: str, source: str) -> bool` (compares fresh fingerprint to stored `roots.fingerprint`; True if missing or differs)
  - `record_root(conn, root: str, domain: str, source: str, fingerprint: str) -> None` (upsert into `roots` with `last_indexed=time.time()`)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_catalog_index_fingerprint.py
from ableton_mcp_max import catalog_db, catalog_index


def test_fingerprint_changes_when_file_added(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "a.wav").write_bytes(b"x")
    fp1 = catalog_index.fingerprint_root(str(tmp_path))
    (tmp_path / "sub" / "b.wav").write_bytes(b"y")  # bumps sub/ mtime
    fp2 = catalog_index.fingerprint_root(str(tmp_path))
    assert fp1 != fp2


def test_fingerprint_stable_when_unchanged(tmp_path):
    (tmp_path / "x").mkdir()
    fp1 = catalog_index.fingerprint_root(str(tmp_path))
    fp2 = catalog_index.fingerprint_root(str(tmp_path))
    assert fp1 == fp2


def test_root_changed_and_record(tmp_path):
    conn = catalog_db.open_db(str(tmp_path / "c.db"))
    root = str(tmp_path / "lib")
    (tmp_path / "lib").mkdir()
    assert catalog_index.root_changed(conn, root, "sample", "user") is True
    fp = catalog_index.fingerprint_root(root)
    catalog_index.record_root(conn, root, "sample", "user", fp)
    assert catalog_index.root_changed(conn, root, "sample", "user") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_catalog_index_fingerprint.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'ableton_mcp_max.catalog_index'`

- [ ] **Step 3: Write the implementation**

```python
# ableton_mcp_max/catalog_index.py
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_catalog_index_fingerprint.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/catalog_index.py tests/test_catalog_index_fingerprint.py
git commit -m "feat: catalog_index - dir-mtime fingerprint + freshness"
```

---

### Task 3: catalog_index.py - filesystem indexers (serum, sample, groove)

**Files:**
- Modify: `ableton_mcp_max/catalog_index.py` (append)
- Test: `tests/test_catalog_index_fs.py`

**Interfaces:**
- Consumes: `catalog_db` connection; `serum_state_codec.decode`, `serum_fx_utils.list_fx`, `sample_utils.classify_sample`/`name_match` not needed here (indexing stores all files; matching is query-time), `groove_preset_utils.is_xml_agr`. Reuse `fingerprint_root`/`record_root` from Task 2.
- Produces (all upsert into `items`, return count indexed):
  - `index_serum(conn, roots) -> int` where `roots` is `[(root_path, source), ...]`; walks `*.SerumPreset`, decodes via `serum_state_codec`, stores name/path/source/folder, `tags` = fx type names + folder words, `extra` = JSON `{"fx_types": [...]}`. Undecodable file -> row with `loadable=0`, empty fx_types.
  - `index_samples(conn, roots) -> int`; walks `_SAMPLE_EXTS`, stores name/path/source/folder, `kind` via `classify_sample`, `tags` = kind + folder words. (iCloud stubs resolved like `search_samples`.)
  - `index_grooves(conn, roots) -> int`; walks `*.agr`, `loadable` via `is_xml_agr`, `folder`=parent dir name, `tags`=category.
- Module-level: `SAMPLE_EXTS = (".wav",".aif",".aiff",".aifc",".flac",".mp3",".ogg",".adv",".adg")`

**Note:** indexers DELETE existing rows for each `(domain, source, root)` subtree before re-inserting (clean reindex), keyed by `domain` + `source` + path-prefix `root`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_catalog_index_fs.py
import json
import os
from ableton_mcp_max import catalog_db, catalog_index, serum_state_codec


def _write_serum(path, fx_types):
    # Build a minimal decoded tree with one FX rack, encode via the real codec.
    base = serum_state_codec.decode  # ensure module present
    # Construct a tree the codec can round-trip: reuse encode on a tiny state.
    from ableton_mcp_max.serum_state_codec import DecodedState
    tree = {"FXRack0": {"FX": [{"type": t} for t in fx_types],
                        "displayName": "A", "plainParams": {}},
            "FXRack1": {"FX": [], "displayName": "B", "plainParams": {}},
            "FXRack2": {"FX": [], "displayName": "C", "plainParams": {}}}
    meta = {"product": "Serum2", "name": os.path.basename(path)}
    state = DecodedState(meta, json.dumps(meta).encode("utf-8"), tree)
    with open(path, "wb") as f:
        f.write(serum_state_codec.encode(state, tree))


def test_index_serum_and_grooves_and_samples(tmp_path):
    conn = catalog_db.open_db(str(tmp_path / "c.db"))

    # Serum
    sdir = tmp_path / "serum" / "Bass"
    sdir.mkdir(parents=True)
    _write_serum(str(sdir / "Deep Sub.SerumPreset"), [0, 1])
    (sdir / "broken.SerumPreset").write_bytes(b"garbage")
    n = catalog_index.index_serum(conn, [(str(tmp_path / "serum"), "user")])
    assert n == 2
    good = conn.execute(
        "SELECT name,loadable,extra FROM items WHERE domain='serum' AND name='Deep Sub'"
    ).fetchone()
    assert good["loadable"] == 1
    assert json.loads(good["extra"])["fx_types"] == [0, 1]
    bad = conn.execute(
        "SELECT loadable FROM items WHERE domain='serum' AND name='broken'").fetchone()
    assert bad["loadable"] == 0

    # Grooves: one xml (loadable), one binary (not)
    gdir = tmp_path / "grooves" / "Funk"
    gdir.mkdir(parents=True)
    (gdir / "Swing.agr").write_bytes(b"<GrooveFile></GrooveFile>")
    (gdir / "Bin.agr").write_bytes(b"\xab\x1eVx\x00\x00\x00\x00")
    catalog_index.index_grooves(conn, [(str(tmp_path / "grooves"), "factory")])
    sw = conn.execute("SELECT loadable,folder FROM items WHERE name='Swing'").fetchone()
    assert sw["loadable"] == 1 and sw["folder"] == "Funk"
    assert conn.execute("SELECT loadable FROM items WHERE name='Bin'").fetchone()[0] == 0

    # Samples
    smp = tmp_path / "samples" / "Drums"
    smp.mkdir(parents=True)
    (smp / "Deep Kick.wav").write_bytes(b"RIFF")
    catalog_index.index_samples(conn, [(str(tmp_path / "samples"), "user")])
    k = conn.execute("SELECT kind,source FROM items WHERE name='Deep Kick.wav'").fetchone()
    assert k["kind"] in ("one_shot", "loop", "kit", "instrument")
    assert k["source"] == "user"


def test_reindex_replaces_rows(tmp_path):
    conn = catalog_db.open_db(str(tmp_path / "c.db"))
    gdir = tmp_path / "g" / "Cat"
    gdir.mkdir(parents=True)
    f = gdir / "One.agr"
    f.write_bytes(b"<x/>")
    catalog_index.index_grooves(conn, [(str(tmp_path / "g"), "user")])
    f.unlink()
    catalog_index.index_grooves(conn, [(str(tmp_path / "g"), "user")])
    assert conn.execute("SELECT count(*) FROM items WHERE name='One'").fetchone()[0] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_catalog_index_fs.py -q`
Expected: FAIL with `AttributeError: module 'ableton_mcp_max.catalog_index' has no attribute 'index_serum'`

- [ ] **Step 3: Write the implementation (append to catalog_index.py)**

```python
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
    conn.execute(
        "INSERT INTO items(domain,name,path,uri,source,folder,kind,loadable,"
        "mtime,tags,extra,indexed_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)"
        " ON CONFLICT(domain,source,path) DO UPDATE SET"
        " name=excluded.name, folder=excluded.folder, kind=excluded.kind,"
        " loadable=excluded.loadable, mtime=excluded.mtime, tags=excluded.tags,"
        " extra=excluded.extra, indexed_at=excluded.indexed_at",
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_catalog_index_fs.py -q`
Expected: PASS (2 passed). If the codec round-trip in the helper fails, adjust `_write_serum` to match `serum_state_codec.encode`'s required `DecodedState` shape (meta must include a `hash` key the codec recomputes - the encode call handles it).

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/catalog_index.py tests/test_catalog_index_fs.py
git commit -m "feat: catalog_index - serum/sample/groove filesystem indexers"
```

---

### Task 4: catalog_index.py - device-preset indexer (injected browser_reader)

**Files:**
- Modify: `ableton_mcp_max/catalog_index.py` (append)
- Test: `tests/test_catalog_index_device.py`

**Interfaces:**
- Consumes: `catalog_db` connection.
- Produces:
  - `index_device_presets(conn, browser_reader, paths) -> int` where `browser_reader(path) -> {"presets":[{"name","relative_path","uri"}], "count":int}` (the shape `get_browser_presets` returns) and `paths` is a list of top browser paths (e.g. `["instruments", "audio_effects"]`). Stores domain `device_preset`, `uri` (unique key), `name`, `folder` = `relative_path` dir, `source` = `factory`. A reader call that raises or returns `{"error":...}` is skipped (that path contributes 0), never aborts the whole run.
  - Upserts on `(domain, uri)`; replaces all `device_preset` rows at the start of a successful run (full replace, since there is no fs subtree to scope by).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_catalog_index_device.py
from ableton_mcp_max import catalog_db, catalog_index


def test_index_device_presets_with_fake_reader(tmp_path):
    conn = catalog_db.open_db(str(tmp_path / "c.db"))

    def reader(path):
        if path == "instruments":
            return {"presets": [
                {"name": "Dark Pad.adg", "relative_path": "Pads/Dark Pad.adg",
                 "uri": "library://Wavetable/Pads/Dark Pad"}],
                "count": 1}
        if path == "broken":
            raise RuntimeError("no such category")
        return {"error": "empty", "presets": [], "count": 0}

    n = catalog_index.index_device_presets(
        conn, reader, ["instruments", "broken", "audio_effects"])
    assert n == 1
    row = conn.execute(
        "SELECT name,uri,folder,domain FROM items WHERE domain='device_preset'"
    ).fetchone()
    assert row["uri"] == "library://Wavetable/Pads/Dark Pad"
    assert row["folder"] == "Pads"


def test_device_reindex_replaces(tmp_path):
    conn = catalog_db.open_db(str(tmp_path / "c.db"))
    catalog_index.index_device_presets(
        conn, lambda p: {"presets": [
            {"name": "A.adg", "relative_path": "X/A.adg", "uri": "u://A"}],
            "count": 1}, ["instruments"])
    catalog_index.index_device_presets(
        conn, lambda p: {"presets": [
            {"name": "B.adg", "relative_path": "X/B.adg", "uri": "u://B"}],
            "count": 1}, ["instruments"])
    names = {r[0] for r in conn.execute(
        "SELECT name FROM items WHERE domain='device_preset'")}
    assert names == {"B"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_catalog_index_device.py -q`
Expected: FAIL with `AttributeError: ... has no attribute 'index_device_presets'`

- [ ] **Step 3: Write the implementation (append to catalog_index.py)**

```python
def index_device_presets(conn, browser_reader, paths):
    conn.execute("DELETE FROM items WHERE domain='device_preset'")
    count = 0
    for path in paths:
        try:
            result = browser_reader(path)
        except Exception:
            continue
        if not result or result.get("error"):
            continue
        for p in result.get("presets", []):
            uri = p.get("uri")
            if not uri:
                continue
            rel = p.get("relative_path", "") or ""
            name = os.path.splitext(os.path.basename(p.get("name", "")))[0]
            folder = os.path.dirname(rel)
            tags = _folder_words(folder)
            conn.execute(
                "INSERT INTO items(domain,name,path,uri,source,folder,kind,"
                "loadable,mtime,tags,extra,indexed_at)"
                " VALUES('device_preset',?,?,?,?,?,?,1,?,?,?,?)"
                " ON CONFLICT(domain,uri) DO UPDATE SET"
                " name=excluded.name, folder=excluded.folder,"
                " tags=excluded.tags, indexed_at=excluded.indexed_at",
                (name, None, uri, "factory", folder, None, None, tags, None,
                 time.time()))
            count += 1
    record_root(conn, "lom:device_presets", "device_preset", "factory", "live")
    conn.commit()
    return count
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_catalog_index_device.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/catalog_index.py tests/test_catalog_index_device.py
git commit -m "feat: catalog_index - device-preset indexer via injected reader"
```

---

### Task 5: catalog_query.py - search, find_similar, stats

**Files:**
- Create: `ableton_mcp_max/catalog_query.py`
- Test: `tests/test_catalog_query.py`

**Interfaces:**
- Consumes: a `catalog_db` connection with rows present.
- Produces:
  - `score_tokens(intent: str, name: str, folder: str, tags: str) -> int` (token-overlap: +1 per intent term found in `name+folder+tags`, +1 whole-word bonus per term matching `name`; empty intent -> 0)
  - `search_catalog(conn, query, domains=None, kinds=None, sources=None, limit=50) -> dict` -> `{"count","returned","truncated","items":[row_dict,...]}` (FTS MATCH narrows, then Python token-sort; empty query returns all filtered, name-sorted)
  - `find_similar(conn, intent, domain, limit=10) -> list[dict]` -> `[{"name","path","uri","source","folder","kind","score"}]` sorted by score desc
  - `catalog_stats(conn) -> dict` -> `{"total","by_domain":{...},"by_source":{...},"by_kind":{...},"roots":[{"root_path","domain","source","last_indexed"}],"device_presets_last_indexed":float|None}`
- Internal: `_fts_query(text) -> str|None` builds an OR FTS expression from terms (quote each term, join with `OR`); returns None for empty.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_catalog_query.py
from ableton_mcp_max import catalog_db, catalog_query


def _seed(conn):
    rows = [
        ("serum", "Deep Sub Bass", "/s/Deep Sub Bass.SerumPreset", None, "user",
         "Bass", None, 1, "bass fx0"),
        ("serum", "Bright Lead", "/s/Bright Lead.SerumPreset", None, "factory",
         "Lead", None, 1, "lead fx1"),
        ("sample", "Deep Kick.wav", "/x/Deep Kick.wav", None, "user", "Drums",
         "one_shot", 1, "one_shot drums"),
    ]
    for r in rows:
        conn.execute(
            "INSERT INTO items(domain,name,path,uri,source,folder,kind,loadable,"
            "tags,indexed_at) VALUES(?,?,?,?,?,?,?,?,?,1.0)", r)
    conn.commit()


def test_score_tokens():
    assert catalog_query.score_tokens("deep bass", "Deep Sub Bass", "Bass",
                                      "bass fx0") >= 2
    assert catalog_query.score_tokens("", "x", "y", "z") == 0


def test_search_catalog_filters_domain(tmp_path):
    conn = catalog_db.open_db(str(tmp_path / "c.db"))
    _seed(conn)
    res = catalog_query.search_catalog(conn, "deep", domains=["serum"])
    names = [i["name"] for i in res["items"]]
    assert "Deep Sub Bass" in names and "Deep Kick.wav" not in names
    assert res["count"] == len(res["items"])


def test_find_similar_scored(tmp_path):
    conn = catalog_db.open_db(str(tmp_path / "c.db"))
    _seed(conn)
    hits = catalog_query.find_similar(conn, "deep bass", "serum", limit=5)
    assert hits[0]["name"] == "Deep Sub Bass"
    assert hits[0]["score"] >= 2


def test_stats(tmp_path):
    conn = catalog_db.open_db(str(tmp_path / "c.db"))
    _seed(conn)
    s = catalog_query.catalog_stats(conn)
    assert s["total"] == 3
    assert s["by_domain"]["serum"] == 2
    assert s["by_kind"]["one_shot"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_catalog_query.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'ableton_mcp_max.catalog_query'`

- [ ] **Step 3: Write the implementation**

```python
# ableton_mcp_max/catalog_query.py
"""Read side of the catalog: FTS narrowing + token scoring, similarity, stats."""
import re

_ITEM_COLS = ("name", "path", "uri", "source", "folder", "kind", "loadable",
              "domain")


def _terms(text):
    return [t for t in re.split(r"[\W_]+", (text or "").lower()) if t]


def score_tokens(intent, name, folder, tags):
    terms = _terms(intent)
    if not terms:
        return 0
    hay = " ".join([name or "", folder or "", tags or ""]).lower()
    name_words = set(_terms(name))
    score = 0
    for t in terms:
        if t in hay:
            score += 1
        if t in name_words:
            score += 1
    return score


def _fts_query(text):
    terms = _terms(text)
    if not terms:
        return None
    return " OR ".join('"%s"' % t for t in terms)


def _candidate_rows(conn, query, domains, kinds, sources):
    where, args = [], []
    if domains:
        where.append("domain IN (%s)" % ",".join("?" * len(domains)))
        args += list(domains)
    if kinds:
        where.append("kind IN (%s)" % ",".join("?" * len(kinds)))
        args += list(kinds)
    if sources:
        where.append("source IN (%s)" % ",".join("?" * len(sources)))
        args += list(sources)
    fts = _fts_query(query)
    if fts:
        sql = ("SELECT items.*, items.tags AS _tags FROM items_fts"
               " JOIN items ON items.id=items_fts.rowid"
               " WHERE items_fts MATCH ?")
        a = [fts]
        if where:
            sql += " AND " + " AND ".join(where)
            a += args
    else:
        sql = "SELECT items.*, items.tags AS _tags FROM items"
        if where:
            sql += " WHERE " + " AND ".join(where)
        a = args
    return conn.execute(sql, a).fetchall()


def _row_dict(r, score=None):
    d = {c: r[c] for c in _ITEM_COLS}
    if score is not None:
        d["score"] = score
    return d


def search_catalog(conn, query, domains=None, kinds=None, sources=None,
                   limit=50):
    rows = _candidate_rows(conn, query, domains, kinds, sources)
    scored = [(score_tokens(query, r["name"], r["folder"], r["tags"]), r)
              for r in rows]
    if _terms(query):
        scored.sort(key=lambda x: (-x[0], x[1]["name"] or ""))
    else:
        scored.sort(key=lambda x: (x[1]["name"] or ""))
    total = len(scored)
    shown = scored[:limit] if limit and limit > 0 else scored
    return {
        "count": total,
        "returned": len(shown),
        "truncated": len(shown) < total,
        "items": [_row_dict(r) for _s, r in shown],
    }


def find_similar(conn, intent, domain, limit=10):
    rows = _candidate_rows(conn, intent, [domain], None, None)
    scored = [(score_tokens(intent, r["name"], r["folder"], r["tags"]), r)
              for r in rows]
    scored.sort(key=lambda x: (-x[0], x[1]["name"] or ""))
    out = []
    for s, r in scored[:limit] if limit and limit > 0 else scored:
        out.append(_row_dict(r, score=s))
    return out


def catalog_stats(conn):
    def counts(col):
        return {row[0]: row[1] for row in conn.execute(
            "SELECT %s, count(*) FROM items GROUP BY %s" % (col, col))
            if row[0] is not None}
    total = conn.execute("SELECT count(*) FROM items").fetchone()[0]
    roots = [{"root_path": r["root_path"], "domain": r["domain"],
              "source": r["source"], "last_indexed": r["last_indexed"]}
             for r in conn.execute("SELECT * FROM roots")]
    dp = conn.execute(
        "SELECT last_indexed FROM roots WHERE domain='device_preset'").fetchone()
    return {
        "total": total,
        "by_domain": counts("domain"),
        "by_source": counts("source"),
        "by_kind": counts("kind"),
        "roots": roots,
        "device_presets_last_indexed": dp["last_indexed"] if dp else None,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_catalog_query.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/catalog_query.py tests/test_catalog_query.py
git commit -m "feat: catalog_query - FTS search, similarity scoring, stats"
```

---

### Task 6: catalog_decide.py - recommend + dispatch resolution

**Files:**
- Create: `ableton_mcp_max/catalog_decide.py`
- Test: `tests/test_catalog_decide.py`

**Interfaces:**
- Consumes: `catalog_query.find_similar`; constants `REUSE_MIN_SCORE = 2`.
- Produces:
  - `recommend(conn, intent, domain) -> dict` -> `{"decision","top_matches","create_plan","reason"}`. `decision`: `"reuse"` if top score >= `REUSE_MIN_SCORE`; else `"create"` for creatable domains (`serum`,`wavetable`,`simpler`) or `"gap"` for `sample`/`groove`/`device_preset`. `top_matches` = up to 5 from `find_similar`. `create_plan` (only when decision == `"create"`): see `_make_plan`. Propose only - never writes.
  - `resolve_dispatch(plan) -> dict` -> `{"creator","kwargs"}` where `creator` is one of `"create_wavetable_preset"`,`"create_simpler_instrument"`,`"serum_clone"`; raises `ValueError` for unknown/invalid plans. This is what `server.py`'s `create_from_plan` uses to know which tool to call.
- Domain note: `recommend` accepts `domain` in `{"serum","sample","groove","device_preset","wavetable","simpler"}`. For `wavetable`/`simpler` the catalog has no rows yet (they are Ableton device presets), so similarity runs against `device_preset` rows; document this mapping in the docstring.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_catalog_decide.py
import pytest
from ableton_mcp_max import catalog_db, catalog_decide


def _seed_serum(conn, names):
    for n in names:
        conn.execute(
            "INSERT INTO items(domain,name,path,source,folder,loadable,tags,"
            "indexed_at) VALUES('serum',?,?,'user','Bass',1,?,1.0)",
            (n, "/s/%s.SerumPreset" % n, "bass"))
    conn.commit()


def test_recommend_reuse_when_strong_match(tmp_path):
    conn = catalog_db.open_db(str(tmp_path / "c.db"))
    _seed_serum(conn, ["Deep Sub Bass"])
    r = catalog_decide.recommend(conn, "deep sub bass", "serum")
    assert r["decision"] == "reuse"
    assert r["create_plan"] is None
    assert r["top_matches"][0]["name"] == "Deep Sub Bass"


def test_recommend_create_when_no_match_serum(tmp_path):
    conn = catalog_db.open_db(str(tmp_path / "c.db"))
    _seed_serum(conn, ["Bright Lead"])
    r = catalog_decide.recommend(conn, "wobble reese growl", "serum")
    assert r["decision"] == "create"
    assert r["create_plan"]["tool"] == "serum_clone"


def test_recommend_gap_for_samples(tmp_path):
    conn = catalog_db.open_db(str(tmp_path / "c.db"))
    r = catalog_decide.recommend(conn, "vinyl crackle texture", "sample")
    assert r["decision"] == "gap"
    assert r["create_plan"] is None


def test_resolve_dispatch():
    d = catalog_decide.resolve_dispatch(
        {"tool": "create_wavetable_preset", "params": {"name": "X", "table1": "Basics"}})
    assert d["creator"] == "create_wavetable_preset"
    assert d["kwargs"]["name"] == "X"
    with pytest.raises(ValueError):
        catalog_decide.resolve_dispatch({"tool": "nope", "params": {}})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_catalog_decide.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'ableton_mcp_max.catalog_decide'`

- [ ] **Step 3: Write the implementation**

```python
# ableton_mcp_max/catalog_decide.py
"""Decision engine: reuse-vs-create over the catalog, plus dispatch resolution.

Propose only - recommend() never writes. resolve_dispatch() maps a create plan to
the existing creator server.py should call; the actual invocation lives in
server.py (it needs the Ableton connection).
"""
from ableton_mcp_max import catalog_query

REUSE_MIN_SCORE = 2

_CREATABLE = {"serum", "wavetable", "simpler"}
# domains whose similarity runs against device_preset rows
_QUERY_DOMAIN = {"wavetable": "device_preset", "simpler": "device_preset"}
_VALID_CREATORS = {"create_wavetable_preset", "create_simpler_instrument",
                   "serum_clone"}


def _make_plan(domain, intent, top):
    name = (intent or "Untitled").strip()[:48] or "Untitled"
    if domain == "serum":
        base = top[0]["path"] if top else None
        return {"tool": "serum_clone", "params": {"name": name},
                "base_preset": base}
    if domain == "wavetable":
        return {"tool": "create_wavetable_preset",
                "params": {"name": name, "table1": "Basics"}, "base_preset": None}
    if domain == "simpler":
        return {"tool": "create_simpler_instrument",
                "params": {"name": name, "sample_path": None}, "base_preset": None}
    return None


def recommend(conn, intent, domain):
    qdomain = _QUERY_DOMAIN.get(domain, domain)
    matches = catalog_query.find_similar(conn, intent, qdomain, limit=5)
    top = matches
    top_score = top[0]["score"] if top else 0
    if top_score >= REUSE_MIN_SCORE:
        return {"decision": "reuse", "top_matches": top, "create_plan": None,
                "reason": "Top match scored %d (>= %d)." % (top_score, REUSE_MIN_SCORE)}
    if domain in _CREATABLE:
        return {"decision": "create", "top_matches": top,
                "create_plan": _make_plan(domain, intent, top),
                "reason": "No match scored >= %d; proposing a new %s."
                          % (REUSE_MIN_SCORE, domain)}
    return {"decision": "gap", "top_matches": top, "create_plan": None,
            "reason": "No match and %s assets cannot be synthesized." % domain}


def resolve_dispatch(plan):
    if not isinstance(plan, dict):
        raise ValueError("plan must be an object")
    tool = plan.get("tool")
    if tool not in _VALID_CREATORS:
        raise ValueError("unknown create tool: %r (valid: %s)"
                         % (tool, ", ".join(sorted(_VALID_CREATORS))))
    params = plan.get("params") or {}
    if not isinstance(params, dict):
        raise ValueError("plan.params must be an object")
    out = {"creator": tool, "kwargs": dict(params)}
    if tool == "serum_clone":
        base = plan.get("base_preset")
        if not base:
            raise ValueError("serum_clone requires base_preset")
        out["kwargs"]["base_preset"] = base
        if plan.get("fx_edits"):
            out["kwargs"]["fx_edits"] = plan["fx_edits"]
    return out
```

**Baseless-serum-plan note:** when `recommend` finds zero FTS candidates for a novel
Serum intent, `create_plan.base_preset` is `None`. `resolve_dispatch` then raises
`serum_clone requires base_preset`, which `create_from_plan` surfaces as a clear
error (in both dry-run and confirm) telling the caller to pick a base via
`search_catalog` and fill `base_preset` in. This is intended v1 behavior, not a bug.
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_catalog_decide.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/catalog_decide.py tests/test_catalog_decide.py
git commit -m "feat: catalog_decide - reuse-vs-create recommend + dispatch"
```

---

### Task 7: server.py - DB wiring + query/maintenance tools

**Files:**
- Modify: `ableton_mcp_max/server.py` (imports near line 147; new tools + helpers in a new section)
- Test: `tests/test_server_catalog_tools.py`

**Interfaces:**
- Consumes: `catalog_db`, `catalog_index`, `catalog_query`, `_sample_search_roots`, `_groove_search_roots`, `_user_library_dir`, `_app_core`, `get_ableton_connection`, `_ok`, `_err`.
- Produces (module-level in server.py):
  - `_catalog_conn() -> sqlite3.Connection` (opens via `catalog_db.open_db()`; cached in a module global `_catalog_db_conn`)
  - `_serum_roots() -> [(path, source)]` (factory `/Library/Audio/Presets/Xfer Records/Serum 2 Presets/Presets` + user `~/Music/Serum/Presets` if present; only existing dirs)
  - `_browser_reader(path) -> dict` (wraps `get_ableton_connection().send_command("get_browser_presets", {"path": path, "max_depth": 6})`)
  - `_ensure_catalog_fresh(conn, domains)` (per-domain: if any root changed, reindex it; 60s in-process throttle via `_catalog_checked` dict)
  - Tools: `search_catalog`, `catalog_stats`, `find_similar`, `reindex_catalog`
- Tool count after this task: +4.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_server_catalog_tools.py
import json
import os
import importlib


def _fresh_server(tmp_path, monkeypatch):
    monkeypatch.setenv("ABLETON_MCP_CATALOG_DB", str(tmp_path / "c.db"))
    import ableton_mcp_max.server as server
    importlib.reload(server)
    # reset cached connection
    server._catalog_db_conn = None
    return server


def test_search_catalog_tool_reads_db(tmp_path, monkeypatch):
    server = _fresh_server(tmp_path, monkeypatch)
    conn = server._catalog_conn()
    conn.execute(
        "INSERT INTO items(domain,name,path,source,folder,loadable,tags,"
        "indexed_at) VALUES('serum','Deep Sub','/s/Deep Sub.SerumPreset','user',"
        "'Bass',1,'bass',1.0)")
    conn.commit()
    # call the underlying function (tools are plain funcs decorated by FastMCP)
    out = json.loads(server.search_catalog.fn(None, "deep", domains=["serum"]))
    assert out["ok"] is True
    assert out["data"]["items"][0]["name"] == "Deep Sub"


def test_catalog_stats_tool(tmp_path, monkeypatch):
    server = _fresh_server(tmp_path, monkeypatch)
    out = json.loads(server.catalog_stats.fn(None))
    assert out["ok"] is True
    assert "by_domain" in out["data"]
```

Note: FastMCP exposes the wrapped function as `.fn`. If the project's FastMCP version differs, the implementer should confirm the attribute (`.fn` in `mcp>=1.3.0`) and adjust the test accessor accordingly - this is the only place tests reach into a tool.

- [ ] **Step 2: Run test to verify it fails**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_server_catalog_tools.py -q`
Expected: FAIL with `AttributeError: module 'ableton_mcp_max.server' has no attribute 'search_catalog'`

- [ ] **Step 3: Write the implementation**

Add imports after line 147 (`from ableton_mcp_max import serum_fx_catalog as _sfxcat`):

```python
from ableton_mcp_max import catalog_db as _cat_db
from ableton_mcp_max import catalog_index as _cat_index
from ableton_mcp_max import catalog_query as _cat_query
from ableton_mcp_max import catalog_decide as _cat_decide
```

Add a new section (place near the existing sample/groove tools):

```python
# --- Local catalog -------------------------------------------------------
_catalog_db_conn = None
_catalog_checked = {}
_CATALOG_THROTTLE_S = 60
_SERUM_FACTORY = ("/Library/Audio/Presets/Xfer Records/Serum 2 Presets/Presets")


def _catalog_conn():
    global _catalog_db_conn
    if _catalog_db_conn is None:
        _catalog_db_conn = _cat_db.open_db()
    return _catalog_db_conn


def _serum_roots():
    roots = []
    if os.path.isdir(_SERUM_FACTORY):
        roots.append((_SERUM_FACTORY, "factory"))
    user = os.path.expanduser("~/Music/Serum/Presets")
    if os.path.isdir(user):
        roots.append((user, "user"))
    return roots


def _browser_reader(path):
    return get_ableton_connection().send_command(
        "get_browser_presets", {"path": path, "max_depth": 6})


def _ensure_catalog_fresh(conn, domains):
    """Reindex any changed roots for the given domains, honoring a per-root
    in-process throttle. Never raises - freshness is best-effort."""
    now = time.time()
    try:
        if "serum" in domains:
            for root, src in _serum_roots():
                key = ("serum", root, src)
                if now - _catalog_checked.get(key, 0) < _CATALOG_THROTTLE_S:
                    continue
                _catalog_checked[key] = now
                if _cat_index.root_changed(conn, root, "serum", src):
                    _cat_index.index_serum(conn, [(root, src)])
        if "sample" in domains:
            for root, src in _sample_search_roots(["factory", "user"]):
                key = ("sample", root, src)
                if now - _catalog_checked.get(key, 0) < _CATALOG_THROTTLE_S:
                    continue
                _catalog_checked[key] = now
                if _cat_index.root_changed(conn, root, "sample", src):
                    _cat_index.index_samples(conn, [(root, src)])
        if "groove" in domains:
            for root, src in _groove_search_roots(["factory", "user"]):
                key = ("groove", root, src)
                if now - _catalog_checked.get(key, 0) < _CATALOG_THROTTLE_S:
                    continue
                _catalog_checked[key] = now
                if _cat_index.root_changed(conn, root, "groove", src):
                    _cat_index.index_grooves(conn, [(root, src)])
    except Exception as e:
        logger.error("catalog freshness check failed: %s", e)


@mcp.tool()
def search_catalog(ctx: Context, query: str, domains: list = None,
                   kinds: list = None, sources: list = None,
                   limit: int = 50) -> str:
    """Search the local content catalog (Serum presets, samples, grooves, device
    presets) by name/folder/tags. Fast persistent index; auto-refreshes changed
    filesystem roots. Returns {ok, data:{count, returned, truncated, items}}."""
    try:
        conn = _catalog_conn()
        want = domains or ["serum", "sample", "groove", "device_preset"]
        _ensure_catalog_fresh(conn, [d for d in want
                                     if d in ("serum", "sample", "groove")])
        data = _cat_query.search_catalog(conn, query, domains=domains,
                                         kinds=kinds, sources=sources, limit=limit)
        return _ok(data)
    except Exception as e:
        logger.error("search_catalog error: %s", e)
        return _err("search_catalog error: %s" % e)


@mcp.tool()
def catalog_stats(ctx: Context) -> str:
    """Counts and freshness for the local catalog by domain/source/kind, plus
    per-root last-indexed times. Returns {ok, data:{total, by_domain, by_source,
    by_kind, roots, device_presets_last_indexed}}."""
    try:
        conn = _catalog_conn()
        return _ok(_cat_query.catalog_stats(conn))
    except Exception as e:
        logger.error("catalog_stats error: %s", e)
        return _err("catalog_stats error: %s" % e)


@mcp.tool()
def find_similar(ctx: Context, intent: str, domain: str, limit: int = 10) -> str:
    """Rank catalog assets in one domain by lexical similarity to an intent
    string, with scores. domain in serum|sample|groove|device_preset. Returns
    {ok, data:{items:[{name, path, uri, source, folder, kind, score}]}}."""
    try:
        conn = _catalog_conn()
        if domain in ("serum", "sample", "groove"):
            _ensure_catalog_fresh(conn, [domain])
        hits = _cat_query.find_similar(conn, intent, domain, limit=limit)
        return _ok({"count": len(hits), "items": hits})
    except Exception as e:
        logger.error("find_similar error: %s", e)
        return _err("find_similar error: %s" % e)


@mcp.tool()
def reindex_catalog(ctx: Context, domains: list = None,
                    full: bool = False) -> str:
    """Rebuild the catalog. domains defaults to all. full=True drops and rebuilds
    from scratch. Device presets reindex only when Live is connected. Returns
    {ok, data:{indexed:{domain:count}, errors:[...]}}."""
    try:
        conn = _catalog_conn()
        want = domains or ["serum", "sample", "groove", "device_preset"]
        if full:
            _cat_db.rebuild(conn)
            _catalog_checked.clear()
        indexed, errors = {}, []
        if "serum" in want:
            indexed["serum"] = _cat_index.index_serum(conn, _serum_roots())
        if "sample" in want:
            indexed["sample"] = _cat_index.index_samples(
                conn, _sample_search_roots(["factory", "user"]))
        if "groove" in want:
            indexed["groove"] = _cat_index.index_grooves(
                conn, _groove_search_roots(["factory", "user"]))
        if "device_preset" in want:
            try:
                indexed["device_preset"] = _cat_index.index_device_presets(
                    conn, _browser_reader, ["instruments", "audio_effects"])
            except Exception as e:
                errors.append("device_preset: %s (Live connected?)" % e)
        return _ok({"indexed": indexed, "errors": errors})
    except Exception as e:
        logger.error("reindex_catalog error: %s", e)
        return _err("reindex_catalog error: %s" % e)
```

- [ ] **Step 4: Run tests + server import**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_server_catalog_tools.py -q && uv run python -c "import ableton_mcp_max.server"`
Expected: PASS (2 passed) and clean import.

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/server.py tests/test_server_catalog_tools.py
git commit -m "feat: catalog query/maintenance MCP tools + DB wiring"
```

---

### Task 8: server.py - recommend_asset + create_from_plan orchestration

**Files:**
- Modify: `ableton_mcp_max/server.py` (append to the catalog section)
- Test: `tests/test_server_catalog_orchestrate.py`

**Interfaces:**
- Consumes: `catalog_decide.recommend`/`resolve_dispatch`, the existing `create_wavetable_preset`/`create_simpler_instrument` tool functions, `_ok`/`_err`.
- Produces:
  - `recommend_asset(ctx, intent, domain) -> str` (wraps `catalog_decide.recommend`)
  - `_serum_clone_impl(base_preset, name, fx_edits=None) -> dict` (copy a base `.SerumPreset` into the User Serum presets dir under `<name>.SerumPreset`; if `fx_edits` is given - a list of `{"rack","slot","kparam","native"}` - decode the clone, apply each via `serum_fx_utils.set_fx_param`, and re-encode via the codec; return `{"written":True,"path":dest,"base":base_preset,"fx_edits_applied":int}`; raise `FileNotFoundError` if base missing)
  - `create_from_plan(ctx, plan, confirm=False) -> str` (confirm=False -> dry-run echo of resolved dispatch; confirm=True -> invoke the resolved creator and return its result)
- Tool count after this task: +2 (total +6 across the feature).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_server_catalog_orchestrate.py
import json
import importlib


def _server(tmp_path, monkeypatch):
    monkeypatch.setenv("ABLETON_MCP_CATALOG_DB", str(tmp_path / "c.db"))
    import ableton_mcp_max.server as server
    importlib.reload(server)
    server._catalog_db_conn = None
    return server


def test_create_from_plan_dry_run_does_not_write(tmp_path, monkeypatch):
    server = _server(tmp_path, monkeypatch)
    plan = {"tool": "create_wavetable_preset",
            "params": {"name": "Test", "table1": "Basics"}}
    out = json.loads(server.create_from_plan.fn(None, plan, confirm=False))
    assert out["ok"] is True
    assert out["data"]["dry_run"] is True
    assert out["data"]["would_call"] == "create_wavetable_preset"


def test_create_from_plan_bad_plan(tmp_path, monkeypatch):
    server = _server(tmp_path, monkeypatch)
    out = json.loads(server.create_from_plan.fn(None, {"tool": "nope"}, confirm=True))
    assert out["ok"] is False


def test_serum_clone_impl_copies(tmp_path, monkeypatch):
    server = _server(tmp_path, monkeypatch)
    base = tmp_path / "base.SerumPreset"
    base.write_bytes(b"XferJson-bytes")
    monkeypatch.setattr(server, "_user_serum_presets_dir",
                        lambda: str(tmp_path / "out"))
    res = server._serum_clone_impl(str(base), "My Clone")
    assert res["written"] is True
    with open(res["path"], "rb") as f:
        assert f.read() == b"XferJson-bytes"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_server_catalog_orchestrate.py -q`
Expected: FAIL with `AttributeError: ... has no attribute 'create_from_plan'`

- [ ] **Step 3: Write the implementation (append to the catalog section)**

```python
def _user_serum_presets_dir():
    """Where serum_clone writes new presets. Prefer ~/Music/Serum/Presets/User,
    creating it if the Serum tree exists; else the User Library."""
    base = os.path.expanduser("~/Music/Serum/Presets")
    dest = os.path.join(base, "User") if os.path.isdir(base) else \
        os.path.join(_user_library_dir(), "Serum Presets")
    return dest


def _serum_clone_impl(base_preset, name, fx_edits=None):
    if not base_preset or not os.path.isfile(base_preset):
        raise FileNotFoundError("base preset not found: %r" % base_preset)
    out_dir = _user_serum_presets_dir()
    os.makedirs(out_dir, exist_ok=True)
    safe = re.sub(r'[\\/:*?"<>|]', "_", name or "Untitled").strip() or "Untitled"
    dest = os.path.join(out_dir, safe + ".SerumPreset")
    blob = open(base_preset, "rb").read()
    applied = 0
    if fx_edits:
        catalog = _sfxcat.load_catalog()
        state = _ssc.decode(blob)
        tree = state.tree
        for e in fx_edits:
            _sfx.set_fx_param(catalog, tree, e["rack"], e["slot"],
                              e["kparam"], e["native"])
            applied += 1
        blob = _ssc.encode(state, tree)
    with open(dest, "wb") as f:
        f.write(blob)
    return {"written": True, "path": dest, "base": base_preset,
            "fx_edits_applied": applied}


@mcp.tool()
def recommend_asset(ctx: Context, intent: str, domain: str) -> str:
    """Propose reuse-vs-create for a described asset. domain in
    serum|sample|groove|device_preset|wavetable|simpler. Returns {ok, data:
    {decision, top_matches, create_plan, reason}}. PROPOSE ONLY - never writes;
    pass create_plan to create_from_plan(confirm=True) to act on a 'create'."""
    try:
        conn = _catalog_conn()
        qd = domain if domain in ("serum", "sample", "groove",
                                  "device_preset") else "device_preset"
        if qd in ("serum", "sample", "groove"):
            _ensure_catalog_fresh(conn, [qd])
        return _ok(_cat_decide.recommend(conn, intent, domain))
    except Exception as e:
        logger.error("recommend_asset error: %s", e)
        return _err("recommend_asset error: %s" % e)


@mcp.tool()
def create_from_plan(ctx: Context, plan: dict, confirm: bool = False) -> str:
    """Execute a create_plan from recommend_asset. confirm=False (default)
    returns a dry-run describing what would be created and writes nothing.
    confirm=True invokes the matching creator (Wavetable, Simpler, or a Serum
    base-preset clone). Returns {ok, data:{...}}."""
    try:
        dispatch = _cat_decide.resolve_dispatch(plan)
    except ValueError as e:
        return _err("invalid plan: %s" % e)
    creator, kwargs = dispatch["creator"], dispatch["kwargs"]
    if not confirm:
        return _ok({"dry_run": True, "would_call": creator, "kwargs": kwargs})
    try:
        if creator == "create_wavetable_preset":
            return create_wavetable_preset.fn(ctx, **kwargs)
        if creator == "create_simpler_instrument":
            return create_simpler_instrument.fn(ctx, **kwargs)
        if creator == "serum_clone":
            res = _serum_clone_impl(kwargs.get("base_preset"),
                                    kwargs.get("name"),
                                    fx_edits=kwargs.get("fx_edits"))
            return _ok(res)
        return _err("unhandled creator: %s" % creator)
    except Exception as e:
        logger.error("create_from_plan error: %s", e)
        return _err("create_from_plan error: %s" % e)
```

Note: `create_wavetable_preset.fn` / `create_simpler_instrument.fn` calls assume the FastMCP `.fn` accessor confirmed in Task 7. If the running FastMCP wraps differently, call the underlying function the same way the test does.

- [ ] **Step 4: Run tests + server import**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_server_catalog_orchestrate.py -q && uv run python -c "import ableton_mcp_max.server"`
Expected: PASS (3 passed) and clean import.

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/server.py tests/test_server_catalog_orchestrate.py
git commit -m "feat: recommend_asset + create_from_plan orchestration"
```

---

### Task 9: server.py - delegate search_samples/search_grooves to the catalog

**Files:**
- Create: `ableton_mcp_max/catalog_adapt.py`
- Modify: `ableton_mcp_max/server.py` (`search_samples` body ~6025-6107, `search_grooves` body ~4633-4660)
- Test: `tests/test_catalog_adapt.py`

**Interfaces:**
- Consumes: catalog `items` rows.
- Produces (pure, in `catalog_adapt.py`):
  - `rows_to_sample_items(rows) -> list[dict]` -> exact `search_samples` item shape `{name, path, uri, kind, source, folder, is_icloud_placeholder}`
  - `rows_to_groove_items(rows) -> list[dict]` -> exact `search_grooves` item shape `{name, file, category, path, source, loadable}`
- `search_samples`/`search_grooves` keep identical signatures + return shapes; they try the catalog first and fall back to the existing live walk when the catalog is empty or errors.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_catalog_adapt.py
from ableton_mcp_max import catalog_adapt


def test_rows_to_sample_items():
    rows = [{"name": "Kick.wav", "path": "/x/Kick.wav", "kind": "one_shot",
             "source": "user", "folder": "Drums"}]
    out = catalog_adapt.rows_to_sample_items(rows)
    assert out[0] == {"name": "Kick.wav", "path": "/x/Kick.wav", "uri": None,
                      "kind": "one_shot", "source": "user", "folder": "Drums",
                      "is_icloud_placeholder": False}


def test_rows_to_groove_items():
    rows = [{"name": "Swing", "path": "/g/Funk/Swing.agr", "folder": "Funk",
             "source": "factory", "loadable": 1}]
    out = catalog_adapt.rows_to_groove_items(rows)
    assert out[0] == {"name": "Swing", "file": "Swing.agr", "category": "Funk",
                      "path": "/g/Funk/Swing.agr", "source": "factory",
                      "loadable": True}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_catalog_adapt.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'ableton_mcp_max.catalog_adapt'`

- [ ] **Step 3: Write the implementation**

```python
# ableton_mcp_max/catalog_adapt.py
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
```

Then modify `search_samples` - replace the body's walk section so it tries the catalog first (keep the existing walk as `_search_samples_live` fallback). Minimal change: wrap the existing logic in an inner function and add the catalog path at the top:

```python
@mcp.tool()
def search_samples(ctx: Context, query: str, kinds: list = None,
                   limit: int = 40, sources: list = None) -> str:
    """<keep existing docstring verbatim>"""
    kinds = kinds or ["loop", "one_shot", "kit", "instrument"]
    sources = sources or ["factory", "user"]
    try:
        conn = _catalog_conn()
        _ensure_catalog_fresh(conn, ["sample"])
        res = _cat_query.search_catalog(conn, query, domains=["sample"],
                                        kinds=kinds, sources=sources, limit=limit)
        if res["count"] > 0:
            items = catalog_adapt.rows_to_sample_items(res["items"])
            return _ok({"count": res["count"], "returned": len(items),
                        "truncated": res["truncated"], "items": items})
    except Exception as e:
        logger.error("search_samples catalog path failed, falling back: %s", e)
    return _search_samples_live(query, kinds, limit, sources)
```

Move the current walk body into a new module-level `_search_samples_live(query, kinds, limit, sources)` returning the same `_ok({...})`. Apply the equivalent pattern to `search_grooves` (catalog first via `domains=["groove"]` + `rows_to_groove_items`, fallback `_search_grooves_live`). Add `from ableton_mcp_max import catalog_adapt` to the imports.

- [ ] **Step 4: Run tests + import + full suite**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_catalog_adapt.py -q && uv run python -c "import ableton_mcp_max.server" && PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q`
Expected: PASS (the new tests + the entire existing suite green).

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/catalog_adapt.py ableton_mcp_max/server.py tests/test_catalog_adapt.py
git commit -m "feat: search_samples/search_grooves delegate to catalog with live fallback"
```

---

### Task 10: Docs, tool index, version bump

**Files:**
- Modify: `scripts/build_tool_index.py` (add a "Catalog" GROUPS entry), `scripts/gen_docs_site.py` (add a "Catalog" CATEGORIES entry)
- Modify: `pyproject.toml` (version), `.claude-plugin/plugin.json` (version), `uv.lock` (via `uv lock`)
- Modify: `docs/index.md` (5 hardcoded counts), `README.md` (1 hardcoded count)
- Modify: `PROGRESS.md` (append a Catalog section)
- Generated: `docs/tools/*.md`, `docs/tools/index.md`, `commands/tool-index.md`

**Interfaces:** none (build/docs only).

- [ ] **Step 1: Add the new tools to both regen scripts**

In `scripts/build_tool_index.py` GROUPS, add after the "Plugins (VST/AU)" entry:

```python
    ("Catalog", [
        "search_catalog", "find_similar", "catalog_stats", "reindex_catalog",
        "recommend_asset", "create_from_plan",
    ]),
```

In `scripts/gen_docs_site.py` CATEGORIES, add:

```python
    ("catalog", "Catalog", "Persistent local index of Serum presets, samples, "
     "grooves, and device presets, with similarity search and reuse-vs-create "
     "recommendation that can orchestrate the existing create tools.", [
        "search_catalog", "find_similar", "catalog_stats", "reindex_catalog",
        "recommend_asset", "create_from_plan",
    ]),
```

- [ ] **Step 2: Run the regen scripts (they assert every tool is filed)**

Run:
```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python scripts/build_tool_index.py
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python scripts/gen_docs_site.py
```
Expected: `Wrote .../commands/tool-index.md (161 tools)` and `Generated 161 tools across 22 categories into docs/tools/`. If either script raises "Tools missing from GROUPS", a tool name is mismatched - fix the script entry to match the `@mcp.tool()` name exactly.

- [ ] **Step 3: Bump version (3 files) + hardcoded counts**

- `pyproject.toml`: `version = "0.26.0"`
- `.claude-plugin/plugin.json`: matching `"version": "0.26.0"`
- Run `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv lock` to sync `uv.lock`.
- `docs/index.md`: replace the 5 hardcoded `150`/`155` tool counts with `161` (description, tagline, two `stats__num`, the "exposes the N `@mcp.tool()`" line) and bump the category count to `22`.
- `README.md:7`: replace the hardcoded "reference for all N tools" count with `161`.

Verify nothing stale remains:
```bash
grep -rn "155 tools\|150 tools\|reference for all 1" README.md docs/index.md || echo "counts clean"
```
Expected: `counts clean` (or only intended matches).

- [ ] **Step 4: Update PROGRESS.md + run full gate**

Append a short "Local catalog shipped" section to `PROGRESS.md` (date 2026-06-28, 161 tools, new Catalog category, the 6 tools, "next action: live verification"). Then:
```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q
uv run python -c "import ableton_mcp_max.server"
uv run python -m py_compile remote_script/AbletonMCP/__init__.py
```
Expected: full suite green, clean import, py_compile OK.

- [ ] **Step 5: Commit**

```bash
git add scripts/build_tool_index.py scripts/gen_docs_site.py pyproject.toml \
  .claude-plugin/plugin.json uv.lock docs/ README.md commands/tool-index.md \
  PROGRESS.md
git commit -m "docs: catalog tools, regen tool index, bump to v0.26.0 (161 tools)"
```

---

## Post-Plan: Live Verification (manual, before PR merge)

Not a coding task - run against the open Live set and record in PROGRESS.md:
1. `reindex_catalog(full=True)` with Live running; confirm `indexed` counts for all four domains and no `device_preset` error.
2. `catalog_stats` shows nonzero domains + recent `last_indexed`.
3. `search_catalog("deep bass", domains=["serum"])` returns real presets; `search_samples`/`search_grooves` still return their legacy shapes (now catalog-backed).
4. `recommend_asset("warm analog pad","serum")` -> a decision; for a `create`, `create_from_plan(plan, confirm=False)` dry-run, then `confirm=True` writes a `.SerumPreset` clone to the User Serum dir.
5. `create_from_plan` for a Wavetable plan creates a preset via the existing tool.

## Ship (after live verification)

Per CLAUDE.md: branch `feat/local-catalog` -> PR -> `gh pr merge --squash --delete-branch` (verify `gh api user --jq .login` == `ringo380` first) -> `gh release create v0.26.0` -> bump marketplace `ableton` `ref` to `v0.26.0` -> `node scripts/build-readme.js` in the marketplace repo -> push. Verify chain: local main = origin/main = `git ls-remote --tags origin v0.26.0` = marketplace `ref`.
