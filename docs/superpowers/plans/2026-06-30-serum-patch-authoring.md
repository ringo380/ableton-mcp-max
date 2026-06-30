# Serum full-instrument patch authoring (Release 3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Author a complete Serum 2 patch from scratch by patching the whole Serum CBOR state tree in the live `.als` - oscillator params + mode + wavetable, filters, envelopes, LFOs, the mod matrix, and macros - via the proven Release 2 ProcessorState-patch + reload-in-place mechanism.

**Architecture:** Reuse the Release 2 read/mutate scaffolding (`_serum_fx_read_impl` / `_serum_fx_mutate_impl` in `server.py`, which decode the device's `<ProcessorState>` XferJson blob, run a `mutate_fn(catalog, tree)`, re-encode, and reload). Add a new pure module `serum_patch_utils.py` with per-module read/set helpers over the decoded tree, a `serum2_patch.json` friendly-name catalog (loaded by `serum_patch_catalog.py`), granular per-module tools, and a declarative `create_serum_patch`. The processor-only patch is already proven sufficient (Release 2: a Wet change survived a real reload with no controller patch).

**Tech Stack:** Python (server side, `uv`), `cbor2` + `zstandard` (via existing `serum_state_codec`), FastMCP `@mcp.tool()`, pytest (offline). Remote Script is NOT touched.

## Global Constraints

- `*_utils.py` and catalog modules are imported by `server.py` ONLY; never by the Remote Script. All resolve/validate/clamp happens server-side. (CLAUDE.md architecture rule.)
- Processor-only patch: mutate `<ProcessorState>` ONLY; leave `<ControllerState>`/`<Vst3Preset>` untouched (Release 2 proved sufficient).
- `plainParams` is sparse: absent key = Serum default. Setting a value inserts/updates a `kParam*` key; never write a full param set.
- Native units everywhere (like the Release 2 FX tools): tool params are native Serum values, range-validated against the catalog's observed min/max.
- Offline gate before any "done" claim: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q` + `uv run python -c "import ableton_mcp_max.server"`. No CI; do NOT reformat existing files to ruff style.
- ASCII only in source and JSON (no Unicode); use `%`-formatting style consistent with the file being edited.
- Tool docstrings follow the Release 2 style: one-line summary, then Parameters, then `Returns JSON {ok, data:{...}}`.
- No AI attribution in any commit message (public-repo rule).
- Tool-count bookkeeping at ship time is MANUAL: `docs/index.md` (5 hardcoded spots) and `README.md:7` are not touched by the regen scripts.

---

### Task 0: Spike - confirm wavetable storage + mod-matrix Rosetta (research, gates Tasks 3 & 6)

This task produces a findings file; it has no test cycle. It resolves the two genuine unknowns before any code that depends on them is written.

**Files:**
- Create: `.vst-harvest-local/release3_spike_findings.md` (scratch, not committed)

**Interfaces:**
- Produces (consumed by Tasks 1, 3, 6): the wavetable-storage verdict (path-ref vs embedded-binary vs defer), the `WTOsc{n}` node layout for a WT-mode oscillator, the oscillator-mode enum int values for `kParamType`, and a verified mod-source / mod-dest ID table (`source:[moduleID, idx]` meaning + `destModuleID`/`destModuleParamID`/`destModuleParamName`/`destModuleTypeString` for several real routed presets).

- [ ] **Step 1: Locate a WT-based factory preset.** Find factory `.SerumPreset` files (the Release 2 work scanned 791). List candidates:

```bash
cd /Users/ryanrobson/git/ableton-mcp-max
find ~ -name "*.SerumPreset" 2>/dev/null | head -20
# Also check the harvest dir / any path recorded in serum_fx_path-design or PROGRESS for the 791-preset scan root.
grep -rn "SerumPreset\|factory" docs/superpowers/specs/2026-06-28-serum-fx-path-design.md | head
```

- [ ] **Step 2: Decode candidates and find one whose `Oscillator0.plainParams.kParamType` selects WT mode and whose `WTOsc0` is non-empty.**

```python
# scratchpad script; run with: PATH=... uv run python <script>
import glob, json
from ableton_mcp_max import serum_state_codec as ssc
for p in glob.glob("<FACTORY_ROOT>/**/*.SerumPreset", recursive=True)[:200]:
    tree = ssc.decode(open(p,"rb").read()).tree
    osc0 = tree.get("Oscillator0", {})
    wt = osc0.get("WTOsc0", {})
    if wt and wt != {"plainParams": {}}:
        print(p)
        print("  Oscillator0.plainParams:", osc0.get("plainParams"))
        print("  WTOsc0 keys:", list(wt.keys()))
        for k, v in wt.items():
            kind = (("dict[%d]" % len(v)) if isinstance(v, dict)
                    else ("list[%d]" % len(v)) if isinstance(v, list)
                    else ("str[%d]" % len(v)) if isinstance(v, str) else type(v).__name__)
            print("    %s: %s" % (k, kind))
        break
```

- [ ] **Step 3: Determine wavetable storage.** From the WT-mode preset, inspect `WTOsc0` for either (a) a path/name string field referencing a `.wav`/wavetable file, or (b) an embedded binary/base64 table blob. Record the verdict:
  - If a **path/name reference** exists and no large embedded blob: `set_serum_wavetable` writes that string (path-ref approach). Capture the exact key name and a couple of real factory values.
  - If the table is **embedded binary**: capture the embedding key + encoding; decide path-ref-only for v1 and defer embed (per spec degrade rule).
  - Capture the `kParamType` int for each mode by decoding presets known to use WT vs Sample vs MultiSample (compare `Oscillator0.plainParams.kParamType`).

- [ ] **Step 4: Verify the mod-matrix Rosetta.** Decode 3-4 presets that have active mod routes (non-default `ModSlot{n}`). Record for each routed slot: `source` (list `[moduleID, idx]`), and the dest fields (`destModuleID`, `destModuleParamID`, `destModuleParamName`, `destModuleTypeString`) if present, plus `plainParams.kParamAmount`. Cross-check the IDs against `ableton_mcp_max/param_maps/serum2.json` (the 128-param id map) and the memory's module-base scheme (osc 1M, filter 2M, env 3M, lfo 4M, macro 7M, routing 9M). Confirm how a free slot is identified (e.g. `source == [0,0]` / absent dest).

- [ ] **Step 5: Write `release3_spike_findings.md`** with: wavetable verdict + exact keys/values, the `kParamType` mode enum, the mod-source table (friendly name -> moduleID), the mod-dest table (friendly name -> {moduleID, paramID, paramName, typeString}), and the free-slot predicate. This file is the input to Tasks 1, 3, and 6.

- [ ] **Step 6: Commit the spec note only if any spec assumption changed.** If the spike contradicts the spec (e.g. wavetable must be deferred), edit `docs/superpowers/specs/2026-06-30-serum-patch-authoring-design.md` Risks section to record the resolved decision, then:

```bash
git add docs/superpowers/specs/2026-06-30-serum-patch-authoring-design.md
git commit -m "docs: record Release 3 spike findings (wavetable + mod-matrix)"
```

---

### Task 1: Catalog generator + `serum_patch_catalog.py` loader

**Files:**
- Create: `scripts/build_serum_patch_catalog.py` (offline scan -> JSON)
- Create: `ableton_mcp_max/param_maps/serum2_patch.json`
- Create: `ableton_mcp_max/serum_patch_catalog.py`
- Test: `tests/test_serum_patch_catalog.py`

**Interfaces:**
- Consumes (from Task 0): the `kParamType` mode enum, mod-source table, mod-dest table.
- Produces (consumed by Tasks 2-6):
  - `serum_patch_catalog.load_catalog(path=None) -> dict` with shape:
    ```
    {"plugin":"Serum2",
     "modules":{
        "oscillator":{"count":5,"node":"Oscillator{n}","params":{<friendly>:{"kparam":str,"native_min":float,"native_max":float}},"modes":{<name>:int}},
        "filter":   {"count":2,"node":"VoiceFilter{n}","params":{...}},
        "envelope": {"count":4,"node":"Env{n}","params":{...}},
        "lfo":      {"count":10,"node":"LFO{n}","params":{...}},
        "macro":    {"count":8,"node":"Macro{n}"}},
     "mod_sources":{<friendly>:int},
     "mod_dests":{<friendly>:{"moduleID":int,"paramID":int,"paramName":str,"typeString":str}}}
    ```
  - `serum_patch_catalog.module_info(catalog, module_type) -> dict` (raises ValueError on unknown type, listing valid types).
  - `serum_patch_catalog.param_info(catalog, module_type, name) -> {"kparam","native_min","native_max"}`. `name` matches either the friendly name OR the raw `kParam*` key. Raises ValueError listing valid names.
  - `serum_patch_catalog.node_key(catalog, module_type, index) -> str` (e.g. `"Oscillator2"`), validating `0 <= index < count`.

- [ ] **Step 1: Write the catalog builder.** Friendly names are derived mechanically (strip the `kParam` prefix), observed ranges come from the factory scan. `<FACTORY_ROOT>` is the scan root confirmed in Task 0.

```python
# scripts/build_serum_patch_catalog.py
"""Scan factory .SerumPreset files and emit param_maps/serum2_patch.json.
Friendly name = kParam* with the 'kParam' prefix stripped. Ranges are the
observed min/max across all scanned presets. Mode enum + mod tables come from
the Task 0 spike findings (paste the verified values into MODES/MOD_SOURCES/
MOD_DESTS below)."""
import glob, json, os, sys

from ableton_mcp_max import serum_state_codec as ssc

MODULE_NODES = {
    "oscillator": ("Oscillator%d", 5),
    "filter": ("VoiceFilter%d", 2),
    "envelope": ("Env%d", 4),
    "lfo": ("LFO%d", 10),
}
# Paste verified values from .vst-harvest-local/release3_spike_findings.md:
MODES = {}        # e.g. {"wt": 0, "sample": 1, "multisample": 2, ...}
MOD_SOURCES = {}  # e.g. {"env1": 25, ...}
MOD_DESTS = {}    # e.g. {"filter1_freq": {"moduleID":..,"paramID":..,"paramName":..,"typeString":..}, ...}


def friendly(kparam):
    return kparam[6:] if kparam.startswith("kParam") else kparam


def scan(root):
    ranges = {m: {} for m in MODULE_NODES}  # module -> kparam -> [min,max]
    files = glob.glob(os.path.join(root, "**", "*.SerumPreset"), recursive=True)
    for p in files:
        try:
            tree = ssc.decode(open(p, "rb").read()).tree
        except Exception:
            continue
        for m, (fmt, count) in MODULE_NODES.items():
            for n in range(count):
                node = tree.get(fmt % n)
                if not isinstance(node, dict):
                    continue
                for k, v in node.get("plainParams", {}).items():
                    if not isinstance(v, (int, float)):
                        continue
                    cur = ranges[m].setdefault(k, [float(v), float(v)])
                    cur[0] = min(cur[0], float(v))
                    cur[1] = max(cur[1], float(v))
    return ranges, len(files)


def build(root):
    ranges, nfiles = scan(root)
    modules = {}
    for m, (fmt, count) in MODULE_NODES.items():
        params = {}
        for k, (lo, hi) in sorted(ranges[m].items()):
            params[friendly(k)] = {"kparam": k, "native_min": lo, "native_max": hi}
        entry = {"count": count, "node": fmt.replace("%d", "{n}"), "params": params}
        if m == "oscillator":
            entry["modes"] = MODES
        modules[m] = entry
    modules["macro"] = {"count": 8, "node": "Macro{n}"}
    return {"plugin": "Serum2", "scanned_presets": nfiles, "modules": modules,
            "mod_sources": MOD_SOURCES, "mod_dests": MOD_DESTS}


if __name__ == "__main__":
    root = sys.argv[1]
    out = os.path.join(os.path.dirname(__file__), "..", "ableton_mcp_max",
                       "param_maps", "serum2_patch.json")
    cat = build(root)
    with open(out, "w") as fh:
        json.dump(cat, fh, indent=1, sort_keys=True)
    print("wrote %s (%d presets, modules=%s)"
          % (out, cat["scanned_presets"], list(cat["modules"])))
```

- [ ] **Step 2: Run the builder** (after pasting Task 0 spike values into MODES/MOD_SOURCES/MOD_DESTS):

```bash
cd /Users/ryanrobson/git/ableton-mcp-max
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python scripts/build_serum_patch_catalog.py <FACTORY_ROOT>
```
Expected: `wrote .../serum2_patch.json (<N> presets, modules=['oscillator','filter','envelope','lfo','macro'])` with N in the hundreds.

- [ ] **Step 3: Write the failing loader test.**

```python
# tests/test_serum_patch_catalog.py
import pytest
from ableton_mcp_max import serum_patch_catalog as pc

def _cat():
    return {"plugin": "Serum2", "modules": {
        "oscillator": {"count": 5, "node": "Oscillator{n}",
                       "params": {"Volume": {"kparam": "kParamVolume",
                                             "native_min": 0.0, "native_max": 1.0}},
                       "modes": {"wt": 0}},
        "macro": {"count": 8, "node": "Macro{n}"}},
        "mod_sources": {"env1": 25}, "mod_dests": {}}

def test_module_info_ok():
    assert pc.module_info(_cat(), "oscillator")["count"] == 5

def test_module_info_unknown_raises():
    with pytest.raises(ValueError):
        pc.module_info(_cat(), "nope")

def test_param_info_by_friendly_and_kparam():
    c = _cat()
    assert pc.param_info(c, "oscillator", "Volume")["kparam"] == "kParamVolume"
    assert pc.param_info(c, "oscillator", "kParamVolume")["kparam"] == "kParamVolume"

def test_param_info_unknown_raises():
    with pytest.raises(ValueError):
        pc.param_info(_cat(), "oscillator", "Bogus")

def test_node_key_and_bounds():
    assert pc.node_key(_cat(), "oscillator", 2) == "Oscillator2"
    with pytest.raises(ValueError):
        pc.node_key(_cat(), "oscillator", 5)

def test_real_catalog_loads():
    cat = pc.load_catalog()
    assert cat["plugin"] == "Serum2"
    assert set(["oscillator", "filter", "envelope", "lfo", "macro"]).issubset(cat["modules"])
```

- [ ] **Step 4: Run it to verify failure.**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_serum_patch_catalog.py -q
```
Expected: FAIL with `ModuleNotFoundError: ableton_mcp_max.serum_patch_catalog`.

- [ ] **Step 5: Write the loader.**

```python
# ableton_mcp_max/serum_patch_catalog.py
"""Load + query the Serum patch catalog (param_maps/serum2_patch.json)."""
import json
import os

_DEFAULT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "param_maps", "serum2_patch.json")


def load_catalog(path=None):
    with open(path or _DEFAULT) as fh:
        return json.load(fh)


def module_info(catalog, module_type):
    mods = catalog["modules"]
    if module_type not in mods:
        raise ValueError("unknown module type %r; valid: %s"
                         % (module_type, ", ".join(sorted(mods))))
    return mods[module_type]


def node_key(catalog, module_type, index):
    info = module_info(catalog, module_type)
    count = info["count"]
    if index < 0 or index >= count:
        raise ValueError("%s index %r out of range (0..%d)"
                         % (module_type, index, count - 1))
    return info["node"].replace("{n}", str(index))


def param_info(catalog, module_type, name):
    info = module_info(catalog, module_type)
    params = info.get("params", {})
    if name in params:
        return params[name]
    for friendly, p in params.items():
        if p["kparam"] == name:
            return p
    raise ValueError("unknown param %r for %s; valid: %s"
                     % (name, module_type, ", ".join(sorted(params))))
```

- [ ] **Step 6: Run tests to verify they pass.**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_serum_patch_catalog.py -q
```
Expected: PASS (6 tests).

- [ ] **Step 7: Commit.**

```bash
git add scripts/build_serum_patch_catalog.py ableton_mcp_max/param_maps/serum2_patch.json ableton_mcp_max/serum_patch_catalog.py tests/test_serum_patch_catalog.py
git commit -m "feat: Serum patch catalog (serum2_patch.json) + loader"
```

---

### Task 2: `serum_patch_utils.py` - plainParams modules (osc/filter/env/lfo/macro) read + set

**Files:**
- Create: `ableton_mcp_max/serum_patch_utils.py`
- Test: `tests/test_serum_patch_utils.py`

**Interfaces:**
- Consumes: `serum_patch_catalog` (`module_info`, `node_key`, `param_info`).
- Produces (consumed by Tasks 4, 5):
  - `summarize(catalog, tree) -> dict` - per-module friendly summary: `{"oscillators":[{index,mode,params}], "filters":[...], "envelopes":[...], "lfos":[...], "macros":[{index,name,value}]}`. Reads only present nodes; sparse params reported as-is.
  - `set_module_params(catalog, tree, module_type, index, params) -> None` - for module_type in oscillator/filter/envelope/lfo; `params` is `{name: native}` (friendly or kParam); range-validated; writes into `tree[node].plainParams`.
  - `set_oscillator_mode(catalog, tree, index, mode) -> None` - sets `Oscillator{index}.plainParams.kParamType` to the catalog's mode int.
  - `set_macro(catalog, tree, index, value, name=None) -> None` - sets `Macro{index}.plainParams.kParamValue` (range 0..100 observed; validated if catalog has it, else 0..100) and optionally `Macro{index}.name`.

- [ ] **Step 1: Write the failing tests.**

```python
# tests/test_serum_patch_utils.py
import pytest
from ableton_mcp_max import serum_patch_utils as pu

CAT = {"plugin": "Serum2", "modules": {
    "oscillator": {"count": 5, "node": "Oscillator{n}",
                   "params": {"Volume": {"kparam": "kParamVolume", "native_min": 0.0, "native_max": 1.0},
                              "Pan": {"kparam": "kParamPan", "native_min": -1.0, "native_max": 1.0}},
                   "modes": {"wt": 0, "multisample": 2}},
    "filter": {"count": 2, "node": "VoiceFilter{n}",
               "params": {"Freq": {"kparam": "kParamFreq", "native_min": 0.0, "native_max": 1.0}}},
    "envelope": {"count": 4, "node": "Env{n}",
                 "params": {"Attack": {"kparam": "kParamAttack", "native_min": 0.0, "native_max": 16.0}}},
    "lfo": {"count": 10, "node": "LFO{n}",
            "params": {"Rate": {"kparam": "kParamRate", "native_min": 0.0, "native_max": 1.0}}},
    "macro": {"count": 8, "node": "Macro{n}"}},
    "mod_sources": {}, "mod_dests": {}}

def _tree():
    return {"Oscillator0": {"plainParams": {"kParamVolume": 0.5, "kParamType": 0}},
            "VoiceFilter0": {"plainParams": {}},
            "Env0": {"plainParams": {}},
            "LFO0": {"plainParams": {}},
            "Macro0": {"name": "HIGH", "plainParams": {"kParamValue": 56.0}}}

def test_set_param_friendly_name():
    t = _tree()
    pu.set_module_params(CAT, t, "oscillator", 0, {"Volume": 0.8})
    assert t["Oscillator0"]["plainParams"]["kParamVolume"] == 0.8

def test_set_param_kparam_name():
    t = _tree()
    pu.set_module_params(CAT, t, "oscillator", 0, {"kParamPan": -0.5})
    assert t["Oscillator0"]["plainParams"]["kParamPan"] == -0.5

def test_set_param_out_of_range_raises():
    t = _tree()
    with pytest.raises(ValueError):
        pu.set_module_params(CAT, t, "oscillator", 0, {"Volume": 9.0})

def test_set_param_creates_node_when_absent():
    t = _tree()
    pu.set_module_params(CAT, t, "filter", 1, {"Freq": 0.3})
    assert t["VoiceFilter1"]["plainParams"]["kParamFreq"] == 0.3

def test_set_oscillator_mode():
    t = _tree()
    pu.set_oscillator_mode(CAT, t, 0, "multisample")
    assert t["Oscillator0"]["plainParams"]["kParamType"] == 2

def test_set_oscillator_mode_unknown_raises():
    t = _tree()
    with pytest.raises(ValueError):
        pu.set_oscillator_mode(CAT, t, 0, "bogus")

def test_set_macro_value_and_name():
    t = _tree()
    pu.set_macro(CAT, t, 0, 25.0, name="CUTOFF")
    assert t["Macro0"]["plainParams"]["kParamValue"] == 25.0
    assert t["Macro0"]["name"] == "CUTOFF"

def test_summarize_reports_present_modules():
    s = pu.summarize(CAT, _tree())
    osc0 = [o for o in s["oscillators"] if o["index"] == 0][0]
    assert osc0["params"].get("kParamVolume") == 0.5
    mac0 = [m for m in s["macros"] if m["index"] == 0][0]
    assert mac0["name"] == "HIGH" and mac0["value"] == 56.0
```

- [ ] **Step 2: Run to verify failure.**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_serum_patch_utils.py -q
```
Expected: FAIL with `ModuleNotFoundError: ableton_mcp_max.serum_patch_utils`.

- [ ] **Step 3: Write the module.**

```python
# ableton_mcp_max/serum_patch_utils.py
"""Pure read/set helpers over a decoded Serum CBOR state tree's instrument
modules (oscillators, filters, envelopes, LFOs, macros). No IO. plainParams is
sparse (absent key = Serum default); setting a value inserts/updates a kParam*.
FX live in serum_fx_utils; mod routes are added in this module (Task 3)."""
from ableton_mcp_max import serum_patch_catalog as pc

_PLAIN_MODULES = ("oscillator", "filter", "envelope", "lfo")


def _node(tree, key, create=False):
    node = tree.get(key) if hasattr(tree, "get") else None
    if node is None:
        if not create:
            return None
        node = {"plainParams": {}}
        tree[key] = node
    if "plainParams" not in node:
        node["plainParams"] = {}
    return node


def set_module_params(catalog, tree, module_type, index, params):
    if module_type not in _PLAIN_MODULES:
        raise ValueError("set_module_params: module_type must be one of %s, got %r"
                         % (", ".join(_PLAIN_MODULES), module_type))
    key = pc.node_key(catalog, module_type, index)
    node = _node(tree, key, create=True)
    for name, native in params.items():
        info = pc.param_info(catalog, module_type, name)
        val = float(native)
        if val < info["native_min"] or val > info["native_max"]:
            raise ValueError("%s.%s=%s out of observed range [%s, %s]"
                             % (module_type, name, val, info["native_min"], info["native_max"]))
        node["plainParams"][info["kparam"]] = val


def set_oscillator_mode(catalog, tree, index, mode):
    info = pc.module_info(catalog, "oscillator")
    modes = info.get("modes", {})
    if mode not in modes:
        raise ValueError("unknown oscillator mode %r; valid: %s"
                         % (mode, ", ".join(sorted(modes))))
    key = pc.node_key(catalog, "oscillator", index)
    _node(tree, key, create=True)["plainParams"]["kParamType"] = int(modes[mode])


def set_macro(catalog, tree, index, value, name=None):
    key = pc.node_key(catalog, "macro", index)
    val = float(value)
    if val < 0.0 or val > 100.0:
        raise ValueError("macro value %s out of range [0, 100]" % val)
    node = _node(tree, key, create=True)
    node["plainParams"]["kParamValue"] = val
    if name is not None:
        node["name"] = name


def summarize(catalog, tree):
    out = {"oscillators": [], "filters": [], "envelopes": [], "lfos": [], "macros": []}
    plural = {"oscillator": "oscillators", "filter": "filters",
              "envelope": "envelopes", "lfo": "lfos"}
    for mtype, bucket in plural.items():
        info = pc.module_info(catalog, mtype)
        for n in range(info["count"]):
            node = tree.get(info["node"].replace("{n}", str(n)))
            if not isinstance(node, dict):
                continue
            entry = {"index": n, "params": dict(node.get("plainParams", {}))}
            if mtype == "oscillator":
                entry["mode"] = entry["params"].get("kParamType")
            out[bucket].append(entry)
    minfo = pc.module_info(catalog, "macro")
    for n in range(minfo["count"]):
        node = tree.get("Macro%d" % n)
        if not isinstance(node, dict):
            continue
        out["macros"].append({"index": n, "name": node.get("name", ""),
                              "value": node.get("plainParams", {}).get("kParamValue")})
    return out
```

- [ ] **Step 4: Run tests to verify pass.**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_serum_patch_utils.py -q
```
Expected: PASS (8 tests).

- [ ] **Step 5: Add the 791-preset roundtrip-gate test** (mutate one node, encode, decode, assert tree equal except the patched key). Uses the same factory root as Task 0/1.

```python
# append to tests/test_serum_patch_utils.py
import glob, os
from ableton_mcp_max import serum_state_codec as ssc
from ableton_mcp_max import serum_patch_catalog as realpc

_ROOT = os.environ.get("SERUM_FACTORY_ROOT", "")  # set to the scan root for the live gate

@pytest.mark.skipif(not _ROOT or not glob.glob(os.path.join(_ROOT, "**", "*.SerumPreset"), recursive=True),
                    reason="no factory preset root (set SERUM_FACTORY_ROOT)")
def test_roundtrip_setting_macro_only_changes_that_node():
    cat = realpc.load_catalog()
    files = glob.glob(os.path.join(_ROOT, "**", "*.SerumPreset"), recursive=True)
    for p in files[:50]:
        st = ssc.decode(open(p, "rb").read())
        before = {k: v for k, v in st.tree.items() if k != "Macro0"}
        pu.set_macro(cat, st.tree, 0, 42.0)
        reblob = ssc.encode(st, st.tree)
        re = ssc.decode(reblob).tree
        after = {k: v for k, v in re.items() if k != "Macro0"}
        assert after == before, "patch perturbed an unrelated node in %s" % p
        assert re["Macro0"]["plainParams"]["kParamValue"] == 42.0
```

- [ ] **Step 6: Run the offline suite (gate test skips without the root; that's fine for the commit gate).**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_serum_patch_utils.py -q
```
Expected: PASS (8 pass, 1 skipped). Optionally run with `SERUM_FACTORY_ROOT=<root>` to exercise the gate.

- [ ] **Step 7: Commit.**

```bash
git add ableton_mcp_max/serum_patch_utils.py tests/test_serum_patch_utils.py
git commit -m "feat: Serum patch utils (osc/filter/env/lfo/macro read+set) + roundtrip gate"
```

---

### Task 3: Mod-matrix routes in `serum_patch_utils.py` (gated on Task 0 Rosetta)

**Files:**
- Modify: `ableton_mcp_max/serum_patch_utils.py`
- Test: `tests/test_serum_patch_utils.py` (append)

**Interfaces:**
- Consumes (from Task 0): the free-slot predicate, mod-source table (`mod_sources`), mod-dest table (`mod_dests`).
- Produces (consumed by Tasks 4, 5):
  - `add_mod_route(catalog, tree, source, dest, amount) -> int` - finds a free `ModSlot{n}`, sets `source` (`[moduleID, idx]` from the catalog `mod_sources`), the dest fields from `mod_dests`, and `plainParams.kParamAmount`. Returns the slot index used. Raises ValueError if no free slot, or unknown source/dest.
  - `clear_mod_route(catalog, tree, source, dest) -> int` - clears the matching slot (reset to the free-slot shape). Returns the cleared slot index, or raises ValueError if not found.
  - `_is_free_slot(node) -> bool` - per the Task 0 predicate.

  > NOTE: The exact dest-field write shape and `_is_free_slot` predicate are filled from `release3_spike_findings.md`. The code below uses the documented shape (`source:[id,idx]`, dest fields `destModuleID/destModuleParamID/destModuleParamName/destModuleTypeString`, free = `kParamAmount` absent/0 AND source `[0,0]`); adjust to the verified findings if they differ.

- [ ] **Step 1: Write the failing tests.**

```python
# append to tests/test_serum_patch_utils.py
MODCAT = dict(CAT)
MODCAT["mod_sources"] = {"env1": 25, "lfo1": 30}
MODCAT["mod_dests"] = {"filter1_freq": {"moduleID": 2000000, "paramID": 2000003,
                                        "paramName": "Filter 1 Freq", "typeString": "VoiceFilter"}}

def _mod_tree():
    t = {}
    for n in range(64):
        t["ModSlot%d" % n] = {"source": [0, 0], "plainParams": {}}
    return t

def test_add_mod_route_uses_first_free_slot():
    t = _mod_tree()
    idx = pu.add_mod_route(MODCAT, t, "env1", "filter1_freq", 40.0)
    assert idx == 0
    s = t["ModSlot0"]
    assert s["source"] == [25, 0]
    assert s["destModuleParamID"] == 2000003
    assert s["plainParams"]["kParamAmount"] == 40.0

def test_add_mod_route_unknown_source_raises():
    with pytest.raises(ValueError):
        pu.add_mod_route(MODCAT, _mod_tree(), "nope", "filter1_freq", 10.0)

def test_add_mod_route_no_free_slot_raises():
    t = _mod_tree()
    for n in range(64):
        pu.add_mod_route(MODCAT, t, "env1", "filter1_freq", 1.0)
    with pytest.raises(ValueError):
        pu.add_mod_route(MODCAT, t, "env1", "filter1_freq", 1.0)

def test_clear_mod_route_frees_slot():
    t = _mod_tree()
    pu.add_mod_route(MODCAT, t, "env1", "filter1_freq", 40.0)
    idx = pu.clear_mod_route(MODCAT, t, "env1", "filter1_freq")
    assert idx == 0
    assert pu._is_free_slot(t["ModSlot0"])
```

- [ ] **Step 2: Run to verify failure.**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_serum_patch_utils.py -k mod -q
```
Expected: FAIL with `AttributeError: module ... has no attribute 'add_mod_route'`.

- [ ] **Step 3: Implement (adjust the dest shape / free predicate to the Task 0 findings).**

```python
# append to ableton_mcp_max/serum_patch_utils.py
_MOD_SLOTS = 64


def _is_free_slot(node):
    if not isinstance(node, dict):
        return True
    src = node.get("source")
    amt = node.get("plainParams", {}).get("kParamAmount", 0.0)
    return (not src or src == [0, 0]) and not amt


def _resolve_source(catalog, source):
    srcs = catalog.get("mod_sources", {})
    if source not in srcs:
        raise ValueError("unknown mod source %r; valid: %s"
                         % (source, ", ".join(sorted(srcs))))
    return [int(srcs[source]), 0]


def _resolve_dest(catalog, dest):
    dests = catalog.get("mod_dests", {})
    if dest not in dests:
        raise ValueError("unknown mod dest %r; valid: %s"
                         % (dest, ", ".join(sorted(dests))))
    return dests[dest]


def _slot_matches(node, src, d):
    return (node.get("source") == src
            and node.get("destModuleParamID") == d["paramID"])


def add_mod_route(catalog, tree, source, dest, amount):
    src = _resolve_source(catalog, source)
    d = _resolve_dest(catalog, dest)
    for n in range(_MOD_SLOTS):
        key = "ModSlot%d" % n
        node = tree.get(key)
        if node is None or _is_free_slot(node):
            tree[key] = {"source": src,
                         "destModuleID": int(d["moduleID"]),
                         "destModuleParamID": int(d["paramID"]),
                         "destModuleParamName": d["paramName"],
                         "destModuleTypeString": d["typeString"],
                         "plainParams": {"kParamAmount": float(amount)}}
            return n
    raise ValueError("no free ModSlot (all %d used)" % _MOD_SLOTS)


def clear_mod_route(catalog, tree, source, dest):
    src = _resolve_source(catalog, source)
    d = _resolve_dest(catalog, dest)
    for n in range(_MOD_SLOTS):
        node = tree.get("ModSlot%d" % n)
        if isinstance(node, dict) and _slot_matches(node, src, d):
            tree["ModSlot%d" % n] = {"source": [0, 0], "plainParams": {}}
            return n
    raise ValueError("no mod route from %r to %r found" % (source, dest))
```

- [ ] **Step 4: Run to verify pass.**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_serum_patch_utils.py -q
```
Expected: PASS (all prior + 4 new).

- [ ] **Step 5: Commit.**

```bash
git add ableton_mcp_max/serum_patch_utils.py tests/test_serum_patch_utils.py
git commit -m "feat: Serum mod-matrix route add/clear in patch utils"
```

---

### Task 4: Generalize the mutate/read impls + granular server tools

**Files:**
- Modify: `ableton_mcp_max/server.py` (generalize `_serum_fx_mutate_impl`/`_serum_fx_read_impl`; add imports + tools)
- Test: `tests/test_serum_patch_tools.py`

**Interfaces:**
- Consumes: `serum_patch_utils` (`set_module_params`, `set_oscillator_mode`, `set_macro`, `add_mod_route`, `clear_mod_route`, `summarize`), `serum_patch_catalog.load_catalog`, and the existing `_serum_fx_mutate_impl`/`_serum_fx_read_impl`.
- Produces (consumed by Task 5): the generalized impls accept a `catalog_loader` (mutate) and a `project_fn` (read); plus the granular `@mcp.tool()` functions.

- [ ] **Step 1: Generalize the existing impls** so the patch tools can supply their own catalog and read projection (keep FX behavior identical via defaults).

In `ableton_mcp_max/server.py`, change the `_serum_fx_mutate_impl` signature to add `catalog_loader=_sfxcat.load_catalog` and replace the hardcoded catalog load:

```python
def _serum_fx_mutate_impl(track_index, device_index, mutate_fn, *, reload,
                          save_impl, reload_impl,
                          catalog_loader=_sfxcat.load_catalog,
                          read_als=als.read_als, write_als=als.write_als,
                          find_track_span=als.find_track_span,
                          resolve_path=None, title_fn=None):
    ...
    # was: catalog = _sfxcat.load_catalog()
    catalog = catalog_loader()
    ...
```

And change `_serum_fx_read_impl` to add `project_fn=None` and use it for the returned payload:

```python
def _serum_fx_read_impl(track_index, device_index, *, save_impl,
                        project_fn=None,
                        read_als=als.read_als, find_track_span=als.find_track_span,
                        resolve_path=None, title_fn=None):
    ...
    blob = _ssc.from_hex(xml[s:e])
    tree = _ssc.decode(blob).tree
    if project_fn is None:
        return {"ok": True, "set_path": path, "fx": _sfx.list_fx(tree)}
    payload = {"ok": True, "set_path": path}
    payload.update(project_fn(tree))
    return payload
```

- [ ] **Step 2: Add imports** near the existing serum imports (`server.py` ~line 145-147):

```python
from ableton_mcp_max import serum_patch_utils as _spu
from ableton_mcp_max import serum_patch_catalog as _spcat
```

- [ ] **Step 3: Write the tool-wiring test** (drives the impl with a fake catalog/tree via `resolve_path` + monkeypatched codec is heavy; instead test the mutate_fn closures against an in-memory tree using the utils directly, mirroring `tests/test_serum_fx_tools.py`). Inspect that file first for the established harness:

```bash
sed -n '1,60p' tests/test_serum_fx_tools.py
```

Then write `tests/test_serum_patch_tools.py` following the same harness (a fake `_serum_fx_mutate_impl` capturing the `mutate_fn`, applied to a sample tree, asserting the tree changed). Example shape:

```python
# tests/test_serum_patch_tools.py
import json
from ableton_mcp_max import server
from ableton_mcp_max import serum_patch_catalog as pc

def _osc_tree():
    return {"Oscillator0": {"plainParams": {}}}

def test_set_serum_oscillator_builds_mutation(monkeypatch):
    captured = {}
    def fake_mutate(track_index, device_index, mutate_fn, **kw):
        cat = kw["catalog_loader"]()
        tree = _osc_tree()
        mutate_fn(cat, tree)
        captured["tree"] = tree
        return {"ok": True, "reloaded": False, "set_path": "/x.als"}
    monkeypatch.setattr(server, "_serum_fx_mutate_impl", fake_mutate)
    monkeypatch.setattr(server, "get_ableton_connection", lambda: object())
    out = json.loads(server.set_serum_oscillator(None, 1, 0, {"Volume": 0.8}))
    assert out["ok"] is True
    osc = captured["tree"]["Oscillator0"]["plainParams"]
    # the real Volume kparam came from the loaded catalog
    assert any(k for k in osc), "expected a param written"
```

(Adjust assertions to the loaded catalog's actual friendly names; the harness pattern - monkeypatch the impl, run the closure - is the contract.)

- [ ] **Step 4: Run to verify failure.**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_serum_patch_tools.py -q
```
Expected: FAIL with `AttributeError: module 'ableton_mcp_max.server' has no attribute 'set_serum_oscillator'`.

- [ ] **Step 5: Add the granular tools** in `server.py` after the Release 2 serum FX tools. Each mirrors `set_serum_fx_param`'s structure (try/except, `get_ableton_connection()`, build `mutate_fn`, call `_serum_fx_mutate_impl` with `catalog_loader=_spcat.load_catalog`).

```python
@mcp.tool()
def get_serum_patch(ctx: Context, track_index: int, device_index: int = 0) -> str:
    """Read a Serum 2 instance's full instrument state (read-only).

    Saves the set, decodes the device's ProcessorState from disk (no reload), and
    returns a per-module summary. State authoring view - not LOM knobs.

    Parameters:
    - track_index: track holding the Serum 2 instance.
    - device_index: which VST/AU plugin device on the track (0 = first plugin).

    Returns JSON {ok, data:{set_path, oscillators, filters, envelopes, lfos, macros}}."""
    try:
        get_ableton_connection()
        result = _serum_fx_read_impl(
            track_index, device_index,
            save_impl=lambda: _save_set_impl(name=""),
            project_fn=lambda tree: _spu.summarize(_spcat.load_catalog(), tree))
        if not result.get("ok"):
            return _err(result.get("error", "get_serum_patch failed"))
        return _ok(result)
    except (ValueError, RuntimeError, FileNotFoundError) as e:
        return _err(str(e))
    except Exception as e:
        logger.error("get_serum_patch error: %s", e)
        return _err("get_serum_patch error: %s" % e)


@mcp.tool()
def set_serum_oscillator(ctx: Context, track_index: int, osc: int,
                         params: dict = None, mode: str = None,
                         device_index: int = 0, reload: bool = True) -> str:
    """Set Serum oscillator params (native units) and/or its mode.

    Patches plugin state in the .als and reloads in place. params keys are friendly
    names or raw kParam* keys; values are native, range-validated against the
    catalog. mode (when given) selects the oscillator engine (e.g. 'wt').

    Parameters:
    - track_index: track holding the Serum 2 instance.
    - osc: oscillator index (0-4).
    - params: {name: native_value} dict (optional).
    - mode: oscillator mode name (optional).
    - device_index: which VST/AU plugin device on the track (0 = first plugin).
    - reload: reload the set after patching (default True).

    Returns JSON {ok, data:{reloaded, set_path}}."""
    try:
        get_ableton_connection()
        def mutate_fn(catalog, tree):
            if mode is not None:
                _spu.set_oscillator_mode(catalog, tree, osc, mode)
            if params:
                _spu.set_module_params(catalog, tree, "oscillator", osc, params)
        result = _serum_fx_mutate_impl(
            track_index, device_index, mutate_fn, reload=reload,
            catalog_loader=_spcat.load_catalog,
            save_impl=lambda: _save_set_impl(name=""),
            reload_impl=lambda p, n: _reload_set(p, n))
        if not result.get("ok"):
            return _err(result.get("error", "set_serum_oscillator failed"))
        return _ok(result)
    except (ValueError, RuntimeError, FileNotFoundError) as e:
        return _err(str(e))
    except Exception as e:
        logger.error("set_serum_oscillator error: %s", e)
        return _err("set_serum_oscillator error: %s" % e)
```

Add `set_serum_filter`, `set_serum_envelope`, `set_serum_lfo` identically (each calls `_spu.set_module_params(catalog, tree, "<type>", index, params)`; param is `filter`/`env`/`lfo` index). Add `set_serum_macro`:

```python
@mcp.tool()
def set_serum_macro(ctx: Context, track_index: int, macro: int, value: float,
                    name: str = None, device_index: int = 0,
                    reload: bool = True) -> str:
    """Set a Serum macro value (0-100) and optionally its name.

    Parameters:
    - track_index: track holding the Serum 2 instance.
    - macro: macro index (0-7).
    - value: macro value 0-100.
    - name: optional macro label.
    - device_index: which VST/AU plugin device on the track (0 = first plugin).
    - reload: reload the set after patching (default True).

    Returns JSON {ok, data:{reloaded, set_path}}."""
    try:
        get_ableton_connection()
        def mutate_fn(catalog, tree):
            _spu.set_macro(catalog, tree, macro, value, name=name)
        result = _serum_fx_mutate_impl(
            track_index, device_index, mutate_fn, reload=reload,
            catalog_loader=_spcat.load_catalog,
            save_impl=lambda: _save_set_impl(name=""),
            reload_impl=lambda p, n: _reload_set(p, n))
        if not result.get("ok"):
            return _err(result.get("error", "set_serum_macro failed"))
        return _ok(result)
    except (ValueError, RuntimeError, FileNotFoundError) as e:
        return _err(str(e))
    except Exception as e:
        logger.error("set_serum_macro error: %s", e)
        return _err("set_serum_macro error: %s" % e)
```

Add `add_serum_mod_route(track_index, source, dest, amount, device_index=0, reload=True)` and `clear_serum_mod_route(track_index, source, dest, device_index=0, reload=True)` calling `_spu.add_mod_route` / `_spu.clear_mod_route`.

- [ ] **Step 6: Run the tool test + full suite + import check.**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python -c "import ableton_mcp_max.server"
```
Expected: all PASS; import prints nothing (exit 0).

- [ ] **Step 7: Commit.**

```bash
git add ableton_mcp_max/server.py tests/test_serum_patch_tools.py
git commit -m "feat: granular Serum patch tools (oscillator/filter/env/lfo/macro/mod)"
```

---

### Task 5: `create_serum_patch` declarative composer (one reload)

**Files:**
- Modify: `ableton_mcp_max/server.py`
- Test: `tests/test_serum_patch_tools.py` (append)

**Interfaces:**
- Consumes: all `serum_patch_utils` setters + `serum_fx_utils` setters (for the optional `fx` section), the generalized `_serum_fx_mutate_impl`.
- Produces: `create_serum_patch(track_index, spec, device_index=0, reload=True)` - applies the whole `spec` to one decoded tree in a single mutate_fn, then one reload. Returns `{ok, data:{reloaded, set_path, applied:{...counts...}}}`.

- [ ] **Step 1: Write the failing test** (spec applied to an in-memory tree via the monkeypatch harness from Task 4):

```python
# append to tests/test_serum_patch_tools.py
def test_create_serum_patch_applies_all_sections(monkeypatch):
    captured = {}
    def fake_mutate(track_index, device_index, mutate_fn, **kw):
        cat = kw["catalog_loader"]()
        tree = {"Oscillator0": {"plainParams": {}}, "Macro0": {"plainParams": {}}}
        for n in range(64):
            tree["ModSlot%d" % n] = {"source": [0, 0], "plainParams": {}}
        mutate_fn(cat, tree)
        captured["tree"] = tree
        return {"ok": True, "reloaded": True, "set_path": "/x.als"}
    monkeypatch.setattr(server, "_serum_fx_mutate_impl", fake_mutate)
    monkeypatch.setattr(server, "get_ableton_connection", lambda: object())
    spec = {"oscillators": [{"index": 0, "params": {"Volume": 0.7}}],
            "macros": [{"index": 0, "value": 30.0, "name": "X"}]}
    out = json.loads(server.create_serum_patch(None, 1, spec))
    assert out["ok"] is True
    assert captured["tree"]["Macro0"]["name"] == "X"
```

- [ ] **Step 2: Run to verify failure.**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_serum_patch_tools.py -k create -q
```
Expected: FAIL (`no attribute 'create_serum_patch'`).

- [ ] **Step 3: Implement.**

```python
@mcp.tool()
def create_serum_patch(ctx: Context, track_index: int, spec: dict,
                       device_index: int = 0, reload: bool = True) -> str:
    """Build a Serum 2 patch from a single declarative spec in one reload.

    spec sections (all optional; absent = untouched):
      oscillators: [{index, mode?, params?}]   filters: [{index, params}]
      envelopes:   [{index, params}]           lfos:    [{index, params}]
      macros:      [{index, value, name?}]      mod_routes: [{source, dest, amount}]
      fx:          [{rack, slot, kparam, value}]  (delegates to Serum FX setters)
    Params are native units, range-validated. Applies everything to one decoded
    tree then reloads once.

    Parameters:
    - track_index: track holding the Serum 2 instance.
    - spec: the patch description dict.
    - device_index: which VST/AU plugin device on the track (0 = first plugin).
    - reload: reload the set after patching (default True).

    Returns JSON {ok, data:{reloaded, set_path, applied}}."""
    try:
        get_ableton_connection()
        applied = {"oscillators": 0, "filters": 0, "envelopes": 0,
                   "lfos": 0, "macros": 0, "mod_routes": 0, "fx": 0}
        def mutate_fn(catalog, tree):
            for o in spec.get("oscillators", []):
                if o.get("mode") is not None:
                    _spu.set_oscillator_mode(catalog, tree, o["index"], o["mode"])
                if o.get("params"):
                    _spu.set_module_params(catalog, tree, "oscillator", o["index"], o["params"])
                applied["oscillators"] += 1
            for mtype, key in (("filter", "filters"), ("envelope", "envelopes"), ("lfo", "lfos")):
                for m in spec.get(key, []):
                    _spu.set_module_params(catalog, tree, mtype, m["index"], m.get("params", {}))
                    applied[key] += 1
            for mc in spec.get("macros", []):
                _spu.set_macro(catalog, tree, mc["index"], mc["value"], name=mc.get("name"))
                applied["macros"] += 1
            for r in spec.get("mod_routes", []):
                _spu.add_mod_route(catalog, tree, r["source"], r["dest"], r["amount"])
                applied["mod_routes"] += 1
            if spec.get("fx"):
                fxcat = _sfxcat.load_catalog()
                for f in spec["fx"]:
                    _sfx.set_fx_param(fxcat, tree, f["rack"], f["slot"], f["kparam"], f["value"])
                    applied["fx"] += 1
        result = _serum_fx_mutate_impl(
            track_index, device_index, mutate_fn, reload=reload,
            catalog_loader=_spcat.load_catalog,
            save_impl=lambda: _save_set_impl(name=""),
            reload_impl=lambda p, n: _reload_set(p, n))
        if not result.get("ok"):
            return _err(result.get("error", "create_serum_patch failed"))
        result["applied"] = applied
        return _ok(result)
    except (ValueError, RuntimeError, FileNotFoundError) as e:
        return _err(str(e))
    except Exception as e:
        logger.error("create_serum_patch error: %s", e)
        return _err("create_serum_patch error: %s" % e)
```

- [ ] **Step 4: Run the test + full suite + import.**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python -c "import ableton_mcp_max.server"
```
Expected: all PASS; import exit 0.

- [ ] **Step 5: Commit.**

```bash
git add ableton_mcp_max/server.py tests/test_serum_patch_tools.py
git commit -m "feat: declarative create_serum_patch composer (one reload)"
```

---

### Task 6: `set_serum_wavetable` (per Task 0 verdict)

**Files:**
- Modify: `ableton_mcp_max/serum_patch_utils.py`
- Modify: `ableton_mcp_max/server.py`
- Test: `tests/test_serum_patch_utils.py` (append)

**Interfaces:**
- Consumes (from Task 0): the wavetable storage verdict + exact `WTOsc{n}` key.
- Produces: `serum_patch_utils.set_wavetable(catalog, tree, osc, table) -> None` and the `set_serum_wavetable(track_index, osc, table, device_index=0, reload=True)` tool.

> If Task 0 verdict = **path-ref**: `set_wavetable` writes the table name/path string into the verified `WTOsc{n}` key and ensures the oscillator is in WT mode. If verdict = **embedded-binary / defer**: implement `set_wavetable` to accept only an existing factory/user table NAME (path-ref subset) and raise a clear "embedded-table authoring not supported in v1" ValueError for anything requiring an embed. Either way the tool ships; the degraded form is the spec-approved fallback.

- [ ] **Step 1: Write the failing test** (path-ref shape shown; adapt the key to the Task 0 finding):

```python
# append to tests/test_serum_patch_utils.py
WTCAT = dict(CAT)  # modes include 'wt': 0

def test_set_wavetable_writes_ref_and_wt_mode():
    t = {"Oscillator0": {"plainParams": {}, "WTOsc0": {"plainParams": {}}}}
    pu.set_wavetable(WTCAT, t, 0, "Analog/Basic Shapes")
    assert t["Oscillator0"]["plainParams"]["kParamType"] == 0  # wt mode
    # the verified WTOsc ref key (e.g. 'wtName'/'wtPathRelative') holds the table
    wt = t["Oscillator0"]["WTOsc0"]
    assert "Analog/Basic Shapes" in str(wt)
```

- [ ] **Step 2: Run to verify failure.**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_serum_patch_utils.py -k wavetable -q
```
Expected: FAIL (`no attribute 'set_wavetable'`).

- [ ] **Step 3: Implement `set_wavetable`** using the verified `WTOsc{n}` key (replace `WT_REF_KEY`):

```python
# append to ableton_mcp_max/serum_patch_utils.py
WT_REF_KEY = "<from Task 0 findings, e.g. 'wtName' or 'wtPathRelative'>"


def set_wavetable(catalog, tree, osc, table):
    key = pc.node_key(catalog, "oscillator", osc)
    node = _node(tree, key, create=True)
    # ensure WT mode
    modes = pc.module_info(catalog, "oscillator").get("modes", {})
    if "wt" in modes:
        node["plainParams"]["kParamType"] = int(modes["wt"])
    wtkey = "WTOsc%d" % osc
    wt = node.get(wtkey)
    if not isinstance(wt, dict):
        wt = {"plainParams": {}}
        node[wtkey] = wt
    wt[WT_REF_KEY] = table
```

- [ ] **Step 4: Add the `set_serum_wavetable` tool** in `server.py` (same wrapper shape as `set_serum_macro`, calling `_spu.set_wavetable`).

- [ ] **Step 5: Run tests + import.**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python -c "import ableton_mcp_max.server"
```
Expected: all PASS; import exit 0.

- [ ] **Step 6: Commit.**

```bash
git add ableton_mcp_max/serum_patch_utils.py ableton_mcp_max/server.py tests/test_serum_patch_utils.py
git commit -m "feat: set_serum_wavetable (oscillator wavetable selection)"
```

---

### Task 7: Live verify + docs + ship

**Files:**
- Modify: `pyproject.toml`, `.claude-plugin/plugin.json`, `uv.lock` (version bump)
- Modify: `docs/tools/*`, `docs/tools/index.md`, `commands/tool-index.md` (regen)
- Modify: `docs/index.md` (5 hardcoded count spots), `README.md:7` (count) - BY HAND
- Modify: `PROGRESS.md`

**Interfaces:**
- Consumes: all prior tasks. No new code interfaces.

- [ ] **Step 1: Live verify on Live 12.4.** Per CLAUDE.md, to test working-tree `server.py` edits either restart Claude Code (reloads AbletonDev) or subprocess-import the working-tree server on 9877. Disable the cached `ableton` plugin if it would fight for the port. On a scratch track: load a fresh Serum 2, `save_set_as` to a scratch set, then drive `create_serum_patch` with a small spec (one osc param, one filter param, one macro, one mod route; add a wavetable if Task 0 allowed path-ref). Reload, then `get_serum_patch` to confirm the values survived; audition. Confirm a mod route actually modulates (move the macro / play a note). Delete the scratch device, restore baseline.

- [ ] **Step 2: Record live results** in `PROGRESS.md` and the `vst-plugin-support` memory (what survived reload, any per-module gotchas, the wavetable outcome).

- [ ] **Step 3: Decide the version.** Check shipped tags vs unreleased commits (CLAUDE.md version-drift rule):

```bash
gh release list | head
git log $(git describe --tags --abbrev=0)..HEAD --oneline
```
Pick the next minor (e.g. v0.27.0 if v0.26.0 is the latest shipped). Update `pyproject.toml` + `.claude-plugin/plugin.json` to the same version, then:

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv lock
```

- [ ] **Step 4: Regen tool docs + hand-bump counts.** New tool count = old + the tools actually added (get_serum_patch, set_serum_oscillator/filter/envelope/lfo/macro, add/clear_serum_mod_route, create_serum_patch, set_serum_wavetable = 10).

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python scripts/build_tool_index.py
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python scripts/gen_docs_site.py
```
Then edit `docs/index.md` (5 hardcoded spots: description, tagline, two `stats__num`, the "exposes the N `@mcp.tool()`" line) and `README.md:7` ("reference for all N tools") to the new total by hand. Verify the count with the AST enumerator (CLAUDE.md):

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python -c "import ast;m=ast.parse(open('ableton_mcp_max/server.py').read());print(sum(1 for n in ast.walk(m) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and any(getattr(d,'attr','')=='tool' or getattr(getattr(d,'func',None),'attr','')=='tool' for d in n.decorator_list)))"
```

- [ ] **Step 5: Final offline gate.**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python -c "import ableton_mcp_max.server"
```
Expected: all PASS; import exit 0.

- [ ] **Step 6: Commit, PR, merge, release, marketplace bump.** Verify `gh api user --jq .login` == `ringo380` first.

```bash
git add -A
git commit -m "chore: Serum patch authoring docs + vX.Y.Z bump"
git push -u origin feat/serum-patch-authoring
gh pr create --title "feat: Serum full-instrument patch authoring (Release 3)" --body "<summary>"
# after merge:
gh pr merge --squash --delete-branch
git checkout main && git pull && git remote prune origin
gh release create vX.Y.Z --target main --title "vX.Y.Z" --notes "<notes>"
```
Then bump the `ableton` entry's `ref` to `vX.Y.Z` in the marketplace repo's `marketplace.json`, run its `node scripts/build-readme.js`, and push. Confirm the chain per CLAUDE.md (local main = origin/main = `git ls-remote --tags origin vX.Y.Z` commit; marketplace ref bumped).

---

## Self-Review

**Spec coverage:**
- Full patch authoring via Release 2 mechanism -> Tasks 4/5 reuse `_serum_fx_mutate_impl`. ✓
- Both granular + declarative -> Tasks 4 (granular) + 5 (`create_serum_patch`). ✓
- Osc params + mode -> Task 2 (`set_module_params`/`set_oscillator_mode`) + Task 4 tool. ✓
- Wavetable selection (gated, degrade-to-path-ref) -> Task 0 spike + Task 6. ✓
- Filters, envelopes, LFOs -> Task 2 + Task 4 tools. ✓
- Mod matrix (Rosetta) -> Task 0 verify + Task 3 + Task 4 tools. ✓
- Macros -> Task 2 (`set_macro`) + Task 4 tool. ✓
- Catalog (friendly names, ranges, mode/mod tables) -> Task 1. ✓
- 791-preset roundtrip gate -> Task 2 Step 5. ✓
- Live verify + ship (version/docs/marketplace) -> Task 7. ✓

**Placeholder scan:** The `<FACTORY_ROOT>`, `WT_REF_KEY`, `MODES`/`MOD_SOURCES`/`MOD_DESTS`, and the mod-dest write shape are intentional Task-0-resolved values, each flagged with where the value comes from - not vague TODOs. All code steps include full code.

**Type consistency:** `load_catalog`/`module_info`/`node_key`/`param_info` (catalog) and `set_module_params`/`set_oscillator_mode`/`set_macro`/`add_mod_route`/`clear_mod_route`/`summarize`/`set_wavetable` (utils) names match across Tasks 1-6 and their server-tool callers in Tasks 4-6. The generalized `_serum_fx_mutate_impl(..., catalog_loader=...)` and `_serum_fx_read_impl(..., project_fn=...)` signatures (Task 4 Step 1) match every call site in Tasks 4/5/6.
