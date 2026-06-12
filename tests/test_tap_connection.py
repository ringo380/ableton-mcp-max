"""Offline tests for AudioTapConnection using a FakeSocket (no live device)."""
import json
import socket

import pytest

from ableton_mcp_max.tap_connection import AudioTapConnection


class FakeSocket:
    """Returns one framed JSON response; optionally fails on send/recv once."""

    def __init__(self, response=None, fail_on=None):
        if response is None:
            response = {"ok": True, "data": {"device": "mcp-audio-tap"}}
        self._payload = json.dumps(response).encode("utf-8")
        self.fail_on = fail_on
        self.sent = []
        self._sent_done = False
        self.closed = False

    def settimeout(self, _t):
        pass

    def connect(self, _addr):
        pass

    def sendall(self, data):
        if self.fail_on == "send":
            raise socket.error("send failed")
        self.sent.append(data)

    def recv(self, _n):
        if self.fail_on == "recv":
            raise socket.error("recv failed")
        if self._sent_done:
            return b""
        self._sent_done = True
        return self._payload

    def close(self):
        self.closed = True


def _conn_with(monkeypatch, **kwargs):
    conn = AudioTapConnection()
    fake = FakeSocket(**kwargs)
    monkeypatch.setattr(conn, "_open_socket", lambda: fake)
    return conn, fake


def test_send_returns_data(monkeypatch):
    conn, _ = _conn_with(monkeypatch)
    data = conn.send("ping")
    assert data["device"] == "mcp-audio-tap"


def test_send_frames_command_as_json(monkeypatch):
    conn, fake = _conn_with(monkeypatch)
    conn.send("read")
    assert json.loads(fake.sent[0].decode("utf-8")) == {"command": "read"}


def test_send_includes_params(monkeypatch):
    conn, fake = _conn_with(monkeypatch)
    conn.send("measure", {"seconds": 3})
    assert json.loads(fake.sent[0].decode("utf-8")) == {"command": "measure", "seconds": 3}


def test_device_error_raises(monkeypatch):
    conn, _ = _conn_with(monkeypatch, response={"ok": False, "error": "boom"})
    with pytest.raises(RuntimeError, match="boom"):
        conn.send("read")


def test_connect_failure_is_graceful(monkeypatch):
    conn = AudioTapConnection()

    def refuse():
        raise ConnectionRefusedError("nope")

    monkeypatch.setattr(conn, "_open_socket", refuse)
    assert conn.connect() is False
    with pytest.raises(ConnectionError):
        conn.send("ping")


def test_is_connected_true(monkeypatch):
    conn, _ = _conn_with(monkeypatch)
    assert conn.is_connected() is True


def test_is_connected_false(monkeypatch):
    conn = AudioTapConnection()

    def refuse():
        raise ConnectionRefusedError()

    monkeypatch.setattr(conn, "_open_socket", refuse)
    assert conn.is_connected() is False


def test_retry_reconnects_after_stale_send(monkeypatch):
    # First socket fails on send (stale); send() must reset, reconnect via a
    # fresh socket, and succeed - returning data, with both sockets consumed.
    conn = AudioTapConnection()
    sockets = [FakeSocket(fail_on="send"), FakeSocket()]
    monkeypatch.setattr(conn, "_open_socket", lambda: sockets.pop(0))
    data = conn.send("ping")
    assert data["device"] == "mcp-audio-tap"
    assert sockets == []


def test_two_failures_raise_connection_error(monkeypatch):
    # Both attempts fail on send -> ConnectionError (not the raw OSError).
    conn = AudioTapConnection()
    monkeypatch.setattr(conn, "_open_socket", lambda: FakeSocket(fail_on="send"))
    with pytest.raises(ConnectionError):
        conn.send("ping")


def test_device_error_does_not_retry(monkeypatch):
    # A device-reported {ok:false} raises RuntimeError immediately and must NOT
    # trigger a reconnect/retry (only one socket is ever opened).
    conn = AudioTapConnection()
    calls = []

    def make():
        sock = FakeSocket(response={"ok": False, "error": "boom"})
        calls.append(sock)
        return sock

    monkeypatch.setattr(conn, "_open_socket", make)
    with pytest.raises(RuntimeError, match="boom"):
        conn.send("read")
    assert len(calls) == 1
