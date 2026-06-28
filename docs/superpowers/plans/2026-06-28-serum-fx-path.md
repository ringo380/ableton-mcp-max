# Serum 2 FX Control (Release 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Author Serum 2's FX racks (set params, bypass, insert/remove/reorder FX) by patching the plugin-state CBOR in the live set's `.als` and reloading in place.

**Architecture:** Serum's `<ProcessorState>` and `<ControllerState>` blobs in the `.als` are hex-encoded `XferJson -> zstd -> CBOR` containers holding the full FX tree (`FXRack0/1/2`). A pure codec decodes/re-encodes the container; pure FX-tree helpers mutate the decoded CBOR; a server impl mirrors the proven `_expose_plugin_impl` flow (save_set -> read .als -> decode both blobs -> mutate -> re-encode -> splice -> write -> reload). Five new MCP tools wrap it. All host-side; the Remote Script is unchanged.

**Tech Stack:** Python 3 (host-side MCP server, FastMCP), `zstandard`, `cbor2`, pytest, `uv`.

## Global Constraints

- ASCII hyphens only in all code/comments/docs/commits; never em/en-dashes. No AI attribution anywhere (commits, docs).
- Pure `*_utils`/codec modules are imported by `server.py` only; the Remote Script cannot import them. No RS changes in this plan.
- Native units are the source of truth for FX values; `normalized` is optional/deferred.
- This is state authoring, not LOM automation - document in every tool docstring. One save+reload per mutation; reads are reload-free.
- Patch BOTH `ProcessorState` and `ControllerState` consistently. `Vst3Preset` left untouched pending live verification (Task 7).
- Run tests with: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q`. Syntax-check server: `uv run python -c "import ableton_mcp_max.server"`.
- Container framing (verified): `b"XferJson"` + `b"\x00"` + uint64 LE metadata-JSON length + metadata JSON (utf-8) + 8-byte header (`<II` = uint32 uncompressed CBOR length, uint32 flags `2`) + zstd frame to end. `meta["hash"]` = `md5(zstd_blob).hexdigest()` (32 hex chars).
- Factory presets: `/Library/Audio/Presets/Xfer Records/Serum 2 Presets/Presets/` (791 `*.SerumPreset`). Live test set: `/Users/ryanrobson/Desktop/serum2_test Project/serum2_idtest.als`.
- Existing seams: `als.read_als`, `als.write_als`, `als.find_track_span` (in `ableton_mcp_max/als_automation_utils.py`, imported as `als`); `plugin_config_utils` as `pcu`; `_reload_set`, `_current_set_path`, `_find_saved_set`, `_live_window_title`, `is_untitled_title`, `set_name_from_path` in `server.py`.

---

### Task 1: XferJson container codec

**Files:**
- Create: `ableton_mcp_max/serum_state_codec.py`
- Test: `tests/test_serum_state_codec.py`
- Modify: `pyproject.toml` (add `cbor2`, `zstandard` to `dependencies`), then `uv lock`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `class DecodedState` with attrs `meta: dict`, `meta_bytes: bytes`, `tree: object`.
  - `decode(blob: bytes) -> DecodedState`
  - `encode(state: DecodedState, tree: object) -> bytes` (re-encodes `tree`, swaps `hash` in `meta_bytes` in place, rebuilds header/framing)
  - `from_hex(hexstr: str) -> bytes`, `to_hex(blob: bytes) -> str` (uppercase, no whitespace)

- [ ] **Step 1: Add dependencies**

Edit `pyproject.toml` `dependencies` list to include (keep existing entries):

```toml
    "cbor2>=5.6.0",
    "zstandard>=0.22.0",
```

Then run:

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv lock
```

- [ ] **Step 2: Write the failing roundtrip test**

```python
# tests/test_serum_state_codec.py
import binascii, gzip, re, glob, os
import pytest
from ableton_mcp_max import serum_state_codec as sc

FACTORY = "/Library/Audio/Presets/Xfer Records/Serum 2 Presets/Presets"
TEST_ALS = "/Users/ryanrobson/Desktop/serum2_test Project/serum2_idtest.als"

def _als_processor_blob(path):
    raw = gzip.open(path, "rb").read()
    txt = raw.decode("utf-8", "replace")
    m = re.search(r"<ProcessorState[^>]*>(.*?)</ProcessorState>", txt, re.S)
    hexonly = re.sub(r"<[^>]+>", "", re.sub(r"\s", "", m.group(1)))
    return binascii.unhexlify(hexonly[: len(hexonly) // 2 * 2])

@pytest.mark.skipif(not os.path.exists(TEST_ALS), reason="live test set absent")
def test_decode_then_encode_noop_is_tree_equal():
    blob = _als_processor_blob(TEST_ALS)
    st = sc.decode(blob)
    assert "FXRack0" in st.tree
    re_blob = sc.encode(st, st.tree)
    st2 = sc.decode(re_blob)
    assert st2.tree == st.tree
    assert st2.meta["hash"] == sc.hashlib.md5(re_blob[re_blob.find(b"\x28\xb5\x2f\xfd"):]).hexdigest()

@pytest.mark.skipif(not glob.glob(FACTORY + "/**/*.SerumPreset", recursive=True),
                    reason="factory presets absent")
def test_all_factory_presets_roundtrip_tree_equal():
    files = glob.glob(FACTORY + "/**/*.SerumPreset", recursive=True)
    for f in files:
        blob = open(f, "rb").read()
        st = sc.decode(blob)
        st2 = sc.decode(sc.encode(st, st.tree))
        assert st2.tree == st.tree, f
```

- [ ] **Step 3: Run test to verify it fails**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_serum_state_codec.py -q`
Expected: FAIL (ModuleNotFoundError: serum_state_codec).

- [ ] **Step 4: Write the codec**

```python
# ableton_mcp_max/serum_state_codec.py
"""Codec for Serum 2's XferJson plugin-state container (as found in .SerumPreset
files and inside an .als <ProcessorState>/<ControllerState> blob).

Framing (verified): b"XferJson" + b"\\x00" + uint64-LE meta-json-len + meta-json
+ 8-byte header (<II = uint32 uncompressed-cbor-len, uint32 flags=2) + zstd-frame.
meta["hash"] = md5(zstd_blob).hexdigest() (32 hex chars).
"""
import binascii
import hashlib
import json
import struct

import cbor2
import zstandard as zstd

_MAGIC = b"XferJson"
_ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"


class DecodedState(object):
    __slots__ = ("meta", "meta_bytes", "tree")

    def __init__(self, meta, meta_bytes, tree):
        self.meta = meta
        self.meta_bytes = meta_bytes
        self.tree = tree


def from_hex(hexstr):
    h = "".join(hexstr.split())
    return binascii.unhexlify(h[: len(h) // 2 * 2])


def to_hex(blob):
    return binascii.hexlify(blob).decode("ascii").upper()


def decode(blob):
    if blob[:8] != _MAGIC:
        raise ValueError("not an XferJson container")
    jlen = struct.unpack("<Q", blob[9:17])[0]
    meta_bytes = blob[17:17 + jlen]
    meta = json.loads(meta_bytes.decode("utf-8"))
    z = blob.find(_ZSTD_MAGIC, 17 + jlen)
    if z < 0:
        raise ValueError("no zstd blob found")
    cbor = zstd.ZstdDecompressor().decompress(blob[z:], max_output_size=64 * 1024 * 1024)
    tree = cbor2.loads(cbor)
    return DecodedState(meta, meta_bytes, tree)


def encode(state, tree):
    cbor = cbor2.dumps(tree)
    zblob = zstd.ZstdCompressor().compress(cbor)
    new_hash = hashlib.md5(zblob).hexdigest()
    old_hash = state.meta["hash"]
    if len(new_hash) != len(old_hash):
        raise ValueError("hash length mismatch")
    meta_bytes = state.meta_bytes.replace(old_hash.encode("ascii"),
                                          new_hash.encode("ascii"), 1)
    header = struct.pack("<II", len(cbor), 2)
    return (_MAGIC + b"\x00" + struct.pack("<Q", len(meta_bytes))
            + meta_bytes + header + zblob)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_serum_state_codec.py -q`
Expected: PASS (2 passed, or skipped if the factory/live files are absent on this machine).

- [ ] **Step 6: Commit**

```bash
git add ableton_mcp_max/serum_state_codec.py tests/test_serum_state_codec.py pyproject.toml uv.lock
git commit -m "feat: Serum XferJson plugin-state codec"
```

---

### Task 2: FX catalog (factory scan) + serum2_fx.json

**Files:**
- Create: `scripts/build_serum_fx_catalog.py`
- Create: `ableton_mcp_max/param_maps/serum2_fx.json` (generated, committed)
- Create: `ableton_mcp_max/serum_fx_catalog.py` (loader/validator)
- Test: `tests/test_serum_fx_catalog.py`

**Interfaces:**
- Consumes: `serum_state_codec.decode` (Task 1).
- Produces:
  - JSON shape: `{"plugin": "Serum2", "fx_types": {"<int>": {"name": str, "wrapper_key": str, "params": [{"kparam": str, "native_min": float, "native_max": float}], "default_template": {"<kParam>": float}}}}`
  - `load_catalog(path=None) -> dict`
  - `fx_type_info(catalog, fx_type: int) -> dict` (raises KeyError-style ValueError listing valid types)
  - `param_info(catalog, fx_type: int, kparam: str) -> dict` (raises listing valid kparams)
  - `WRAPPER_BY_TYPE` derived helper: `wrapper_key(catalog, fx_type) -> str`

- [ ] **Step 1: Write the scan script**

```python
# scripts/build_serum_fx_catalog.py
"""Decode every factory .SerumPreset and union all FX types/wrappers/params into
ableton_mcp_max/param_maps/serum2_fx.json. Rerunnable. Native ranges are observed
across the factory corpus (approximate; native is source of truth at runtime)."""
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ableton_mcp_max import serum_state_codec as sc

FACTORY = "/Library/Audio/Presets/Xfer Records/Serum 2 Presets/Presets"
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "ableton_mcp_max", "param_maps", "serum2_fx.json")


def _fx_entries(tree):
    for rk in ("FXRack0", "FXRack1", "FXRack2"):
        rack = tree.get(rk) if hasattr(tree, "get") else None
        if not rack:
            continue
        for fx in rack.get("FX", []):
            yield fx


def _wrapper_and_params(fx):
    wrapper = None
    params = {}
    for k, v in fx.items():
        if k == "type":
            continue
        if isinstance(v, dict):
            wrapper = wrapper or k
            pp = v.get("plainParams")
            if isinstance(pp, dict):
                params.update(pp)
    return wrapper, params


def main():
    files = glob.glob(FACTORY + "/**/*.SerumPreset", recursive=True)
    if not files:
        raise SystemExit("no factory presets found at %s" % FACTORY)
    types = {}
    for f in files:
        try:
            tree = sc.decode(open(f, "rb").read()).tree
        except Exception:
            continue
        for fx in _fx_entries(tree):
            t = int(fx.get("type"))
            wrapper, params = _wrapper_and_params(fx)
            slot = types.setdefault(t, {"name": (wrapper or "FX%d" % t).replace("FX", "", 1) or "FX%d" % t,
                                        "wrapper_key": wrapper, "params": {}, "default_template": {}})
            if wrapper and not slot["wrapper_key"]:
                slot["wrapper_key"] = wrapper
            for kp, val in params.items():
                if not isinstance(val, (int, float)):
                    continue
                rng = slot["params"].setdefault(kp, [float(val), float(val)])
                rng[0] = min(rng[0], float(val))
                rng[1] = max(rng[1], float(val))
    out = {"plugin": "Serum2", "fx_types": {}}
    for t, slot in sorted(types.items()):
        out["fx_types"][str(t)] = {
            "name": slot["name"],
            "wrapper_key": slot["wrapper_key"],
            "params": [{"kparam": kp, "native_min": lo, "native_max": hi}
                       for kp, (lo, hi) in sorted(slot["params"].items())],
            "default_template": {},
        }
    with open(OUT, "w") as fh:
        json.dump(out, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print("wrote %s: %d fx types" % (OUT, len(out["fx_types"])))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Generate the catalog**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python scripts/build_serum_fx_catalog.py`
Expected: prints `wrote .../serum2_fx.json: N fx types` (N >= 5; types 3,4,5,7,12 at minimum). Open the JSON and confirm each entry has a non-null `wrapper_key`. If any `default_template` is needed for insert (Task 3), it is filled there using a known-good FX instance's params; for now leave `{}` (insert uses an empty plainParams = Serum defaults).

- [ ] **Step 3: Write the failing loader test**

```python
# tests/test_serum_fx_catalog.py
import os
import pytest
from ableton_mcp_max import serum_fx_catalog as cat

CATALOG = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                       "ableton_mcp_max", "param_maps", "serum2_fx.json")

@pytest.mark.skipif(not os.path.exists(CATALOG), reason="catalog not generated")
def test_load_and_lookup():
    c = cat.load_catalog()
    assert c["plugin"] == "Serum2"
    info = cat.fx_type_info(c, 12)          # FXUtils
    assert info["wrapper_key"] == "FXUtils"
    assert any(p["kparam"] == "kParamWet" for p in info["params"])
    assert cat.wrapper_key(c, 12) == "FXUtils"

def test_unknown_type_lists_valid():
    c = {"plugin": "Serum2", "fx_types": {"12": {"name": "Utils", "wrapper_key": "FXUtils", "params": [], "default_template": {}}}}
    with pytest.raises(ValueError) as e:
        cat.fx_type_info(c, 999)
    assert "12" in str(e.value)
```

- [ ] **Step 4: Run test to verify it fails**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_serum_fx_catalog.py -q`
Expected: FAIL (ModuleNotFoundError: serum_fx_catalog).

- [ ] **Step 5: Write the loader**

```python
# ableton_mcp_max/serum_fx_catalog.py
"""Load + query the Serum FX catalog (param_maps/serum2_fx.json)."""
import json
import os

_DEFAULT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "param_maps", "serum2_fx.json")


def load_catalog(path=None):
    with open(path or _DEFAULT) as fh:
        return json.load(fh)


def fx_type_info(catalog, fx_type):
    key = str(int(fx_type))
    types = catalog["fx_types"]
    if key not in types:
        raise ValueError("unknown fx_type %s; valid: %s"
                         % (key, ", ".join(sorted(types, key=int))))
    return types[key]


def wrapper_key(catalog, fx_type):
    return fx_type_info(catalog, fx_type)["wrapper_key"]


def param_info(catalog, fx_type, kparam):
    info = fx_type_info(catalog, fx_type)
    for p in info["params"]:
        if p["kparam"] == kparam:
            return p
    raise ValueError("unknown param %s for fx_type %s; valid: %s"
                     % (kparam, fx_type, ", ".join(p["kparam"] for p in info["params"])))
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_serum_fx_catalog.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add scripts/build_serum_fx_catalog.py ableton_mcp_max/param_maps/serum2_fx.json ableton_mcp_max/serum_fx_catalog.py tests/test_serum_fx_catalog.py
git commit -m "feat: Serum FX catalog from factory-preset scan"
```

---

### Task 3: FX-tree mutation helpers

**Files:**
- Create: `ableton_mcp_max/serum_fx_utils.py`
- Test: `tests/test_serum_fx_utils.py`

**Interfaces:**
- Consumes: `serum_fx_catalog` (Task 2).
- Produces (all operate on a decoded CBOR `tree` dict in place; raise `ValueError` on bad input):
  - `RACK_KEYS = ("FXRack0", "FXRack1", "FXRack2")`
  - `list_fx(tree) -> list[dict]` items `{rack: int, slot: int, type: int, name: str, enabled: bool, params: dict}`
  - `get_fx_params(tree, rack, slot) -> dict`
  - `set_fx_param(catalog, tree, rack, slot, kparam, native) -> None`
  - `set_fx_enabled(tree, rack, slot, on: bool) -> None`
  - `insert_fx(catalog, tree, rack, index, fx_type) -> None`
  - `remove_fx(tree, rack, slot) -> None`
  - `reorder_fx(tree, rack, from_index, to_index) -> None`
  - Internal: `_rack_list(tree, rack) -> list`, `_fx_wrapper(fx) -> (wrapper_key, plainParams_dict)`, `_plain_params(fx) -> dict` (creates the wrapper/plainParams path if missing).

- [ ] **Step 1: Write failing tests**

```python
# tests/test_serum_fx_utils.py
import pytest
from ableton_mcp_max import serum_fx_utils as fx

CAT = {"plugin": "Serum2", "fx_types": {
    "12": {"name": "Utils", "wrapper_key": "FXUtils", "params": [
        {"kparam": "kParamWet", "native_min": 0.0, "native_max": 100.0}], "default_template": {}},
    "4": {"name": "Delay", "wrapper_key": "FXDelay", "params": [
        {"kparam": "kParamWet", "native_min": 0.0, "native_max": 100.0}], "default_template": {}},
}}

def _tree():
    return {"FXRack0": {"FX": [
        {"type": 12, "FXUtils": {"plainParams": {"kParamWet": 96.7}}, "kUIParamMixOrGain": 0.0}],
        "displayName": "", "plainParams": {}},
        "FXRack1": {"FX": [], "displayName": "", "plainParams": {}},
        "FXRack2": {"FX": [], "displayName": "", "plainParams": {}}}

def test_list_fx():
    items = fx.list_fx(_tree())
    assert items[0]["rack"] == 0 and items[0]["slot"] == 0 and items[0]["type"] == 12
    assert items[0]["params"]["kParamWet"] == 96.7

def test_set_fx_param_in_range():
    t = _tree()
    fx.set_fx_param(CAT, t, 0, 0, "kParamWet", 50.0)
    assert fx.get_fx_params(t, 0, 0)["kParamWet"] == 50.0

def test_set_fx_param_out_of_range_raises():
    t = _tree()
    with pytest.raises(ValueError):
        fx.set_fx_param(CAT, t, 0, 0, "kParamWet", 999.0)

def test_insert_and_remove_fx():
    t = _tree()
    fx.insert_fx(CAT, t, 1, 0, 4)
    assert t["FXRack1"]["FX"][0]["type"] == 4
    assert "FXDelay" in t["FXRack1"]["FX"][0]
    fx.remove_fx(t, 1, 0)
    assert t["FXRack1"]["FX"] == []

def test_reorder_fx():
    t = _tree()
    fx.insert_fx(CAT, t, 0, 1, 4)          # rack0 now [12, 4]
    fx.reorder_fx(t, 0, 0, 1)              # -> [4, 12]
    assert [f["type"] for f in t["FXRack0"]["FX"]] == [4, 12]

def test_set_enabled():
    t = _tree()
    fx.set_fx_enabled(t, 0, 0, False)
    assert fx.get_fx_params(t, 0, 0)["kParamEnable"] == 0.0

def test_bad_rack_slot_raises():
    t = _tree()
    with pytest.raises(ValueError):
        fx.get_fx_params(t, 0, 5)
    with pytest.raises(ValueError):
        fx.get_fx_params(t, 9, 0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_serum_fx_utils.py -q`
Expected: FAIL (ModuleNotFoundError: serum_fx_utils).

- [ ] **Step 3: Write the helpers**

```python
# ableton_mcp_max/serum_fx_utils.py
"""Pure mutation helpers over a decoded Serum CBOR state tree's FX racks.
No IO. Each FX entry is {type:int, <WrapperKey>:{plainParams:{kParam*:native}}}
plus an optional sibling kUIParamMixOrGain. plainParams is sparse (absent key =
Serum default). kParamEnable 0.0/1.0 toggles bypass."""
from ableton_mcp_max import serum_fx_catalog as cat

RACK_KEYS = ("FXRack0", "FXRack1", "FXRack2")


def _rack_list(tree, rack):
    if rack < 0 or rack >= len(RACK_KEYS):
        raise ValueError("rack must be 0..2, got %r" % (rack,))
    node = tree.get(RACK_KEYS[rack]) if hasattr(tree, "get") else None
    if not node:
        node = {"FX": [], "displayName": "", "plainParams": {}}
        tree[RACK_KEYS[rack]] = node
    return node["FX"]


def _fx_at(tree, rack, slot):
    fxs = _rack_list(tree, rack)
    if slot < 0 or slot >= len(fxs):
        raise ValueError("slot %r out of range (rack %d has %d FX)"
                         % (slot, rack, len(fxs)))
    return fxs[slot]


def _fx_wrapper(fx):
    for k, v in fx.items():
        if k != "type" and isinstance(v, dict):
            return k, v
    return None, None


def _plain_params(fx, create_wrapper=None):
    wk, wrapper = _fx_wrapper(fx)
    if wrapper is None:
        if not create_wrapper:
            raise ValueError("fx entry has no wrapper dict")
        wrapper = {}
        fx[create_wrapper] = wrapper
    pp = wrapper.get("plainParams")
    if pp is None:
        pp = {}
        wrapper["plainParams"] = pp
    return pp


def list_fx(tree):
    out = []
    for ri, rk in enumerate(RACK_KEYS):
        node = tree.get(rk) if hasattr(tree, "get") else None
        if not node:
            continue
        for si, fx in enumerate(node.get("FX", [])):
            pp = _plain_params(fx) if _fx_wrapper(fx)[1] else {}
            out.append({"rack": ri, "slot": si, "type": int(fx.get("type")),
                        "name": _fx_wrapper(fx)[0] or "", "enabled": pp.get("kParamEnable", 1.0) != 0.0,
                        "params": dict(pp)})
    return out


def get_fx_params(tree, rack, slot):
    return dict(_plain_params(_fx_at(tree, rack, slot)))


def set_fx_param(catalog, tree, rack, slot, kparam, native):
    fx = _fx_at(tree, rack, slot)
    info = cat.param_info(catalog, int(fx.get("type")), kparam)
    val = float(native)
    if val < info["native_min"] or val > info["native_max"]:
        raise ValueError("%s=%s out of observed range [%s, %s]"
                         % (kparam, val, info["native_min"], info["native_max"]))
    _plain_params(fx)[kparam] = val


def set_fx_enabled(tree, rack, slot, on):
    _plain_params(_fx_at(tree, rack, slot))["kParamEnable"] = 1.0 if on else 0.0


def insert_fx(catalog, tree, rack, index, fx_type):
    info = cat.fx_type_info(catalog, fx_type)
    wk = info["wrapper_key"]
    if not wk:
        raise ValueError("fx_type %s has no wrapper_key in catalog" % fx_type)
    entry = {"type": int(fx_type), wk: {"plainParams": dict(info.get("default_template") or {})}}
    fxs = _rack_list(tree, rack)
    if index < 0 or index > len(fxs):
        raise ValueError("index %r out of range (0..%d)" % (index, len(fxs)))
    fxs.insert(index, entry)


def remove_fx(tree, rack, slot):
    fxs = _rack_list(tree, rack)
    if slot < 0 or slot >= len(fxs):
        raise ValueError("slot %r out of range" % (slot,))
    fxs.pop(slot)


def reorder_fx(tree, rack, from_index, to_index):
    fxs = _rack_list(tree, rack)
    n = len(fxs)
    if not (0 <= from_index < n) or not (0 <= to_index < n):
        raise ValueError("indices out of range (rack has %d FX)" % n)
    fxs.insert(to_index, fxs.pop(from_index))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_serum_fx_utils.py -q`
Expected: PASS (7 passed).

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/serum_fx_utils.py tests/test_serum_fx_utils.py
git commit -m "feat: Serum FX-tree mutation helpers"
```

---

### Task 4: Plugin-state blob navigator

**Files:**
- Modify: `ableton_mcp_max/plugin_config_utils.py` (append `locate_plugin_state`)
- Test: `tests/test_locate_plugin_state.py`

**Interfaces:**
- Consumes: nothing (string navigation, like `locate_param_list`).
- Produces:
  - `locate_plugin_state(full_xml, track_start, track_end, device_index) -> {"processor": (s, e), "controller": (s, e)}` where each tuple brackets the INNER hex text of the device's `<ProcessorState>...</ProcessorState>` / `<ControllerState>...</ControllerState>`. Raises `ValueError` if the device_index-th plugin device or its state tags are not found.
  - `is_serum_state(inner_hex) -> bool` (decodes the container metadata, checks `product == "Serum2"`).

- [ ] **Step 1: Write failing tests**

```python
# tests/test_locate_plugin_state.py
import gzip, os, re
import pytest
from ableton_mcp_max import plugin_config_utils as pcu
from ableton_mcp_max import als_automation_utils as als

TEST_ALS = "/Users/ryanrobson/Desktop/serum2_test Project/serum2_idtest.als"

@pytest.mark.skipif(not os.path.exists(TEST_ALS), reason="live test set absent")
def test_locate_and_identify_serum_state():
    xml = gzip.open(TEST_ALS, "rb").read().decode("utf-8", "replace")
    ts, te = als.find_track_span(xml, 0)
    spans = pcu.locate_plugin_state(xml, ts, te, 0)
    for key in ("processor", "controller"):
        s, e = spans[key]
        inner = xml[s:e]
        assert pcu.is_serum_state(inner)

def test_missing_device_raises():
    xml = "<Tracks><MidiTrack></MidiTrack></Tracks>"
    with pytest.raises(ValueError):
        pcu.locate_plugin_state(xml, 0, len(xml), 0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_locate_plugin_state.py -q`
Expected: FAIL (AttributeError: locate_plugin_state).

- [ ] **Step 3: Append the navigator to plugin_config_utils.py**

```python
# append to ableton_mcp_max/plugin_config_utils.py
import binascii as _binascii
import json as _json
import re as _re
import struct as _struct


def _state_inner_span(full_xml, search_from, search_to, tag):
    m = _re.compile(r"<%s[^>]*>" % tag).search(full_xml, search_from, search_to)
    if not m:
        return None
    close = full_xml.find("</%s>" % tag, m.end(), search_to)
    if close < 0:
        return None
    return (m.end(), close)


def locate_plugin_state(full_xml, track_start, track_end, device_index):
    """Return inner-hex spans of the device_index-th plugin device's
    <ProcessorState> and <ControllerState> within [track_start, track_end).
    A VST3/AU plugin device chain holds exactly one of each."""
    # Plugin devices are <PluginDevice>/<AuPluginDevice>; the state tags appear
    # in document order. We index by occurrence of <ProcessorState>.
    proc_iter = list(_re.finditer(r"<ProcessorState[^>]*>", full_xml[track_start:track_end]))
    if device_index >= len(proc_iter):
        raise ValueError("no plugin ProcessorState #%d in track" % device_index)
    base = track_start
    # Re-scan from the chosen ProcessorState start to bracket both tags for this device.
    proc_start = base + proc_iter[device_index].start()
    proc = _state_inner_span(full_xml, proc_start, track_end, "ProcessorState")
    ctrl = _state_inner_span(full_xml, proc[1], track_end, "ControllerState")
    if proc is None or ctrl is None:
        raise ValueError("ProcessorState/ControllerState not found for device %d"
                         % device_index)
    return {"processor": proc, "controller": ctrl}


def is_serum_state(inner_hex):
    h = "".join(inner_hex.split())
    try:
        blob = _binascii.unhexlify(h[: len(h) // 2 * 2])
        if blob[:8] != b"XferJson":
            return False
        jlen = _struct.unpack("<Q", blob[9:17])[0]
        meta = _json.loads(blob[17:17 + jlen].decode("utf-8"))
        return meta.get("product") == "Serum2"
    except Exception:
        return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_locate_plugin_state.py -q`
Expected: PASS (or the live-set test skips if the file is absent; `test_missing_device_raises` must pass regardless).

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/plugin_config_utils.py tests/test_locate_plugin_state.py
git commit -m "feat: locate Serum ProcessorState/ControllerState blobs in .als"
```

---

### Task 5: Server impl + get_serum_fx (read path)

**Files:**
- Modify: `ableton_mcp_max/server.py` (add `_serum_fx_read_impl`, `_serum_fx_mutate_impl`, and the `get_serum_fx` tool)
- Test: `tests/test_serum_fx_impl.py`

**Interfaces:**
- Consumes: `serum_state_codec`, `serum_fx_utils`, `serum_fx_catalog`, `plugin_config_utils.locate_plugin_state`, `als.find_track_span/read_als/write_als`, `_reload_set` + path helpers (Task 1-4 + existing).
- Produces:
  - `_serum_fx_read_impl(track_index, device_index, *, save_impl, read_als=..., find_track_span=..., resolve_path=..., title_fn=...) -> dict` returns `{"ok": True, "fx": [...], "set_path": path}`.
  - `_serum_fx_mutate_impl(track_index, device_index, mutate_fn, *, reload, save_impl, reload_impl, read_als=..., write_als=..., find_track_span=..., resolve_path=..., title_fn=...) -> dict` where `mutate_fn(catalog, tree)` applies one edit to a decoded tree. Decodes BOTH processor+controller blobs, applies `mutate_fn` to each, re-encodes, splices, writes, reloads. Returns `{"ok", "reloaded", "set_path"}`.
  - `get_serum_fx` MCP tool.

- [ ] **Step 1: Write the failing impl test (offline, seams stubbed)**

```python
# tests/test_serum_fx_impl.py
import gzip, os
import pytest
from ableton_mcp_max import server

TEST_ALS = "/Users/ryanrobson/Desktop/serum2_test Project/serum2_idtest.als"

@pytest.mark.skipif(not os.path.exists(TEST_ALS), reason="live test set absent")
def test_read_impl_lists_fx(tmp_path):
    xml = gzip.open(TEST_ALS, "rb").read().decode("utf-8", "replace")
    res = server._serum_fx_read_impl(
        0, 0,
        save_impl=lambda: {"saved": True},
        read_als=lambda p: xml,
        find_track_span=__import__("ableton_mcp_max.als_automation_utils", fromlist=["x"]).find_track_span,
        resolve_path=lambda: str(TEST_ALS),
        title_fn=lambda: "serum2_idtest")
    assert res["ok"] is True
    assert isinstance(res["fx"], list)

@pytest.mark.skipif(not os.path.exists(TEST_ALS), reason="live test set absent")
def test_mutate_impl_roundtrips_and_writes(tmp_path):
    xml = gzip.open(TEST_ALS, "rb").read().decode("utf-8", "replace")
    written = {}
    def mutate(catalog, tree):
        from ableton_mcp_max import serum_fx_utils as fx
        items = fx.list_fx(tree)
        if items:
            it = items[0]
            # set first param of first fx to its current value (no-op, in range not enforced via catalog here)
            pp = fx.get_fx_params(tree, it["rack"], it["slot"])
            for k, v in pp.items():
                if isinstance(v, float):
                    fx.set_fx_enabled(tree, it["rack"], it["slot"], True)
                    break
    res = server._serum_fx_mutate_impl(
        0, 0, mutate, reload=False,
        save_impl=lambda: {"saved": True},
        reload_impl=lambda p, n: True,
        read_als=lambda p: xml,
        write_als=lambda p, x: written.update(xml=x),
        find_track_span=__import__("ableton_mcp_max.als_automation_utils", fromlist=["x"]).find_track_span,
        resolve_path=lambda: str(TEST_ALS),
        title_fn=lambda: "serum2_idtest")
    assert res["ok"] is True
    assert "xml" in written and len(written["xml"]) > 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_serum_fx_impl.py -q`
Expected: FAIL (AttributeError: _serum_fx_read_impl).

- [ ] **Step 3: Add imports + impls to server.py**

Near the other `from ableton_mcp_max import ...` imports add:

```python
from ableton_mcp_max import serum_state_codec as _ssc
from ableton_mcp_max import serum_fx_utils as _sfx
from ableton_mcp_max import serum_fx_catalog as _sfxcat
```

Add the impls (place them next to `_expose_plugin_impl`):

```python
def _serum_fx_resolve_path(title_fn, resolve_path):
    title = (title_fn or _live_window_title)()
    if is_untitled_title(title):
        raise ValueError("Set is untitled - save it first via save_set_as, then retry.")
    path = (resolve_path or (lambda: _current_set_path(title) or _find_saved_set(title)))()
    if not path:
        raise RuntimeError("Could not resolve the current set's .als path.")
    return path


def _serum_fx_read_impl(track_index, device_index, *, save_impl,
                        read_als=als.read_als, find_track_span=als.find_track_span,
                        resolve_path=None, title_fn=None):
    save_res = save_impl()
    if not save_res.get("saved"):
        return {"ok": False, "error": "save_set failed: %s" % save_res.get("error", save_res)}
    path = _serum_fx_resolve_path(title_fn, resolve_path)
    xml = read_als(path)
    ts, te = find_track_span(xml, track_index)
    spans = pcu.locate_plugin_state(xml, ts, te, device_index)
    s, e = spans["processor"]
    if not pcu.is_serum_state(xml[s:e]):
        return {"ok": False, "set_path": path,
                "error": "device %d on track %d is not a Serum 2 plugin" % (device_index, track_index)}
    blob = _ssc.from_hex(xml[s:e])
    tree = _ssc.decode(blob).tree
    return {"ok": True, "set_path": path, "fx": _sfx.list_fx(tree)}


def _serum_fx_mutate_impl(track_index, device_index, mutate_fn, *, reload,
                          save_impl, reload_impl,
                          read_als=als.read_als, write_als=als.write_als,
                          find_track_span=als.find_track_span,
                          resolve_path=None, title_fn=None):
    save_res = save_impl()
    if not save_res.get("saved"):
        return {"ok": False, "reloaded": False,
                "error": "save_set failed: %s" % save_res.get("error", save_res)}
    path = _serum_fx_resolve_path(title_fn, resolve_path)
    xml = read_als(path)
    ts, te = find_track_span(xml, track_index)
    spans = pcu.locate_plugin_state(xml, ts, te, device_index)
    if not pcu.is_serum_state(xml[spans["processor"][0]:spans["processor"][1]]):
        return {"ok": False, "reloaded": False, "set_path": path,
                "error": "device %d on track %d is not a Serum 2 plugin" % (device_index, track_index)}
    catalog = _sfxcat.load_catalog()
    # Patch processor first, then controller; splice high-offset span first so the
    # earlier span's offsets stay valid.
    edits = []
    for key in ("processor", "controller"):
        s, e = spans[key]
        st = _ssc.decode(_ssc.from_hex(xml[s:e]))
        mutate_fn(catalog, st.tree)
        new_hex = _ssc.to_hex(_ssc.encode(st, st.tree))
        edits.append((s, e, new_hex))
    for s, e, new_hex in sorted(edits, key=lambda t: t[0], reverse=True):
        xml = xml[:s] + new_hex + xml[e:]
    write_als(path, xml)
    reloaded = False
    if reload:
        reloaded = bool(reload_impl(path, set_name_from_path(path)))
    return {"ok": True, "reloaded": reloaded, "set_path": path}
```

Add the read-only tool (place in the "Plugins (VST/AU)" tool group):

```python
@mcp.tool()
def get_serum_fx(track_index: int, device_index: int = 0) -> dict:
    """List the FX in a Serum 2 instance's three FX racks (read-only).

    Saves the set, then decodes the device's plugin state from the .als on disk
    (no reload). Returns {ok, set_path, fx:[{rack, slot, type, name, enabled,
    params}]}. params are native Serum units. State authoring only - FX are NOT
    LOM-automatable knobs; use set_serum_fx_param etc. to change them."""
    return _serum_fx_read_impl(track_index, device_index,
                               save_impl=lambda: save_set(""))
```

- [ ] **Step 4: Run tests + server import**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_serum_fx_impl.py -q && uv run python -c "import ableton_mcp_max.server"`
Expected: PASS (or skip if live set absent) and clean import.

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/server.py tests/test_serum_fx_impl.py
git commit -m "feat: get_serum_fx read path + Serum FX server impls"
```

---

### Task 6: Mutator tools

**Files:**
- Modify: `ableton_mcp_max/server.py` (add `set_serum_fx_param`, `insert_serum_fx`, `remove_serum_fx`, `reorder_serum_fx`)
- Test: `tests/test_serum_fx_tools.py`

**Interfaces:**
- Consumes: `_serum_fx_mutate_impl` (Task 5), `serum_fx_utils` (Task 3).
- Produces: 4 MCP tools, each building a `mutate_fn` closure and delegating to `_serum_fx_mutate_impl`.

- [ ] **Step 1: Write the failing test (mutate_fn closures, no IO)**

```python
# tests/test_serum_fx_tools.py
from ableton_mcp_max import serum_fx_utils as fx

CAT = {"plugin": "Serum2", "fx_types": {
    "12": {"name": "Utils", "wrapper_key": "FXUtils",
           "params": [{"kparam": "kParamWet", "native_min": 0.0, "native_max": 100.0}],
           "default_template": {}},
    "4": {"name": "Delay", "wrapper_key": "FXDelay",
          "params": [{"kparam": "kParamWet", "native_min": 0.0, "native_max": 100.0}],
          "default_template": {}}}}

def _tree():
    return {"FXRack0": {"FX": [{"type": 12, "FXUtils": {"plainParams": {"kParamWet": 96.7}}}],
                        "displayName": "", "plainParams": {}},
            "FXRack1": {"FX": [], "displayName": "", "plainParams": {}},
            "FXRack2": {"FX": [], "displayName": "", "plainParams": {}}}

def test_set_param_closure():
    t = _tree()
    (lambda catalog, tree: fx.set_fx_param(catalog, tree, 0, 0, "kParamWet", 25.0))(CAT, t)
    assert fx.get_fx_params(t, 0, 0)["kParamWet"] == 25.0

def test_insert_closure():
    t = _tree()
    (lambda catalog, tree: fx.insert_fx(catalog, tree, 1, 0, 4))(CAT, t)
    assert t["FXRack1"]["FX"][0]["type"] == 4
```

(These lock the closure semantics the tools must use; the tools themselves are exercised live in Task 7.)

- [ ] **Step 2: Run test to verify it fails**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_serum_fx_tools.py -q`
Expected: FAIL only if a typo; if `serum_fx_utils` from Task 3 exists it may PASS immediately - that is acceptable (these assert the closure contract). If it errors, fix the closure call.

- [ ] **Step 3: Add the 4 tools to server.py**

```python
@mcp.tool()
def set_serum_fx_param(track_index: int, rack: int, slot: int, kparam: str,
                       value: float, device_index: int = 0, reload: bool = True) -> dict:
    """Set one Serum FX parameter (native units) on rack (0-2) / slot.

    Patches the plugin state in the .als and reloads the set in place. value is a
    native Serum value (e.g. kParamWet in %, kParamFreq in Hz); validated against
    the catalog's observed range. State authoring - not a live LOM knob. Returns
    {ok, reloaded, set_path}."""
    def mutate(catalog, tree):
        _sfx.set_fx_param(catalog, tree, rack, slot, kparam, value)
    return _serum_fx_mutate_impl(track_index, device_index, mutate, reload=reload,
                                 save_impl=lambda: save_set(""),
                                 reload_impl=lambda p, n: _reload_set(p, n))


@mcp.tool()
def insert_serum_fx(track_index: int, rack: int, index: int, fx_type: int,
                    device_index: int = 0, reload: bool = True) -> dict:
    """Insert an FX of catalog fx_type into a Serum rack (0-2) at index.

    fx_type ints come from get_serum_fx / the serum2_fx catalog. New FX uses
    Serum defaults (empty plainParams). Patches the .als and reloads. Returns
    {ok, reloaded, set_path}."""
    def mutate(catalog, tree):
        _sfx.insert_fx(catalog, tree, rack, index, fx_type)
    return _serum_fx_mutate_impl(track_index, device_index, mutate, reload=reload,
                                 save_impl=lambda: save_set(""),
                                 reload_impl=lambda p, n: _reload_set(p, n))


@mcp.tool()
def remove_serum_fx(track_index: int, rack: int, slot: int,
                    device_index: int = 0, reload: bool = True) -> dict:
    """Remove the FX at rack (0-2) / slot from a Serum instance. Reloads the set.
    Returns {ok, reloaded, set_path}."""
    def mutate(catalog, tree):
        _sfx.remove_fx(tree, rack, slot)
    return _serum_fx_mutate_impl(track_index, device_index, mutate, reload=reload,
                                 save_impl=lambda: save_set(""),
                                 reload_impl=lambda p, n: _reload_set(p, n))


@mcp.tool()
def reorder_serum_fx(track_index: int, rack: int, from_index: int, to_index: int,
                     bypass: bool = None, device_index: int = 0,
                     reload: bool = True) -> dict:
    """Move an FX within a Serum rack (0-2) from from_index to to_index. If bypass
    is not None, instead toggle the FX at from_index on/off (bypass=True disables).
    Reloads the set. Returns {ok, reloaded, set_path}."""
    def mutate(catalog, tree):
        if bypass is not None:
            _sfx.set_fx_enabled(tree, rack, from_index, not bypass)
        else:
            _sfx.reorder_fx(tree, rack, from_index, to_index)
    return _serum_fx_mutate_impl(track_index, device_index, mutate, reload=reload,
                                 save_impl=lambda: save_set(""),
                                 reload_impl=lambda p, n: _reload_set(p, n))
```

- [ ] **Step 4: Run full suite + server import**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q && uv run python -c "import ableton_mcp_max.server"`
Expected: PASS (whole suite green), clean import.

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/server.py tests/test_serum_fx_tools.py
git commit -m "feat: Serum FX mutator tools (set param / insert / remove / reorder)"
```

---

### Task 7: Live verification (manual)

**Files:** none (manual checklist against Live 12.4 Suite via the AbletonDev working-tree tools). Requires a Claude Code restart so AbletonDev loads the 5 new tools.

**Goal:** Confirm a patched ProcessorState+ControllerState actually changes the reloaded FX sound, and settle whether `Vst3Preset` also needs patching.

- [ ] **Step 1: Prepare** - In Live, load a factory Serum 2 preset that has audible FX (e.g. a pad with Reverb/Delay) onto a regular track. `save_set_as` to a named scratch set. Note the track index.

- [ ] **Step 2: Read** - `get_serum_fx(track_index)`. Expected: `ok:true`, `fx` lists the racks/slots with types matching the preset (cross-check against the catalog names).

- [ ] **Step 3: Set a param** - Pick an audible FX param (e.g. the Utility/Reverb `kParamWet`). `set_serum_fx_param(track_index, rack, slot, "kParamWet", <clearly different value>)`. Expected: `ok:true, reloaded:true`. After reload, confirm in Serum's GUI the FX knob moved AND the sound changed. If the GUI/sound did NOT change but the `.als` shows the new value, the `Vst3Preset` blob is authoritative: extend `_serum_fx_mutate_impl` to also patch `Vst3Preset` (same decode/mutate/encode), re-run.

- [ ] **Step 4: Insert** - `insert_serum_fx(track_index, rack=1, index=0, fx_type=<a Delay type from catalog>)`. Expected: `reloaded:true`; Serum shows the new FX in that rack.

- [ ] **Step 5: Remove + reorder + bypass** - exercise `remove_serum_fx`, `reorder_serum_fx` (move and `bypass=True`). Confirm each reflects in Serum.

- [ ] **Step 6: Clean up** - remove the scratch device/track; do not save over a real set. Record results (which blobs were authoritative) in `PROGRESS.md` and the `ableton-mcp` note + memory.

- [ ] **Step 7: Commit any fix** (only if Step 3 forced a `Vst3Preset` change)

```bash
git add ableton_mcp_max/server.py
git commit -m "fix: also patch Vst3Preset blob for Serum FX state"
```

---

### Task 8: Docs, version bump, ship

**Files:**
- Modify: `pyproject.toml`, `.claude-plugin/plugin.json` (version), `uv.lock`
- Modify: `docs/index.md` (hardcoded tool/category counts - 5 spots), `README.md` (line ~7 count)
- Regenerate: `docs/tools/`, `docs/tools/index.md`, `commands/tool-index.md` via the scripts
- Modify: `PROGRESS.md`

**Interfaces:** none (release mechanics).

- [ ] **Step 1: Bump version** - Set the next version (check `gh release list` + `git log <latest-tag>..origin/main` for drift; Release 1 shipped v0.24.0, so this is likely v0.25.0) in `pyproject.toml` and `.claude-plugin/plugin.json`, then:

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv lock
```

- [ ] **Step 2: Regenerate tool docs**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python scripts/gen_docs_site.py
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python scripts/build_tool_index.py
```

Expected: tool count now 155 (150 + 5). Confirm `commands/tool-index.md` lists the 5 new tools under "Plugins (VST/AU)".

- [ ] **Step 3: Hand-bump hardcoded counts** - In `docs/index.md` update the 5 hardcoded spots (description, tagline, two `stats__num`, the "exposes the N @mcp.tool()" line) from 150 to 155. In `README.md` update the "reference for all N tools" count. Verify:

```bash
grep -n "150\|151" docs/index.md README.md
```

Expected: no stale 150 references remain for tool count.

- [ ] **Step 4: Update PROGRESS.md** - Mark Release 2 FX path shipped (tools, version, the live-verified blob decision from Task 7).

- [ ] **Step 5: Commit + tag + marketplace**

```bash
git add -A && git commit -m "docs: Release 2 Serum FX control vX.Y.Z (155 tools)"
gh api user --jq .login   # must print ringo380
gh release create vX.Y.Z --target main --title vX.Y.Z --notes "Serum 2 FX rack control (set/insert/remove/reorder/get)."
```

Then in the marketplace repo `ringo380/robworks-claude-code-plugins`: bump the `ableton` `ref` to `vX.Y.Z`, run `node scripts/build-readme.js`, commit, push. Verify the chain: local `main` == `origin/main` == `git ls-remote --tags origin vX.Y.Z` commit, and the marketplace ref is pushed.

---

## Self-Review notes

- **Spec coverage:** codec (Task 1), catalog/scan (Task 2), fx-tree authoring incl. insert/remove/reorder/bypass (Task 3), navigator for both blobs (Task 4), read tool (Task 5), 4 mutator tools (Task 6), live verification of the processor/controller/Vst3Preset risk (Task 7), ship incl. hand-bumped counts (Task 8). All spec sections covered.
- **Type consistency:** `decode`/`encode`/`DecodedState`, `locate_plugin_state` return `{"processor","controller"}` tuples, `set_fx_param(catalog, tree, rack, slot, kparam, native)`, `_serum_fx_mutate_impl(..., mutate_fn(catalog, tree), ...)` used consistently across Tasks 1-6.
- **Native ranges** are observed-from-factory and validated in `set_fx_param`; if live testing finds a legitimate value rejected, widen the catalog range (note in Task 7 cleanup) rather than removing validation.
