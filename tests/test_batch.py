"""Offline tests for the batch protocol (Phase B): batch_utils validation and
the AbletonConnection.send_batch transport path."""
import json
import socket

import pytest

import ableton_mcp_max.server as server
from ableton_mcp_max.batch_utils import (
    validate_batch, coerce_stop_on_error, MAX_BATCH_COMMANDS,
)

ALLOWED = {"set_tempo", "create_midi_track", "add_notes_to_clip"}


# --- validate_batch -------------------------------------------------------

def test_valid_batch_normalizes():
    out = validate_batch(
        [{"type": "set_tempo", "params": {"tempo": 120}},
         {"type": "create_midi_track"}],
        ALLOWED)
    assert out == [
        {"type": "set_tempo", "params": {"tempo": 120}},
        {"type": "create_midi_track", "params": {}},  # missing params -> {}
    ]


def test_empty_list_rejected():
    with pytest.raises(ValueError):
        validate_batch([], ALLOWED)


def test_non_list_rejected():
    with pytest.raises(ValueError):
        validate_batch({"type": "set_tempo"}, ALLOWED)


def test_too_large_rejected():
    big = [{"type": "set_tempo"}] * (MAX_BATCH_COMMANDS + 1)
    with pytest.raises(ValueError):
        validate_batch(big, ALLOWED)


def test_member_missing_type_rejected():
    with pytest.raises(ValueError):
        validate_batch([{"params": {}}], ALLOWED)


def test_nested_batch_rejected():
    with pytest.raises(ValueError) as ei:
        validate_batch([{"type": "batch", "params": {}}], ALLOWED)
    assert "nested" in str(ei.value)


def test_non_mutation_rejected():
    with pytest.raises(ValueError) as ei:
        validate_batch([{"type": "get_session_info"}], ALLOWED)
    assert "batchable" in str(ei.value) or "mutating" in str(ei.value)


def test_params_must_be_object():
    with pytest.raises(ValueError):
        validate_batch([{"type": "set_tempo", "params": 5}], ALLOWED)


def test_real_mutation_passes_against_server_set():
    # set_device_parameter is a genuine mutation in the production set.
    out = validate_batch(
        [{"type": "set_device_parameter",
          "params": {"track_index": 0, "device_index": 0,
                     "parameter_index": 1, "value": 0.5}}],
        server.MUTATING_COMMANDS)
    assert out[0]["type"] == "set_device_parameter"


def test_coerce_stop_on_error():
    assert coerce_stop_on_error(None) is True
    assert coerce_stop_on_error(False) is False
    assert coerce_stop_on_error(0) is False
    assert coerce_stop_on_error(1) is True


# --- send_batch transport -------------------------------------------------

class FakeSocket:
    def __init__(self, response, fail_on=None):
        self.response = response
        self.fail_on = fail_on
        self.sent = []
        self._done = False

    def sendall(self, data):
        if self.fail_on == "send":
            raise socket.error("send failed")
        self.sent.append(data)

    def settimeout(self, _t):
        pass

    def recv(self, _n):
        if self.fail_on == "recv":
            raise socket.error("recv failed")
        if self._done:
            return b""
        self._done = True
        return json.dumps(self.response).encode("utf-8")

    def close(self):
        pass


BATCH_RESULT = {
    "status": "success",
    "result": {"count": 2, "completed": 2, "failed_index": -1,
               "results": [{"status": "success", "result": {}},
                           {"status": "success", "result": {}}]},
}


@pytest.fixture(autouse=True)
def _no_settle(monkeypatch):
    monkeypatch.setattr(server, "_SETTLE_DELAY", 0.0)


def _conn(sock):
    c = server.AbletonConnection(host="localhost", port=9877)
    c.sock = sock
    return c


def test_send_batch_returns_result_and_sends_batch_type():
    sock = FakeSocket(BATCH_RESULT)
    conn = _conn(sock)
    res = conn.send_batch([{"type": "set_tempo", "params": {"tempo": 120}},
                           {"type": "create_midi_track", "params": {}}])
    assert res["completed"] == 2 and res["failed_index"] == -1
    wire = json.loads(sock.sent[0].decode("utf-8"))
    assert wire["type"] == "batch"
    assert wire["params"]["stop_on_error"] is True
    assert len(wire["params"]["commands"]) == 2


def test_send_batch_send_phase_failure_retries(monkeypatch):
    conn = _conn(FakeSocket(BATCH_RESULT, fail_on="send"))
    good = FakeSocket(BATCH_RESULT)

    def fake_connect():
        conn.sock = good
        return True

    monkeypatch.setattr(conn, "connect", fake_connect)
    res = conn.send_batch([{"type": "set_tempo", "params": {}}])
    assert res["completed"] == 2  # recovered on the fresh socket
    assert good.sent


def test_send_batch_recv_phase_failure_no_retry(monkeypatch):
    conn = _conn(FakeSocket(BATCH_RESULT, fail_on="recv"))
    calls = {"n": 0}

    def fake_connect():
        calls["n"] += 1
        return True

    monkeypatch.setattr(conn, "connect", fake_connect)
    with pytest.raises(Exception):
        conn.send_batch([{"type": "set_tempo", "params": {}}])
    assert calls["n"] == 0  # batch contains mutations -> never recv-retry


# --- the batch MCP tool (tool-level, Phase E) -----------------------------

class FakeConn:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def send_batch(self, commands, stop_on_error=True):
        self.calls.append((commands, stop_on_error))
        return self.result


def test_batch_tool_marshals_and_returns_json(monkeypatch):
    fake = FakeConn(BATCH_RESULT["result"])
    monkeypatch.setattr(server, "get_ableton_connection", lambda: fake)
    out = server.batch(None,
                       commands=[{"type": "set_tempo", "params": {"tempo": 120}}],
                       stop_on_error=True)
    parsed = json.loads(out)
    assert parsed["ok"] is True
    assert parsed["data"]["completed"] == 2
    # validated + normalized members reached send_batch
    assert fake.calls[0][0] == [{"type": "set_tempo", "params": {"tempo": 120}}]
    assert fake.calls[0][1] is True


def test_batch_tool_rejects_non_mutation_without_calling_connection(monkeypatch):
    fake = FakeConn(BATCH_RESULT["result"])
    monkeypatch.setattr(server, "get_ableton_connection", lambda: fake)
    out = server.batch(None, commands=[{"type": "get_session_info"}])
    parsed = json.loads(out)
    assert parsed["ok"] is False
    assert "batch" in parsed["error"].lower()
    assert fake.calls == []  # validation failed before any round-trip
