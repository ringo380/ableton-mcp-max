import json
import ableton_mcp_max.server as server


def test_populate_drum_rack_loads_all(monkeypatch):
    # Stub the single-pad loader to succeed and record calls.
    seen = []
    def fake_pad(ctx, track_index, pad_note, sample_path):
        seen.append((track_index, pad_note, sample_path))
        return json.dumps({"ok": True, "data": {"track_index": track_index,
                          "pad_note": pad_note, "sample": sample_path, "loaded": True}})
    monkeypatch.setattr(server, "load_sample_to_drum_pad", fake_pad)

    mapping = [
        {"pad_note": 36, "sample_path": "/s/Kick.wav"},
        {"pad_note": 38, "sample_path": "/s/Snare.wav"},
    ]
    out = json.loads(server.populate_drum_rack(ctx=None, track_index=1, mapping=mapping))
    assert out["ok"] is True
    d = out["data"]
    assert d["loaded_count"] == 2
    assert len(d["results"]) == 2
    assert all(r["status"] == "loaded" for r in d["results"])
    assert len(seen) == 2


def test_populate_drum_rack_partial_failure(monkeypatch):
    def fake_pad(ctx, track_index, pad_note, sample_path):
        if pad_note == 40:
            return json.dumps({"ok": False, "error": "undownloaded iCloud placeholder"})
        return json.dumps({"ok": True, "data": {"loaded": True}})
    monkeypatch.setattr(server, "load_sample_to_drum_pad", fake_pad)

    mapping = [
        {"pad_note": 36, "sample_path": "/s/Kick.wav"},
        {"pad_note": 40, "sample_path": "/s/Clap.wav"},  # fails
    ]
    out = json.loads(server.populate_drum_rack(ctx=None, track_index=1, mapping=mapping))
    assert out["ok"] is True   # the call itself succeeds; per-entry failures are reported
    d = out["data"]
    assert d["loaded_count"] == 1
    statuses = {r["pad_note"]: r["status"] for r in d["results"]}
    assert statuses[36] == "loaded"
    assert statuses[40] == "error"
    err_entry = next(r for r in d["results"] if r["pad_note"] == 40)
    assert "error" in err_entry


def test_populate_drum_rack_bad_mapping_entry():
    out = json.loads(server.populate_drum_rack(
        ctx=None, track_index=1, mapping=[{"sample_path": "/s/x.wav"}]))  # missing pad_note
    assert out["ok"] is False
