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
    """Drop everything and recreate from scratch. Drops the known objects
    explicitly: dropping items_fts cascades its FTS5 shadow tables, and
    dropping a table drops its triggers."""
    for stmt in ("DROP TABLE IF EXISTS items_fts",
                 "DROP TABLE IF EXISTS items",
                 "DROP TABLE IF EXISTS roots",
                 "DROP TABLE IF EXISTS meta"):
        conn.execute(stmt)
    conn.commit()
    _create(conn)


def _schema_ok(conn):
    try:
        row = conn.execute(
            "SELECT value FROM meta WHERE key='schema_version'").fetchone()
        return row is not None and int(row[0]) == SCHEMA_VERSION
    except (sqlite3.DatabaseError, ValueError, TypeError):
        return False


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
