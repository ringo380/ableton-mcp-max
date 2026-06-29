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
