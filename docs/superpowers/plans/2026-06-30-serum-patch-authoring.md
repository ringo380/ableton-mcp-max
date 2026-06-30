# Serum full-instrument patch authoring (Release 3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Author a complete Serum 2 patch from scratch by patching the whole Serum CBOR state tree in the live `.als` - oscillator params + mode + wavetable, filters, envelopes, LFOs, the mod matrix, and macros - via the proven Release 2 ProcessorState-patch + reload-in-place mechanism.

**Architecture:** Reuse the Release 2 read/mutate scaffolding (`_serum_fx_read_impl` / `_serum_fx_mutate_impl` in `server.py`, which decode the device's `<ProcessorState>` XferJson blob, run a `mutate_fn(catalog, tree)`, re-encode, and reload). Add a new pure module `serum_patch_utils.py` with per-module read/set helpers over the decoded tree, a `serum2_patch.json` catalog (loaded by `serum_patch_catalog.py`), granular per-module tools, and a declarative `create_serum_patch`. The processor-only patch is already proven sufficient (Release 2: a Wet change survived a real reload with no controller patch).

**Tech Stack:** Python (server side, `uv`), `cbor2` + `zstandard` (via existing `serum_state_codec`), FastMCP `@mcp.tool()`, pytest (offline). Remote Script is NOT touched.

## Global Constraints

- `*_utils.py` and catalog modules are imported by `server.py` ONLY; never by the Remote Script. All resolve/validate/clamp happens server-side. (CLAUDE.md architecture rule.)
- Processor-only patch: mutate `<ProcessorState>` ONLY; leave `<ControllerState>`/`<Vst3Preset>` untouched (Release 2 proved sufficient).
- `plainParams` is sparse: absent key = Serum default. Setting a value inserts/updates a `kParam*` key; never write a full param set.
- Native units everywhere (like the Release 2 FX tools): tool params are native Serum values, range-validated against the catalog's observed min/max.
- Factory preset root (Release 2 constant): `/Library/Audio/Presets/Xfer Records/Serum 2 Presets/Presets` (791 `*.SerumPreset`). Live test set: `/Users/ryanrobson/Desktop/serum2_test Project/serum2_idtest.als`.
- Offline gate before any "done" claim: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q` + `uv run python -c "import ableton_mcp_max.server"`. No CI; do NOT reformat existing files to ruff style.
- ASCII only in source and JSON (no Unicode); use `%`-formatting style consistent with the file being edited.
- Tool docstrings follow the Release 2 style: one-line summary, then Parameters, then `Returns JSON {ok, data:{...}}`.
- No AI attribution in any commit message (public-repo rule).
- Tool-count bookkeeping at ship time is MANUAL: `docs/index.md` (5 hardcoded spots) and `README.md:7` are not touched by the regen scripts.

### Spike findings (Task 0, COMPLETE - baked into the tasks below)

Source of truth: `.vst-harvest-local/release3_spike_findings.md`. The three plan-shaping facts:
1. **Oscillator mode is a STRING enum** in `Oscillator{n}.plainParams.kParamType`: WaveTable = the default (key ABSENT in 582/791 presets), `kOsc_MultiSample`, `kOsc_Sample`, `kOsc_Granular`, `kOsc_Spectral`. Selecting WT = delete the `kParamType` key.
2. **Wavetable selection = path-ref**: `Oscillator{n}.WTOsc{n}.relativePathToWT` (str, e.g. `"S2 Tables/Default Shapes.wav"`). Serum reloads/recomputes from the file. No embedded-binary work.
3. **Mod matrix**: a routed `ModSlot{n}` = `{source:[id,sub], destModuleID, destModuleParamID, destModuleParamName, destModuleTypeString, plainParams:{kParamAmount,...}}`. A FREE slot = `{"plainParams": {}}` (no source/dest keys). The dest `(destModuleTypeString, destModuleParamName) -> destModuleParamID` map is deterministic (215 combos) and harvested into the catalog. The mod-SOURCE id->name map is NOT in preset data: `add_serum_mod_route` accepts a raw int source id OR a friendly name (catalog `mod_sources`, filled by the Task 7 live oracle).

---

### Task 0: Spike (COMPLETE)

Done in the controller's main loop. Findings written to `.vst-harvest-local/release3_spike_findings.md`. No implementer dispatch. Subsequent tasks consume the baked findings above.

---

### Task 1: Catalog generator + `serum_patch_catalog.py` loader

**Files:**
- Create: `scripts/build_serum_patch_catalog.py` (offline factory scan -> JSON)
- Create: `ableton_mcp_max/param_maps/serum2_patch.json`
- Create: `ableton_mcp_max/serum_patch_catalog.py`
- Test: `tests/test_serum_patch_catalog.py`

**Interfaces:**
- Produces (consumed by Tasks 2-6):
  - `serum_patch_catalog.load_catalog(path=None) -> dict` with shape:
    ```
    {"plugin":"Serum2","scanned_presets":int,
     "modules":{
        "oscillator":{"count":5,"node":"Oscillator{n}","params":{<friendly>:{"kparam","native_min","native_max"}},
                      "modes":{"wavetable":null,"multisample":"kOsc_MultiSample","sample":"kOsc_Sample",
                               "granular":"kOsc_Granular","spectral":"kOsc_Spectral"}},
        "filter":  {"count":2,"node":"VoiceFilter{n}","params":{...}},
        "envelope":{"count":4,"node":"Env{n}","params":{...}},
        "lfo":     {"count":10,"node":"LFO{n}","params":{...}},
        "macro":   {"count":8,"node":"Macro{n}"}},
     "mod_dest_types":{"oscillator":"Oscillator","filter":"VoiceFilter","envelope":"Env","lfo":"LFO",
                       "wt":"WTOsc","macro":"Macro","global":"Global"},
     "mod_dest_params":{<typeString>:{<kparam>:int}},   # harvested (type,paramName)->paramID
     "mod_sources":{}}                                   # friendly->int, filled by Task 7 oracle
    ```
  - `serum_patch_catalog.module_info(catalog, module_type) -> dict` (ValueError on unknown, lists valid).
  - `serum_patch_catalog.node_key(catalog, module_type, index) -> str` (e.g. `"Oscillator2"`; ValueError out of range).
  - `serum_patch_catalog.param_info(catalog, module_type, name) -> {"kparam","native_min","native_max"}`. `name` matches a friendly name OR a raw `kParam*`. ValueError lists valid names.
  - `serum_patch_catalog.dest_param_id(catalog, type_string, name) -> int`. `name` matches a `kParam*` OR a friendly (kParam minus the `kParam` prefix) within `mod_dest_params[type_string]`. ValueError on unknown.
  - `serum_patch_catalog.dest_type_string(catalog, module_type) -> str` (from `mod_dest_types`; ValueError on unknown).

- [ ] **Step 1: Write the catalog builder.** Friendly param names = `kParam*` with the `kParam` prefix stripped; ranges from the factory scan. Mode enum + `mod_dest_types` are constants from the spike; `mod_dest_params` is harvested; `mod_sources` starts empty.

```python
# scripts/build_serum_patch_catalog.py
"""Scan factory .SerumPreset files and emit param_maps/serum2_patch.json.
Friendly param name = kParam* minus the 'kParam' prefix. Param ranges are the
observed min/max across all presets. mod_dest_params harvests the deterministic
(destModuleTypeString -> {destModuleParamName: destModuleParamID}) map. Mode enum
and mod_dest_types are spike constants. mod_sources starts empty (Task 7 oracle)."""
import glob, json, os, sys

from ableton_mcp_max import serum_state_codec as ssc

FACTORY = "/Library/Audio/Presets/Xfer Records/Serum 2 Presets/Presets"
MODULE_NODES = {
    "oscillator": ("Oscillator%d", 5),
    "filter": ("VoiceFilter%d", 2),
    "envelope": ("Env%d", 4),
    "lfo": ("LFO%d", 10),
}
MODES = {"wavetable": None, "multisample": "kOsc_MultiSample", "sample": "kOsc_Sample",
         "granular": "kOsc_Granular", "spectral": "kOsc_Spectral"}
MOD_DEST_TYPES = {"oscillator": "Oscillator", "filter": "VoiceFilter", "envelope": "Env",
                  "lfo": "LFO", "wt": "WTOsc", "macro": "Macro", "global": "Global"}


def friendly(kparam):
    return kparam[6:] if kparam.startswith("kParam") else kparam


def _pp(node):
    x = node.get("plainParams") if isinstance(node, dict) else None
    return x if isinstance(x, dict) else {}


def scan(root):
    ranges = {m: {} for m in MODULE_NODES}     # module -> kparam -> [min,max]
    dest = {}                                   # typeString -> {paramName: paramID}
    files = glob.glob(os.path.join(root, "**", "*.SerumPreset"), recursive=True)
    for p in files:
        try:
            tree = ssc.decode(open(p, "rb").read()).tree
        except Exception:
            continue
        for m, (fmt, count) in MODULE_NODES.items():
            for n in range(count):
                for k, v in _pp(tree.get(fmt % n)).items():
                    if not isinstance(v, (int, float)) or isinstance(v, bool):
                        continue
                    cur = ranges[m].setdefault(k, [float(v), float(v)])
                    cur[0] = min(cur[0], float(v)); cur[1] = max(cur[1], float(v))
        for n in range(64):
            ms = tree.get("ModSlot%d" % n)
            if not isinstance(ms, dict) or "destModuleTypeString" not in ms:
                continue
            ts = ms.get("destModuleTypeString"); pn = ms.get("destModuleParamName")
            pid = ms.get("destModuleParamID")
            if ts is None or pn is None or pid is None:
                continue
            dest.setdefault(ts, {}).setdefault(pn, int(pid))
    return ranges, dest, len(files)


def build(root):
    ranges, dest, nfiles = scan(root)
    modules = {}
    for m, (fmt, count) in MODULE_NODES.items():
        params = {friendly(k): {"kparam": k, "native_min": lo, "native_max": hi}
                  for k, (lo, hi) in sorted(ranges[m].items())}
        entry = {"count": count, "node": fmt.replace("%d", "{n}"), "params": params}
        if m == "oscillator":
            entry["modes"] = MODES
        modules[m] = entry
    modules["macro"] = {"count": 8, "node": "Macro{n}"}
    return {"plugin": "Serum2", "scanned_presets": nfiles, "modules": modules,
            "mod_dest_types": MOD_DEST_TYPES,
            "mod_dest_params": {ts: dict(sorted(d.items())) for ts, d in sorted(dest.items())},
            "mod_sources": {}}


if __name__ == "__main__":
    root = sys.argv[1] if len(sys.argv) > 1 else FACTORY
    out = os.path.join(os.path.dirname(__file__), "..", "ableton_mcp_max",
                       "param_maps", "serum2_patch.json")
    cat = build(root)
    with open(out, "w") as fh:
        json.dump(cat, fh, indent=1, sort_keys=True)
    print("wrote %s (%d presets, dest_types=%d)"
          % (out, cat["scanned_presets"], len(cat["mod_dest_params"])))
```

- [ ] **Step 2: Run the builder.**

```bash
cd /Users/ryanrobson/git/ableton-mcp-max
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python scripts/build_serum_patch_catalog.py
```
Expected: `wrote .../serum2_patch.json (791 presets, dest_types=~24)`.

- [ ] **Step 3: Write the failing loader test.**

```python
# tests/test_serum_patch_catalog.py
import pytest
from ableton_mcp_max import serum_patch_catalog as pc

def _cat():
    return {"plugin": "Serum2", "modules": {
        "oscillator": {"count": 5, "node": "Oscillator{n}",
                       "params": {"Volume": {"kparam": "kParamVolume", "native_min": 0.0, "native_max": 1.0}},
                       "modes": {"wavetable": None, "multisample": "kOsc_MultiSample"}},
        "macro": {"count": 8, "node": "Macro{n}"}},
        "mod_dest_types": {"filter": "VoiceFilter"},
        "mod_dest_params": {"VoiceFilter": {"kParamFreq": 3}},
        "mod_sources": {}}

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

def test_dest_type_string():
    assert pc.dest_type_string(_cat(), "filter") == "VoiceFilter"
    with pytest.raises(ValueError):
        pc.dest_type_string(_cat(), "nope")

def test_dest_param_id_by_kparam_and_friendly():
    c = _cat()
    assert pc.dest_param_id(c, "VoiceFilter", "kParamFreq") == 3
    assert pc.dest_param_id(c, "VoiceFilter", "Freq") == 3
    with pytest.raises(ValueError):
        pc.dest_param_id(c, "VoiceFilter", "Nope")

def test_real_catalog_loads():
    cat = pc.load_catalog()
    assert cat["plugin"] == "Serum2"
    assert set(["oscillator", "filter", "envelope", "lfo", "macro"]).issubset(cat["modules"])
    assert "VoiceFilter" in cat["mod_dest_params"]
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
    params = module_info(catalog, module_type).get("params", {})
    if name in params:
        return params[name]
    for _friendly, p in params.items():
        if p["kparam"] == name:
            return p
    raise ValueError("unknown param %r for %s; valid: %s"
                     % (name, module_type, ", ".join(sorted(params))))


def dest_type_string(catalog, module_type):
    types = catalog.get("mod_dest_types", {})
    if module_type not in types:
        raise ValueError("unknown mod dest module %r; valid: %s"
                         % (module_type, ", ".join(sorted(types))))
    return types[module_type]


def dest_param_id(catalog, type_string, name):
    table = catalog.get("mod_dest_params", {}).get(type_string)
    if not table:
        raise ValueError("no dest params for type %r" % type_string)
    if name in table:
        return table[name]
    cand = "kParam" + name
    if cand in table:
        return table[cand]
    raise ValueError("unknown dest param %r for %s; valid: %s"
                     % (name, type_string, ", ".join(sorted(table))))
```

- [ ] **Step 6: Run tests to verify pass.**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_serum_patch_catalog.py -q
```
Expected: PASS (8 tests).

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
  - `summarize(catalog, tree) -> dict` - `{"oscillators":[{index,mode,params}], "filters":[...], "envelopes":[...], "lfos":[...], "macros":[{index,name,value}]}`. Reads only present nodes; `mode` is the raw `kParamType` value (or None for WT default).
  - `set_module_params(catalog, tree, module_type, index, params) -> None` - module_type in oscillator/filter/envelope/lfo; `params` is `{name: native}` (friendly or kParam); range-validated; writes into `tree[node].plainParams`.
  - `set_oscillator_mode(catalog, tree, index, mode) -> None` - sets `Oscillator{index}.plainParams.kParamType` to the catalog's mode STRING; for `mode == "wavetable"` (catalog value None), DELETES the `kParamType` key (WT is the default).
  - `set_macro(catalog, tree, index, value, name=None) -> None` - sets `Macro{index}.plainParams.kParamValue` (range 0..100) and optionally `Macro{index}.name`.

- [ ] **Step 1: Write the failing tests.**

```python
# tests/test_serum_patch_utils.py
import pytest
from ableton_mcp_max import serum_patch_utils as pu

CAT = {"plugin": "Serum2", "modules": {
    "oscillator": {"count": 5, "node": "Oscillator{n}",
                   "params": {"Volume": {"kparam": "kParamVolume", "native_min": 0.0, "native_max": 1.0},
                              "Pan": {"kparam": "kParamPan", "native_min": -1.0, "native_max": 1.0}},
                   "modes": {"wavetable": None, "multisample": "kOsc_MultiSample"}},
    "filter": {"count": 2, "node": "VoiceFilter{n}",
               "params": {"Freq": {"kparam": "kParamFreq", "native_min": 0.0, "native_max": 1.0}}},
    "envelope": {"count": 4, "node": "Env{n}",
                 "params": {"Attack": {"kparam": "kParamAttack", "native_min": 0.0, "native_max": 16.0}}},
    "lfo": {"count": 10, "node": "LFO{n}",
            "params": {"Rate": {"kparam": "kParamRate", "native_min": 0.0, "native_max": 1.0}}},
    "macro": {"count": 8, "node": "Macro{n}"}},
    "mod_dest_types": {}, "mod_dest_params": {}, "mod_sources": {}}

def _tree():
    return {"Oscillator0": {"plainParams": {"kParamVolume": 0.5, "kParamType": "kOsc_Sample"}},
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

def test_set_oscillator_mode_string():
    t = _tree()
    pu.set_oscillator_mode(CAT, t, 0, "multisample")
    assert t["Oscillator0"]["plainParams"]["kParamType"] == "kOsc_MultiSample"

def test_set_oscillator_mode_wavetable_deletes_key():
    t = _tree()  # starts as kOsc_Sample
    pu.set_oscillator_mode(CAT, t, 0, "wavetable")
    assert "kParamType" not in t["Oscillator0"]["plainParams"]

def test_set_oscillator_mode_unknown_raises():
    t = _tree()
    with pytest.raises(ValueError):
        pu.set_oscillator_mode(CAT, t, 0, "bogus")

def test_set_macro_value_and_name():
    t = _tree()
    pu.set_macro(CAT, t, 0, 25.0, name="CUTOFF")
    assert t["Macro0"]["plainParams"]["kParamValue"] == 25.0
    assert t["Macro0"]["name"] == "CUTOFF"

def test_set_macro_out_of_range_raises():
    with pytest.raises(ValueError):
        pu.set_macro(CAT, _tree(), 0, 250.0)

def test_summarize_reports_present_modules():
    s = pu.summarize(CAT, _tree())
    osc0 = [o for o in s["oscillators"] if o["index"] == 0][0]
    assert osc0["params"].get("kParamVolume") == 0.5
    assert osc0["mode"] == "kOsc_Sample"
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
modules (oscillators, filters, envelopes, LFOs, macros) and mod matrix. No IO.
plainParams is sparse (absent key = Serum default); setting a value inserts/updates
a kParam*. FX live in serum_fx_utils. kParamType (oscillator mode) is a STRING; WT
mode is the default = absence of the key."""
from ableton_mcp_max import serum_patch_catalog as pc

_PLAIN_MODULES = ("oscillator", "filter", "envelope", "lfo")


def _node(tree, key, create=False):
    node = tree.get(key) if hasattr(tree, "get") else None
    if node is None:
        if not create:
            return None
        node = {"plainParams": {}}
        tree[key] = node
    if "plainParams" not in node or not isinstance(node["plainParams"], dict):
        node["plainParams"] = {}
    return node


def set_module_params(catalog, tree, module_type, index, params):
    if module_type not in _PLAIN_MODULES:
        raise ValueError("set_module_params: module_type must be one of %s, got %r"
                         % (", ".join(_PLAIN_MODULES), module_type))
    node = _node(tree, pc.node_key(catalog, module_type, index), create=True)
    for name, native in params.items():
        info = pc.param_info(catalog, module_type, name)
        val = float(native)
        if val < info["native_min"] or val > info["native_max"]:
            raise ValueError("%s.%s=%s out of observed range [%s, %s]"
                             % (module_type, name, val, info["native_min"], info["native_max"]))
        node["plainParams"][info["kparam"]] = val


def set_oscillator_mode(catalog, tree, index, mode):
    modes = pc.module_info(catalog, "oscillator").get("modes", {})
    if mode not in modes:
        raise ValueError("unknown oscillator mode %r; valid: %s"
                         % (mode, ", ".join(sorted(modes))))
    node = _node(tree, pc.node_key(catalog, "oscillator", index), create=True)
    value = modes[mode]
    if value is None:               # wavetable = default => remove the key
        node["plainParams"].pop("kParamType", None)
    else:
        node["plainParams"]["kParamType"] = value


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
            pp = node.get("plainParams", {})
            pp = pp if isinstance(pp, dict) else {}
            entry = {"index": n, "params": dict(pp)}
            if mtype == "oscillator":
                entry["mode"] = pp.get("kParamType")
            out[bucket].append(entry)
    minfo = pc.module_info(catalog, "macro")
    for n in range(minfo["count"]):
        node = tree.get("Macro%d" % n)
        if not isinstance(node, dict):
            continue
        pp = node.get("plainParams", {})
        pp = pp if isinstance(pp, dict) else {}
        out["macros"].append({"index": n, "name": node.get("name", ""),
                              "value": pp.get("kParamValue")})
    return out
```

- [ ] **Step 4: Run tests to verify pass.**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_serum_patch_utils.py -q
```
Expected: PASS (10 tests).

- [ ] **Step 5: Add the 791-preset roundtrip-gate test** (mutate one node, encode, decode, assert tree equal except the patched node).

```python
# append to tests/test_serum_patch_utils.py
import glob, os
from ableton_mcp_max import serum_state_codec as ssc
from ableton_mcp_max import serum_patch_catalog as realpc

_ROOT = "/Library/Audio/Presets/Xfer Records/Serum 2 Presets/Presets"

@pytest.mark.skipif(not glob.glob(os.path.join(_ROOT, "**", "*.SerumPreset"), recursive=True),
                    reason="factory presets absent")
def test_roundtrip_setting_macro_only_changes_that_node():
    cat = realpc.load_catalog()
    files = glob.glob(os.path.join(_ROOT, "**", "*.SerumPreset"), recursive=True)
    for p in files[:50]:
        st = ssc.decode(open(p, "rb").read())
        before = {k: v for k, v in st.tree.items() if k != "Macro0"}
        pu.set_macro(cat, st.tree, 0, 42.0)
        re = ssc.decode(ssc.encode(st, st.tree)).tree
        after = {k: v for k, v in re.items() if k != "Macro0"}
        assert after == before, "patch perturbed an unrelated node in %s" % p
        assert re["Macro0"]["plainParams"]["kParamValue"] == 42.0
```

- [ ] **Step 6: Run the offline suite.**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_serum_patch_utils.py -q
```
Expected: PASS (10 + roundtrip gate; gate runs on this dev machine since factory presets are present).

- [ ] **Step 7: Commit.**

```bash
git add ableton_mcp_max/serum_patch_utils.py tests/test_serum_patch_utils.py
git commit -m "feat: Serum patch utils (osc/filter/env/lfo/macro read+set) + roundtrip gate"
```

---

### Task 3: Mod-matrix routes in `serum_patch_utils.py`

**Files:**
- Modify: `ableton_mcp_max/serum_patch_utils.py`
- Test: `tests/test_serum_patch_utils.py` (append)

**Interfaces:**
- Consumes: `serum_patch_catalog` (`dest_type_string`, `dest_param_id`, `node_key`), and `catalog["mod_sources"]`.
- Produces (consumed by Tasks 4, 5):
  - `resolve_source(catalog, source) -> list` - if `source` is an int (or int-like), returns `[int(source), 0]`; else looks `source` up in `catalog["mod_sources"]` (friendly->int) and returns `[id, 0]`. ValueError on unknown friendly name.
  - `add_mod_route(catalog, tree, source, dest_module, dest_index, dest_param, amount) -> int` - finds the first free `ModSlot{n}` (`_is_free_slot`), writes `source` (via `resolve_source`), `destModuleTypeString` (from `dest_module`), `destModuleID = dest_index`, `destModuleParamName` (the resolved `kParam*`), `destModuleParamID` (via `dest_param_id`), and `plainParams.kParamAmount`. Returns the slot index. ValueError if no free slot.
  - `clear_mod_route(catalog, tree, dest_module, dest_index, dest_param) -> int` - resets the first `ModSlot` matching that dest to `{"plainParams": {}}`. Returns the slot index, or ValueError if none match.
  - `_is_free_slot(node) -> bool` - True if the slot has no `source` and no `destModuleTypeString` (i.e. `{"plainParams": {}}`-shaped or absent).

- [ ] **Step 1: Write the failing tests.**

```python
# append to tests/test_serum_patch_utils.py
MODCAT = {"plugin": "Serum2",
          "modules": CAT["modules"],
          "mod_dest_types": {"filter": "VoiceFilter", "oscillator": "Oscillator"},
          "mod_dest_params": {"VoiceFilter": {"kParamFreq": 3}, "Oscillator": {"kParamVolume": 1}},
          "mod_sources": {"env1": 26}}

def _mod_tree():
    return {"ModSlot%d" % n: {"plainParams": {}} for n in range(64)}

def test_resolve_source_int_and_name():
    assert pu.resolve_source(MODCAT, 30) == [30, 0]
    assert pu.resolve_source(MODCAT, "env1") == [26, 0]

def test_resolve_source_unknown_name_raises():
    with pytest.raises(ValueError):
        pu.resolve_source(MODCAT, "nope")

def test_add_mod_route_uses_first_free_slot():
    t = _mod_tree()
    idx = pu.add_mod_route(MODCAT, t, "env1", "filter", 0, "Freq", 40.0)
    assert idx == 0
    s = t["ModSlot0"]
    assert s["source"] == [26, 0]
    assert s["destModuleTypeString"] == "VoiceFilter"
    assert s["destModuleID"] == 0
    assert s["destModuleParamName"] == "kParamFreq"
    assert s["destModuleParamID"] == 3
    assert s["plainParams"]["kParamAmount"] == 40.0

def test_add_mod_route_raw_int_source():
    t = _mod_tree()
    pu.add_mod_route(MODCAT, t, 31, "oscillator", 1, "kParamVolume", 10.0)
    assert t["ModSlot0"]["source"] == [31, 0]
    assert t["ModSlot0"]["destModuleID"] == 1

def test_add_mod_route_no_free_slot_raises():
    t = _mod_tree()
    for _ in range(64):
        pu.add_mod_route(MODCAT, t, 26, "filter", 0, "Freq", 1.0)
    with pytest.raises(ValueError):
        pu.add_mod_route(MODCAT, t, 26, "filter", 0, "Freq", 1.0)

def test_clear_mod_route_frees_slot():
    t = _mod_tree()
    pu.add_mod_route(MODCAT, t, "env1", "filter", 0, "Freq", 40.0)
    idx = pu.clear_mod_route(MODCAT, t, "filter", 0, "Freq")
    assert idx == 0
    assert pu._is_free_slot(t["ModSlot0"])

def test_clear_mod_route_not_found_raises():
    with pytest.raises(ValueError):
        pu.clear_mod_route(MODCAT, _mod_tree(), "filter", 0, "Freq")
```

- [ ] **Step 2: Run to verify failure.**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_serum_patch_utils.py -k "mod or source" -q
```
Expected: FAIL with `AttributeError: module ... has no attribute 'resolve_source'`.

- [ ] **Step 3: Implement.**

```python
# append to ableton_mcp_max/serum_patch_utils.py
_MOD_SLOTS = 64


def _is_free_slot(node):
    if not isinstance(node, dict):
        return True
    return "source" not in node and "destModuleTypeString" not in node


def resolve_source(catalog, source):
    if isinstance(source, bool):
        raise ValueError("mod source must be an int id or a name, not a bool")
    if isinstance(source, int):
        return [int(source), 0]
    if isinstance(source, str) and source.lstrip("-").isdigit():
        return [int(source), 0]
    srcs = catalog.get("mod_sources", {})
    if source not in srcs:
        raise ValueError("unknown mod source %r; pass a raw int id, or one of: %s"
                         % (source, ", ".join(sorted(srcs)) or "(none configured yet)"))
    return [int(srcs[source]), 0]


def _dest_fields(catalog, dest_module, dest_index, dest_param):
    ts = pc.dest_type_string(catalog, dest_module)
    info = pc.param_info(catalog, dest_module, dest_param) if dest_module in catalog["modules"] else None
    kparam = info["kparam"] if info else (dest_param if dest_param.startswith("kParam") else "kParam" + dest_param)
    pid = pc.dest_param_id(catalog, ts, kparam)
    return ts, int(dest_index), kparam, pid


def add_mod_route(catalog, tree, source, dest_module, dest_index, dest_param, amount):
    src = resolve_source(catalog, source)
    ts, did, kparam, pid = _dest_fields(catalog, dest_module, dest_index, dest_param)
    for n in range(_MOD_SLOTS):
        key = "ModSlot%d" % n
        node = tree.get(key)
        if node is None or _is_free_slot(node):
            tree[key] = {"source": src, "destModuleID": did, "destModuleParamID": pid,
                         "destModuleParamName": kparam, "destModuleTypeString": ts,
                         "plainParams": {"kParamAmount": float(amount)}}
            return n
    raise ValueError("no free ModSlot (all %d used)" % _MOD_SLOTS)


def clear_mod_route(catalog, tree, dest_module, dest_index, dest_param):
    ts, did, kparam, pid = _dest_fields(catalog, dest_module, dest_index, dest_param)
    for n in range(_MOD_SLOTS):
        node = tree.get("ModSlot%d" % n)
        if (isinstance(node, dict) and node.get("destModuleTypeString") == ts
                and node.get("destModuleID") == did
                and node.get("destModuleParamID") == pid):
            tree["ModSlot%d" % n] = {"plainParams": {}}
            return n
    raise ValueError("no mod route to %s[%d].%s found" % (dest_module, dest_index, dest_param))
```

- [ ] **Step 4: Run to verify pass.**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_serum_patch_utils.py -q
```
Expected: PASS (all prior + 7 new).

- [ ] **Step 5: Commit.**

```bash
git add ableton_mcp_max/serum_patch_utils.py tests/test_serum_patch_utils.py
git commit -m "feat: Serum mod-matrix route add/clear (structural dest, int-or-name source)"
```

---

### Task 4: Generalize the mutate/read impls + granular server tools

**Files:**
- Modify: `ableton_mcp_max/server.py` (generalize `_serum_fx_mutate_impl`/`_serum_fx_read_impl`; add imports + tools)
- Test: `tests/test_serum_patch_tools.py`

**Interfaces:**
- Consumes: `serum_patch_utils` (`set_module_params`, `set_oscillator_mode`, `set_macro`, `add_mod_route`, `clear_mod_route`, `summarize`), `serum_patch_catalog.load_catalog`, and the existing `_serum_fx_mutate_impl`/`_serum_fx_read_impl`.
- Produces (consumed by Task 5): generalized `_serum_fx_mutate_impl(..., catalog_loader=_sfxcat.load_catalog)` and `_serum_fx_read_impl(..., project_fn=None)`; plus the granular `@mcp.tool()` functions `get_serum_patch`, `set_serum_oscillator`, `set_serum_filter`, `set_serum_envelope`, `set_serum_lfo`, `set_serum_macro`, `add_serum_mod_route`, `clear_serum_mod_route`.

- [ ] **Step 1: Generalize the existing impls.** In `ableton_mcp_max/server.py`, add `catalog_loader=_sfxcat.load_catalog` to `_serum_fx_mutate_impl`'s keyword-only args and replace the hardcoded `catalog = _sfxcat.load_catalog()` line with `catalog = catalog_loader()`. Add `project_fn=None` to `_serum_fx_read_impl`'s keyword-only args and replace its return with:

```python
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

- [ ] **Step 3: Inspect the existing FX-tool test harness, then write the tool-wiring test.**

```bash
sed -n '1,80p' tests/test_serum_fx_tools.py
```

Write `tests/test_serum_patch_tools.py` using the SAME harness style (monkeypatch the impl, run the captured `mutate_fn`/`project_fn` against an in-memory tree). NOTE: installed FastMCP `@mcp.tool()` returns the PLAIN function - call `server.set_serum_oscillator(None, ...)` directly (per the catalog work's Task 7 finding).

```python
# tests/test_serum_patch_tools.py
import json
from ableton_mcp_max import server

def test_set_serum_oscillator_writes_param(monkeypatch):
    captured = {}
    def fake_mutate(track_index, device_index, mutate_fn, **kw):
        cat = kw["catalog_loader"]()
        tree = {"Oscillator0": {"plainParams": {}}}
        mutate_fn(cat, tree)
        captured["tree"] = tree
        return {"ok": True, "reloaded": False, "set_path": "/x.als"}
    monkeypatch.setattr(server, "_serum_fx_mutate_impl", fake_mutate)
    monkeypatch.setattr(server, "get_ableton_connection", lambda: object())
    out = json.loads(server.set_serum_oscillator(None, 1, 0, {"Volume": 0.8}))
    assert out["ok"] is True
    assert captured["tree"]["Oscillator0"]["plainParams"].get("kParamVolume") == 0.8

def test_set_serum_macro_writes_value_and_name(monkeypatch):
    captured = {}
    def fake_mutate(track_index, device_index, mutate_fn, **kw):
        cat = kw["catalog_loader"]()
        tree = {"Macro0": {"plainParams": {}}}
        mutate_fn(cat, tree)
        captured["tree"] = tree
        return {"ok": True, "reloaded": True, "set_path": "/x.als"}
    monkeypatch.setattr(server, "_serum_fx_mutate_impl", fake_mutate)
    monkeypatch.setattr(server, "get_ableton_connection", lambda: object())
    out = json.loads(server.set_serum_macro(None, 1, 0, 30.0, name="CUTOFF"))
    assert out["ok"] is True
    assert captured["tree"]["Macro0"]["name"] == "CUTOFF"
    assert captured["tree"]["Macro0"]["plainParams"]["kParamValue"] == 30.0

def test_add_serum_mod_route(monkeypatch):
    captured = {}
    def fake_mutate(track_index, device_index, mutate_fn, **kw):
        cat = kw["catalog_loader"]()
        tree = {"ModSlot%d" % n: {"plainParams": {}} for n in range(64)}
        mutate_fn(cat, tree)
        captured["tree"] = tree
        return {"ok": True, "reloaded": True, "set_path": "/x.als"}
    monkeypatch.setattr(server, "_serum_fx_mutate_impl", fake_mutate)
    monkeypatch.setattr(server, "get_ableton_connection", lambda: object())
    out = json.loads(server.add_serum_mod_route(None, 1, 26, "filter", 0, "Freq", 40.0))
    assert out["ok"] is True
    assert captured["tree"]["ModSlot0"]["destModuleTypeString"] == "VoiceFilter"
    assert captured["tree"]["ModSlot0"]["source"] == [26, 0]

def test_get_serum_patch_projects_summary(monkeypatch):
    def fake_read(track_index, device_index, **kw):
        tree = {"Oscillator0": {"plainParams": {"kParamVolume": 0.5}}}
        payload = {"ok": True, "set_path": "/x.als"}
        payload.update(kw["project_fn"](tree))
        return payload
    monkeypatch.setattr(server, "_serum_fx_read_impl", fake_read)
    monkeypatch.setattr(server, "get_ableton_connection", lambda: object())
    out = json.loads(server.get_serum_patch(None, 1))
    assert out["ok"] is True
    assert any(o["index"] == 0 for o in out["data"]["oscillators"])
```

- [ ] **Step 4: Run to verify failure.**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_serum_patch_tools.py -q
```
Expected: FAIL with `AttributeError: module 'ableton_mcp_max.server' has no attribute 'set_serum_oscillator'`.

- [ ] **Step 5: Add the granular tools** in `server.py` after the Release 2 serum FX tools. Each mirrors `set_serum_fx_param`'s structure (try/except, `get_ableton_connection()`, build `mutate_fn`, call `_serum_fx_mutate_impl(..., catalog_loader=_spcat.load_catalog)`).

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
    catalog. mode (when given) selects the oscillator engine: 'wavetable' (default),
    'multisample', 'sample', 'granular', 'spectral'.

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

Add `set_serum_filter(track_index, filt, params=None, device_index=0, reload=True)`, `set_serum_envelope(track_index, env, params=None, ...)`, `set_serum_lfo(track_index, lfo, params=None, ...)` identically - each `mutate_fn` calls `_spu.set_module_params(catalog, tree, "<filter|envelope|lfo>", <index>, params)` (guard `if params:`). Add `set_serum_macro`:

```python
@mcp.tool()
def set_serum_macro(ctx: Context, track_index: int, macro: int, value: float,
                    name: str = None, device_index: int = 0, reload: bool = True) -> str:
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


@mcp.tool()
def add_serum_mod_route(ctx: Context, track_index: int, source, dest_module: str,
                        dest_index: int, dest_param: str, amount: float,
                        device_index: int = 0, reload: bool = True) -> str:
    """Add a Serum mod-matrix route into a free ModSlot.

    source is a raw integer mod-source id OR a configured friendly name (catalog
    mod_sources). dest is structural: dest_module ('oscillator'|'filter'|'envelope'|
    'lfo'|'wt'|'macro'|'global'), dest_index (instance), dest_param (friendly or
    kParam*). amount is native (typically 0-100). Patches state + reloads in place.

    Parameters:
    - track_index: track holding the Serum 2 instance.
    - source: int source id (or friendly name once configured).
    - dest_module: destination module type.
    - dest_index: destination instance index.
    - dest_param: destination parameter (friendly or kParam*).
    - amount: modulation amount (native).
    - device_index: which VST/AU plugin device on the track (0 = first plugin).
    - reload: reload the set after patching (default True).

    Returns JSON {ok, data:{reloaded, set_path}}."""
    try:
        get_ableton_connection()
        def mutate_fn(catalog, tree):
            _spu.add_mod_route(catalog, tree, source, dest_module, dest_index, dest_param, amount)
        result = _serum_fx_mutate_impl(
            track_index, device_index, mutate_fn, reload=reload,
            catalog_loader=_spcat.load_catalog,
            save_impl=lambda: _save_set_impl(name=""),
            reload_impl=lambda p, n: _reload_set(p, n))
        if not result.get("ok"):
            return _err(result.get("error", "add_serum_mod_route failed"))
        return _ok(result)
    except (ValueError, RuntimeError, FileNotFoundError) as e:
        return _err(str(e))
    except Exception as e:
        logger.error("add_serum_mod_route error: %s", e)
        return _err("add_serum_mod_route error: %s" % e)
```

Add `clear_serum_mod_route(track_index, dest_module, dest_index, dest_param, device_index=0, reload=True)` calling `_spu.clear_mod_route(catalog, tree, dest_module, dest_index, dest_param)`.

- [ ] **Step 6: Run the tool test + full suite + import check.**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python -c "import ableton_mcp_max.server"
```
Expected: all PASS (including the existing FX-tool tests, proving the generalization didn't regress); import exit 0.

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
- Consumes: all `serum_patch_utils` setters + `serum_fx_utils.set_fx_param` (optional `fx` section), the generalized `_serum_fx_mutate_impl`.
- Produces: `create_serum_patch(track_index, spec, device_index=0, reload=True)` - applies the whole `spec` to one decoded tree in a single `mutate_fn`, one reload. Returns `{ok, data:{reloaded, set_path, applied}}`.

- [ ] **Step 1: Write the failing test.**

```python
# append to tests/test_serum_patch_tools.py
def test_create_serum_patch_applies_sections(monkeypatch):
    captured = {}
    def fake_mutate(track_index, device_index, mutate_fn, **kw):
        cat = kw["catalog_loader"]()
        tree = {"Oscillator0": {"plainParams": {}}, "Macro0": {"plainParams": {}}}
        for n in range(64):
            tree["ModSlot%d" % n] = {"plainParams": {}}
        mutate_fn(cat, tree)
        captured["tree"] = tree
        return {"ok": True, "reloaded": True, "set_path": "/x.als"}
    monkeypatch.setattr(server, "_serum_fx_mutate_impl", fake_mutate)
    monkeypatch.setattr(server, "get_ableton_connection", lambda: object())
    spec = {"oscillators": [{"index": 0, "params": {"Volume": 0.7}}],
            "macros": [{"index": 0, "value": 30.0, "name": "X"}],
            "mod_routes": [{"source": 26, "dest_module": "filter", "dest_index": 0,
                            "dest_param": "Freq", "amount": 40.0}]}
    out = json.loads(server.create_serum_patch(None, 1, spec))
    assert out["ok"] is True
    assert captured["tree"]["Macro0"]["name"] == "X"
    assert captured["tree"]["ModSlot0"]["destModuleTypeString"] == "VoiceFilter"
    assert out["data"]["applied"]["mod_routes"] == 1
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
      oscillators: [{index, mode?, params?}]   filters:   [{index, params}]
      envelopes:   [{index, params}]           lfos:      [{index, params}]
      macros:      [{index, value, name?}]     wavetables:[{index, table}]
      mod_routes:  [{source, dest_module, dest_index, dest_param, amount}]
      fx:          [{rack, slot, kparam, value}]   (Serum FX setters)
    Params are native, range-validated. Applies everything to one decoded tree then
    reloads once.

    Parameters:
    - track_index: track holding the Serum 2 instance.
    - spec: the patch description dict.
    - device_index: which VST/AU plugin device on the track (0 = first plugin).
    - reload: reload the set after patching (default True).

    Returns JSON {ok, data:{reloaded, set_path, applied}}."""
    try:
        get_ableton_connection()
        applied = {"oscillators": 0, "filters": 0, "envelopes": 0, "lfos": 0,
                   "macros": 0, "wavetables": 0, "mod_routes": 0, "fx": 0}
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
            for w in spec.get("wavetables", []):
                _spu.set_wavetable(catalog, tree, w["index"], w["table"])
                applied["wavetables"] += 1
            for r in spec.get("mod_routes", []):
                _spu.add_mod_route(catalog, tree, r["source"], r["dest_module"],
                                   r["dest_index"], r["dest_param"], r["amount"])
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

> NOTE: the `wavetables` section calls `_spu.set_wavetable`, added in Task 6. If Task 6 is not yet merged when this task is implemented, OMIT the `wavetables` loop and its `applied` key, and add them in Task 6. (Implement Task 6 before this one to avoid the gap, OR leave the loop out here and fold it in during Task 6.)

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

### Task 6: `set_serum_wavetable` (path-ref via relativePathToWT)

**Files:**
- Modify: `ableton_mcp_max/serum_patch_utils.py`
- Modify: `ableton_mcp_max/server.py`
- Test: `tests/test_serum_patch_utils.py` (append)

**Interfaces:**
- Produces: `serum_patch_utils.set_wavetable(catalog, tree, osc, table) -> None` and the `set_serum_wavetable(track_index, osc, table, device_index=0, reload=True)` tool.

Spike-confirmed: a WT-mode oscillator stores its table at `Oscillator{n}.WTOsc{n}.relativePathToWT` (e.g. `"S2 Tables/Default Shapes.wav"`). `set_wavetable` writes that string and ensures WT mode (delete `kParamType`). Serum reloads + recomputes `numFrames`/`sampleRate` from the file on load.

- [ ] **Step 1: Write the failing test.**

```python
# append to tests/test_serum_patch_utils.py
def test_set_wavetable_writes_ref_and_wt_mode():
    t = {"Oscillator0": {"plainParams": {"kParamType": "kOsc_Sample"},
                         "WTOsc0": {"plainParams": "default"}}}
    pu.set_wavetable(CAT, t, 0, "S2 Tables/Basic Shapes.wav")
    assert "kParamType" not in t["Oscillator0"]["plainParams"]  # WT = default
    assert t["Oscillator0"]["WTOsc0"]["relativePathToWT"] == "S2 Tables/Basic Shapes.wav"

def test_set_wavetable_creates_wtosc_when_absent():
    t = {"Oscillator1": {"plainParams": {}}}
    pu.set_wavetable(CAT, t, 1, "S2 Tables/Default Shapes.wav")
    assert t["Oscillator1"]["WTOsc1"]["relativePathToWT"] == "S2 Tables/Default Shapes.wav"
```

- [ ] **Step 2: Run to verify failure.**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_serum_patch_utils.py -k wavetable -q
```
Expected: FAIL (`no attribute 'set_wavetable'`).

- [ ] **Step 3: Implement `set_wavetable`.**

```python
# append to ableton_mcp_max/serum_patch_utils.py
def set_wavetable(catalog, tree, osc, table):
    node = _node(tree, pc.node_key(catalog, "oscillator", osc), create=True)
    node["plainParams"].pop("kParamType", None)   # WT is the default mode
    wtkey = "WTOsc%d" % osc
    wt = node.get(wtkey)
    if not isinstance(wt, dict):
        wt = {"plainParams": "default"}
        node[wtkey] = wt
    wt["relativePathToWT"] = table
```

- [ ] **Step 4: Add the `set_serum_wavetable` tool** in `server.py` (same wrapper shape as `set_serum_macro`, `mutate_fn` calls `_spu.set_wavetable(catalog, tree, osc, table)`):

```python
@mcp.tool()
def set_serum_wavetable(ctx: Context, track_index: int, osc: int, table: str,
                        device_index: int = 0, reload: bool = True) -> str:
    """Point a Serum oscillator at a wavetable file and put it in WaveTable mode.

    Writes the table path into Oscillator{osc}.WTOsc{osc}.relativePathToWT (relative
    to Serum's table library, e.g. 'S2 Tables/Default Shapes.wav') and clears the
    oscillator mode to WaveTable (the default). Serum loads + recomputes the table on
    reload. State authoring - the table must exist in Serum's library.

    Parameters:
    - track_index: track holding the Serum 2 instance.
    - osc: oscillator index (0-4).
    - table: wavetable path relative to Serum's table library.
    - device_index: which VST/AU plugin device on the track (0 = first plugin).
    - reload: reload the set after patching (default True).

    Returns JSON {ok, data:{reloaded, set_path}}."""
    try:
        get_ableton_connection()
        def mutate_fn(catalog, tree):
            _spu.set_wavetable(catalog, tree, osc, table)
        result = _serum_fx_mutate_impl(
            track_index, device_index, mutate_fn, reload=reload,
            catalog_loader=_spcat.load_catalog,
            save_impl=lambda: _save_set_impl(name=""),
            reload_impl=lambda p, n: _reload_set(p, n))
        if not result.get("ok"):
            return _err(result.get("error", "set_serum_wavetable failed"))
        return _ok(result)
    except (ValueError, RuntimeError, FileNotFoundError) as e:
        return _err(str(e))
    except Exception as e:
        logger.error("set_serum_wavetable error: %s", e)
        return _err("set_serum_wavetable error: %s" % e)
```

(If Task 5's `create_serum_patch` omitted the `wavetables` loop, add it now.)

- [ ] **Step 5: Run tests + import.**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python -c "import ableton_mcp_max.server"
```
Expected: all PASS; import exit 0.

- [ ] **Step 6: Commit.**

```bash
git add ableton_mcp_max/serum_patch_utils.py ableton_mcp_max/server.py tests/test_serum_patch_utils.py
git commit -m "feat: set_serum_wavetable (path-ref wavetable selection)"
```

---

### Task 7: Live verify (+ mod-source oracle) + docs + ship

**Files:**
- Modify: `ableton_mcp_max/param_maps/serum2_patch.json` (`mod_sources` from the oracle)
- Modify: `pyproject.toml`, `.claude-plugin/plugin.json`, `uv.lock` (version bump)
- Modify: `docs/tools/*`, `docs/tools/index.md`, `commands/tool-index.md` (regen)
- Modify: `docs/index.md` (5 hardcoded count spots), `README.md:7` (count) - BY HAND
- Modify: `PROGRESS.md`

This task is the controller's main-loop work (live Live + ship), not an implementer dispatch.

- [ ] **Step 1: Live verify on Live 12.4.** To exercise working-tree `server.py`, use the AbletonDev MCP tools (restart Claude Code to reload) or subprocess-import the working-tree server on 9877; disable the cached `ableton` plugin if it fights for the port. On a scratch track: load fresh Serum 2, `save_set_as` to a scratch set, drive `create_serum_patch` with a small spec (one osc param + mode, one filter param, one envelope param, one macro, one wavetable path, one mod route via raw int source). Reload; `get_serum_patch` to confirm values survived; audition. Move the macro / play notes to confirm the mod route modulates. Delete the scratch device; restore baseline.

- [ ] **Step 2: Mod-source oracle.** In Serum's GUI, drag a KNOWN source (Env 1, then LFO 1, then Macro 1, Velocity, Note) onto a known dest to create routes; `save_set`; parse the `.als` ModSlots for each route's `source[0]` id. Fill `mod_sources` in `serum2_patch.json` (friendly name -> int id) with the verified mappings. Re-run the offline suite (catalog test still green). Commit:

```bash
git add ableton_mcp_max/param_maps/serum2_patch.json
git commit -m "feat: populate Serum mod_sources from live oracle capture"
```

- [ ] **Step 3: Record live results** in `PROGRESS.md` and the `vst-plugin-support` memory (what survived reload, wavetable outcome, the verified source-id table, any gotchas).

- [ ] **Step 4: Version + docs.** Check shipped tags vs unreleased commits (CLAUDE.md version-drift rule):

```bash
gh release list | head
git log $(git describe --tags --abbrev=0)..HEAD --oneline
```
Pick the next minor. Update `pyproject.toml` + `.claude-plugin/plugin.json` to the same version, then `uv lock`. Regen docs + hand-bump counts (new tools added: get_serum_patch, set_serum_oscillator/filter/envelope/lfo/macro, add/clear_serum_mod_route, create_serum_patch, set_serum_wavetable = 10):

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python scripts/build_tool_index.py
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python scripts/gen_docs_site.py
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python -c "import ast;m=ast.parse(open('ableton_mcp_max/server.py').read());print(sum(1 for n in ast.walk(m) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and any(getattr(d,'attr','')=='tool' or getattr(getattr(d,'func',None),'attr','')=='tool' for d in n.decorator_list)))"
```
Edit `docs/index.md` (5 hardcoded spots) and `README.md:7` to the new total by hand.

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
Then bump the `ableton` entry's `ref` to `vX.Y.Z` in the marketplace repo's `marketplace.json`, run its `node scripts/build-readme.js`, push. Confirm the chain per CLAUDE.md.

---

## Self-Review

**Spec coverage:**
- Full patch authoring via Release 2 mechanism -> Tasks 4/5 reuse `_serum_fx_mutate_impl`. OK
- Both granular + declarative -> Task 4 (granular) + Task 5 (`create_serum_patch`). OK
- Osc params + string mode -> Task 2 + Task 4. OK
- Wavetable (path-ref) -> Task 6. OK
- Filters / envelopes / LFOs -> Task 2 + Task 4. OK
- Mod matrix (structural dest, int-or-name source) -> Task 3 + Task 4; source names via Task 7 oracle. OK
- Macros -> Task 2 + Task 4. OK
- Catalog (params, modes, dest table, sources) -> Task 1. OK
- 791-preset roundtrip gate -> Task 2 Step 5. OK
- Live verify + ship -> Task 7. OK

**Placeholder scan:** No TBDs. `vX.Y.Z` is resolved in Task 7 Step 4 (version-drift rule); `<summary>`/`<notes>` are PR prose. The Task 5 `wavetables` ordering note is an explicit sequencing instruction (implement Task 6 before Task 5's loop runs, or fold in during Task 6), not a placeholder.

**Type consistency:** catalog (`load_catalog`/`module_info`/`node_key`/`param_info`/`dest_type_string`/`dest_param_id`) and utils (`set_module_params`/`set_oscillator_mode`/`set_macro`/`summarize`/`resolve_source`/`add_mod_route`/`clear_mod_route`/`set_wavetable`) names match across Tasks 1-6 and their server-tool callers. The generalized `_serum_fx_mutate_impl(..., catalog_loader=...)` / `_serum_fx_read_impl(..., project_fn=...)` signatures (Task 4 Step 1) match every call site in Tasks 4/5/6. `add_mod_route(source, dest_module, dest_index, dest_param, amount)` is consistent between Task 3 (util), Task 4 (tool), and Task 5 (spec composer).

**Ordering note:** Task 6 (`set_wavetable`) is referenced by Task 5's `create_serum_patch` `wavetables` loop. Implement Task 6 before Task 5, or omit the loop in Task 5 and add it in Task 6 (instruction in Task 5 Step 3).
