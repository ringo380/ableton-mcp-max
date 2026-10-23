import time

from ableton_mcp_max import catalog_db, catalog_index


def test_fingerprint_changes_when_file_added(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "a.wav").write_bytes(b"x")
    fp1 = catalog_index.fingerprint_root(str(tmp_path))
    # Windows stamps directory mtimes from a ~15.6ms clock tick, so two writes
    # in the same tick leave sub/'s mtime unchanged. Real libraries change
    # seconds apart; step past one tick so the test is deterministic.
    time.sleep(0.05)
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
