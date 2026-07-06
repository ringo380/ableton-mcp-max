# Ozone 12 Phase 2 - Native Param Authoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Read and write ALL Ozone 12 params by authoring the plugin state blob directly in the `.als`, removing Phase 1's 128-slot Configure cap and Hz/dB normalization clamp.

**Architecture:** A new pure module `ozone_state_utils.py` decodes/encodes Ozone's `<ProcessorState>` container (16-byte header + zlib -> typed-dict JSON) and gets/sets param leaves by `(module, param)` with native values. A ProcessorState-only locator is added to `plugin_config_utils.py` (Ozone's `<ControllerState>` is self-closing, which the existing paired locator rejects). Two new server tools - `get_ozone_state` (save + decode + read) and `set_ozone_state` (save + patch + reload, batched across modules) - reuse the proven Serum save/splice/reload seams. Phase 1's live tools are untouched.

**Tech Stack:** Python 3 (server-side, not the Remote Script), `zlib` + `json` + `struct` + `binascii` (stdlib), pytest, `uv`.

## Global Constraints

- **Server-side only.** `ozone_state_utils.py` is imported by `server.py` only; the Remote Script (Live's own Python) cannot import it. Do NOT add imports to `remote_script/`.
- **Container header rule (verified in the spike):** `[4B magic=DE8A6800][4B version LE][4B field3 LE = 4 + len(zlib)][4B raw_len LE = len(json_bytes)][zlib stream]`. field3 is `4 + len(compressed)`, NOT `len(compressed)`.
- **Blob-native module names are canonical** (`"Maximizer"`, `"Dynamic EQ"`, `"Stereo Imager"`). Phase 1 short keys (`MAX`, `DYNEQ`) are accepted via an alias map and normalized before addressing.
- **Only change existing leaves; never add/remove keys.** The setter supports leaf types Float / Bool / UInt only; String / Base64 / Dictionary leaves are rejected.
- **Never silently no-op.** Unknown module, unknown param, or type mismatch is reported in `skipped`; the rest of the batch still applies.
- **Non-breaking.** Do not modify or route the existing Phase 1 tools (`set_ozone_module_param`, `set_ozone_eq_band`, etc.) through the blob.
- **Uniform envelope.** Every `@mcp.tool()` returns `{"ok": true, "data": ...}` or `{"ok": false, "error": ...}`.
- **Public repo:** no AI attribution in any commit message. Standard hyphen `-` only in prose/docstrings (no em/en dashes).
- **Offline gate (run for every code task):**
  `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q <files>`
  plus `PATH=... uv run python -c "import ableton_mcp_max.server"` after any `server.py` change.

**Test fixture (already in the working tree):** `tests/fixtures/ozone_processor_state.bin` is a real 12433-byte master-Ozone ProcessorState blob (decompresses to 321402 bytes of JSON). Task 1 commits it. Concrete leaves it contains (module / param -> Type, value):
- `Maximizer` / `Character` -> Float, 2
- `Maximizer` / `Target Loudness [dB]` -> Float, -11  (real dB, native)
- `Maximizer` / `Mode` -> UInt, 0
- `Dynamics` / `Sidechain HPF` -> Float, 200  (real Hz, native)
- `Global` / `Global Bypass` -> Bool, False
- `Maximizer` / `Element Name` -> String, "Maximizer"  (must be rejected by the setter)

---

### Task 1: Container codec in `ozone_state_utils.py`

**Files:**
- Create: `ableton_mcp_max/ozone_state_utils.py`
- Create: `tests/test_ozone_state_utils.py`
- Commit: `tests/fixtures/ozone_processor_state.bin` (already present in working tree)

**Interfaces:**
- Consumes: nothing (pure stdlib).
- Produces:
  - `MAGIC = b"\xDE\x8A\x68\x00"`
  - `from_hex(hexstr) -> bytes`, `to_hex(blob) -> str` (uppercase, whitespace-stripped)
  - `class DecodedState` with attrs `version: int`, `tree: dict`
  - `decode(blob: bytes) -> DecodedState`
  - `encode(state: DecodedState, tree: dict) -> bytes`
  - `is_ozone_state(inner_hex: str) -> bool`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ozone_state_utils.py
import os
import pytest
from ableton_mcp_max import ozone_state_utils as osu

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "ozone_processor_state.bin")
BLOB = open(FIXTURE, "rb").read()


def test_decode_reads_header_and_tree():
    st = osu.decode(BLOB)
    assert st.version == 4
    assert set(st.tree.keys()) >= {"Context State", "DSP State"}
    elems = st.tree["DSP State"]["Value"]["DSP Elements"]["Value"]
    assert elems["Maximizer"]["Value"]["Character"]["Value"] == 2


def test_decode_rejects_bad_magic():
    with pytest.raises(ValueError):
        osu.decode(b"NOPE" + BLOB[4:])


def test_encode_roundtrips_tree_and_header():
    st = osu.decode(BLOB)
    blob2 = osu.encode(st, st.tree)
    st2 = osu.decode(blob2)
    assert st2.tree == st.tree
    # header field3 == 4 + len(zlib payload); raw_len == len(json bytes)
    import struct, zlib
    field3 = struct.unpack("<I", blob2[8:12])[0]
    raw_len = struct.unpack("<I", blob2[12:16])[0]
    assert field3 == 4 + len(blob2[16:])
    assert raw_len == len(zlib.decompress(blob2[16:]))


def test_hex_roundtrip_and_is_ozone_state():
    h = osu.to_hex(BLOB)
    assert osu.from_hex(h) == BLOB
    assert osu.is_ozone_state(h) is True
    assert osu.is_ozone_state("DEADBEEF") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q tests/test_ozone_state_utils.py`
Expected: FAIL - `ModuleNotFoundError: No module named 'ableton_mcp_max.ozone_state_utils'`.

- [ ] **Step 3: Write minimal implementation**

```python
# ableton_mcp_max/ozone_state_utils.py
"""Codec for Ozone 12's plugin-state container (found inside an .als
<ProcessorState> blob). Server-side only - the Remote Script cannot import this.

Framing (verified): 4-byte magic DE8A6800 + uint32-LE version + uint32-LE field3
(= 4 + len(zlib payload)) + uint32-LE raw_len (= decompressed byte length) +
zlib stream. The zlib stream decompresses to UTF-8 JSON in iZotope's
typed-dictionary format: every value is {"Type": <T>, "Value": <v>}.
"""
import binascii
import json
import struct
import zlib

MAGIC = b"\xDE\x8A\x68\x00"


class DecodedState(object):
    __slots__ = ("version", "tree")

    def __init__(self, version, tree):
        self.version = version
        self.tree = tree


def from_hex(hexstr):
    h = "".join(hexstr.split())
    return binascii.unhexlify(h[: len(h) // 2 * 2])


def to_hex(blob):
    return binascii.hexlify(blob).decode("ascii").upper()


def decode(blob):
    if blob[:4] != MAGIC:
        raise ValueError("not an Ozone state blob")
    version = struct.unpack("<I", blob[4:8])[0]
    raw_len = struct.unpack("<I", blob[12:16])[0]
    raw = zlib.decompress(blob[16:], bufsize=64 * 1024 * 1024)
    if len(raw) != raw_len:
        raise ValueError("raw length mismatch: header %d, actual %d"
                         % (raw_len, len(raw)))
    return DecodedState(version, json.loads(raw.decode("utf-8")))


def encode(state, tree):
    raw = json.dumps(tree, separators=(",", ":")).encode("utf-8")
    z = zlib.compress(raw, 9)
    header = (MAGIC + struct.pack("<I", state.version)
              + struct.pack("<I", 4 + len(z)) + struct.pack("<I", len(raw)))
    return header + z


def is_ozone_state(inner_hex):
    try:
        return from_hex(inner_hex)[:4] == MAGIC
    except Exception:
        return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q tests/test_ozone_state_utils.py`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/ozone_state_utils.py tests/test_ozone_state_utils.py tests/fixtures/ozone_processor_state.bin
git commit -m "feat: Ozone 12 state-blob container codec"
```

---

### Task 2: Leaf get/set + apply_changes in `ozone_state_utils.py`

**Files:**
- Modify: `ableton_mcp_max/ozone_state_utils.py`
- Modify: `tests/test_ozone_state_utils.py`

**Interfaces:**
- Consumes: `DecodedState.tree` from Task 1.
- Produces:
  - `module_leaves(tree, module) -> dict` mapping `param_name -> {"type": str, "value": ...}`; raises `ValueError` if module absent.
  - `get_param(tree, module, param) -> dict` (`{"type","value"}`); raises `ValueError` if absent.
  - `set_param(tree, module, param, value) -> value` (coerces to the leaf's type, writes it, returns the coerced value); raises `ValueError(reason)` on unknown param / unsupported type / type mismatch.
  - `apply_changes(tree, changes) -> (applied, skipped)` where `changes` is `{module: {param: value}}`; `applied` is a list of `{"module","param","value"}`, `skipped` is a list of `{"module","param","reason"}`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_ozone_state_utils.py

def _tree():
    return osu.decode(BLOB).tree


def test_module_leaves_and_get_param():
    tree = _tree()
    leaves = osu.module_leaves(tree, "Maximizer")
    assert leaves["Character"] == {"type": "Float", "value": 2}
    assert leaves["Mode"]["type"] == "UInt"
    assert osu.get_param(tree, "Dynamics", "Sidechain HPF") == {"type": "Float", "value": 200}
    with pytest.raises(ValueError):
        osu.module_leaves(tree, "NoSuchModule")


def test_set_param_coerces_by_type():
    tree = _tree()
    assert osu.set_param(tree, "Maximizer", "Target Loudness [dB]", -9) == -9.0
    assert osu.get_param(tree, "Maximizer", "Target Loudness [dB]")["value"] == -9.0
    assert osu.set_param(tree, "Global", "Global Bypass", 1) is True
    assert osu.get_param(tree, "Global", "Global Bypass")["value"] is True
    assert osu.set_param(tree, "Maximizer", "Mode", 2) == 2  # UInt


def test_set_param_rejects_bad_input():
    tree = _tree()
    with pytest.raises(ValueError):
        osu.set_param(tree, "Maximizer", "NoParam", 1)          # unknown param
    with pytest.raises(ValueError):
        osu.set_param(tree, "Maximizer", "Element Name", "x")   # String unsupported
    with pytest.raises(ValueError):
        osu.set_param(tree, "Maximizer", "Mode", -1)            # UInt negative
    with pytest.raises(ValueError):
        osu.set_param(tree, "Maximizer", "Character", True)     # bool into Float


def test_apply_changes_reports_applied_and_skipped():
    tree = _tree()
    applied, skipped = osu.apply_changes(tree, {
        "Maximizer": {"Target Loudness [dB]": -8.0, "NoParam": 1},
        "Ghost": {"x": 1},
    })
    assert {"module": "Maximizer", "param": "Target Loudness [dB]", "value": -8.0} in applied
    assert osu.get_param(tree, "Maximizer", "Target Loudness [dB]")["value"] == -8.0
    reasons = {(s["module"], s["param"]): s["reason"] for s in skipped}
    assert reasons[("Maximizer", "NoParam")] == "unknown param"
    assert reasons[("Ghost", "x")] == "unknown module"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q tests/test_ozone_state_utils.py -k "leaves or set_param or apply_changes"`
Expected: FAIL - `AttributeError: module ... has no attribute 'module_leaves'`.

- [ ] **Step 3: Write minimal implementation**

Append to `ableton_mcp_max/ozone_state_utils.py`:

```python
_SETTABLE = ("Float", "Bool", "UInt")


def _module_dict(tree, module):
    elems = tree["DSP State"]["Value"]["DSP Elements"]["Value"]
    if module not in elems:
        raise ValueError("unknown module")
    return elems[module]["Value"]


def module_leaves(tree, module):
    md = _module_dict(tree, module)
    out = {}
    for name, node in md.items():
        if isinstance(node, dict) and "Type" in node and "Value" in node:
            out[name] = {"type": node["Type"], "value": node["Value"]}
    return out


def get_param(tree, module, param):
    md = _module_dict(tree, module)
    node = md.get(param)
    if not (isinstance(node, dict) and "Type" in node and "Value" in node):
        raise ValueError("unknown param")
    return {"type": node["Type"], "value": node["Value"]}


def _coerce(t, value):
    # bool is a subclass of int; guard it explicitly per target type.
    if t == "Bool":
        if isinstance(value, bool):
            return value
        if isinstance(value, int) and value in (0, 1):
            return bool(value)
        raise ValueError("type mismatch")
    if t == "Float":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("type mismatch")
        return float(value)
    if t == "UInt":
        if isinstance(value, bool):
            raise ValueError("type mismatch")
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        if not isinstance(value, int) or value < 0:
            raise ValueError("type mismatch")
        return value
    raise ValueError("unsupported type")


def set_param(tree, module, param, value):
    md = _module_dict(tree, module)          # raises "unknown module"
    node = md.get(param)
    if not (isinstance(node, dict) and "Type" in node and "Value" in node):
        raise ValueError("unknown param")
    coerced = _coerce(node["Type"], value)   # raises "unsupported type"/"type mismatch"
    node["Value"] = coerced
    return coerced


def apply_changes(tree, changes):
    applied, skipped = [], []
    for module, params in changes.items():
        for param, value in params.items():
            try:
                coerced = set_param(tree, module, param, value)
                applied.append({"module": module, "param": param, "value": coerced})
            except ValueError as e:
                skipped.append({"module": module, "param": param, "reason": str(e)})
    return applied, skipped
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q tests/test_ozone_state_utils.py`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/ozone_state_utils.py tests/test_ozone_state_utils.py
git commit -m "feat: Ozone state-blob leaf get/set + apply_changes"
```

---

### Task 3: Module-name alias normalizer in `ozone_utils.py`

**Files:**
- Modify: `ableton_mcp_max/ozone_utils.py`
- Modify: `tests/test_ozone_utils.py`

**Interfaces:**
- Consumes: the existing `MODULES` short-key -> friendly-name map in `ozone_utils.py`.
- Produces: `normalize_module(name) -> str` - maps a Phase 1 short key (`"MAX"`) or friendly name (`"Maximizer"`) to the blob-native module name; passes any already-blob-native or unknown string through unchanged (blob validation decides).

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_ozone_utils.py
from ableton_mcp_max import ozone_utils as _oz  # if not already imported


def test_normalize_module_maps_aliases_to_blob_names():
    assert _oz.normalize_module("MAX") == "Maximizer"
    assert _oz.normalize_module("DYNEQ") == "Dynamic EQ"
    assert _oz.normalize_module("IMG") == "Stereo Imager"
    assert _oz.normalize_module("MATCH EQ") == "Match Equalizer"
    # already blob-native passes through
    assert _oz.normalize_module("Maximizer") == "Maximizer"
    # unknown passes through unchanged
    assert _oz.normalize_module("Whatever") == "Whatever"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q tests/test_ozone_utils.py -k normalize_module`
Expected: FAIL - `AttributeError: ... has no attribute 'normalize_module'`.

- [ ] **Step 3: Write minimal implementation**

Add to `ableton_mcp_max/ozone_utils.py` (after the `MODULES` dict). The blob-native names differ from a few Phase 1 friendly names (Imager -> Stereo Imager, Match EQ -> Match Equalizer, Gain -> Gain Output, EQ2 -> Post Equalizer), so map short keys explicitly:

```python
# Phase 1 short key -> Ozone state-blob native module name (DSP Elements key).
# Blob-native names are canonical for the Phase 2 state tools.
ALIAS_TO_BLOB = {
    "EQ": "Equalizer",
    "EQ2": "Post Equalizer",
    "IMG": "Stereo Imager",
    "MAX": "Maximizer",
    "DYN": "Dynamics",
    "DYNEQ": "Dynamic EQ",
    "EXC": "Exciter",
    "VCOMP": "Vintage Compressor",
    "VEQ": "Vintage EQ",
    "VLIM": "Vintage Limiter",
    "VTAPE": "Vintage Tape",
    "SPSHPR": "Spectral Shaper",
    "MREBAL": "Master Rebalance",
    "MATCH EQ": "Match Equalizer",
    "LEF": "Low End Focus",
    "IMP": "Impact",
    "STBL": "Stabilizer",
    "CLA": "Clarity",
    "BAS": "Bass Control",
    "STEMEQ": "Stem EQ",
    "UNLIMITER": "Unlimiter",
    "GAIN": "Gain Output",
}

# Phase 1 friendly name (MODULES value) -> blob-native, for callers who pass the
# friendly form. Only the ones whose friendly name differs from the blob name.
_FRIENDLY_TO_BLOB = {
    "Imager": "Stereo Imager",
    "Match EQ": "Match Equalizer",
    "Gain": "Gain Output",
    "Equalizer 2": "Post Equalizer",
}


def normalize_module(name):
    """Map a Phase 1 short key or friendly name to the Ozone state-blob native
    module name. Already-blob-native or unrecognized names pass through
    unchanged (the blob's own key set is the final validator)."""
    if name in ALIAS_TO_BLOB:
        return ALIAS_TO_BLOB[name]
    if name in _FRIENDLY_TO_BLOB:
        return _FRIENDLY_TO_BLOB[name]
    return name
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q tests/test_ozone_utils.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/ozone_utils.py tests/test_ozone_utils.py
git commit -m "feat: Ozone module-name alias normalizer for state tools"
```

---

### Task 4: ProcessorState-only locator in `plugin_config_utils.py`

**Files:**
- Modify: `ableton_mcp_max/plugin_config_utils.py`
- Modify: `tests/test_locate_plugin_state.py`

**Interfaces:**
- Consumes: the existing internal `_state_inner_span(full_xml, search_from, search_to, tag)`.
- Produces: `locate_processor_state(full_xml, track_start, track_end, device_index) -> (start, end)` - the inner-hex span of the device_index-th `<ProcessorState>` in the track span. Unlike `locate_plugin_state`, it does NOT require a paired non-empty `<ControllerState>` (Ozone's is self-closing `<ControllerState />`).

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_locate_plugin_state.py

def test_locate_processor_state_ignores_self_closing_controller():
    # Ozone emits a self-closing <ControllerState /> that the paired locator
    # rejects. The processor-only locator must still find the ProcessorState.
    xml = ("<MainTrack><DeviceChain>"
           "<ProcessorState>DE8A6800AA</ProcessorState>"
           "<ControllerState />"
           "</DeviceChain></MainTrack>")
    s, e = pcu.locate_processor_state(xml, 0, len(xml), 0)
    assert xml[s:e] == "DE8A6800AA"
    # the paired locator fails on the same input:
    with pytest.raises(ValueError):
        pcu.locate_plugin_state(xml, 0, len(xml), 0)


def test_locate_processor_state_missing_device_raises():
    xml = "<MainTrack></MainTrack>"
    with pytest.raises(ValueError):
        pcu.locate_processor_state(xml, 0, len(xml), 0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q tests/test_locate_plugin_state.py -k processor_state`
Expected: FAIL - `AttributeError: ... has no attribute 'locate_processor_state'`.

- [ ] **Step 3: Write minimal implementation**

Add to `ableton_mcp_max/plugin_config_utils.py` (next to `locate_plugin_state`):

```python
def locate_processor_state(full_xml, track_start, track_end, device_index):
    """Return the inner-hex span (start, end) of the device_index-th
    <ProcessorState> within [track_start, track_end).

    Unlike locate_plugin_state, does NOT require a paired non-empty
    <ControllerState> - Ozone 12 emits a self-closing <ControllerState /> that
    the paired locator rejects. Raises ValueError if the device is absent or the
    ProcessorState close tag is missing.
    """
    proc_iter = list(re.finditer(r"<ProcessorState[^>]*>",
                                 full_xml[track_start:track_end]))
    if device_index >= len(proc_iter):
        raise ValueError("no plugin ProcessorState #%d in track" % device_index)
    proc_start = track_start + proc_iter[device_index].start()
    span = _state_inner_span(full_xml, proc_start, track_end, "ProcessorState")
    if span is None:
        raise ValueError("ProcessorState close tag not found for device %d"
                         % device_index)
    return span
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q tests/test_locate_plugin_state.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/plugin_config_utils.py tests/test_locate_plugin_state.py
git commit -m "feat: ProcessorState-only locator for self-closing ControllerState (Ozone)"
```

---

### Task 5: Server tools `get_ozone_state` / `set_ozone_state`

**Files:**
- Modify: `ableton_mcp_max/server.py` (add impls + tools; place after `set_ozone_dynamics_band`, before `_serum_fx_resolve_path` at line ~3106, so the Ozone tools stay grouped)
- Create: `tests/test_ozone_state_tools.py`

**Interfaces:**
- Consumes: `ozone_state_utils` (Task 1-2) as `_osu`; `ozone_utils.normalize_module` (Task 3) as `_oz.normalize_module`; `plugin_config_utils.locate_processor_state` (Task 4) as `pcu.locate_processor_state`; existing `_serum_fx_resolve_path`, `_save_set_impl`, `_reload_set`, `als.read_als/write_als/find_track_span/find_return_track_span/find_master_track_span`, `set_name_from_path`.
- Produces:
  - `_resolve_track_span(xml, track_index, track_type) -> (ts, te)`
  - `_ozone_state_read_impl(...) -> dict`
  - `_ozone_state_mutate_impl(...) -> dict`
  - tools `get_ozone_state`, `set_ozone_state`.

- [ ] **Step 1: Add the import**

At the top of `server.py`, next to line 156-157 (`import ozone_utils as _oz` / `ozone_param_catalog as _ozcat`), add:

```python
from ableton_mcp_max import ozone_state_utils as _osu
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_ozone_state_tools.py
import os
from ableton_mcp_max import server
from ableton_mcp_max import ozone_state_utils as osu

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "ozone_processor_state.bin")
BLOB = open(FIXTURE, "rb").read()
HEX = osu.to_hex(BLOB)

# Minimal Live 12 master-track XML embedding the real Ozone ProcessorState.
XML = (
    '<Ableton><LiveSet><Tracks></Tracks>'
    '<MainTrack Id="9" SelectedToolPanel="7"><DeviceChain>'
    '<ProcessorState>' + HEX + '</ProcessorState>'
    '<ControllerState />'
    '</DeviceChain></MainTrack>'
    '</LiveSet></Ableton>'
)


def test_read_impl_returns_module_leaves():
    res = server._ozone_state_read_impl(
        0, 0, "master", "MAX",
        save_impl=lambda: {"saved": True},
        read_als=lambda p: XML,
        resolve_path=lambda: "/x.als",
        title_fn=lambda: "x")
    assert res["ok"] is True
    assert res["module"] == "Maximizer"
    names = {p["name"]: p for p in res["params"]}
    assert names["Character"]["value"] == 2
    assert names["Target Loudness [dB]"]["type"] == "Float"


def test_read_impl_rejects_non_ozone():
    bad = XML.replace(HEX, "DEADBEEF")
    res = server._ozone_state_read_impl(
        0, 0, "master", "MAX",
        save_impl=lambda: {"saved": True},
        read_als=lambda p: bad,
        resolve_path=lambda: "/x.als", title_fn=lambda: "x")
    assert res["ok"] is False
    assert "Ozone" in res["error"]


def test_mutate_impl_writes_native_value_and_reports_skips():
    written = {}
    res = server._ozone_state_mutate_impl(
        0, 0, "master",
        {"MAX": {"Target Loudness [dB]": -9.0, "NoParam": 1}}, reload=False,
        save_impl=lambda: {"saved": True},
        reload_impl=lambda p, n: {"reloaded": True},
        read_als=lambda p: XML,
        write_als=lambda p, x: written.update(xml=x),
        resolve_path=lambda: "/x.als", title_fn=lambda: "x")
    assert res["ok"] is True
    assert {"module": "Maximizer", "param": "Target Loudness [dB]", "value": -9.0} in res["applied"]
    assert any(s["param"] == "NoParam" for s in res["skipped"])
    # the written .als carries the native value in the re-encoded blob
    import re
    m = re.search(r"<ProcessorState>([0-9A-F]+)</ProcessorState>", written["xml"])
    tree = osu.decode(osu.from_hex(m.group(1))).tree
    assert tree["DSP State"]["Value"]["DSP Elements"]["Value"]["Maximizer"]["Value"]["Target Loudness [dB]"]["Value"] == -9.0
```

- [ ] **Step 3: Run test to verify it fails**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q tests/test_ozone_state_tools.py`
Expected: FAIL - `AttributeError: module 'ableton_mcp_max.server' has no attribute '_ozone_state_read_impl'`.

- [ ] **Step 4: Write minimal implementation**

Add to `server.py` (impls + tools). The impls mirror `_serum_fx_read_impl` / `_serum_fx_mutate_impl` but use the track-type span resolver, the ProcessorState-only locator, and the Ozone codec:

```python
def _resolve_track_span(xml, track_index, track_type):
    if track_type == "regular":
        return als.find_track_span(xml, track_index)
    if track_type == "return":
        return als.find_return_track_span(xml, track_index)
    if track_type == "master":
        return als.find_master_track_span(xml)
    raise ValueError("track_type must be regular, return, or master")


def _ozone_state_read_impl(track_index, device_index, track_type, module, *,
                           save_impl, read_als=als.read_als,
                           resolve_path=None, title_fn=None):
    """Save the set, decode the target Ozone device's ProcessorState from disk,
    and return native param values. module=None -> a per-module summary.
    Returns {ok, set_path, ...} or {ok:False, error}."""
    save_res = save_impl()
    if not save_res.get("saved"):
        return {"ok": False, "error": "save_set failed: %s" % save_res.get("error", save_res)}
    path = _serum_fx_resolve_path(title_fn, resolve_path)
    xml = read_als(path)
    ts, te = _resolve_track_span(xml, track_index, track_type)
    s, e = pcu.locate_processor_state(xml, ts, te, device_index)
    if not _osu.is_ozone_state(xml[s:e]):
        return {"ok": False, "set_path": path,
                "error": "device %d on track %d is not an Ozone 12 plugin"
                         % (device_index, track_index)}
    tree = _osu.decode(_osu.from_hex(xml[s:e])).tree
    if module is None:
        elems = tree["DSP State"]["Value"]["DSP Elements"]["Value"]
        mods = []
        for name in sorted(elems):
            leaves = _osu.module_leaves(tree, name)
            byp = leaves.get("Bypass") or leaves.get("Global Bypass")
            mods.append({"name": name, "param_count": len(leaves),
                         "bypass": byp["value"] if byp else None})
        return {"ok": True, "set_path": path, "modules": mods}
    blob_module = _oz.normalize_module(module)
    try:
        leaves = _osu.module_leaves(tree, blob_module)
    except ValueError:
        return {"ok": False, "set_path": path,
                "error": "unknown module %r (normalized %r)" % (module, blob_module)}
    params = [{"name": n, "type": v["type"], "value": v["value"]}
              for n, v in sorted(leaves.items())]
    return {"ok": True, "set_path": path, "module": blob_module, "params": params}


def _ozone_state_mutate_impl(track_index, device_index, track_type, changes, *,
                             reload, save_impl, reload_impl,
                             read_als=als.read_als, write_als=als.write_als,
                             resolve_path=None, title_fn=None):
    """Save, patch the target Ozone device's ProcessorState with `changes`
    ({module: {param: value}}, module names normalized), re-encode, splice, write,
    and optionally reload. Returns {ok, reloaded, set_path, applied, skipped}."""
    save_res = save_impl()
    if not save_res.get("saved"):
        return {"ok": False, "reloaded": False,
                "error": "save_set failed: %s" % save_res.get("error", save_res)}
    path = _serum_fx_resolve_path(title_fn, resolve_path)
    xml = read_als(path)
    ts, te = _resolve_track_span(xml, track_index, track_type)
    s, e = pcu.locate_processor_state(xml, ts, te, device_index)
    if not _osu.is_ozone_state(xml[s:e]):
        return {"ok": False, "reloaded": False, "set_path": path,
                "error": "device %d on track %d is not an Ozone 12 plugin"
                         % (device_index, track_index)}
    normalized = {_oz.normalize_module(m): p for m, p in changes.items()}
    st = _osu.decode(_osu.from_hex(xml[s:e]))
    applied, skipped = _osu.apply_changes(st.tree, normalized)
    new_hex = _osu.to_hex(_osu.encode(st, st.tree))
    xml = xml[:s] + new_hex + xml[e:]
    write_als(path, xml)
    reloaded = False
    if reload:
        rr = reload_impl(path, set_name_from_path(path))
        reloaded = bool(rr.get("reloaded", False)) if isinstance(rr, dict) else bool(rr)
    return {"ok": True, "reloaded": reloaded, "set_path": path,
            "applied": applied, "skipped": skipped}


@mcp.tool()
def get_ozone_state(ctx: Context, track_index: int, device_index: int = 0,
                    track_type: str = "master", module: str = None) -> str:
    """Read Ozone 12 params directly from the plugin state blob (native values).

    Unlike get_ozone_module, this needs NO Configure/exposure and returns REAL
    native units (Hz/dB, not clamped 0-1) for ANY module. Saves the set, then
    decodes the device's ProcessorState from the .als on disk (no reload).

    Parameters:
    - track_index: track holding the Ozone 12 instance.
    - device_index: which plugin device on the track (0 = first).
    - track_type: 'master' (default), 'return', or 'regular'.
    - module: a module name (blob-native like 'Maximizer', or a Phase 1 key like
      'MAX'). Omit for a per-module summary of the whole instance.

    Returns JSON {ok, data:{set_path, module, params:[{name,type,value}]}} for one
    module, or {ok, data:{set_path, modules:[{name,param_count,bypass}]}} for all.
    """
    try:
        get_ableton_connection()  # fail fast if Live is unreachable
        res = _ozone_state_read_impl(
            track_index, device_index, track_type, module,
            save_impl=lambda: _save_set_impl(name=""))
        if not res.get("ok"):
            return _err(res.get("error", "get_ozone_state failed"))
        res.pop("ok", None)
        return _ok(res)
    except (ValueError, RuntimeError, FileNotFoundError) as e:
        return _err(str(e))
    except Exception as e:
        logger.error("get_ozone_state error: %s", e)
        return _err("get_ozone_state error: %s" % e)


@mcp.tool()
def set_ozone_state(ctx: Context, track_index: int, changes: dict,
                    device_index: int = 0, track_type: str = "master",
                    reload: bool = True) -> str:
    """Author Ozone 12 params in native units by patching the state blob.

    Batch authoring: `changes` sets many params across many modules in ONE
    save+patch+reload. Native units land un-clamped (unlike the Phase 1 wrappers),
    with no 128-slot cap. Only changes existing params (never adds modules);
    unknown module/param or a wrong type is reported in `skipped`, not silently
    dropped. The set must be saved to a real file first (save_set_as).

    Parameters:
    - track_index: track holding the Ozone 12 instance.
    - changes: {module: {param: value}}. module is blob-native ('Maximizer',
      'Dynamic EQ') or a Phase 1 key ('MAX','DYNEQ'). value is native and typed
      per the param (Float dB/Hz, Bool bypass, UInt mode); see get_ozone_state.
    - device_index: which plugin device on the track (0 = first).
    - track_type: 'master' (default), 'return', or 'regular'.
    - reload: reload the set in place after patching (default True).

    Returns JSON {ok, data:{set_path, reloaded, applied:[...], skipped:[...]}}.
    """
    try:
        get_ableton_connection()
        res = _ozone_state_mutate_impl(
            track_index, device_index, track_type, changes, reload=reload,
            save_impl=lambda: _save_set_impl(name=""),
            reload_impl=lambda p, n: _reload_set(
                p, n, probe=lambda: get_ableton_connection().send_command(
                    "get_session_info")))
        if not res.get("ok"):
            return _err(res.get("error", "set_ozone_state failed"))
        res.pop("ok", None)
        return _ok(res)
    except (ValueError, RuntimeError, FileNotFoundError) as e:
        return _err(str(e))
    except Exception as e:
        logger.error("set_ozone_state error: %s", e)
        return _err("set_ozone_state error: %s" % e)
```

- [ ] **Step 5: Run tests + import gate**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q tests/test_ozone_state_tools.py`
Expected: PASS (3 tests).
Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python -c "import ableton_mcp_max.server"`
Expected: no output, exit 0.

- [ ] **Step 6: Commit**

```bash
git add ableton_mcp_max/server.py tests/test_ozone_state_tools.py
git commit -m "feat: get_ozone_state / set_ozone_state native param authoring tools"
```

---

### Task 6: Tool-index + docs regen

**Files:**
- Modify: `scripts/build_tool_index.py` (add the 2 tools to the "Mastering (Ozone)" group)
- Modify: `scripts/gen_docs_site.py` (add the 2 tools to the same category map)
- Regenerated: `commands/tool-index.md`, `docs/tools/*.md`, `docs/tools/index.md`

**Interfaces:**
- Consumes: nothing new; both scripts already have a "Mastering (Ozone)" category (from Phase 1). Append the two names so the "every tool is filed" assertion passes.

- [ ] **Step 1: Add the tools to `scripts/build_tool_index.py`**

In the `GROUPS` list, extend the `"Mastering (Ozone)"` entry (currently ends with `"set_ozone_dynamics_band"`) to include the two new tools:

```python
    ("Mastering (Ozone)", [
        "get_ozone_modules", "expose_ozone_modules", "get_ozone_module",
        "set_ozone_module_param", "set_ozone_module_enabled",
        "set_ozone_eq_band", "set_ozone_maximizer", "set_ozone_dynamics_band",
        "get_ozone_state", "set_ozone_state",
    ]),
```

- [ ] **Step 2: Add the tools to `scripts/gen_docs_site.py`**

Find the matching "Mastering (Ozone)" category map in `gen_docs_site.py` and add `"get_ozone_state"` and `"set_ozone_state"` in the same way (grep for `set_ozone_dynamics_band` to locate it).

- [ ] **Step 3: Regenerate docs**

Run:
```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python scripts/build_tool_index.py
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python scripts/build_tool_index.py && PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python scripts/gen_docs_site.py
```
Expected: both print a tool count of **182** (was 180). No `AssertionError: Tools missing from GROUPS`.

- [ ] **Step 4: Commit**

```bash
git add scripts/build_tool_index.py scripts/gen_docs_site.py commands/tool-index.md docs/tools/
git commit -m "docs: index the two Ozone state-authoring tools"
```

---

### Task 7 (controller-run, live + release): verify and ship

> **Not a subagent task** - requires a running Live 12 with Ozone 12 on the master and a Claude Code restart to load the new tools. The controller runs this per the project's live-verification protocol (CLAUDE.md). Stop and report if the Task 0 live gate fails.

- [ ] **Step 1: Load the new tools.** Restart Claude Code (server.py changed). Load the deferred tools:
  `ToolSearch select:mcp__AbletonDev__get_ozone_state,mcp__AbletonDev__set_ozone_state` (working-tree server via AbletonDev, with the cached `ableton` plugin disabled so AbletonDev owns the socket).

- [ ] **Step 2: Task 0 live gate (make-or-break).** With Ozone 12 on the master of a saved scratch set:
  - `get_ozone_state(track_index=<master idx or 0>, track_type="master", module="MAX")` -> confirm it returns native values (e.g. `Target Loudness [dB]` as a real dB).
  - `set_ozone_state(track_index=..., track_type="master", changes={"MAX": {"Target Loudness [dB]": -9.0}})` -> expect `reloaded: true`, `applied` contains the change, `skipped: []`.
  - After reload, `get_ozone_state(... module="MAX")` -> confirm `Target Loudness [dB]` == -9.0 and Live did NOT pop a recovery/crash modal.
  - **If Live rejects the set or the value did not take:** STOP. The container round-trip is proven at file level, so a failure here means Ozone validates something in the header/format we have not matched - report it; do not ship.

- [ ] **Step 3: Multi-module author verification.** `set_ozone_state(changes={"MAX": {"Target Loudness [dB]": -10.0}, "Dynamics": {"Sidechain HPF": 120.0}})` in one call -> confirm both land after one reload, native units un-clamped, `skipped: []`. Restore the original values afterward. Record results in PROGRESS.md.

- [ ] **Step 4: Update PROGRESS.md.** Add an "Ozone 12 Phase 2 - native param authoring" section: the 2 new tools, tool count 180 -> 182, the container format, the Task 0 gate result, and "NEXT = chain structure (deferred; needs the GUI-reorder-diff spike)".

- [ ] **Step 5: Release chain.** Bump version 0.29.0 -> 0.30.0 in `pyproject.toml` + `.claude-plugin/plugin.json`, then `uv lock`. Hand-fix the hardcoded counts: `docs/index.md` (5 spots: description, tagline, two `stats__num`, the "exposes the N @mcp.tool()" line) 180 -> 182 and category count if unchanged at 23; `README.md:7` ("reference for all N tools") 180 -> 182. Full offline gate green. Commit, open PR, `gh pr merge --squash --delete-branch` (verify `gh api user --jq .login` == `ringo380` first), `gh release create v0.30.0`, bump the `ableton` `ref` to `v0.30.0` in `robworks-claude-code-plugins/.claude-plugin/marketplace.json`, `node scripts/build-readme.js`, push the marketplace repo. Verify: local `main` == `origin/main` == `git ls-remote --tags origin v0.30.0` commit; marketplace ref bumped.

---

## Self-Review

**Spec coverage:**
- `ozone_state_utils.py` container codec (decode/encode/from_hex/to_hex/is_ozone_state) -> Task 1.
- Leaf get/set by (module,param), type coercion, apply_changes -> Task 2.
- Module-name alias normalizer (short keys -> blob-native) -> Task 3.
- ProcessorState-only locator (self-closing ControllerState) -> Task 4 (NEW; caught because `locate_plugin_state` requires a paired ControllerState, which Ozone lacks - verified in the spike).
- `get_ozone_state` / `set_ozone_state` tools, track_type targeting, batch changes, applied/skipped -> Task 5.
- Testing against the real 321 KB fixture -> Tasks 1, 2, 5.
- Docs/index regen -> Task 6.
- Task 0 live gate + multi-module author + release -> Task 7.
- Chain add/remove/reorder -> deliberately OUT (deferred per spec).

**Placeholder scan:** No TBD/TODO; every code step shows full code; every command shows expected output.

**Type consistency:** `DecodedState(version, tree)` used consistently (Tasks 1, 2, 5). `apply_changes -> (applied, skipped)` with the `{"module","param","value"}` / `{"module","param","reason"}` shapes used identically in Tasks 2 and 5. `locate_processor_state -> (start,end)` matches its use in Task 5. `normalize_module` (Task 3) used in Task 5's impls. `_osu` / `_oz` / `pcu` aliases match server.py's existing imports.
