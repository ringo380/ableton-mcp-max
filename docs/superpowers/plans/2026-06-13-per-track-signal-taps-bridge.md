# Per-Track Signal Taps via a General Bridge Device - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-track signal taps (loudness, peak/crest, 8-band spectrum, stereo) that report to a Python-hosted registry over one socket, powering new signal-backed cross-track `mixing.*` rules in `analyze_set`, and unify the v0.7.0 master tap into the same device/registry.

**Architecture:** The MCP server hosts a TCP registry on a background thread. Self-identifying Max-for-Live tap devices are TCP clients that announce their track identity (stable uuid + name/index) and stream per-100ms stat blocks. Python keeps per-track ring buffers; a deterministic timed measure pass (reset → play → read → restore) gathers simultaneous signal during playback; pure Python modules compute cross-track findings.

**Tech Stack:** Python 3.13 (stdlib only for pure modules), FastMCP (server.py), Max for Live + Node-for-Max (`max-api`, `net`), pytest + `uv`, the `ampf`/`meta`/`ptch` `.amxd` script-build recipe.

**Reference docs:** spec `docs/superpowers/specs/2026-06-13-per-track-signal-taps-bridge-design.md`; existing patterns in `ableton_mcp_max/loudness_utils.py`, `ableton_mcp_max/tap_connection.py`, `tests/test_connection.py`, `m4l/tap-server.js`, `m4l/README.md`; project conventions in `CLAUDE.md` + `PROGRESS.md`.

**Conventions carried from the codebase:**
- Pure helper modules (`*_utils.py`) are imported by server.py ONLY; the Remote Script and Max device cannot import them. Resolve/normalize on the server.
- Every MCP tool returns `{"ok":true,"data":...}` / `{"ok":false,"error":...}` via the existing `_ok`/`_err`.
- Run tests with: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q` (the PATH clobber drops the pyenv `uv` shim).
- Syntax-check: `PATH=... uv run python -c "import ableton_mcp_max.server"`.
- Editing server.py or any module it imports requires a Claude Code restart to reload (no hot reload). Editing the device requires re-install + Live bounce. Batch both, do ONE dual-restart.
- gh account must be `ringo380`. No AI attribution in any commit/PR/doc.
- Port reused: **9878** (the old master tap is being replaced).

---

## Phase 0: Risk spikes (LIVE gate - run in main loop, not a subagent)

These two unproven assumptions gate the rest of the plan. Do them first. If spike 1 fails, `deploy_taps` (Phase 5) degrades to a manual-drag helper - note that and continue; the rest of the plan is unaffected. If spike 2 fails, the device cannot self-identify and the whole approach needs rethink - STOP and report.

### Task 0.1: Spike - browser-load instantiates an `.amxd`

**Files:** none (live probe only).

- [ ] **Step 1: Place the existing v0.7.0 `MCP Audio Tap.amxd` into the User Library**

Copy it into the User Library so the LOM browser indexes it:
```bash
ULIB="$(python3 -c "import glob,re,os; cfgs=glob.glob(os.path.expanduser('~/Library/Preferences/Ableton/Live */Library.cfg')); print(cfgs[0])")"
echo "Library.cfg: $ULIB"
```
Resolve the real User Library from the `<UserLibrary>` ProjectPath in that cfg (NOT the first `User Library` string - that matches a UserFolderInfo Place; see CLAUDE.md). Then copy `m4l/MCP Audio Tap.amxd` into `<UserLibrary>/Presets/Audio Effects/Max Audio Effect/` (or the Devices area Live indexes for M4L).

- [ ] **Step 2: Confirm Live indexes it, then attempt a scripted load**

With Live running and Claude Code restarted (AbletonDev tools), find it in the browser and load it onto an empty audio track:
```
get_browser_tree (or get_browser_items_at_path on the user_library branch) -> confirm "MCP Audio Tap" appears
create_audio_track()
load_browser_item(track_index=<new>, uri=<the .amxd uri>)   # or load_preset path form
get_device_info(track_index=<new>) -> expect a Max device present
```
Expected: the device appears on the track AND its node.script binds (the old tap would start serving 9878). 

- [ ] **Step 3: Record the result**

Write the outcome (PASS = `deploy_taps` is feasible; FAIL = manual-drag fallback) into PROGRESS.md under a new "Per-track taps - spike results" note. Clean up the scratch track (`delete_track`).

### Task 0.2: Spike - device self-identification via the LOM inside Node-for-Max

**Files:** `m4l/spike-identify.js` (throwaway, delete after).

- [ ] **Step 1: Write a minimal Node-for-Max identity probe**

```js
// m4l/spike-identify.js - throwaway: prove this_device -> parent track read works in N4M
const Max = require('max-api');
Max.addHandler('whoami', () => {
  // In M4L, the device's own track is reachable via the LOM path
  // "live_set view selected_track" is NOT it; use this_device's canonical parent.
  // Strategy: a [live.path this_device] -> [live.object] chain in the patch feeds us
  // the track id; here we just echo what the patch sends.
  Max.outlet('ack');
});
Max.addHandler('track', (name, index) => {
  Max.post('TRACK name=' + name + ' index=' + index);
});
```

- [ ] **Step 2: Build a throwaway probe device**

In a scratch `.maxpat`/device: `[live.path this_device]` → `[live.object]` querying `canonical_parent`, then read `name` and resolve the track index (via `live.path` on the parent and counting, or `get path`). Wire those to `[node.script spike-identify.js]` as a `track <name> <index>` message. Drop the device on a named track.

- [ ] **Step 3: Verify the Max console prints the correct track name + index**

Expected: `TRACK name=<the track's name> index=<n>`. Confirm it updates (or is re-readable) and that a uuid can be generated device-side (`Date.now()`-style is unavailable cross-restart but a random id at load is fine for session identity).

- [ ] **Step 4: Record result + delete the throwaway**

Note PASS/FAIL in PROGRESS.md. `rm m4l/spike-identify.js`. If PASS, capture the exact LOM object path/property chain that worked - Phase 1 reuses it verbatim in the real device.

- [ ] **Step 5: Commit the spike findings**

```bash
git add PROGRESS.md && git commit -m "chore: record per-track tap spike results (browser-load + self-id)"
```

---

## Phase 1: Bridge + levels-only unified device

Proves the registry end to end with the simplest signal set, replacing the master tap.

### Task 1.1: `tap_registry.py` - frame parsing (pure)

**Files:**
- Create: `ableton_mcp_max/tap_registry.py`
- Test: `tests/test_tap_registry.py`

- [ ] **Step 1: Write failing tests for frame parsing**

```python
# tests/test_tap_registry.py
from ableton_mcp_max.tap_registry import parse_frames

def test_parse_single_frame():
    frames, rest = parse_frames('{"type":"hello","track":{"uuid":"a"}}\n')
    assert len(frames) == 1
    assert frames[0]["type"] == "hello"
    assert rest == ""

def test_parse_partial_frame_buffers_remainder():
    frames, rest = parse_frames('{"type":"block"}\n{"type":"par')
    assert len(frames) == 1
    assert rest == '{"type":"par'

def test_parse_multiple_frames():
    frames, rest = parse_frames('{"a":1}\n{"b":2}\n')
    assert len(frames) == 2
    assert frames[0]["a"] == 1 and frames[1]["b"] == 2

def test_parse_ignores_blank_lines():
    frames, rest = parse_frames('\n{"a":1}\n\n')
    assert len(frames) == 1
```

- [ ] **Step 2: Run to verify failure**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_tap_registry.py -q`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement `parse_frames`**

```python
# ableton_mcp_max/tap_registry.py
import json

def parse_frames(buf):
    """Split a newline-delimited JSON buffer into (frames, remainder).
    Tolerates blank lines and a trailing partial frame (kept in remainder)."""
    frames = []
    while "\n" in buf:
        line, buf = buf.split("\n", 1)
        line = line.strip()
        if not line:
            continue
        try:
            frames.append(json.loads(line))
        except ValueError:
            # malformed complete line: skip it
            continue
    return frames, buf
```

- [ ] **Step 4: Run to verify pass**

Run: same pytest command. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/tap_registry.py tests/test_tap_registry.py
git commit -m "feat(taps): newline-delimited frame parser for the tap registry"
```

### Task 1.2: `tap_registry.py` - ring buffer + identity map (pure)

**Files:**
- Modify: `ableton_mcp_max/tap_registry.py`
- Test: `tests/test_tap_registry.py`

- [ ] **Step 1: Write failing tests**

```python
from ableton_mcp_max.tap_registry import TapState

def test_hello_registers_track():
    s = TapState(buffer_max=4)
    s.handle_frame("conn1", {"type":"hello","track":{"uuid":"u1","name":"Bass","index":2,"kind":"midi"},"sample_rate":48000})
    assert s.tracks()[0]["name"] == "Bass"
    assert s.tracks()[0]["uuid"] == "u1"

def test_block_appends_to_ring_and_evicts():
    s = TapState(buffer_max=2)
    s.handle_frame("c", {"type":"hello","track":{"uuid":"u1"}})
    for i in range(3):
        s.handle_frame("c", {"type":"block","data":{"rms":i}})
    buf = s.buffer("u1")
    assert len(buf) == 2          # capped
    assert [b["rms"] for b in buf] == [1, 2]   # oldest evicted

def test_reset_clears_buffer():
    s = TapState(buffer_max=4)
    s.handle_frame("c", {"type":"hello","track":{"uuid":"u1"}})
    s.handle_frame("c", {"type":"block","data":{"rms":9}})
    s.reset("u1")
    assert s.buffer("u1") == []

def test_block_before_hello_is_dropped():
    s = TapState(buffer_max=4)
    s.handle_frame("c", {"type":"block","data":{"rms":1}})
    assert s.tracks() == []
```

- [ ] **Step 2: Run to verify failure**

Run: `... pytest tests/test_tap_registry.py -q`. Expected: FAIL (`TapState` undefined).

- [ ] **Step 3: Implement `TapState`**

```python
from collections import deque

class TapState:
    """In-memory registry state: connection -> track identity + ring buffer.
    Keyed by track uuid (stable across rename/reorder). Pure; no sockets."""
    def __init__(self, buffer_max=36000):
        self.buffer_max = buffer_max
        self._by_conn = {}        # conn_id -> uuid
        self._identity = {}       # uuid -> identity dict
        self._buffers = {}        # uuid -> deque
        self._sr = {}             # uuid -> sample_rate

    def handle_frame(self, conn_id, frame):
        t = frame.get("type")
        if t == "hello":
            ident = dict(frame.get("track") or {})
            uuid = ident.get("uuid")
            if not uuid:
                return
            self._by_conn[conn_id] = uuid
            self._identity[uuid] = ident
            self._sr[uuid] = frame.get("sample_rate", 48000)
            self._buffers.setdefault(uuid, deque(maxlen=self.buffer_max))
        elif t == "block":
            uuid = self._by_conn.get(conn_id)
            if uuid is None:
                return
            self._buffers[uuid].append(frame.get("data") or {})

    def tracks(self):
        return [dict(self._identity[u], sample_rate=self._sr.get(u, 48000),
                     block_count=len(self._buffers.get(u, ())))
                for u in self._identity]

    def buffer(self, uuid):
        return list(self._buffers.get(uuid, ()))

    def reset(self, uuid=None):
        targets = [uuid] if uuid else list(self._buffers)
        for u in targets:
            if u in self._buffers:
                self._buffers[u].clear()

    def drop_conn(self, conn_id):
        self._by_conn.pop(conn_id, None)
```

- [ ] **Step 4: Run to verify pass**

Run: same. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/tap_registry.py tests/test_tap_registry.py
git commit -m "feat(taps): TapState identity map + per-track ring buffers"
```

### Task 1.3: `tap_registry.py` - listening server thread

**Files:**
- Modify: `ableton_mcp_max/tap_registry.py`
- Test: `tests/test_tap_registry.py` (FakeSocket harness)

- [ ] **Step 1: Write failing test using a fake socket feed**

```python
from ableton_mcp_max.tap_registry import TapRegistry

def test_registry_ingests_frames_from_a_fed_connection():
    reg = TapRegistry(port=0)         # port 0 = do not actually bind in this test
    reg.feed("c1", '{"type":"hello","track":{"uuid":"u1","name":"Kick"}}\n')
    reg.feed("c1", '{"type":"block","data":{"rms":0.5}}\n{"type":"block","data":{"rms":0.6}}\n')
    assert reg.state.tracks()[0]["name"] == "Kick"
    assert [b["rms"] for b in reg.state.buffer("u1")] == [0.5, 0.6]

def test_registry_feed_buffers_partial_then_completes():
    reg = TapRegistry(port=0)
    reg.feed("c1", '{"type":"hello","track":{"uuid":"u1"}}\n{"type":"bl')
    reg.feed("c1", 'ock","data":{"rms":1}}\n')
    assert [b["rms"] for b in reg.state.buffer("u1")] == [1]
```

- [ ] **Step 2: Run to verify failure**

Run: `... pytest tests/test_tap_registry.py -q`. Expected: FAIL (`TapRegistry` undefined).

- [ ] **Step 3: Implement `TapRegistry` (thread + per-conn buffering on top of TapState)**

```python
import socket
import threading

class TapRegistry:
    """Background TCP server: accepts tap-device client connections, parses
    newline-delimited JSON frames, feeds TapState. feed() is the testable seam."""
    def __init__(self, port=9878, host="127.0.0.1", buffer_max=36000):
        self.port = port
        self.host = host
        self.state = TapState(buffer_max=buffer_max)
        self._recv_buf = {}       # conn_id -> str
        self._srv = None
        self._thread = None
        self._stop = threading.Event()
        self._lock = threading.Lock()

    def feed(self, conn_id, chunk):
        """Ingest a raw text chunk for a connection (the testable core)."""
        with self._lock:
            buf = self._recv_buf.get(conn_id, "") + chunk
            frames, rest = parse_frames(buf)
            self._recv_buf[conn_id] = rest
            for f in frames:
                self.state.handle_frame(conn_id, f)

    def send_command(self, conn_id, command):
        """Best-effort registry->device command (reset/ping). No-op if no socket."""
        sock = self._sockets.get(conn_id) if hasattr(self, "_sockets") else None
        if sock:
            try:
                sock.sendall((json.dumps({"command": command}) + "\n").encode())
            except OSError:
                pass

    def start(self):
        if self.port == 0:
            return
        self._sockets = {}
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind((self.host, self.port))
        self._srv.listen(16)
        self._srv.settimeout(0.5)
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        cid = 0
        while not self._stop.is_set():
            try:
                conn, _ = self._srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            cid += 1
            self._sockets[str(cid)] = conn
            threading.Thread(target=self._handle, args=(str(cid), conn), daemon=True).start()

    def _handle(self, conn_id, conn):
        conn.settimeout(1.0)
        try:
            while not self._stop.is_set():
                try:
                    chunk = conn.recv(65536)
                except socket.timeout:
                    continue
                except OSError:
                    break
                if not chunk:
                    break
                self.feed(conn_id, chunk.decode("utf-8", "replace"))
        finally:
            self.state.drop_conn(conn_id)
            self._sockets.pop(conn_id, None)
            try:
                conn.close()
            except OSError:
                pass

    def stop(self):
        self._stop.set()
        if self._srv:
            try:
                self._srv.close()
            except OSError:
                pass
```

- [ ] **Step 4: Run to verify pass**

Run: same. Expected: PASS (tests use `port=0`, never bind).

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/tap_registry.py tests/test_tap_registry.py
git commit -m "feat(taps): TapRegistry background TCP server with testable feed() seam"
```

### Task 1.4: Wire the registry into server.py + reimplement the 4 metering tools

**Files:**
- Modify: `ableton_mcp_max/server.py` (registry singleton at startup; replace `tap_connection`-based tools)
- Modify: `ableton_mcp_max/tap_connection.py` (kept only if still referenced; otherwise remove import)
- Test: `tests/test_taps_tools.py`

- [ ] **Step 1: Write failing tool-shape tests (registry injected, no real socket)**

```python
# tests/test_taps_tools.py
from ableton_mcp_max import server

def _seed_registry():
    reg = server._tap_registry          # module-level singleton
    reg.state.reset()
    reg.feed("c1", '{"type":"hello","track":{"uuid":"master","name":"Master","index":-1,"kind":"master"}}\n')
    reg.feed("c1", '{"type":"block","data":{"ms_k_l":0.01,"ms_k_r":0.01,"peak":0.5,"rms":0.1}}\n')

def test_get_audio_tap_status_reports_connected():
    _seed_registry()
    out = server.get_audio_tap_status()
    assert out["ok"] is True
    assert out["data"]["connected"] is True
    assert any(t["uuid"] == "master" for t in out["data"]["tracks"])

def test_list_taps_lists_tracks():
    _seed_registry()
    out = server.list_taps()
    assert out["ok"] is True
    assert out["data"]["count"] >= 1
```

- [ ] **Step 2: Run to verify failure**

Run: `... pytest tests/test_taps_tools.py -q`. Expected: FAIL (`_tap_registry`/`list_taps` undefined).

- [ ] **Step 3: Add the registry singleton + reimplement tools**

At server import time, create and start the registry once:
```python
# near other module-level singletons in server.py
from ableton_mcp_max.tap_registry import TapRegistry
_tap_registry = TapRegistry(port=9878)
try:
    _tap_registry.start()
except OSError:
    pass   # port busy (stale server / double-load) - tools degrade to disconnected
```
Reimplement (replacing the `tap_connection`-based versions):
```python
@mcp.tool()
def get_audio_tap_status() -> dict:
    """Report tap registry connectivity. Returns JSON {ok,data:{connected,tracks}}."""
    tracks = _tap_registry.state.tracks()
    return _ok({"connected": len(tracks) > 0, "tracks": tracks})

@mcp.tool()
def list_taps() -> dict:
    """List connected per-track taps. Returns JSON {ok,data:{count,tracks}}."""
    tracks = _tap_registry.state.tracks()
    return _ok({"count": len(tracks), "tracks": tracks})

@mcp.tool()
def reset_meter(track_index: int = None) -> dict:
    """Reset tap accumulators (all taps, or the one on track_index). Returns {ok,data}."""
    uuid = _uuid_for_index(track_index) if track_index is not None else None
    _tap_registry.state.reset(uuid)
    return _ok({"reset": True})

@mcp.tool()
def read_meter() -> dict:
    """Master loudness/peak snapshot from the master tap (compat shim). Returns {ok,data}."""
    return read_track_meter(track_index=-1)
```
Add the `_uuid_for_index` helper (maps a Live track index to a connected tap uuid by matching `identity["index"]`; master index = -1 → identity kind=="master").

- [ ] **Step 4: Run to verify pass**

Run: `... pytest tests/test_taps_tools.py -q`. Expected: PASS.

- [ ] **Step 5: Verify server still imports**

Run: `PATH=... uv run python -c "import ableton_mcp_max.server"`. Expected: no error.

- [ ] **Step 6: Commit**

```bash
git add ableton_mcp_max/server.py tests/test_taps_tools.py
git commit -m "feat(taps): host the tap registry in server.py; reimplement metering tools against it"
```

### Task 1.5: `read_track_meter` + `measure_loudness` (registry-backed) over `loudness_utils`

**Files:**
- Modify: `ableton_mcp_max/server.py`
- Test: `tests/test_taps_tools.py`

- [ ] **Step 1: Write failing tests**

```python
def test_read_track_meter_integrates_master_blocks():
    _seed_registry()
    out = server.read_track_meter(track_index=-1)
    assert out["ok"] is True
    d = out["data"]
    assert "peak" in d and "rms" in d and "block_count" in d

def test_read_track_meter_unknown_track_errors():
    server._tap_registry.state.reset()
    out = server.read_track_meter(track_index=99)
    assert out["ok"] is False
```

- [ ] **Step 2: Run to verify failure**

Run: `... pytest tests/test_taps_tools.py -q`. Expected: FAIL.

- [ ] **Step 3: Implement `read_track_meter` + `measure_loudness`**

`read_track_meter(track_index)` resolves uuid via `_uuid_for_index`, pulls the buffer, and feeds the K-weighted mean-square blocks through the EXISTING `loudness_utils` integration (absolute -70 / relative -10 gates, momentary/short-term, dBTP from `peak`). Return `{ok,data:{integrated_lufs,momentary_lufs,short_term_lufs,true_peak_dbtp,peak,rms,crest,block_count,sample_rate}}`. `measure_loudness` keeps its v0.7.0 contract but reads the master uuid buffer after a playback pass (the master-only special case of `measure_mix`).

- [ ] **Step 4: Run to verify pass**

Run: same. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/server.py tests/test_taps_tools.py
git commit -m "feat(taps): read_track_meter + registry-backed measure_loudness via loudness_utils"
```

### Task 1.6: Build the unified levels-only `.amxd` (DEVICE AUTHORING - main loop)

**Files:**
- Create: `m4l/MCP Tap.maxpat` (editable source), `m4l/registry-client.js`
- Create: `m4l/MCP Tap.amxd` (script-built)
- Modify: `m4l/README.md`
- Modify (build helper): reuse the Phase-prior `.amxd` graft script approach.

- [ ] **Step 1: Write `registry-client.js` (Node-for-Max client + relay)**

```js
// m4l/registry-client.js - Node-for-Max client: connect OUT to the MCP registry,
// announce track identity, stream per-100ms blocks. Reconnects if the registry restarts.
const net = require('net');
const Max = require('max-api');
const PORT = 9878, HOST = '127.0.0.1';

let identity = { uuid: 'u' + Math.floor(Math.random() * 1e9), name: '', index: -1, kind: '', color: 0 };
let sampleRate = 48000;
let sock = null, connected = false;

Max.addHandler('identity', (name, index, kind, color) => {
  identity.name = name; identity.index = index; identity.kind = kind; identity.color = color;
  if (connected) sendHello();
});
Max.addHandler('sr', (v) => { sampleRate = v; });
Max.addHandler('block', (msL, msR, peak, rms, b0, b1, b2, b3, b4, b5, b6, b7, mid, side) => {
  send({ type: 'block', data: { ms_k_l: msL, ms_k_r: msR, peak: peak, rms: rms,
         bands: [b0, b1, b2, b3, b4, b5, b6, b7], mid: mid, side: side } });
});

function sendHello() { send({ type: 'hello', track: identity, device: 'mcp-tap', version: '2.0.0', sample_rate: sampleRate }); }
function send(obj) { if (sock && connected) { try { sock.write(JSON.stringify(obj) + '\n'); } catch (e) {} } }

function connect() {
  sock = net.connect(PORT, HOST, () => { connected = true; sendHello(); });
  sock.on('data', () => {});     // reset/ping handled later (Phase 4)
  sock.on('error', () => {});
  sock.on('close', () => { connected = false; setTimeout(connect, 2000); });
}
connect();
```
(Levels-only Phase 1: the patch will send `block` with bands all 0 and mid/side 0 until Phases 2-3 fill them. registry-client.js already accepts the full arg list so the device JS does not change in later phases.)

- [ ] **Step 2: Author the levels-only patch in `MCP Tap.maxpat`**

Signal chain (graft onto a known-good M4L wrapper per the `.amxd` recipe in `m4l/README.md` / `~/.claude/notes/max-for-live.md`):
- `plugin~` (L/R) → two-stage `biquad~` BS.1770 K-weighting (48k coeffs via `loadmess`, from notes) → `*~` square → `average~ 4800` (100ms mean-square) per channel.
- `peakamp~ 100` per channel → `[expr max($f1,$f2)]` for `peak` (NO `max` object).
- wideband `rms`: `average~ 4800` on the squared unweighted signal → `sqrt`.
- Identity: `[live.path this_device]`→`[live.object]` `canonical_parent` → read `name`; resolve index (the exact chain confirmed in spike 0.2) → `identity <name> <index> <kind> <color>` message into `[node.script registry-client.js @autostart 1]`.
- Pack `block ms_l ms_r peak rms 0 0 0 0 0 0 0 0 0 0` (bands+stereo zeroed for now) every 100ms via `snapshot~ 100`.

- [ ] **Step 3: Script-build `MCP Tap.amxd`**

Use the Python graft (`ampf`/`meta`/`ptch`: `b[0:24] + b"ptch" + struct.pack("<I",len(payload)) + payload`, `payload=json.dumps(d,indent=1).encode()+b"\n\x00"`), swapping `boxes`/`lines` from the new patch onto the known-good wrapper. Verify it parses: `python3 -c "import json,struct; b=open('m4l/MCP Tap.amxd','rb').read(); json.JSONDecoder().raw_decode(b[32:].decode())"`.

- [ ] **Step 4: LIVE verify the bridge end to end (main loop)**

Restart Claude Code (load new server.py) + bounce Live (no remote-script change, but load the device). Drag `MCP Tap.amxd` onto an audio track playing signal. Then:
```
get_audio_tap_status -> connected:true, the track listed with correct name/index
read_track_meter(track_index=<that track>) -> sane loudness/peak (audio -> real LUFS; silence -> null/low)
```
Cross-check against the old master-tap numbers / Live meter (within ~1 LU, per v0.7.0 validation). Record in PROGRESS.md.

- [ ] **Step 5: Commit**

```bash
git add m4l/registry-client.js "m4l/MCP Tap.maxpat" "m4l/MCP Tap.amxd" m4l/README.md
git commit -m "feat(taps): unified self-identifying levels-only tap device + registry client"
```

---

## Phase 2: Spectral bands

### Task 2.1: `spectrum_utils.py` (pure)

**Files:**
- Create: `ableton_mcp_max/spectrum_utils.py`
- Test: `tests/test_spectrum_utils.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_spectrum_utils.py
from ableton_mcp_max.spectrum_utils import BAND_LABELS, integrate_bands, band_profile_db

def test_eight_bands_labeled():
    assert len(BAND_LABELS) == 8

def test_integrate_bands_averages_per_band_energy():
    blocks = [{"bands":[1,0,0,0,0,0,0,0]}, {"bands":[3,0,0,0,0,0,0,0]}]
    out = integrate_bands(blocks)
    assert out[0] == 2.0           # mean of band 0
    assert out[7] == 0.0

def test_band_profile_db_is_relative_normalized():
    energy = [1,1,1,1,1,1,1,1]
    prof = band_profile_db(energy)
    assert max(prof) == 0.0        # loudest band = 0 dB reference
    assert all(p <= 0.0 for p in prof)

def test_integrate_bands_empty_returns_zeros():
    assert integrate_bands([]) == [0.0]*8
```

- [ ] **Step 2: Run to verify failure**

Run: `... pytest tests/test_spectrum_utils.py -q`. Expected: FAIL.

- [ ] **Step 3: Implement**

```python
# ableton_mcp_max/spectrum_utils.py
import math

BAND_LABELS = ["sub", "low", "low_mid", "mid", "high_mid", "presence", "brilliance", "air"]
# nominal log-spaced crossover centers (Hz), documentation only; the device filterbank owns the real splits
BAND_HZ = [40, 100, 250, 600, 1500, 3500, 8000, 15000]

def integrate_bands(blocks):
    """Mean per-band energy across blocks. Returns 8 floats (zeros if empty)."""
    if not blocks:
        return [0.0] * 8
    acc = [0.0] * 8
    n = 0
    for b in blocks:
        bands = b.get("bands") or [0.0] * 8
        for i in range(8):
            acc[i] += bands[i] if i < len(bands) else 0.0
        n += 1
    return [a / n for a in acc] if n else [0.0] * 8

def band_profile_db(energy, floor_db=-60.0):
    """Normalize a band-energy vector to dB relative to its loudest band (<=0 dB)."""
    peak = max(energy) if energy else 0.0
    if peak <= 0.0:
        return [floor_db] * len(energy)
    out = []
    for e in energy:
        if e <= 0.0:
            out.append(floor_db)
        else:
            out.append(max(floor_db, 10.0 * math.log10(e / peak)))
    return out
```

- [ ] **Step 4: Run to verify pass**

Run: same. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/spectrum_utils.py tests/test_spectrum_utils.py
git commit -m "feat(taps): spectrum_utils - per-band integration + relative dB profile"
```

### Task 2.2: Add the 8-band filterbank to the device (DEVICE AUTHORING - main loop)

**Files:** Modify `m4l/MCP Tap.maxpat` + rebuild `m4l/MCP Tap.amxd`.

- [ ] **Step 1: Add the filterbank to the patch**

Per band (8): `biquad~` bandpass at the `BAND_HZ` center → `*~` square → `average~ 4800`. Coefficients computed offline (a small Python helper printing 8 bandpass `a0 a1 a2 b1 b2` sets for 48k) and `loadmess`-fed. Wire the 8 band outputs into the `block` message slots that registry-client.js already expects (positions 5-12).

- [ ] **Step 2: Rebuild + parse-check the `.amxd`** (same graft + raw_decode check as Task 1.6 Step 3).

- [ ] **Step 3: LIVE verify band profiles (main loop)**

Restart/bounce, re-drop the device. Play a kick → expect energy concentrated in `sub`/`low`; play a hi-hat → `brilliance`/`air`. `read_track_meter` now returns non-zero `bands`. Record in PROGRESS.md.

- [ ] **Step 4: Commit**

```bash
git add "m4l/MCP Tap.maxpat" "m4l/MCP Tap.amxd"
git commit -m "feat(taps): 8-band log filterbank in the tap device"
```

---

## Phase 3: Stereo

### Task 3.1: stereo math in `spectrum_utils.py` (or new `stereo_utils.py`)

**Files:**
- Modify: `ableton_mcp_max/spectrum_utils.py`
- Test: `tests/test_spectrum_utils.py`

- [ ] **Step 1: Write failing tests**

```python
from ableton_mcp_max.spectrum_utils import stereo_metrics

def test_mono_signal_is_fully_correlated():
    # side ~ 0 -> correlation ~ 1, width ~ 0
    blocks = [{"mid":1.0,"side":0.0}]*3
    m = stereo_metrics(blocks)
    assert m["correlation"] > 0.95
    assert m["width"] < 0.05

def test_wide_signal_has_high_width():
    blocks = [{"mid":0.5,"side":0.5}]*3
    m = stereo_metrics(blocks)
    assert m["width"] > 0.4

def test_empty_blocks_safe():
    m = stereo_metrics([])
    assert m["correlation"] == 0.0 and m["width"] == 0.0
```

- [ ] **Step 2: Run to verify failure** — Run: `... pytest tests/test_spectrum_utils.py -q`. Expected: FAIL.

- [ ] **Step 3: Implement `stereo_metrics`**

```python
def stereo_metrics(blocks):
    """Aggregate mid/side energy into width + a correlation proxy.
    width = side/(mid+side); correlation proxy = (mid-side)/(mid+side) clamped to [-1,1]."""
    if not blocks:
        return {"width": 0.0, "correlation": 0.0}
    mid = sum(b.get("mid", 0.0) for b in blocks)
    side = sum(b.get("side", 0.0) for b in blocks)
    total = mid + side
    if total <= 0.0:
        return {"width": 0.0, "correlation": 0.0}
    width = side / total
    corr = max(-1.0, min(1.0, (mid - side) / total))
    return {"width": width, "correlation": corr}
```

- [ ] **Step 4: Run to verify pass** — Run: same. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/spectrum_utils.py tests/test_spectrum_utils.py
git commit -m "feat(taps): stereo width + correlation proxy from mid/side energy"
```

### Task 3.2: add mid/side to the device (DEVICE AUTHORING - main loop)

**Files:** Modify `m4l/MCP Tap.maxpat` + rebuild `.amxd`.

- [ ] **Step 1:** Add `mid = (L+R)*0.5`, `side = (L-R)*0.5` (`+~`/`-~`/`*~`), square + `average~ 4800` each, into `block` slots 13-14. **Step 2:** Rebuild + parse-check. **Step 3:** LIVE verify (pan a mono source hard → width rises, correlation drops; centered → correlation ~1). Record in PROGRESS.md. **Step 4:** Commit:

```bash
git add "m4l/MCP Tap.maxpat" "m4l/MCP Tap.amxd"
git commit -m "feat(taps): mid/side stereo metering in the tap device"
```

---

## Phase 4: Cross-track rules + `measure_mix`

### Task 4.1: `masking_utils.py` (pure)

**Files:**
- Create: `ableton_mcp_max/masking_utils.py`
- Test: `tests/test_masking_utils.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_masking_utils.py
from ableton_mcp_max.masking_utils import (
    masking_score, loudness_balance, headroom_flags, stereo_flags)

def test_masking_high_when_two_tracks_share_a_loud_band():
    a = {"name":"Kick","bands":[1,0,0,0,0,0,0,0]}
    b = {"name":"Bass","bands":[1,0,0,0,0,0,0,0]}
    pairs = masking_score([a, b], threshold=0.6)
    assert pairs and pairs[0]["score"] > 0.6
    assert {pairs[0]["a"], pairs[0]["b"]} == {"Kick", "Bass"}

def test_masking_low_when_bands_disjoint():
    a = {"name":"Kick","bands":[1,0,0,0,0,0,0,0]}
    b = {"name":"Hat","bands":[0,0,0,0,0,0,0,1]}
    assert masking_score([a, b], threshold=0.6) == []

def test_loudness_balance_flags_outlier():
    tracks = [{"name":"A","integrated_lufs":-18},{"name":"B","integrated_lufs":-19},
              {"name":"C","integrated_lufs":-40}]
    out = loudness_balance(tracks, spread_db=12.0)
    assert any(f["name"] == "C" for f in out)

def test_headroom_flags_near_clip():
    tracks = [{"name":"Loud","true_peak_dbtp":-0.2,"crest":3.0}]
    out = headroom_flags(tracks, peak_ceiling=-1.0, crest_floor=4.0)
    assert any(f["name"] == "Loud" for f in out)

def test_stereo_flags_negative_correlation():
    tracks = [{"name":"Wide","correlation":-0.5}]
    out = stereo_flags(tracks, corr_floor=-0.2)
    assert any(f["name"] == "Wide" for f in out)
```

- [ ] **Step 2: Run to verify failure** — Run: `... pytest tests/test_masking_utils.py -q`. Expected: FAIL.

- [ ] **Step 3: Implement**

```python
# ableton_mcp_max/masking_utils.py
"""Pure cross-track mix analysis. All inputs are integrated per-track dicts
produced by the measure pass (server-side); no Live/Max imports."""

def _norm(v):
    s = sum(v) or 1.0
    return [x / s for x in v]

def masking_score(tracks, threshold=0.6):
    """Pairwise spectral overlap (cosine-like on normalized band vectors).
    Returns sorted list of {a,b,score,bands} for pairs above threshold."""
    out = []
    n = len(tracks)
    for i in range(n):
        for j in range(i + 1, n):
            va, vb = tracks[i].get("bands") or [], tracks[j].get("bands") or []
            if not va or not vb:
                continue
            na, nb = _norm(va), _norm(vb)
            dot = sum(x * y for x, y in zip(na, nb))
            mag = (sum(x*x for x in na) ** 0.5) * (sum(y*y for y in nb) ** 0.5) or 1.0
            score = dot / mag
            if score >= threshold:
                out.append({"a": tracks[i].get("name"), "b": tracks[j].get("name"),
                            "score": round(score, 3)})
    return sorted(out, key=lambda d: -d["score"])

def loudness_balance(tracks, spread_db=12.0):
    """Flag tracks sitting more than spread_db below the loudest active track."""
    active = [t for t in tracks if t.get("integrated_lufs") is not None
              and t["integrated_lufs"] > -70.0]
    if not active:
        return []
    loudest = max(t["integrated_lufs"] for t in active)
    return [{"name": t.get("name"), "integrated_lufs": t["integrated_lufs"],
             "below_db": round(loudest - t["integrated_lufs"], 1)}
            for t in active if loudest - t["integrated_lufs"] > spread_db]

def headroom_flags(tracks, peak_ceiling=-1.0, crest_floor=4.0):
    out = []
    for t in tracks:
        tp, crest = t.get("true_peak_dbtp"), t.get("crest")
        if tp is not None and tp > peak_ceiling:
            out.append({"name": t.get("name"), "issue": "near_clip", "true_peak_dbtp": tp})
        elif crest is not None and crest < crest_floor:
            out.append({"name": t.get("name"), "issue": "over_compressed", "crest": crest})
    return out

def stereo_flags(tracks, corr_floor=-0.2):
    return [{"name": t.get("name"), "correlation": t["correlation"]}
            for t in tracks
            if t.get("correlation") is not None and t["correlation"] < corr_floor]
```

- [ ] **Step 4: Run to verify pass** — Run: same. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/masking_utils.py tests/test_masking_utils.py
git commit -m "feat(taps): masking_utils - masking/balance/headroom/stereo cross-track math"
```

### Task 4.2: `measure_mix` tool + per-track signal integration

**Files:**
- Modify: `ableton_mcp_max/server.py`
- Test: `tests/test_taps_tools.py`

- [ ] **Step 1: Write failing test (injected buffers, transport stubbed)**

```python
def test_measure_mix_returns_per_track_signal_and_findings(monkeypatch):
    reg = server._tap_registry
    reg.state.reset()
    reg.feed("c1", '{"type":"hello","track":{"uuid":"k","name":"Kick","index":0}}\n')
    reg.feed("c2", '{"type":"hello","track":{"uuid":"b","name":"Bass","index":1}}\n')
    for _ in range(20):
        reg.feed("c1", '{"type":"block","data":{"ms_k_l":0.01,"ms_k_r":0.01,"peak":0.5,"rms":0.1,"bands":[1,0,0,0,0,0,0,0],"mid":1,"side":0}}\n')
        reg.feed("c2", '{"type":"block","data":{"ms_k_l":0.01,"ms_k_r":0.01,"peak":0.5,"rms":0.1,"bands":[1,0,0,0,0,0,0,0],"mid":1,"side":0}}\n')
    # stub the playback pass so the test never touches Live
    monkeypatch.setattr(server, "_run_measure_playback", lambda window_s, region: None)
    out = server.measure_mix(window_s=0)
    assert out["ok"] is True
    names = {t["name"] for t in out["data"]["tracks"]}
    assert {"Kick", "Bass"} <= names
    # Kick+Bass share band 0 -> masking finding present
    assert out["data"]["findings"]["masking"]
```

- [ ] **Step 2: Run to verify failure** — Run: `... pytest tests/test_taps_tools.py -q`. Expected: FAIL.

- [ ] **Step 3: Implement `measure_mix` + `_run_measure_playback`**

`_run_measure_playback(window_s, region)` snapshots transport, `reset`s all taps (via `_tap_registry.state.reset()` and best-effort `send_command(reset)`), starts playback (`start_playback`/loop/region), sleeps `window_s`, stops, restores - using the separate-read settle discipline. `measure_mix` then: reads every connected tap buffer → builds a per-track `signal` dict (loudness via `loudness_utils`, `integrate_bands` via `spectrum_utils`, `stereo_metrics`, peak/crest) → runs all four `masking_utils` functions → returns `{ok,data:{tracks:[{name,index,signal}],findings:{masking,balance,headroom,stereo}}}`. `_run_measure_playback` is the monkeypatch seam so tests never drive Live.

- [ ] **Step 4: Run to verify pass** — Run: same. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/server.py tests/test_taps_tools.py
git commit -m "feat(taps): measure_mix timed measure pass + per-track signal integration"
```

### Task 4.3: registry→device reset command + analyze_set integration

**Files:**
- Modify: `ableton_mcp_max/server.py` (analyze_set: fill per-track `signal` from a measure pass when taps present)
- Modify: `ableton_mcp_max/rulesets/mixing.json` (4 new signal-backed rules)
- Modify: `m4l/registry-client.js` (handle inbound `{"command":"reset"}`)
- Test: `tests/test_ruleset_utils.py` or `tests/test_analyze_tool.py`

- [ ] **Step 1: Write failing rule-evaluation tests**

Add synthetic per-track `signal` snapshots and assert the 4 new rules evaluate (pass/fail) rather than defer when `signal` is present, and defer when absent. Mirror the existing `test_analysis_utils`/`test_ruleset_utils` style. (Concrete: build a snapshot with two tracks sharing band 0 → `mixing.spectral_masking` fails; disjoint → passes.)

- [ ] **Step 2: Run to verify failure** — Run: `... pytest tests/test_ruleset_utils.py tests/test_analyze_tool.py -q`. Expected: FAIL.

- [ ] **Step 3: Add the 4 rules + wire analyze_set**

Add to `mixing.json` (signal-backed; `signal_required: true` so they defer honestly without taps): `mixing.spectral_masking`, `mixing.loudness_balance`, `mixing.headroom_per_track`, `mixing.stereo_correlation`, each with `rationale`, `evidence_template`, `source` (add entries to `rulesets/sources.md`). These are cross-track aggregate rules, so analyze_set computes them via `masking_utils` from the measure pass and injects the findings (the JSON rule entries document/severity-tag them; the evaluator path mirrors how `master.signal` rules are filled). In `analyze_set`, when `_tap_registry.state.tracks()` is non-empty, run a measure pass and populate each track's `signal` + the cross-track findings; otherwise leave them deferred. Add inbound reset handling to `registry-client.js`:
```js
sock.on('data', (chunk) => {
  String(chunk).split('\n').forEach((line) => {
    if (!line.trim()) return;
    try { const m = JSON.parse(line); if (m.command === 'reset') Max.outlet('reset'); } catch (e) {}
  });
});
```
(The patch routes that `reset` outlet to clear `average~`/`peakamp~` history if needed; buffer reset is Python-side, so device-side reset is best-effort.)

- [ ] **Step 4: Run to verify pass** — Run: same. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/server.py ableton_mcp_max/rulesets/mixing.json ableton_mcp_max/rulesets/sources.md m4l/registry-client.js tests/
git commit -m "feat(taps): signal-backed cross-track mixing rules + analyze_set measure-pass integration"
```

---

## Phase 5: Scripted deploy + docs + release prep

### Task 5.1: `deploy_taps` / `remove_taps` (gated by spike 0.1)

**Files:**
- Modify: `ableton_mcp_max/server.py`
- Test: `tests/test_taps_tools.py`

- [ ] **Step 1: Write failing tests (resolution logic, Live calls stubbed)**

```python
def test_deploy_taps_targets_all_audio_and_instrument_tracks(monkeypatch):
    calls = []
    monkeypatch.setattr(server, "_load_tap_on_track", lambda i: calls.append(i))
    monkeypatch.setattr(server, "_audio_instrument_track_indices", lambda: [0, 2, 3])
    out = server.deploy_taps(track_indices=None)
    assert out["ok"] is True
    assert calls == [0, 2, 3]

def test_deploy_taps_explicit_indices(monkeypatch):
    calls = []
    monkeypatch.setattr(server, "_load_tap_on_track", lambda i: calls.append(i))
    out = server.deploy_taps(track_indices=[1])
    assert calls == [1]
```

- [ ] **Step 2: Run to verify failure** — Run: `... pytest tests/test_taps_tools.py -q`. Expected: FAIL.

- [ ] **Step 3: Implement**

`deploy_taps(track_indices=None)` resolves targets (`_audio_instrument_track_indices` reads session info, filters to regular audio/instrument tracks) and calls `_load_tap_on_track` (browser-loads the User-Library `MCP Tap.amxd` via the existing load path). `remove_taps` deletes the tap device by name match. If spike 0.1 was FAIL, `deploy_taps` instead returns `{ok:true,data:{manual:true, message:"Drag 'MCP Tap' onto these tracks", tracks:[...]}}`.

- [ ] **Step 4: Run to verify pass** — Run: same. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/server.py tests/test_taps_tools.py
git commit -m "feat(taps): deploy_taps/remove_taps scripted tap deployment"
```

### Task 5.2: Full offline suite + server import + remote py_compile

- [ ] **Step 1: Run the whole gate**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python -c "import ableton_mcp_max.server"
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python -m py_compile remote_script/AbletonMCP/__init__.py
```
Expected: all pass, no import error, no compile error. Fix anything red before continuing.

- [ ] **Step 2: Commit any fixes**

```bash
git add -A && git commit -m "test: full offline gate green for per-track taps" || echo "nothing to commit"
```

### Task 5.3: Docs, tool-index, landing counts, README + migration note

**Files:** `m4l/README.md`, docs site (`scripts/gen_docs_site.py`, `scripts/build_tool_index.py`, `commands/tool-index.md`, `docs/tools/**`, `docs/index.md` hardcoded counts), `commands/ableton-analyze` skill guidance (offer a measure pass).

- [ ] **Step 1: Regenerate the auto docs**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python scripts/build_tool_index.py
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python scripts/gen_docs_site.py
```
Expected: tool count rises from 112 to the new total (112 minus any removed + new: list_taps, read_track_meter, measure_mix, deploy_taps, remove_taps added; the 4 existing metering tools reimplemented not added). Compute the exact number from `scripts/build_tool_index.py` output.

- [ ] **Step 2: Hand-edit the 5 hardcoded count spots in `docs/index.md`** (description, tagline, two `stats__num`, the "exposes the N `@mcp.tool()`" line) to the new tool + category counts.

- [ ] **Step 3: Update `m4l/README.md`** with the new unified device, the registry model, and a **migration note** (v0.7.0 master-tap users must replace the old device with `MCP Tap`).

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "docs: per-track taps - device README, tool index, docs site, migration note"
```

### Task 5.4: PROGRESS.md + finish the branch

- [ ] **Step 1: Update PROGRESS.md** with the full per-track-taps summary (architecture, spike results, live-verify results, tool count, "shipped pending release as v0.8.0 - BREAKING device change").

- [ ] **Step 2: Commit + open PR**

```bash
git add PROGRESS.md && git commit -m "docs: PROGRESS.md - per-track signal taps bridge"
git push -u origin feat/per-track-taps-bridge
gh pr create --title "Per-track signal taps via a general bridge device" --body "<summary>"
```
(gh must be `ringo380`: `gh api user --jq .login`.)

- [ ] **Step 3: Release (user-triggered, AFTER live verification)** — bump version to 0.8.0 in `pyproject.toml` + `.claude-plugin/plugin.json`, `uv lock`; squash-merge; `gh release create v0.8.0`; bump `ableton` `ref` in the marketplace repo's `marketplace.json`; `node scripts/build-readme.js`; push. Confirm latest shipped tag first (`gh release list`).

---

## Self-review notes (addressed inline)

- **Spec coverage:** registry/protocol (Tasks 1.1-1.4, 1.6), levels (1.5-1.6), spectral (2.x), stereo (3.x), masking+rules+measure_mix (4.x), deploy/docs/unify (5.x), master unification (1.4-1.6 reimplement + 5.3 migration note), both risk spikes (0.1-0.2). All spec sections map to a task.
- **Type consistency:** `block` payload keys (`ms_k_l/ms_k_r/peak/rms/bands/mid/side`) are identical across `registry-client.js`, `TapState`, `spectrum_utils`, `masking_utils`, and the `measure_mix` test. `bands` is always length 8. uuid is the registry key everywhere. `_uuid_for_index`, `_run_measure_playback`, `_load_tap_on_track`, `_audio_instrument_track_indices` are the named server.py seams referenced consistently.
- **Placeholder scan:** device-authoring steps are procedural (Max patches can't be unit-tested) but each names exact objects, the build/parse-check command, and a concrete live-verify assertion. The only intentional deferral is the exact new tool count (computed from `build_tool_index.py` at Task 5.3, since it depends on the reimplement-vs-add split).
- **Known-risk reminders inlined:** PATH clobber for `uv`, Claude-restart-on-server-edit, Live-bounce-on-device-edit, no `max` object, EADDRINUSE/one-device, `docs/index.md` hardcoded counts, gh=ringo380, no AI attribution.
