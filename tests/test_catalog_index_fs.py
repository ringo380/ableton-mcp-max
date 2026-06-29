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
    # encode() calls state.meta["hash"] and replaces it in meta_bytes, so we
    # must include a placeholder hash (32 hex chars = md5 length).
    meta = {"product": "Serum2", "name": os.path.basename(path),
            "hash": "0" * 32}
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
