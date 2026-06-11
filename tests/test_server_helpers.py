"""Offline tests for server-level helpers: the {ok, data|error} return envelope
and the additive index-alias resolver."""
import json

import pytest

import ableton_mcp_max.server as server


# --- envelope -------------------------------------------------------------

def test_ok_envelope():
    assert json.loads(server._ok({"a": 1})) == {"ok": True, "data": {"a": 1}}


def test_ok_accepts_string_data():
    assert json.loads(server._ok("done")) == {"ok": True, "data": "done"}


def test_err_envelope():
    assert json.loads(server._err("boom")) == {"ok": False, "error": "boom"}


def test_err_stringifies_exceptions():
    out = json.loads(server._err(ValueError("nope")))
    assert out["ok"] is False and out["error"] == "nope"


# --- index alias resolver -------------------------------------------------

def test_resolve_canonical():
    assert server._resolve_index(3, None, label="track_index") == 3


def test_resolve_alias():
    assert server._resolve_index(None, 5, label="track_index") == 5


def test_resolve_zero_is_valid():
    # 0 is falsy but not None -> must be honored, not treated as missing
    assert server._resolve_index(0, None, label="track_index") == 0


def test_resolve_default_when_both_none():
    assert server._resolve_index(None, None, default=-1, label="x") == -1


def test_resolve_required_raises():
    with pytest.raises(ValueError):
        server._resolve_index(None, None, label="track_index")


def test_resolve_conflict_raises():
    with pytest.raises(ValueError):
        server._resolve_index(1, 2, label="track_index")


def test_resolve_same_value_ok():
    assert server._resolve_index(4, 4, label="track_index") == 4
