# tests/test_search_samples.py
import json
import os
import ableton_mcp_max.server as server


def _make_tree(root):
    """Build a small fake sample library under root."""
    files = {
        "Samples/Drums/Kicks/Kick Deep 01.wav": b"RIFF",
        "Samples/Drums/Snares/Snare Tight.wav": b"RIFF",
        "Samples/Loops/Drum Loop 120 bpm.wav": b"RIFF",
        "Presets/Instruments/Wavetable/Dark Pad.adv": b"x",
        "Drums/Kits/Acoustic Kit.adg": b"x",
        "readme.txt": b"x",  # non-sample, must be ignored
    }
    for rel, data in files.items():
        p = os.path.join(root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(data)


def test_search_samples_finds_by_name(tmp_path, monkeypatch):
    root = str(tmp_path / "user")
    _make_tree(root)
    monkeypatch.setattr(server, "_sample_search_roots", lambda sources: [(root, "user")])

    out = json.loads(server.search_samples(ctx=None, query="kick"))
    assert out["ok"] is True
    d = out["data"]
    names = [i["name"] for i in d["items"]]
    assert any("Kick Deep" in n for n in names)
    # snare/loop/adv should not match "kick"
    assert not any("Snare" in n for n in names)


def test_search_samples_classifies(tmp_path, monkeypatch):
    root = str(tmp_path / "user")
    _make_tree(root)
    monkeypatch.setattr(server, "_sample_search_roots", lambda sources: [(root, "user")])

    out = json.loads(server.search_samples(ctx=None, query="", limit=100))
    d = out["data"]
    by_name = {i["name"]: i for i in d["items"]}
    assert by_name["Kick Deep 01.wav"]["kind"] == "one_shot"
    assert by_name["Drum Loop 120 bpm.wav"]["kind"] == "loop"
    assert by_name["Dark Pad.adv"]["kind"] == "instrument"
    assert by_name["Acoustic Kit.adg"]["kind"] == "kit"
    # the .txt is not an enumerated sample
    assert "readme.txt" not in by_name


def test_search_samples_kind_filter(tmp_path, monkeypatch):
    root = str(tmp_path / "user")
    _make_tree(root)
    monkeypatch.setattr(server, "_sample_search_roots", lambda sources: [(root, "user")])

    out = json.loads(server.search_samples(ctx=None, query="", kinds=["loop"], limit=100))
    d = out["data"]
    assert all(i["kind"] == "loop" for i in d["items"])
    assert len(d["items"]) >= 1


def test_search_samples_limit_and_truncation(tmp_path, monkeypatch):
    root = str(tmp_path / "user")
    _make_tree(root)
    monkeypatch.setattr(server, "_sample_search_roots", lambda sources: [(root, "user")])

    out = json.loads(server.search_samples(ctx=None, query="", limit=2))
    d = out["data"]
    assert d["returned"] == 2
    assert d["count"] >= 2
    assert d["truncated"] is True


def test_search_samples_flags_icloud_placeholder(tmp_path, monkeypatch):
    root = str(tmp_path / "user")
    d = os.path.join(root, "Samples", "Drums")
    os.makedirs(d, exist_ok=True)
    # only the stub exists (dataless): .Kick.wav.icloud, no real Kick.wav
    with open(os.path.join(d, ".Kick.wav.icloud"), "wb") as f:
        f.write(b"")
    monkeypatch.setattr(server, "_sample_search_roots", lambda sources: [(root, "user")])

    out = json.loads(server.search_samples(ctx=None, query="kick", limit=100))
    items = out["data"]["items"]
    kick = next(i for i in items if i["name"] == "Kick.wav")
    assert kick["is_icloud_placeholder"] is True
    assert kick["path"].endswith("/Samples/Drums/Kick.wav")
