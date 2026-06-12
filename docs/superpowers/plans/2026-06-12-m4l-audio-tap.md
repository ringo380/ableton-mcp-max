# M4L Audio Tap (Master Loudness / True-Peak) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Max-for-Live device on the Master that meters loudness/true-peak and exposes integrated/short-term/momentary LUFS + dBTP to the MCP server, closing the "Needs metering" gap in `analyze_set`.

**Architecture:** A Max for Live audio-effect device K-weights the master signal and emits per-100ms block stats (mean-square + oversampled true-peak) into an embedded Node-for-Max relay, which serves a reset-able rolling buffer over TCP `:9878` using the same `{ok,data}` envelope as the 9877 Remote Script. A new Python `AudioTapConnection` reads the buffer; a pure, pytest-tested `loudness_utils.py` does the BS.1770 gating + integration; four new MCP tools expose it and feed `master.signal` into the existing rules engine.

**Tech Stack:** Python 3.10+ stdlib only (`math`, `socket`, `json` - no numpy), Max for Live (`biquad~`, `poly~`/oversampling, `peakamp~`), Node-for-Max (`node.script`, Node `net`).

Spec: `docs/superpowers/specs/2026-06-12-m4l-audio-tap-design.md`

---

## File Structure

- Create `ableton_mcp_max/loudness_utils.py` - pure BS.1770 math (block-MS -> LUFS/dBTP). Server-side only.
- Create `ableton_mcp_max/tap_connection.py` - `AudioTapConnection`, TCP client for the M4L relay on 9878.
- Modify `ableton_mcp_max/server.py` - module-level `get_audio_tap_connection()` + 4 tools; fill `master.signal` in `analyze_set`.
- Modify `ableton_mcp_max/analysis_utils.py:evaluate_rules` - evaluate a `signal_required` rule when the signal is present, else defer.
- Modify `ableton_mcp_max/rulesets/mastering.json` - flip `loudness_target` to a real check; add `true_peak`.
- Modify `ableton_mcp_max/rulesets/sources.md` - cite the loudness/true-peak targets.
- Create `tests/test_loudness_utils.py`, `tests/test_tap_connection.py`, `tests/test_audio_tap_tools.py`, and add cases to `tests/test_ruleset_utils.py` (or a new `tests/test_signal_rules.py`).
- Create `m4l/tap-server.js` - Node-for-Max relay source.
- Create `m4l/MCP Audio Tap.amxd` - the Max for Live device (built in Max, committed binary).
- Modify docs: `README.md`, `docs/install` guide, `commands/tool-index.md` + `commands/best-practices`-style note, regen tool/docs indexes.

All commands below assume the repo root and this test invocation (the `uv` pyenv-shim needs the unclobbered PATH):

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q
```

---

## Task 1: `loudness_utils.py` - pure BS.1770 math

**Files:**
- Create: `ableton_mcp_max/loudness_utils.py`
- Test: `tests/test_loudness_utils.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_loudness_utils.py
"""Offline tests for the pure BS.1770 loudness math.

loudness_utils consumes ALREADY-K-weighted per-100ms-block mean-squares (the
.amxd applies the K-filter), so these vectors feed mean-square values directly.

Reference: a stereo block with z_l = z_r = 0.0029377 gives channel-summed
mean-square 0.0058754, and -0.691 + 10*log10(0.0058754) == -23.0 LUFS.
"""
import math

from ableton_mcp_max import loudness_utils as lu

_Z23 = 0.0029377     # per-channel mean-square that yields -23.0 LUFS in stereo
_Z43 = 2.9377e-5     # per-channel mean-square that yields -43.0 LUFS in stereo


def _blocks(z, n):
    return [{"ms_k_l": z, "ms_k_r": z, "tp": 0.0} for _ in range(n)]


def test_integrated_steady_tone_is_minus_23():
    blocks = [(b["ms_k_l"], b["ms_k_r"]) for b in _blocks(_Z23, 50)]
    assert round(lu.integrated_lufs(blocks), 1) == -23.0


def test_integrated_all_silence_is_none():
    blocks = [(0.0, 0.0) for _ in range(50)]
    assert lu.integrated_lufs(blocks) is None


def test_absolute_gate_drops_silence():
    # 30 loud (-23) + 30 silent blocks: silence is below the -70 LUFS absolute
    # gate, so integrated == the loud level.
    loud = [(_Z23, _Z23) for _ in range(30)]
    silent = [(0.0, 0.0) for _ in range(30)]
    assert round(lu.integrated_lufs(loud + silent), 1) == -23.0


def test_relative_gate_drops_quiet_blocks():
    # 10 loud (-23) + 10 quiet (-43): the quiet blocks survive the absolute gate
    # but fall >10 LU below the pre-gate mean, so the relative gate drops them
    # and integrated converges on the loud level (not the -26 ungated mean).
    blocks = [(_Z23, _Z23) for _ in range(10)] + [(_Z43, _Z43) for _ in range(10)]
    assert round(lu.integrated_lufs(blocks), 1) == -23.0


def test_sliding_momentary_window():
    blocks = [(_Z23, _Z23) for _ in range(10)]
    assert round(lu.sliding_loudness(blocks, 4), 1) == -23.0


def test_sliding_returns_none_when_too_short():
    blocks = [(_Z23, _Z23) for _ in range(2)]
    assert lu.sliding_loudness(blocks, 4) is None


def test_true_peak_dbtp_is_max_in_db():
    assert round(lu.true_peak_dbtp([0.5, 1.05, 0.9]), 2) == round(20 * math.log10(1.05), 2)


def test_true_peak_empty_is_none():
    assert lu.true_peak_dbtp([]) is None


def test_compute_metrics_shape():
    payload = {
        "sample_rate": 48000,
        "since_reset_s": 5.0,
        "block_count": 50,
        "blocks": _blocks(_Z23, 50),
        "peak": 0.5,
        "rms": 0.1,
    }
    m = lu.compute_metrics(payload)
    assert m["integrated_lufs"] == -23.0
    assert m["block_count"] == 50
    assert m["duration_s"] == 5.0
    assert m["peak_dbfs"] == round(20 * math.log10(0.5), 1)
    assert set(m) == {
        "integrated_lufs", "short_term_lufs", "momentary_lufs",
        "true_peak_dbtp", "peak_dbfs", "rms_dbfs", "block_count", "duration_s",
    }
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q tests/test_loudness_utils.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'ableton_mcp_max.loudness_utils'`

- [ ] **Step 3: Write the implementation**

```python
# ableton_mcp_max/loudness_utils.py
"""Pure BS.1770 / EBU R128 loudness math, server-side only.

Inputs are ALREADY-K-weighted per-100ms-block mean-squares produced by the
'MCP Audio Tap' Max for Live device; this module only does the gating,
integration, windowing, and dB conversions - the parts that are easy to get
subtly wrong - so they live under the pytest harness.

Stereo channel weights G_L = G_R = 1.0 (BS.1770). A 400 ms gating block is the
mean of four consecutive 100 ms blocks, stepped every 100 ms (75% overlap).
"""
import math

_ABS_GATE_LUFS = -70.0   # BS.1770 absolute gate
_REL_GATE_LU = 10.0      # BS.1770 relative gate (LU below ungated mean)
_BLOCKS_PER_GATE = 4     # 400 ms / 100 ms
_BLOCKS_MOMENTARY = 4    # 400 ms
_BLOCKS_SHORT_TERM = 30  # 3 s


def lin_to_db(x):
    """Linear amplitude -> dB. Returns None for <= 0 or None."""
    if x is None or x <= 0:
        return None
    return 20.0 * math.log10(x)


def _ms_to_loudness(ms_sum):
    """Channel-summed mean-square (K-weighted) -> LKFS/LUFS, or -inf if <= 0."""
    if ms_sum <= 0:
        return float("-inf")
    return -0.691 + 10.0 * math.log10(ms_sum)


def _windowed_ms_sums(blocks, window):
    """Yield channel-summed mean-square for each `window`-block sliding window."""
    for i in range(len(blocks) - window + 1):
        win = blocks[i:i + window]
        zl = sum(b[0] for b in win) / window
        zr = sum(b[1] for b in win) / window
        yield zl + zr


def integrated_lufs(blocks):
    """Gated integrated loudness from 100 ms (ms_l, ms_r) blocks.

    Returns None if no block survives the absolute gate.
    """
    gate_ms = list(_windowed_ms_sums(blocks, _BLOCKS_PER_GATE))
    abs_kept = [z for z in gate_ms if _ms_to_loudness(z) >= _ABS_GATE_LUFS]
    if not abs_kept:
        return None
    rel_thresh = _ms_to_loudness(sum(abs_kept) / len(abs_kept)) - _REL_GATE_LU
    rel_kept = [z for z in abs_kept if _ms_to_loudness(z) >= rel_thresh]
    if not rel_kept:
        return None
    return _ms_to_loudness(sum(rel_kept) / len(rel_kept))


def sliding_loudness(blocks, window):
    """Max sliding-window loudness (momentary=4 blocks, short-term=30 blocks).

    Returns None if there are fewer than `window` blocks.
    """
    if len(blocks) < window:
        return None
    best = max((_ms_to_loudness(z) for z in _windowed_ms_sums(blocks, window)),
               default=float("-inf"))
    return None if best == float("-inf") else best


def true_peak_dbtp(tps):
    """Max per-block true-peak (linear) -> dBTP, or None if empty/all-None."""
    vals = [t for t in tps if t is not None]
    if not vals:
        return None
    return lin_to_db(max(vals))


def _round1(x):
    return None if x is None else round(x, 1)


def compute_metrics(read_payload):
    """Full metering dict from a device `read` payload.

    read_payload: {sample_rate, since_reset_s, block_count,
                   blocks:[{ms_k_l, ms_k_r, tp}, ...], peak, rms}
    """
    raw = read_payload.get("blocks", []) or []
    blocks = [(b.get("ms_k_l", 0.0), b.get("ms_k_r", 0.0)) for b in raw]
    tps = [b.get("tp") for b in raw]
    return {
        "integrated_lufs": _round1(integrated_lufs(blocks)),
        "short_term_lufs": _round1(sliding_loudness(blocks, _BLOCKS_SHORT_TERM)),
        "momentary_lufs": _round1(sliding_loudness(blocks, _BLOCKS_MOMENTARY)),
        "true_peak_dbtp": _round1(true_peak_dbtp(tps)),
        "peak_dbfs": _round1(lin_to_db(read_payload.get("peak"))),
        "rms_dbfs": _round1(lin_to_db(read_payload.get("rms"))),
        "block_count": read_payload.get("block_count", len(blocks)),
        "duration_s": read_payload.get("since_reset_s"),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q tests/test_loudness_utils.py`
Expected: PASS (10 passed)

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/loudness_utils.py tests/test_loudness_utils.py
git commit -m "feat(audio-tap): pure BS.1770 loudness math (loudness_utils)"
```

---

## Task 2: `tap_connection.py` - TCP client for the M4L relay

**Files:**
- Create: `ableton_mcp_max/tap_connection.py`
- Test: `tests/test_tap_connection.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_tap_connection.py
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
    monkeypatch.setattr(conn, "_open_socket",
                        lambda: (_ for _ in ()).throw(ConnectionRefusedError()))
    assert conn.is_connected() is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q tests/test_tap_connection.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'ableton_mcp_max.tap_connection'`

- [ ] **Step 3: Write the implementation**

```python
# ableton_mcp_max/tap_connection.py
"""TCP client for the 'MCP Audio Tap' Max-for-Live relay on localhost:9878.

Mirrors AbletonConnection's shape but simpler: every tap command is an
idempotent read, so a stale socket is reconnected and retried once
unconditionally. A refused connection (device not loaded) is an expected state -
connect() returns False and send() raises ConnectionError, which the tools turn
into a friendly "drop the device on the Master" hint.
"""
import json
import logging
import socket

logger = logging.getLogger("AudioTapConnection")


class AudioTapConnection:
    def __init__(self, host="localhost", port=9878, timeout=5.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock = None

    def _open_socket(self):
        """Create + connect a socket. Seam for tests to patch."""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(self.timeout)
        s.connect((self.host, self.port))
        return s

    def connect(self):
        if self.sock:
            return True
        try:
            self.sock = self._open_socket()
            return True
        except OSError as e:
            logger.info("audio tap not reachable on %s:%s (%s)", self.host, self.port, e)
            self.sock = None
            return False

    def _reset(self):
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
        self.sock = None

    def _recv_full(self, buffer_size=8192):
        chunks = []
        while True:
            chunk = self.sock.recv(buffer_size)
            if not chunk:
                break
            chunks.append(chunk)
            data = b"".join(chunks)
            try:
                json.loads(data.decode("utf-8"))
                return data
            except json.JSONDecodeError:
                continue
        if chunks:
            return b"".join(chunks)
        raise OSError("audio tap closed before sending data")

    def send(self, command, params=None):
        """One round-trip; reconnect + retry once on a stale socket.

        Returns the `data` payload. Raises ConnectionError if the device is not
        reachable, RuntimeError on a device-reported {ok:false} error.
        """
        message = {"command": command}
        if params:
            message.update(params)
        last_err = None
        for attempt in (1, 2):
            if not self.sock and not self.connect():
                raise ConnectionError("audio tap not connected")
            try:
                self.sock.sendall(json.dumps(message).encode("utf-8"))
                resp = json.loads(self._recv_full().decode("utf-8"))
                if not resp.get("ok", False):
                    raise RuntimeError(resp.get("error", "audio tap error"))
                return resp.get("data", {})
            except RuntimeError:
                raise
            except (OSError, json.JSONDecodeError) as e:
                last_err = e
                self._reset()
        raise ConnectionError("audio tap round-trip failed: %s" % last_err)

    def is_connected(self):
        try:
            self.send("ping")
            return True
        except Exception:
            return False

    def disconnect(self):
        self._reset()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q tests/test_tap_connection.py`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/tap_connection.py tests/test_tap_connection.py
git commit -m "feat(audio-tap): AudioTapConnection TCP client for the M4L relay"
```

---

## Task 3: MCP tools (`get_audio_tap_status`, `reset_meter`, `read_meter`, `measure_loudness`)

**Files:**
- Modify: `ableton_mcp_max/server.py` (imports near line 89-90; add module-level connection + tools; place tools after `analyze_set`, before `batch`)
- Test: `tests/test_audio_tap_tools.py`

- [ ] **Step 1: Add imports + module-level connection in server.py**

Near the existing analysis import (`ableton_mcp_max/server.py:90`), add:

```python
from ableton_mcp_max.loudness_utils import compute_metrics
from ableton_mcp_max.tap_connection import AudioTapConnection
```

Below the existing `get_ableton_connection()` helper (search for `def get_ableton_connection`), add:

```python
_audio_tap_connection = None


def get_audio_tap_connection():
    """Return the lazily-created AudioTapConnection (M4L relay on 9878)."""
    global _audio_tap_connection
    if _audio_tap_connection is None:
        _audio_tap_connection = AudioTapConnection()
    return _audio_tap_connection
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_audio_tap_tools.py
"""Tool-level tests for the audio-tap tools, faking the tap connection."""
import json

import ableton_mcp_max.server as server


class FakeTap:
    def __init__(self, responses=None, fail=False):
        self.responses = responses or {}
        self.fail = fail
        self.calls = []

    def send(self, command, params=None):
        self.calls.append((command, params))
        if self.fail:
            raise ConnectionError("audio tap not connected")
        return self.responses.get(command, {})


def _install(monkeypatch, tap):
    monkeypatch.setattr(server, "get_audio_tap_connection", lambda: tap)


def test_status_connected(monkeypatch):
    tap = FakeTap({"ping": {"device": "mcp-audio-tap", "sample_rate": 48000, "channels": 2}})
    _install(monkeypatch, tap)
    out = json.loads(server.get_audio_tap_status(None))
    assert out["ok"] is True
    assert out["data"]["connected"] is True
    assert out["data"]["sample_rate"] == 48000


def test_status_not_connected(monkeypatch):
    _install(monkeypatch, FakeTap(fail=True))
    out = json.loads(server.get_audio_tap_status(None))
    assert out["ok"] is True
    assert out["data"]["connected"] is False
    assert "Master" in out["data"]["hint"]


def test_read_meter_computes_metrics(monkeypatch):
    blocks = [{"ms_k_l": 0.0029377, "ms_k_r": 0.0029377, "tp": 0.0} for _ in range(50)]
    tap = FakeTap({"read": {"sample_rate": 48000, "since_reset_s": 5.0,
                            "block_count": 50, "blocks": blocks, "peak": 0.5, "rms": 0.1}})
    _install(monkeypatch, tap)
    out = json.loads(server.read_meter(None))
    assert out["ok"] is True
    assert out["data"]["integrated_lufs"] == -23.0


def test_read_meter_not_connected(monkeypatch):
    _install(monkeypatch, FakeTap(fail=True))
    out = json.loads(server.read_meter(None))
    assert out["ok"] is False
    assert "not connected" in out["error"]


def test_reset_meter(monkeypatch):
    tap = FakeTap({"reset": {"reset": True}})
    _install(monkeypatch, tap)
    out = json.loads(server.reset_meter(None))
    assert out["ok"] is True and out["data"]["reset"] is True


def test_measure_loudness_orchestrates(monkeypatch):
    blocks = [{"ms_k_l": 0.0029377, "ms_k_r": 0.0029377, "tp": 0.5} for _ in range(50)]
    tap = FakeTap({"reset": {"reset": True},
                   "read": {"sample_rate": 48000, "since_reset_s": 2.0,
                            "block_count": 50, "blocks": blocks, "peak": 0.5, "rms": 0.1}})
    _install(monkeypatch, tap)

    class FakeAbleton:
        def __init__(self):
            self.t = 0.0
            self.commands = []

        def send_command(self, ctype, params=None):
            self.commands.append(ctype)
            if ctype == "get_transport":
                self.t += 4.0
                return {"current_song_time": self.t}
            return {}

    monkeypatch.setattr(server, "get_ableton_connection", FakeAbleton)
    monkeypatch.setattr(server.time, "sleep", lambda _s: None)
    out = json.loads(server.measure_loudness(None, seconds=2))
    assert out["ok"] is True
    assert out["data"]["integrated_lufs"] == -23.0
    assert out["data"]["played"] is True
    assert tap.calls[0][0] == "reset"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q tests/test_audio_tap_tools.py`
Expected: FAIL with `AttributeError: module 'ableton_mcp_max.server' has no attribute 'get_audio_tap_status'`

- [ ] **Step 4: Add the tools in server.py** (place after the `analyze_set` function, before `def batch`)

```python
@mcp.tool()
def get_audio_tap_status(ctx: Context) -> str:
    """Check whether the 'MCP Audio Tap' Max-for-Live device is loaded + reachable.

    Returns JSON {ok, data}. data.connected is True with device info
    (sample_rate, channels) when the tap is running on 9878, else False with a
    setup hint. Use this before read_meter/measure_loudness to guide the
    one-time setup (drag the device onto the Master track).
    """
    tap = get_audio_tap_connection()
    try:
        info = tap.send("ping")
    except Exception:
        return _ok({"connected": False,
                    "hint": "Drop 'MCP Audio Tap' onto the Master track in Live "
                            "(one-time setup), then retry."})
    data = {"connected": True}
    data.update(info)
    return _ok(data)


@mcp.tool()
def reset_meter(ctx: Context) -> str:
    """Reset the audio tap's integrating meter (clears the block buffer).

    Returns JSON {ok, data:{reset:true}} or {ok:false,error} if the tap is not
    connected. Call before playing material you want measured.
    """
    tap = get_audio_tap_connection()
    try:
        return _ok(tap.send("reset"))
    except Exception as e:
        return _err("audio tap not connected - %s" % e)


@mcp.tool()
def read_meter(ctx: Context) -> str:
    """Read the audio tap's master-bus metering since the last reset.

    Returns JSON {ok, data} where data = {integrated_lufs, short_term_lufs,
    momentary_lufs, true_peak_dbtp, peak_dbfs, rms_dbfs, block_count,
    duration_s}. LUFS fields are null until enough audio has played (momentary
    needs >=400 ms, short-term >=3 s; integrated null if all blocks were
    silent). Returns {ok:false,error} if the tap is not connected.
    """
    tap = get_audio_tap_connection()
    try:
        payload = tap.send("read")
    except Exception as e:
        return _err("audio tap not connected - %s" % e)
    return _ok(compute_metrics(payload))


@mcp.tool()
def measure_loudness(ctx: Context, seconds: float = None) -> str:
    """Reset the meter, play the set, wait, and read back master loudness.

    seconds: how long to capture (default 10.0). For an integrated-loudness pass
    over a whole song, pass its length. Returns the same payload as read_meter
    plus data.played (False if the transport did not advance - e.g. nothing to
    play - so a bogus reading is not mistaken for real). {ok:false,error} if the
    tap is not connected.
    """
    tap = get_audio_tap_connection()
    try:
        tap.send("reset")
    except Exception as e:
        return _err("audio tap not connected - %s" % e)
    ableton = get_ableton_connection()
    try:
        start_t = ableton.send_command("get_transport").get("current_song_time", 0.0)
    except Exception:
        start_t = 0.0
    ableton.send_command("start_playback")
    time.sleep(seconds if seconds else 10.0)
    ableton.send_command("stop_playback")
    try:
        end_t = ableton.send_command("get_transport").get("current_song_time", start_t)
    except Exception:
        end_t = start_t
    metrics = compute_metrics(tap.send("read"))
    metrics["played"] = end_t > start_t
    return _ok(metrics)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q tests/test_audio_tap_tools.py`
Expected: PASS (6 passed)

- [ ] **Step 6: Syntax-check the server import**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python -c "import ableton_mcp_max.server"`
Expected: no output, exit 0

- [ ] **Step 7: Commit**

```bash
git add ableton_mcp_max/server.py tests/test_audio_tap_tools.py
git commit -m "feat(audio-tap): get_audio_tap_status/reset_meter/read_meter/measure_loudness tools"
```

---

## Task 4: Wire signal into the rules engine

**Files:**
- Modify: `ableton_mcp_max/analysis_utils.py` (`evaluate_rules`, ~line 105-128) + add `_has_signal`
- Modify: `ableton_mcp_max/server.py` (`analyze_set`, ~line 530-533) - fill `master.signal`
- Modify: `ableton_mcp_max/rulesets/mastering.json` - real `loudness_target` + new `true_peak`
- Modify: `ableton_mcp_max/rulesets/sources.md` - citation anchor
- Test: `tests/test_signal_rules.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_signal_rules.py
"""evaluate_rules treats a signal_required rule as auto when signal is present."""
from ableton_mcp_max.analysis_utils import evaluate_rules

_LOUDNESS = {
    "id": "mastering.loudness_target", "domain": "mastering",
    "title": "Integrated loudness in target range", "severity": "warn",
    "mode": "auto", "signal_required": True, "scope": "master",
    "check": {"all": [
        {"field": "signal.integrated_lufs", "op": "gte", "value": -16.0},
        {"field": "signal.integrated_lufs", "op": "lte", "value": -8.0},
    ]},
}


def _snapshot(signal):
    return {"tracks": [], "returns": [],
            "master": {"name": "Master", "device_names": [], "signal": signal}}


def test_deferred_when_signal_absent():
    res = evaluate_rules([_LOUDNESS], _snapshot(None))
    assert res["findings"] == []
    assert any(d["id"] == "mastering.loudness_target" for d in res["deferred_rules"])


def test_evaluated_pass_when_signal_in_range():
    res = evaluate_rules([_LOUDNESS], _snapshot({"integrated_lufs": -14.0}))
    assert res["deferred_rules"] == []
    f = next(f for f in res["findings"] if f["id"] == "mastering.loudness_target")
    assert f["status"] == "pass"


def test_evaluated_warn_when_signal_out_of_range():
    res = evaluate_rules([_LOUDNESS], _snapshot({"integrated_lufs": -5.0}))
    f = next(f for f in res["findings"] if f["id"] == "mastering.loudness_target")
    assert f["status"] == "warn"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q tests/test_signal_rules.py`
Expected: FAIL on `test_evaluated_pass_when_signal_in_range` (rule is currently always deferred)

- [ ] **Step 3: Update `evaluate_rules` in analysis_utils.py**

Replace the deferral block (the `if rule.get("signal_required") or mode == "deferred":` branch) with:

```python
    findings, manual, deferred = [], [], []
    for rule in rules:
        mode = rule.get("mode", "auto")
        if rule.get("signal_required") and not _has_signal(rule, snapshot):
            deferred.append({"id": rule["id"], "domain": rule["domain"],
                             "title": rule.get("title", rule["id"]),
                             "reason": "needs metering"})
            continue
        if mode == "deferred":
            deferred.append({"id": rule["id"], "domain": rule["domain"],
                             "title": rule.get("title", rule["id"]),
                             "reason": "needs metering"})
            continue
        if mode == "manual":
            manual.append({"id": rule["id"], "domain": rule["domain"],
                           "title": rule.get("title", rule["id"]),
                           "rationale": rule.get("rationale", "")})
            continue
        findings.extend(_eval_auto(rule, snapshot))
    return {"findings": findings, "manual_rules": manual,
            "deferred_rules": deferred, "summary": _summarize(findings, manual, deferred)}
```

Add this helper directly above `evaluate_rules`:

```python
def _has_signal(rule, snapshot):
    """True when the audio-tap signal the rule needs is present in the snapshot.

    v1 only meters the master, so any signal_required rule (scope master or set)
    is gated on master.signal being populated.
    """
    return (snapshot.get("master") or {}).get("signal") is not None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q tests/test_signal_rules.py`
Expected: PASS (3 passed)

- [ ] **Step 5: Replace the loudness rule + add true-peak in `rulesets/mastering.json`**

Replace the `mastering.loudness_target` object with these two objects (keep the first two rules unchanged):

```json
  {
    "id": "mastering.loudness_target",
    "domain": "mastering",
    "title": "Integrated loudness in streaming target range",
    "severity": "warn",
    "mode": "auto",
    "signal_required": true,
    "scope": "master",
    "check": { "all": [
      { "field": "signal.integrated_lufs", "op": "gte", "value": -16.0 },
      { "field": "signal.integrated_lufs", "op": "lte", "value": -8.0 }
    ] },
    "evidence_template": "Integrated loudness: {signal.integrated_lufs} LUFS",
    "rationale": "Streaming platforms normalize near -14 LUFS; -16..-8 is a sane master window.",
    "remediation": "Adjust master gain / limiter ceiling toward your target (e.g. -14 LUFS).",
    "source": "sources.md#signal-loudness"
  },
  {
    "id": "mastering.true_peak",
    "domain": "mastering",
    "title": "True peak below -1 dBTP",
    "severity": "fail",
    "mode": "auto",
    "signal_required": true,
    "scope": "master",
    "check": { "field": "signal.true_peak_dbtp", "op": "lte", "value": -1.0 },
    "evidence_template": "True peak: {signal.true_peak_dbtp} dBTP",
    "rationale": "Inter-sample peaks above -1 dBTP can clip on lossy codecs and DACs.",
    "remediation": "Lower the limiter ceiling to -1 dBTP or below.",
    "source": "sources.md#signal-loudness"
  }
```

- [ ] **Step 6: Add the citation anchor to `rulesets/sources.md`**

Confirm an anchor `signal-loudness` exists; if not, add a section:

```markdown
## signal-loudness

Integrated loudness and true-peak targets (EBU R128 / ITU-R BS.1770-4). Streaming
platforms (Spotify, Apple Music, YouTube) normalize around -14 LUFS; a -1 dBTP
ceiling avoids inter-sample clipping on lossy codecs. Measured via the MCP Audio
Tap Max-for-Live device.
```

- [ ] **Step 7: Fill `master.signal` in `analyze_set` (server.py)**

In `analyze_set`, after `snapshot = normalize_snapshot(raw)` and before `evaluate_rules`, insert:

```python
        try:
            tap = get_audio_tap_connection()
            if tap.is_connected():
                snapshot["master"]["signal"] = compute_metrics(tap.send("read"))
        except Exception as e:
            logger.info("audio tap unavailable for analysis: %s", e)
```

- [ ] **Step 8: Run the full offline suite + server import**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q && PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python -c "import ableton_mcp_max.server"`
Expected: all pass (prior 399 + the new tests), import clean

- [ ] **Step 9: Commit**

```bash
git add ableton_mcp_max/analysis_utils.py ableton_mcp_max/server.py \
        ableton_mcp_max/rulesets/mastering.json ableton_mcp_max/rulesets/sources.md \
        tests/test_signal_rules.py
git commit -m "feat(audio-tap): evaluate loudness/true-peak rules when master signal present"
```

---

## Task 5: Max for Live device + Node relay

This task produces the runtime that feeds the Python side. The Node source is testable by inspection; the `.amxd` is built in Max and live-verified (no pytest possible).

**Files:**
- Create: `m4l/tap-server.js`
- Create: `m4l/MCP Audio Tap.amxd`
- Create: `m4l/README.md` (build notes + filter coefficients)

- [ ] **Step 1: Write the Node-for-Max relay `m4l/tap-server.js`**

```javascript
// tap-server.js - Node-for-Max relay for the MCP Audio Tap device.
// Receives per-100ms block stats from the Max patch via Max messages and serves
// a reset-able rolling buffer over TCP :9878 using the {ok,data} envelope.
//
// Max -> Node messages (via the [node.script] object inlet, handled below):
//   "block"  <ms_k_l> <ms_k_r> <tp>   one 100ms block of stats
//   "sr"     <sample_rate>            report device sample rate
//   "peak"   <linear_peak>            running sample-peak since reset
//   "rms"    <linear_rms>             running RMS since reset
//
// TCP commands (one JSON object per connection write): {"command":"ping|reset|read"}

const net = require('net');
const Max = require('max-api');

const PORT = 9878;
const MAX_BLOCKS = 36000;          // ~1 hour at 10 blocks/s
const BLOCK_SECONDS = 0.1;

let sampleRate = 48000;
let channels = 2;
let blocks = [];
let peak = 0.0;
let rms = 0.0;

Max.addHandler('sr', (v) => { sampleRate = v; });
Max.addHandler('peak', (v) => { peak = v; });
Max.addHandler('rms', (v) => { rms = v; });
Max.addHandler('block', (msL, msR, tp) => {
  blocks.push({ ms_k_l: msL, ms_k_r: msR, tp: tp });
  if (blocks.length > MAX_BLOCKS) blocks.shift();
});

function resetBuffer() {
  blocks = [];
  peak = 0.0;
  rms = 0.0;
}

function readPayload() {
  return {
    sample_rate: sampleRate,
    since_reset_s: blocks.length * BLOCK_SECONDS,
    block_count: blocks.length,
    truncated: blocks.length >= MAX_BLOCKS,
    blocks: blocks,
    peak: peak,
    rms: rms,
  };
}

function handle(command) {
  switch (command) {
    case 'ping':
      return { ok: true, data: { device: 'mcp-audio-tap', version: '1.0.0',
                                 sample_rate: sampleRate, channels: channels } };
    case 'reset':
      resetBuffer();
      return { ok: true, data: { reset: true } };
    case 'read':
      return { ok: true, data: readPayload() };
    default:
      return { ok: false, error: 'unknown command: ' + command };
  }
}

const server = net.createServer((socket) => {
  let buf = '';
  socket.on('data', (chunk) => {
    buf += chunk.toString('utf8');
    let msg;
    try {
      msg = JSON.parse(buf);
    } catch (e) {
      return; // wait for the rest of the frame
    }
    buf = '';
    let resp;
    try {
      resp = handle(msg.command);
    } catch (e) {
      resp = { ok: false, error: String(e) };
    }
    socket.write(JSON.stringify(resp));
  });
  socket.on('error', () => {});
});

server.on('error', (e) => { Max.post('tap-server error: ' + e.message); });
server.listen(PORT, '127.0.0.1', () => { Max.post('tap-server listening on ' + PORT); });
```

- [ ] **Step 2: Build the Max for Live device `m4l/MCP Audio Tap.amxd`**

In Ableton: create an **Audio Effect** Max device, edit it, and build this signal flow (save when done). Recipe:

- `plugin~` (device audio in, L/R) -> two parallel paths per channel.
- **K-weighting** (BS.1770, 48 kHz coefficients): two `biquad~` stages per channel.
  - Stage 1 (pre-filter, high-shelf): `b0 1.53512485958697  b1 -2.69169618940638  b2 1.19839281085285  a1 -1.69065929318241  a2 0.73248077421585`
  - Stage 2 (RLB high-pass): `b0 1.0  b1 -2.0  b2 1.0  a1 -1.99004745483398  a2 0.99007225036621`
  - (`biquad~` arg order is `a1 a2 b0 b1 b2` with feedback-sign convention - verify against the `biquad~` help; coefficients are the standard BS.1770 48 kHz set. Non-48k SR is a live-verify item.)
- **Mean-square per 100 ms block:** square each K-weighted channel (`*~` by itself), then accumulate the mean over a 100 ms window. Use `[average~ 4800 bipolar]`? No - use a `count~`/`accum~` gen approach, or the simplest: `[average~ <N> rms]` gives RMS; square it for mean-square. Drive a `[metro 100]` -> `[snapshot~]` per channel to sample the windowed mean-square at 10 Hz; pack the two channel values.
- **True-peak per block:** upsample 4x via `[poly~]` with an oversampled subpatch (or `[sah~]`/interpolating upsampler) feeding `[peakamp~ 100]`, sampled by the same `[metro 100]`. (If 4x oversampling proves too costly on master, fall back to sample-peak `[peakamp~ 100]` and label it accordingly - flagged in the spec.)
- **Running peak/rms since reset:** `[peakamp~]` (no reset interval) and `[average~ ... rms]` read on demand; reset on the `reset` path.
- Send each block to Node: `[node.script tap-server.js]`; format `block <msL> <msR> <tp>` messages at 10 Hz, plus a `sr <samplerate~>` message on load and `peak`/`rms` updates.
- The Node `reset` command clears the JS buffer; the patch does not need to reset its own meters for integration (Python integrates from the buffer), but DO reset `peakamp~`/`average~` if you want peak/rms scoped to the reset - send them a clear bang when a `reset` arrives (optional; acceptable to leave peak/rms free-running for v1).

- [ ] **Step 3: Write `m4l/README.md`**

```markdown
# MCP Audio Tap (Max for Live)

Master-bus loudness/true-peak meter for the ableton MCP. Drop **MCP Audio Tap**
onto the **Master** track (one-time setup). It serves metering over TCP
`localhost:9878`; the MCP tools `get_audio_tap_status` / `reset_meter` /
`read_meter` / `measure_loudness` read it, and `analyze_set` uses it to evaluate
the loudness/true-peak mastering rules.

## Install
1. Ensure Ableton Live **Suite** (Max for Live) is installed.
2. Drag `MCP Audio Tap.amxd` onto the Master track. Leave it enabled.
3. Run `get_audio_tap_status` from the MCP - it should report `connected: true`.

## Internals
- Max DSP applies BS.1770 K-weighting and emits per-100ms block mean-square +
  true-peak to an embedded `node.script` (`tap-server.js`).
- `tap-server.js` keeps a reset-able rolling buffer and serves `ping`/`reset`/
  `read` as `{ok,data}` JSON.
- All gating + integration math lives in the Python `loudness_utils.py`.

## Sample-rate note
K-weighting coefficients in the device are the standard 48 kHz set. At 44.1/96 kHz
the integrated number drifts slightly; re-derive coefficients per SR if precise
non-48k measurement is required.
```

- [ ] **Step 4: Live-verify the runtime** (manual, requires Live + the device)

1. Reinstall remote script not needed (this is independent of 9877). Open Live Suite.
2. Drag `MCP Audio Tap.amxd` onto the Master.
3. Restart Claude Code (new MCP tools load as deferred -> `ToolSearch select:mcp__AbletonDev__get_audio_tap_status,...`).
4. `get_audio_tap_status` -> `connected:true`, `sample_rate` matches Live's.
5. Load a known clip; `measure_loudness(seconds=8)` while it plays.
6. Compare `integrated_lufs` against Live's own meter / Youlean within +/-0.5 LU; `true_peak_dbtp` sane (<=0).
7. `analyze_set("mastering")` -> `mastering.loudness_target` + `mastering.true_peak` now appear as findings (not deferred).
8. Record results in PROGRESS.md.

- [ ] **Step 5: Commit**

```bash
git add m4l/
git commit -m "feat(audio-tap): MCP Audio Tap M4L device + Node relay"
```

---

## Task 6: Packaging, docs, and indexes

**Files:**
- Modify: `commands/tool-index.md` (regen), `docs/tools/*` (regen), `docs/index.md` (hardcoded counts), `README.md`, install guide, `PROGRESS.md`
- Modify: `ableton/skills/...` best-practices note (audio-tap setup + 9878)

- [ ] **Step 1: Regenerate the tool index + docs site**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python scripts/build_tool_index.py
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python scripts/gen_docs_site.py
```

Expected: tool count rises by 4 (108 -> 112); both scripts assert every tool is categorized. If they error "uncategorized tool", add the 4 audio-tap tools to the category map in `scripts/build_tool_index.py` and `scripts/gen_docs_site.py` (new category e.g. "Metering / Audio Tap"), then rerun.

- [ ] **Step 2: Update the hardcoded counts in `docs/index.md`**

Edit the 5 hardcoded spots (description, tagline, two `stats__num`, the "exposes the N `@mcp.tool()`" line): 108 -> 112 tools, and category count if a new category was added.

- [ ] **Step 3: Add a best-practices note** in the ableton skill (the `best-practices` skill doc): audio tap is a separate device on 9878, one-time drop on Master, independent of the 9877 Remote Script; `get_audio_tap_status` to verify; LUFS null until audio plays.

- [ ] **Step 4: Update README** - add the audio-tap to the feature list + a one-line setup pointer to `m4l/README.md`.

- [ ] **Step 5: Update PROGRESS.md** - new section: M4L audio tap shipped (4 tools, loudness rules un-deferred), offline test count, live-verify results, "next action".

- [ ] **Step 6: Full offline gate**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python -c "import ableton_mcp_max.server"
```

Expected: all pass, import clean.

- [ ] **Step 7: Commit**

```bash
git add commands/ docs/ README.md PROGRESS.md ableton/
git commit -m "docs(audio-tap): tool index, docs site, README, progress for the audio tap"
```

---

## Release (after live-verify, user-triggered)

Not part of implementation. When live-verified, follow the repo release flow:
bump version in `pyproject.toml` + `.claude-plugin/plugin.json` -> `uv lock` ->
commit -> `gh release create vX.Y.0` -> bump `ref` in the marketplace repo's
`marketplace.json` -> `node scripts/build-readme.js` -> push. This is an additive
(non-breaking) minor; the in-tree version is 0.6.0, so confirm the latest shipped
tag with `gh release list` before picking the next number.

---

## Self-Review

- **Spec coverage:** scope A (master loudness/true-peak) - Tasks 1,3,5; measurement model (reset/read + measure_loudness wrapper) - Task 3; transport (9878 Node relay, {ok,data}) - Tasks 2,5; compute split B (Max DSP -> block stats -> Python integrates) - Tasks 1,5; analysis wire-in (master.signal, un-defer rules) - Task 4; error handling (graceful tap-absent) - Tasks 2,3 tests; testing (loudness_utils, tap_connection, tools, signal rules) - Tasks 1-4; distribution (m4l/ dir, one-time drop, status probe) - Tasks 5,6. All spec sections map to a task.
- **Placeholder scan:** no TBD/TODO; all code steps show full code. The Max patch recipe (Task 5 Step 2) is inherently a build-in-GUI step - it lists exact objects + coefficients rather than a code block, which is the most precise form possible for an `.amxd`.
- **Type consistency:** `compute_metrics` payload keys (integrated_lufs/short_term_lufs/momentary_lufs/true_peak_dbtp/peak_dbfs/rms_dbfs/block_count/duration_s) are identical across loudness_utils, the tools, and the tool tests. The device `read` payload keys (sample_rate/since_reset_s/block_count/blocks/peak/rms + per-block ms_k_l/ms_k_r/tp) match between tap-server.js, compute_metrics, and the tests. `signal.integrated_lufs` / `signal.true_peak_dbtp` paths in the rules match the `compute_metrics` output stored at `master.signal`.
```
