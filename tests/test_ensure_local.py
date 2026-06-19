import os
import pytest
import ableton_mcp_max.server as server


def test_ensure_local_already_local(tmp_path):
    real = tmp_path / "Kick.wav"
    real.write_bytes(b"RIFF")
    assert server._ensure_local(str(real)) == str(real)


def test_ensure_local_downloads_placeholder(tmp_path, monkeypatch):
    target = tmp_path / "Kick.wav"
    stub = tmp_path / ".Kick.wav.icloud"
    stub.write_bytes(b"")  # dataless placeholder present, real file absent

    # Simulate brctl: when called, materialize the real file + remove the stub.
    def fake_run(args, **kw):
        target.write_bytes(b"RIFF")
        if stub.exists():
            stub.unlink()
        class _R:
            returncode = 0
        return _R()

    monkeypatch.setattr(server.subprocess, "run", fake_run)
    monkeypatch.setattr(server.time, "sleep", lambda s: None)
    assert server._ensure_local(str(target), timeout=5) == str(target)


def test_ensure_local_timeout_raises(tmp_path, monkeypatch):
    target = tmp_path / "Kick.wav"
    stub = tmp_path / ".Kick.wav.icloud"
    stub.write_bytes(b"")

    # brctl does nothing; the real file never appears -> timeout.
    def fake_run(args, **kw):
        class _R:
            returncode = 0
        return _R()

    monkeypatch.setattr(server.subprocess, "run", fake_run)
    monkeypatch.setattr(server.time, "sleep", lambda s: None)
    with pytest.raises(RuntimeError) as ei:
        server._ensure_local(str(target), timeout=1)
    assert "placeholder" in str(ei.value).lower()


def test_ensure_local_missing_no_stub_raises(tmp_path):
    # Neither a real file nor a stub: a plain missing path.
    with pytest.raises(RuntimeError):
        server._ensure_local(str(tmp_path / "Ghost.wav"), timeout=1)
