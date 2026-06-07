"""Offline tests for the AbletonConnection transport layer (Phase A).

Uses a FakeSocket so send_command's framing, settle-delay, timeout, and
transparent-reconnect logic can be exercised without a live Ableton.
"""
import json
import re
import socket
import pathlib

import pytest

import ableton_mcp_max.server as server


class FakeSocket:
    """Minimal socket stand-in for receive_full_response/send_command.

    fail_on="send"  -> sendall raises (send-phase failure; nothing reached Live)
    fail_on="recv"  -> recv raises (recv-phase failure; command may have run)
    """

    def __init__(self, response=None, fail_on=None):
        if response is None:
            response = {"status": "success", "result": {"ok": True}}
        self.response = response
        self.fail_on = fail_on
        self.sent = []
        self._recv_done = False
        self.closed = False

    def sendall(self, data):
        if self.fail_on == "send":
            raise socket.error("send failed")
        self.sent.append(data)

    def settimeout(self, _t):
        pass

    def recv(self, _n):
        if self.fail_on == "recv":
            raise socket.error("recv failed")
        if self._recv_done:
            return b""
        self._recv_done = True
        return json.dumps(self.response).encode("utf-8")

    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def _no_settle(monkeypatch):
    # Don't actually sleep around mutating writes during tests.
    monkeypatch.setattr(server, "_SETTLE_DELAY", 0.0)


def _conn(sock):
    c = server.AbletonConnection(host="localhost", port=9877)
    c.sock = sock
    return c


def test_mutating_commands_in_sync_with_remote():
    """Guard against the server/remote mutation lists drifting (the original
    bug: 24 real mutations were missing from the server list)."""
    remote = (pathlib.Path(__file__).resolve().parents[1]
              / "remote_script" / "AbletonMCP" / "__init__.py")
    block = re.search(r"elif command_type in \[(.*?)\]:",
                      remote.read_text(), re.S).group(1)
    names = set(re.findall(r'"([a-z_]+)"', block))
    assert names == set(server.MUTATING_COMMANDS)


def test_mutate_timeout_exceeds_remote_task_timeout():
    assert server._MUTATE_TIMEOUT > server._REMOTE_TASK_TIMEOUT


def test_send_command_success_returns_result():
    conn = _conn(FakeSocket(response={"status": "success", "result": {"v": 9}}))
    assert conn.send_command("get_session_info") == {"v": 9}


def test_app_error_raises_without_reconnect(monkeypatch):
    conn = _conn(FakeSocket(response={"status": "error", "message": "boom"}))
    calls = {"n": 0}
    monkeypatch.setattr(conn, "connect",
                        lambda: calls.__setitem__("n", calls["n"] + 1) or True)
    with pytest.raises(Exception) as ei:
        conn.send_command("get_session_info")
    assert "boom" in str(ei.value)
    assert calls["n"] == 0  # app error != connection failure; no reconnect


def test_send_phase_failure_retries_even_for_mutation(monkeypatch):
    conn = _conn(FakeSocket(fail_on="send"))
    good = FakeSocket(response={"status": "success", "result": {"v": 1}})

    def fake_connect():
        conn.sock = good
        return True

    monkeypatch.setattr(conn, "connect", fake_connect)
    # set_tempo is a mutation, but a send-phase failure never reached Live,
    # so retrying is safe.
    assert conn.send_command("set_tempo", {"tempo": 120}) == {"v": 1}
    assert good.sent  # re-sent on the fresh socket


def test_recv_phase_failure_no_retry_for_mutation(monkeypatch):
    conn = _conn(FakeSocket(fail_on="recv"))
    calls = {"n": 0}

    def fake_connect():
        calls["n"] += 1
        conn.sock = FakeSocket(fail_on="recv")
        return True

    monkeypatch.setattr(conn, "connect", fake_connect)
    with pytest.raises(Exception):
        conn.send_command("create_scene", {})  # non-idempotent mutation
    assert calls["n"] == 0  # must NOT reconnect+retry (may have applied)


def test_recv_phase_failure_retries_for_read(monkeypatch):
    conn = _conn(FakeSocket(fail_on="recv"))
    good = FakeSocket(response={"status": "success", "result": {"r": 2}})

    def fake_connect():
        conn.sock = good
        return True

    monkeypatch.setattr(conn, "connect", fake_connect)
    # reads default idempotent=True → recv-phase failure is retried.
    assert conn.send_command("get_session_info") == {"r": 2}


def test_explicit_idempotent_override_retries_mutation(monkeypatch):
    conn = _conn(FakeSocket(fail_on="recv"))
    good = FakeSocket(response={"status": "success", "result": {"v": 3}})

    def fake_connect():
        conn.sock = good
        return True

    monkeypatch.setattr(conn, "connect", fake_connect)
    # Caller asserts this mutation is safe to retry.
    assert conn.send_command("set_tempo", {"tempo": 120},
                             idempotent=True) == {"v": 3}
