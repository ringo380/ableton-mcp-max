# Ozone 12 Deep Mastering Support - Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship deep, module-aware parameter control of an iZotope Ozone 12 instance (read/set every module's params, per-module enable, on-demand exposure within the 128-slot cap) on regular, return, and master tracks.

**Architecture:** Reuse the generic plugin-exposure engine (`plugin_config_utils` + `_expose_plugin_impl`). Ozone 12 exposes all 873 params to the host by structured name, index-addressed (`id = id_base + probe_index`), so a pure module model (`ozone_utils.py`) parses the names, a generated catalog (`param_maps/ozone12.json`) holds all params, and new module-aware `@mcp.tool()`s expose/read/set them. Because Ozone lives on the master, the exposure path is extended to master/return track spans.

**Tech Stack:** Python 3 (server side, `uv`); pure `*_utils.py` modules imported by `server.py` only; pytest offline; the Remote Script is untouched in Phase 1 (probe already exists).

## Global Constraints

- Return `{ok, data|error}` from every `@mcp.tool()` via the existing `_ok`/`_err` helpers.
- `*_utils.py` are imported by `server.py` ONLY; never by the Remote Script. Resolve/normalize/clamp on the server; do not add Remote Script code in Phase 1.
- Offline gate: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q`, plus `uv run python -c "import ableton_mcp_max.server"`.
- ASCII only in source/tests/data (no Unicode dashes or symbols).
- Do NOT reformat existing files to ruff style; match surrounding code.
- The exposure backdoor patches the `.als`: the set MUST be saved to a real file first (untitled errors); Live is briefly focused for the in-place reload.
- Ableton's Configure pool is 128 slots; never silently truncate past it - report `dropped`/`overflow`.
- Live-verify is manual against the open set (Ozone 12 is on the master track). Re-read state each session; verify writes with a separate follow-up read.

## File Structure

- Create `ableton_mcp_max/ozone_utils.py` - pure module model: name parser, module registry, budget packer, value mapping.
- Create `ableton_mcp_max/ozone_param_catalog.py` - loader/validator for the generated pack.
- Create `ableton_mcp_max/param_maps/ozone12.json` - generated catalog of all 873 params.
- Create `scripts/build_ozone_catalog.py` - generates `ozone12.json` from a captured probe dataset + the parser.
- Modify `ableton_mcp_max/als_automation_utils.py` - add `find_master_track_span` / `find_return_track_span`.
- Modify `ableton_mcp_max/server.py` - extend `_expose_plugin_impl` for master/return; add module-aware tools.
- Create tests: `tests/test_ozone_utils.py`, `tests/test_ozone_param_catalog.py`, `tests/test_ozone_track_span.py`, `tests/test_ozone_tools.py`.

---

### Task 1: Ozone name parser + module registry (`ozone_utils.py`)

Pure logic. All 873 names were captured from a live probe (2026-07-01); their shape is `MODULE: [Stereo/Main|Aux] <role words> [band]` (e.g. `EQ: Stereo/Main Frequency 3`, `MAX: Output Level`, `DYN: Stereo/Main Band 2 Comp Threshold`, `Global Bypass`).

**Files:**
- Create: `ableton_mcp_max/ozone_utils.py`
- Test: `tests/test_ozone_utils.py`

**Interfaces:**
- Produces:
  - `MODULES: dict[str, str]` - module key -> friendly name (e.g. `"MAX" -> "Maximizer"`).
  - `parse_param_name(name: str) -> dict` returning `{module, module_name, section, role, band, raw}` where `section in {"stereo_main","aux",None}`, `role` is a lowercased space-joined role string, `band` is `int|None`. Non-module names (`"Global Bypass"`) return `{module:None, module_name:None, section:None, role:"global bypass", band:None, raw:name}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ozone_utils.py
from ableton_mcp_max import ozone_utils as oz


def test_modules_registry_has_core_mastering_modules():
    for key in ("EQ", "MAX", "DYN", "IMG", "DYNEQ", "EXC", "VLIM", "STEMEQ", "UNLIMITER"):
        assert key in oz.MODULES
    assert oz.MODULES["MAX"] == "Maximizer"
    assert oz.MODULES["IMG"] == "Imager"


def test_parse_stereo_main_banded():
    r = oz.parse_param_name("EQ: Stereo/Main Frequency 3")
    assert r["module"] == "EQ"
    assert r["module_name"] == "Equalizer"
    assert r["section"] == "stereo_main"
    assert r["role"] == "frequency"
    assert r["band"] == 3


def test_parse_aux_multiword_role_banded():
    r = oz.parse_param_name("DYN: Aux Band 2 Comp Threshold")
    assert r["module"] == "DYN"
    assert r["section"] == "aux"
    assert r["band"] == 2
    assert r["role"] == "band comp threshold"


def test_parse_module_unbanded():
    r = oz.parse_param_name("MAX: Output Level")
    assert r["module"] == "MAX"
    assert r["section"] is None
    assert r["role"] == "output level"
    assert r["band"] is None


def test_parse_bypass_and_global():
    b = oz.parse_param_name("MAX: Bypass")
    assert b["module"] == "MAX" and b["role"] == "bypass"
    g = oz.parse_param_name("Global Bypass")
    assert g["module"] is None and g["role"] == "global bypass"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_ozone_utils.py -q`
Expected: FAIL with `ModuleNotFoundError: ozone_utils` / attribute errors.

- [ ] **Step 3: Write minimal implementation**

```python
# ableton_mcp_max/ozone_utils.py
"""Pure module model for iZotope Ozone 12 (host-side only).

Ozone 12 exposes 873 host params named `MODULE: [Stereo/Main|Aux] <role> [band]`.
This module parses those names into a structured model, holds the module
registry, packs a chosen module set into Ableton's 128 Configure slots, and maps
values between LOM-normalized 0-1 and native units. Imported by server.py only.
"""
import re

MODULES = {
    "EQ": "Equalizer",
    "EQ2": "Equalizer 2",
    "IMG": "Imager",
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
    "MATCH EQ": "Match EQ",
    "LEF": "Low End Focus",
    "IMP": "Impact",
    "STBL": "Stabilizer",
    "CLA": "Clarity",
    "BAS": "Bass Control",
    "STEMEQ": "Stem EQ",
    "UNLIMITER": "Unlimiter",
    "GAIN": "Gain",
}

# module keys sorted longest-first so "MATCH EQ" wins over a bare "EQ" prefix
_MODULE_KEYS = sorted(MODULES, key=len, reverse=True)
_TRAIL_BAND = re.compile(r"\s+(\d+)$")


def parse_param_name(name):
    """Parse one Ozone host param name into a structured record.

    Returns {module, module_name, section, role, band, raw}. A name with no
    `MODULE:` prefix (e.g. 'Global Bypass') yields module/module_name/section
    None and role = the whole lowercased name.
    """
    raw = name
    module = None
    rest = name
    if ":" in name:
        head, tail = name.split(":", 1)
        if head in MODULES:
            module = head
            rest = tail.strip()
    if module is None:
        return {"module": None, "module_name": None, "section": None,
                "role": name.strip().lower(), "band": None, "raw": raw}
    section = None
    if rest.startswith("Stereo/Main"):
        section = "stereo_main"
        rest = rest[len("Stereo/Main"):].strip()
    elif rest.startswith("Aux"):
        section = "aux"
        rest = rest[len("Aux"):].strip()
    band = None
    m = _TRAIL_BAND.search(rest)
    if m:
        band = int(m.group(1))
        rest = rest[: m.start()].strip()
    return {"module": module, "module_name": MODULES[module], "section": section,
            "role": rest.lower(), "band": band, "raw": raw}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_ozone_utils.py -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/ozone_utils.py tests/test_ozone_utils.py
git commit -m "feat: Ozone 12 name parser + module registry"
```

---

### Task 2: LIVE spike - confirm id_base + capture authoritative param dataset

**RUN IN THE MAIN LOOP (needs Live). Not a subagent task.** Ozone 12 is on the master track. This spike confirms the Configure `id_base` and captures every param's real min/max/quantized/value_items so the catalog carries accurate ranges.

**Files:**
- Create: `scripts/ozone_probe_data.json` (captured dataset; committed so the catalog build is reproducible offline).

- [ ] **Step 1: Probe the master Ozone for the full ordered name list**

Call `mcp__plugin_ableton_AbletonMCPMax__probe_plugin_parameters(track_index=0, device_index=0, track_type="master")` (device_index is Ozone's position on the master chain; re-read `get_track_info`/master devices first).
Expected: `parameter_count: 873`, `names: [...]` (the ordered list; index i -> Configure id `id_base + i`).

- [ ] **Step 2: Confirm id_base on a scratch REGULAR track (decouples from master-span work)**

Create a scratch audio track, load `query:Plugins#VST3:iZotope:Ozone%2012` onto it (effects load on regular tracks), `save_set_as("ozone_idbase_probe")`, then `expose_plugin_parameters` with a tiny hand-built pack of 3 params using `param_id = index` (id_base 0) and sentinel names, `reload=True`. Then `get_device_parameters` on that device.
Expected: the 3 params come back `is_enabled=true` with Live OVERRIDING the sentinel with the REAL Ozone name -> confirms `id_base = 0` (`param_id = probe index`). If they come back `is_enabled=false` with the sentinel kept, id_base != 0: bisect small candidate bases (0, 1000000, 2000000) the same way and record the winner.

- [ ] **Step 3: Capture per-param metadata**

Expose a batch of modules on the scratch instance (fill up to 128 slots), reload, and `get_device_parameters` to read each exposed param's `min`, `max`, `is_quantized`, `value_items`. Repeat across module batches until all 873 are covered. Assemble `scripts/ozone_probe_data.json`:

```json
{
  "id_base": 0,
  "params": [
    {"index": 0, "name": "EQ: Bypass", "min": 0.0, "max": 1.0, "is_quantized": true, "value_items": ["Off", "On"]}
  ]
}
```

- [ ] **Step 4: Clean up**

`delete_track` the scratch track; do NOT save over the user's real set. Leave the master Ozone untouched.

- [ ] **Step 5: Commit**

```bash
git add scripts/ozone_probe_data.json
git commit -m "chore: capture Ozone 12 probe dataset (id_base + param ranges)"
```

---

### Task 3: Catalog build script + `ozone12.json` + loader

**Files:**
- Create: `scripts/build_ozone_catalog.py`
- Create: `ableton_mcp_max/param_maps/ozone12.json` (generated)
- Create: `ableton_mcp_max/ozone_param_catalog.py`
- Test: `tests/test_ozone_param_catalog.py`

**Interfaces:**
- Consumes: `ozone_utils.parse_param_name`, `scripts/ozone_probe_data.json` (Task 2), `param_map_utils.validate_pack`.
- Produces:
  - `ozone12.json` shape: `{plugin:"Ozone12", id_base:int, params:[{param_id, name, category, module, section, role, band, min, max, is_quantized, value_items}]}` (superset of the base pack shape so `expose_plugin_parameters` and `param_map_utils.validate_pack` both accept it; `category` = friendly module name).
  - `ozone_param_catalog.load() -> dict` (validated pack); `catalog_by_module(pack) -> dict[str, list]`; `find_param(pack, module, role, band=None, section=None) -> dict|None`.

- [ ] **Step 1: Write the build script**

```python
# scripts/build_ozone_catalog.py
"""Generate param_maps/ozone12.json from scripts/ozone_probe_data.json.

param_id = id_base + index (index-based Configure scheme, confirmed live).
Each param is enriched via ozone_utils.parse_param_name. Run:
  uv run python scripts/build_ozone_catalog.py
"""
import json
import os

from ableton_mcp_max import ozone_utils as oz

HERE = os.path.dirname(__file__)
SRC = os.path.join(HERE, "ozone_probe_data.json")
OUT = os.path.join(HERE, "..", "ableton_mcp_max", "param_maps", "ozone12.json")


def build():
    data = json.load(open(SRC))
    id_base = data["id_base"]
    params = []
    for p in data["params"]:
        info = oz.parse_param_name(p["name"])
        params.append({
            "param_id": id_base + p["index"],
            "name": p["name"],
            "category": info["module_name"] or "Global",
            "module": info["module"],
            "section": info["section"],
            "role": info["role"],
            "band": info["band"],
            "min": p.get("min"),
            "max": p.get("max"),
            "is_quantized": p.get("is_quantized", False),
            "value_items": p.get("value_items", []),
        })
    pack = {"plugin": "Ozone12", "id_base": id_base, "params": params}
    with open(OUT, "w") as f:
        json.dump(pack, f, indent=1)
        f.write("\n")
    print("wrote %d params to %s" % (len(params), OUT))


if __name__ == "__main__":
    build()
```

- [ ] **Step 2: Generate the catalog**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python scripts/build_ozone_catalog.py`
Expected: `wrote 873 params to .../ozone12.json`.

- [ ] **Step 3: Write the failing test**

```python
# tests/test_ozone_param_catalog.py
from ableton_mcp_max import ozone_param_catalog as cat


def test_catalog_loads_and_validates():
    pack = cat.load()
    assert pack["plugin"] == "Ozone12"
    assert len(pack["params"]) == 873
    ids = [p["param_id"] for p in pack["params"]]
    assert len(ids) == len(set(ids))  # unique


def test_catalog_by_module_groups():
    pack = cat.load()
    groups = cat.catalog_by_module(pack)
    assert "MAX" in groups
    assert any(p["role"] == "output level" for p in groups["MAX"])


def test_find_param_banded():
    pack = cat.load()
    p = cat.find_param(pack, "EQ", "frequency", band=3, section="stereo_main")
    assert p is not None and p["name"] == "EQ: Stereo/Main Frequency 3"
```

- [ ] **Step 4: Run test to verify it fails**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_ozone_param_catalog.py -q`
Expected: FAIL (`ModuleNotFoundError: ozone_param_catalog`).

- [ ] **Step 5: Write the loader**

```python
# ableton_mcp_max/ozone_param_catalog.py
"""Load/validate the committed Ozone 12 catalog (param_maps/ozone12.json)."""
import os

from ableton_mcp_max import param_map_utils as pmu

_PACK = "ozone12"


def load():
    """Load + validate the Ozone 12 catalog pack."""
    return pmu.load_pack(_PACK)


def catalog_by_module(pack):
    """Group params by module key (params with module None -> key 'GLOBAL')."""
    out = {}
    for p in pack["params"]:
        out.setdefault(p.get("module") or "GLOBAL", []).append(p)
    return out


def find_param(pack, module, role, band=None, section=None):
    """First param matching module + role (+ optional band/section), else None."""
    for p in pack["params"]:
        if p.get("module") != module:
            continue
        if p.get("role") != role:
            continue
        if band is not None and p.get("band") != band:
            continue
        if section is not None and p.get("section") != section:
            continue
        return p
    return None
```

- [ ] **Step 6: Run test to verify it passes**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_ozone_param_catalog.py -q`
Expected: PASS (3 tests).

- [ ] **Step 7: Commit**

```bash
git add scripts/build_ozone_catalog.py ableton_mcp_max/param_maps/ozone12.json ableton_mcp_max/ozone_param_catalog.py tests/test_ozone_param_catalog.py
git commit -m "feat: generate Ozone 12 param catalog + loader"
```

---

### Task 4: Budget packer + value mapping (`ozone_utils.py`)

**Files:**
- Modify: `ableton_mcp_max/ozone_utils.py`
- Test: `tests/test_ozone_utils.py`

**Interfaces:**
- Consumes: catalog params (list of dicts with `module`, `param_id`, `name`, `min`, `max`).
- Produces:
  - `pack_modules(params, modules, cap=128) -> {selected, dropped, overflow}` where `selected` is the list of param dicts to Configure (module order preserved), `dropped` is the count beyond `cap`, `overflow` is the list of module keys whose params were partly/fully dropped.
  - `to_native(param, normalized) -> float` and `to_normalized(param, native) -> float` (linear map against `min`/`max`; identity clamp to [min,max]).

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_ozone_utils.py
def test_pack_modules_selects_requested_within_cap():
    params = [
        {"module": "EQ", "param_id": 1, "name": "EQ: a"},
        {"module": "EQ", "param_id": 2, "name": "EQ: b"},
        {"module": "MAX", "param_id": 3, "name": "MAX: c"},
        {"module": "IMG", "param_id": 4, "name": "IMG: d"},
    ]
    res = oz.pack_modules(params, ["EQ", "MAX"], cap=128)
    assert [p["param_id"] for p in res["selected"]] == [1, 2, 3]
    assert res["dropped"] == 0
    assert res["overflow"] == []


def test_pack_modules_reports_overflow():
    params = [{"module": "EQ", "param_id": i, "name": "EQ: %d" % i} for i in range(5)]
    res = oz.pack_modules(params, ["EQ"], cap=3)
    assert len(res["selected"]) == 3
    assert res["dropped"] == 2
    assert res["overflow"] == ["EQ"]


def test_value_mapping_roundtrip():
    p = {"min": 20.0, "max": 20000.0}
    assert abs(oz.to_native(p, 0.0) - 20.0) < 1e-6
    assert abs(oz.to_native(p, 1.0) - 20000.0) < 1e-6
    assert abs(oz.to_normalized(p, 20000.0) - 1.0) < 1e-6
    # clamp
    assert oz.to_normalized(p, 40000.0) == 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_ozone_utils.py -q`
Expected: FAIL (`pack_modules`/`to_native` not defined).

- [ ] **Step 3: Add the implementation**

```python
# append to ableton_mcp_max/ozone_utils.py
def pack_modules(params, modules, cap=128):
    """Select params belonging to `modules` (in module-list order), capped at
    `cap` Configure slots. Returns {selected, dropped, overflow}."""
    wanted = list(modules)
    by_mod = {}
    for p in params:
        by_mod.setdefault(p.get("module"), []).append(p)
    selected = []
    overflow = []
    for mod in wanted:
        mod_params = by_mod.get(mod, [])
        room = cap - len(selected)
        if room <= 0:
            if mod_params:
                overflow.append(mod)
            continue
        take = mod_params[:room]
        selected.extend(take)
        if len(take) < len(mod_params):
            overflow.append(mod)
    total_wanted = sum(len(by_mod.get(m, [])) for m in wanted)
    dropped = total_wanted - len(selected)
    return {"selected": selected, "dropped": dropped, "overflow": overflow}


def _clamp(v, lo, hi):
    return lo if v < lo else (hi if v > hi else v)


def to_native(param, normalized):
    """Map LOM-normalized 0-1 -> native units via the param's min/max."""
    lo = float(param.get("min", 0.0))
    hi = float(param.get("max", 1.0))
    return lo + _clamp(float(normalized), 0.0, 1.0) * (hi - lo)


def to_normalized(param, native):
    """Map native units -> LOM-normalized 0-1 via the param's min/max (clamped)."""
    lo = float(param.get("min", 0.0))
    hi = float(param.get("max", 1.0))
    if hi == lo:
        return 0.0
    return _clamp((float(native) - lo) / (hi - lo), 0.0, 1.0)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_ozone_utils.py -q`
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/ozone_utils.py tests/test_ozone_utils.py
git commit -m "feat: Ozone budget packer + value mapping"
```

---

### Task 5: Master/return track-span locator + expose extension

`find_track_span` finds REGULAR tracks only; Ozone is on the master. Add master/return span locators and let `_expose_plugin_impl` use them.

**Files:**
- Modify: `ableton_mcp_max/als_automation_utils.py` (add `find_master_track_span`, `find_return_track_span`)
- Modify: `ableton_mcp_max/server.py` (`_expose_plugin_impl`: pick the span fn by `track_type`; drop the regular-only guard)
- Test: `tests/test_ozone_track_span.py`

**Interfaces:**
- Produces: `find_master_track_span(xml) -> (start, end)`; `find_return_track_span(xml, return_index) -> (start, end)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ozone_track_span.py
from ableton_mcp_max import als_automation_utils as au

XML = (
    '<Ableton><LiveSet><Tracks>'
    '<AudioTrack><X>1</X></AudioTrack>'
    '<ReturnTrack><R>A</R></ReturnTrack>'
    '<ReturnTrack><R>B</R></ReturnTrack>'
    '</Tracks>'
    '<MasterTrack><M>master here</M></MasterTrack>'
    '</LiveSet></Ableton>'
)


def test_find_master_track_span():
    s, e = au.find_master_track_span(XML)
    assert "master here" in XML[s:e]
    assert XML[s:].startswith("<MasterTrack>")


def test_find_return_track_span():
    s, e = au.find_return_track_span(XML, 1)
    assert "<R>B</R>" in XML[s:e]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_ozone_track_span.py -q`
Expected: FAIL (`find_master_track_span` not defined).

- [ ] **Step 3: Add the span locators**

```python
# append to ableton_mcp_max/als_automation_utils.py
def find_master_track_span(xml):
    """Char span (start, end) of the <MasterTrack>...</MasterTrack> element."""
    open_tag = "<MasterTrack>"
    s = xml.find(open_tag)
    if s == -1:
        raise ValueError("no <MasterTrack> in document")
    close = "</MasterTrack>"
    e = xml.find(close, s)
    if e == -1:
        raise ValueError("unterminated <MasterTrack>")
    return (s, e + len(close))


def find_return_track_span(xml, return_index):
    """Char span (start, end) of the return_index-th <ReturnTrack> (doc order)."""
    idx = 0
    pos = 0
    open_tag = "<ReturnTrack>"
    close = "</ReturnTrack>"
    while True:
        s = xml.find(open_tag, pos)
        if s == -1:
            raise ValueError("return track index %d not found" % return_index)
        e = xml.find(close, s)
        if e == -1:
            raise ValueError("unterminated <ReturnTrack> %d" % return_index)
        e += len(close)
        if idx == return_index:
            return (s, e)
        idx += 1
        pos = e
```

Note: `find_master_track_span` uses a bare `<MasterTrack>` open tag; if the real `.als` emits attributes (`<MasterTrack ...>`), switch the `find` to the `re`-based `_TRACK_OPEN` style already used in this file. Verify against a real saved `.als` during Task 6 live-verify.

- [ ] **Step 4: Extend `_expose_plugin_impl` to select the span function**

In `ableton_mcp_max/server.py`, replace the regular-only guard and the `find_track_span(xml, track_index)` call in `_expose_plugin_impl` so the span function is chosen by `track_type`:

```python
# in _expose_plugin_impl, replace the track_type guard with a span selector:
    if track_type == "regular":
        _span = lambda x: find_track_span(x, track_index)
    elif track_type == "return":
        _span = lambda x: als.find_return_track_span(x, track_index)
    elif track_type == "master":
        _span = lambda x: als.find_master_track_span(x)
    else:
        raise ValueError("track_type must be regular, return, or master")
```

Then change `ts, te = find_track_span(xml, track_index)` to `ts, te = _span(xml)`. (Keep the `find_track_span` default param for backward compat; add `als` import alias if not present.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_ozone_track_span.py tests/test_expose_plugin.py -q && uv run python -c "import ableton_mcp_max.server"`
Expected: PASS; server imports clean.

- [ ] **Step 6: Commit**

```bash
git add ableton_mcp_max/als_automation_utils.py ableton_mcp_max/server.py tests/test_ozone_track_span.py
git commit -m "feat: master/return track-span locators + expose on non-regular tracks"
```

---

### Task 6: `get_ozone_modules` + `expose_ozone_modules` tools

**Files:**
- Modify: `ableton_mcp_max/server.py`
- Test: `tests/test_ozone_tools.py`

**Interfaces:**
- Consumes: `ozone_param_catalog.load`, `ozone_utils.pack_modules`, `_expose_plugin_impl`, `get_device_parameters` (via connection).
- Produces:
  - `get_ozone_modules(track_index, device_index=0, track_type="master") -> str` (JSON `{ok, data:{modules:[{key,name,exposed,bypassed}]}}`).
  - `expose_ozone_modules(track_index, modules, device_index=0, track_type="master", reload=True) -> str` (JSON `{ok, data:{exposed_count, dropped_count, overflow, reloaded}}`).

- [ ] **Step 1: Write the failing test (pure selection logic behind a seam)**

```python
# tests/test_ozone_tools.py
from ableton_mcp_max import ozone_utils as oz
from ableton_mcp_max import ozone_param_catalog as cat


def test_expose_selection_respects_modules_and_cap():
    pack = cat.load()
    res = oz.pack_modules(pack["params"], ["MAX", "IMG"], cap=128)
    # Maximizer + Imager both fit comfortably under 128
    assert res["dropped"] == 0 and res["overflow"] == []
    assert all(p["module"] in ("MAX", "IMG") for p in res["selected"])
    assert len(res["selected"]) > 0
```

- [ ] **Step 2: Run test to verify it fails/passes appropriately**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_ozone_tools.py -q`
Expected: PASS once Task 3's `ozone12.json` exists (it does by now); this locks the selection contract.

- [ ] **Step 3: Add the tools**

```python
# in ableton_mcp_max/server.py (near the other plugin tools)
@mcp.tool()
def get_ozone_modules(ctx: Context, track_index: int, device_index: int = 0,
                      track_type: str = "master") -> str:
    """List an Ozone 12 instance's modules with exposed/bypassed state.

    Reads the device's currently-exposed LOM params (get_device_parameters) and
    reports, per Ozone module, whether any of its params are exposed and whether
    its Bypass is engaged. Ozone 12 lives on the master by default.
    """
    try:
        pack = _ozcat.load()
        conn = get_ableton_connection()
        dp = conn.send_command("get_device_parameters", {
            "track_index": track_index, "device_index": device_index,
            "track_type": track_type})
        exposed_names = {p["name"] for p in dp.get("parameters", [])}
        bypassed = {}
        for p in dp.get("parameters", []):
            info = _oz.parse_param_name(p["name"])
            if info["module"] and info["role"] == "bypass":
                bypassed[info["module"]] = p["value"] >= 0.5
        groups = _ozcat.catalog_by_module(pack)
        modules = []
        for key in sorted(k for k in groups if k != "GLOBAL"):
            names = {p["name"] for p in groups[key]}
            modules.append({
                "key": key, "name": _oz.MODULES.get(key, key),
                "exposed": bool(names & exposed_names),
                "bypassed": bypassed.get(key),
            })
        return _ok({"modules": modules})
    except Exception as e:
        logger.error("get_ozone_modules error: %s", e)
        return _err("get_ozone_modules error: %s" % e)


@mcp.tool()
def expose_ozone_modules(ctx: Context, track_index: int, modules: list,
                         device_index: int = 0, track_type: str = "master",
                         reload: bool = True) -> str:
    """Configure the given Ozone 12 modules' params as settable LOM params.

    Ozone exposes 873 params but Ableton Configures at most 128 at once; this
    fills the device's Configure slots with the requested modules' params (in
    order), reloads the set in place, and reports overflow. The set must be saved
    first (save_set_as). modules: list of module keys (e.g. ["EQ","MAX","IMG"]);
    see get_ozone_modules for keys.
    """
    try:
        pack = _ozcat.load()
        plan = _oz.pack_modules(pack["params"], modules, cap=128)
        if not plan["selected"]:
            return _err("no catalog params for modules %s" % modules)
        get_ableton_connection()  # ensure reachable before save
        data = _expose_plugin_impl(
            track_index, device_index, track_type, plan["selected"],
            _EXPOSE_DEFAULT_MANUAL, reload,
            save_impl=lambda: _save_set_impl(name=""),
            reload_impl=lambda p, n: _reload_set(
                p, n, probe=lambda: get_ableton_connection().send_command(
                    "get_session_info")),
        )
        data["overflow"] = plan["overflow"]
        return _ok(data)
    except (ValueError, RuntimeError, FileNotFoundError) as e:
        return _err(str(e))
    except Exception as e:
        logger.error("expose_ozone_modules error: %s", e)
        return _err("expose_ozone_modules error: %s" % e)
```

Add module-level imports near the other utils imports:

```python
from ableton_mcp_max import ozone_utils as _oz
from ableton_mcp_max import ozone_param_catalog as _ozcat
```

- [ ] **Step 4: Verify server imports + offline suite**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python -c "import ableton_mcp_max.server" && uv run --with pytest pytest -q`
Expected: import clean; full offline suite green.

- [ ] **Step 5: LIVE-VERIFY (main loop)** - restart Claude Code so the new tools load, then against the master Ozone: `expose_ozone_modules(track_index=0, modules=["MAX","IMG"], track_type="master")` -> `exposed_count>0, overflow=[]`, `reloaded=true`; then `get_device_parameters(track_type="master")` shows the MAX/IMG params named + settable; `get_ozone_modules` reflects `exposed:true` for MAX/IMG. (Confirm `find_master_track_span` matched the real `.als`; if the master tag has attributes, apply the Task 5 Step 3 note and re-run.)

- [ ] **Step 6: Commit**

```bash
git add ableton_mcp_max/server.py tests/test_ozone_tools.py
git commit -m "feat: get_ozone_modules + expose_ozone_modules"
```

---

### Task 7: `get_ozone_module` / `set_ozone_module_param` / `set_ozone_module_enabled`

**Files:**
- Modify: `ableton_mcp_max/server.py`
- Test: `tests/test_ozone_tools.py`

**Interfaces:**
- Consumes: `ozone_param_catalog`, `ozone_utils`, connection `get_device_parameters` / `set_device_parameter`.
- Produces:
  - `get_ozone_module(track_index, module, device_index=0, track_type="master") -> str`.
  - `set_ozone_module_param(track_index, module, role, value, band=None, section=None, native=True, device_index=0, track_type="master") -> str`.
  - `set_ozone_module_enabled(track_index, module, on, device_index=0, track_type="master") -> str`.

- [ ] **Step 1: Write the failing test (resolution logic)**

```python
# append to tests/test_ozone_tools.py
def test_find_param_resolves_maximizer_output_level():
    pack = cat.load()
    p = cat.find_param(pack, "MAX", "output level")
    assert p is not None and p["name"] == "MAX: Output Level"


def test_find_param_bypass():
    pack = cat.load()
    p = cat.find_param(pack, "IMG", "bypass")
    assert p is not None and p["name"].endswith("Bypass")
```

- [ ] **Step 2: Run test to verify it passes (contract lock)**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_ozone_tools.py -q`
Expected: PASS.

- [ ] **Step 3: Add the tools**

```python
# in ableton_mcp_max/server.py
def _oz_set_by_name(track_index, device_index, track_type, name, normalized):
    conn = get_ableton_connection()
    return conn.send_command("set_device_parameter", {
        "track_index": track_index, "device_index": device_index,
        "track_type": track_type, "parameter_name": name, "value": normalized})


@mcp.tool()
def get_ozone_module(ctx: Context, track_index: int, module: str,
                     device_index: int = 0, track_type: str = "master") -> str:
    """Read the currently-exposed params of one Ozone 12 module (native + normalized)."""
    try:
        pack = _ozcat.load()
        by_name = {p["name"]: p for p in pack["params"]}
        conn = get_ableton_connection()
        dp = conn.send_command("get_device_parameters", {
            "track_index": track_index, "device_index": device_index,
            "track_type": track_type})
        out = []
        for p in dp.get("parameters", []):
            info = _oz.parse_param_name(p["name"])
            if info["module"] != module:
                continue
            cat_p = by_name.get(p["name"], {})
            out.append({"name": p["name"], "role": info["role"],
                        "band": info["band"], "section": info["section"],
                        "normalized": p["value"],
                        "native": _oz.to_native(cat_p, p["value"]) if cat_p else None})
        if not out:
            return _err("module %s not exposed; call expose_ozone_modules first" % module)
        return _ok({"module": module, "name": _oz.MODULES.get(module, module),
                    "params": out})
    except Exception as e:
        logger.error("get_ozone_module error: %s", e)
        return _err("get_ozone_module error: %s" % e)


@mcp.tool()
def set_ozone_module_param(ctx: Context, track_index: int, module: str, role: str,
                           value: float, band: int = None, section: str = None,
                           native: bool = True, device_index: int = 0,
                           track_type: str = "master") -> str:
    """Set one Ozone 12 module param. role/band/section identify the param (see
    get_ozone_module); value is native units by default (native=False for 0-1).
    The param must be exposed first (expose_ozone_modules)."""
    try:
        pack = _ozcat.load()
        p = _ozcat.find_param(pack, module, role.lower(), band=band, section=section)
        if p is None:
            return _err("no Ozone param for module=%s role=%s band=%s section=%s"
                        % (module, role, band, section))
        normalized = _oz.to_normalized(p, value) if native else max(0.0, min(1.0, value))
        res = _oz_set_by_name(track_index, device_index, track_type, p["name"], normalized)
        return _ok({"name": p["name"], "normalized": normalized, "result": res})
    except Exception as e:
        logger.error("set_ozone_module_param error: %s", e)
        return _err("set_ozone_module_param error: %s" % e)


@mcp.tool()
def set_ozone_module_enabled(ctx: Context, track_index: int, module: str, on: bool,
                             device_index: int = 0, track_type: str = "master") -> str:
    """Enable/disable an Ozone 12 module via its Bypass param (on=True -> not
    bypassed). The module's Bypass must be exposed (expose_ozone_modules)."""
    try:
        pack = _ozcat.load()
        p = _ozcat.find_param(pack, module, "bypass")
        if p is None:
            return _err("no Bypass param for module %s" % module)
        # Bypass = 1 means bypassed; on=True -> value 0
        res = _oz_set_by_name(track_index, device_index, track_type, p["name"],
                              0.0 if on else 1.0)
        return _ok({"name": p["name"], "on": on, "result": res})
    except Exception as e:
        logger.error("set_ozone_module_enabled error: %s", e)
        return _err("set_ozone_module_enabled error: %s" % e)
```

- [ ] **Step 4: Verify import + offline suite**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python -c "import ableton_mcp_max.server" && uv run --with pytest pytest -q`
Expected: clean import; suite green.

- [ ] **Step 5: LIVE-VERIFY (main loop)** - after a Claude Code restart, with MAX exposed: `set_ozone_module_param(track_index=0, module="MAX", role="output level", value=-0.5)` then a SEPARATE `get_ozone_module(module="MAX")` shows the changed value; `set_ozone_module_enabled(module="MAX", on=False)` then re-read shows bypassed. Restore values after.

- [ ] **Step 6: Commit**

```bash
git add ableton_mcp_max/server.py tests/test_ozone_tools.py
git commit -m "feat: Ozone per-module get/set/enable tools"
```

---

### Task 8: Convenience wrappers (EQ band / Maximizer / Dynamics band)

Thin wrappers over `set_ozone_module_param` for the heavy-hitter modules, so common mastering moves are one call.

**Files:**
- Modify: `ableton_mcp_max/server.py`
- Test: `tests/test_ozone_tools.py`

**Interfaces:**
- Produces: `set_ozone_eq_band(track_index, band, freq=None, gain=None, q=None, enable=None, section="stereo_main", ...)`, `set_ozone_maximizer(track_index, threshold=None, ceiling=None, character=None, ...)`, `set_ozone_dynamics_band(track_index, band, comp_threshold=None, comp_ratio=None, ...)`. Each resolves via `ozone_param_catalog.find_param` and delegates to the same set path; returns `{ok, data:{applied:[...]}}`.

- [ ] **Step 1: Write the failing test (name resolution for wrapper roles)**

```python
# append to tests/test_ozone_tools.py
def test_wrapper_role_names_resolve():
    pack = cat.load()
    assert cat.find_param(pack, "EQ", "gain", band=2, section="stereo_main")["name"] == "EQ: Stereo/Main Gain 2"
    assert cat.find_param(pack, "MAX", "output level") is not None
    assert cat.find_param(pack, "DYN", "band comp threshold", band=1, section="stereo_main") is not None
```

- [ ] **Step 2: Run test to verify it passes**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_ozone_tools.py -q`
Expected: PASS (confirms the exact role strings the wrappers must use; adjust wrapper role literals to match the real catalog roles from Task 3).

- [ ] **Step 3: Add the wrappers**

```python
# in ableton_mcp_max/server.py
def _oz_apply(track_index, device_index, track_type, module, items):
    """items: list of (role, band, section, native_value); skip None values."""
    pack = _ozcat.load()
    applied = []
    for role, band, section, val in items:
        if val is None:
            continue
        p = _ozcat.find_param(pack, module, role, band=band, section=section)
        if p is None:
            continue
        normalized = _oz.to_normalized(p, val)
        _oz_set_by_name(track_index, device_index, track_type, p["name"], normalized)
        applied.append(p["name"])
    return applied


@mcp.tool()
def set_ozone_eq_band(ctx: Context, track_index: int, band: int, freq: float = None,
                      gain: float = None, q: float = None, enable: float = None,
                      section: str = "stereo_main", device_index: int = 0,
                      track_type: str = "master") -> str:
    """Set an Ozone 12 EQ band (freq Hz / gain dB / q / enable) in one call.
    The EQ module must be exposed first (expose_ozone_modules ["EQ"])."""
    try:
        applied = _oz_apply(track_index, device_index, track_type, "EQ", [
            ("frequency", band, section, freq),
            ("gain", band, section, gain),
            ("q", band, section, q),
            ("enable", band, section, enable),
        ])
        return _ok({"module": "EQ", "band": band, "applied": applied})
    except Exception as e:
        logger.error("set_ozone_eq_band error: %s", e)
        return _err("set_ozone_eq_band error: %s" % e)


@mcp.tool()
def set_ozone_maximizer(ctx: Context, track_index: int, threshold: float = None,
                        ceiling: float = None, character: float = None,
                        device_index: int = 0, track_type: str = "master") -> str:
    """Set Ozone 12 Maximizer controls (threshold via input gain, output ceiling,
    character). Maximizer must be exposed first (expose_ozone_modules ["MAX"])."""
    try:
        applied = _oz_apply(track_index, device_index, track_type, "MAX", [
            ("input gain", None, None, threshold),
            ("output level", None, None, ceiling),
            ("character", None, None, character),
        ])
        return _ok({"module": "MAX", "applied": applied})
    except Exception as e:
        logger.error("set_ozone_maximizer error: %s", e)
        return _err("set_ozone_maximizer error: %s" % e)


@mcp.tool()
def set_ozone_dynamics_band(ctx: Context, track_index: int, band: int,
                            comp_threshold: float = None, comp_ratio: float = None,
                            comp_attack: float = None, comp_release: float = None,
                            section: str = "stereo_main", device_index: int = 0,
                            track_type: str = "master") -> str:
    """Set an Ozone 12 Dynamics band's compressor controls in one call. Dynamics
    must be exposed first (expose_ozone_modules ["DYN"])."""
    try:
        applied = _oz_apply(track_index, device_index, track_type, "DYN", [
            ("band comp threshold", band, section, comp_threshold),
            ("band comp ratio", band, section, comp_ratio),
            ("band comp attack", band, section, comp_attack),
            ("band comp release", band, section, comp_release),
        ])
        return _ok({"module": "DYN", "band": band, "applied": applied})
    except Exception as e:
        logger.error("set_ozone_dynamics_band error: %s", e)
        return _err("set_ozone_dynamics_band error: %s" % e)
```

Note: the `role` literals above (`"band comp threshold"`, `"input gain"`, etc.) MUST match the roles produced by `parse_param_name` on the real names (Task 3). Task 8 Step 2's test is what pins them; correct the literals to the catalog's actual role strings before implementing.

- [ ] **Step 4: Verify import + full offline suite**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python -c "import ableton_mcp_max.server" && uv run --with pytest pytest -q`
Expected: clean import; suite green.

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/server.py tests/test_ozone_tools.py
git commit -m "feat: Ozone convenience wrappers (EQ band, Maximizer, Dynamics band)"
```

---

### Task 9: Live-verify pass + PROGRESS.md

**Files:**
- Modify: `PROGRESS.md`

- [ ] **Step 1: Full live-verify (main loop, after Claude Code restart)**

Against the open set's master Ozone 12: expose ["EQ","MAX","IMG","DYN"] (report `exposed_count`, `overflow`); set an EQ band (`set_ozone_eq_band` band 3 gain -3, freq 4000) and confirm via `get_ozone_module("EQ")`; drive the Maximizer ceiling; toggle a module via `set_ozone_module_enabled`. Confirm each with a SEPARATE read. Restore changed values.

- [ ] **Step 2: Confirm the offline gate is green**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q && uv run python -c "import ableton_mcp_max.server"`
Expected: all tests pass; import clean.

- [ ] **Step 3: Record results in PROGRESS.md**

Add an "Ozone 12 deep mastering support - Phase 1" section: what shipped (tool names + count delta), the id_base confirmation, master-span note, live-verify results, and "NEXT = Phase 2 (state-blob spike / chain structure)".

- [ ] **Step 4: Commit**

```bash
git add PROGRESS.md
git commit -m "docs: PROGRESS - Ozone 12 Phase 1 module-aware param control"
```

---

## Self-Review

**Spec coverage:**
- Catalog of all 873 params -> Tasks 2, 3.
- `ozone_utils` (parse, registry, budget packer, value map) -> Tasks 1, 4.
- Module-aware tools (get_modules, expose, get/set/enable) -> Tasks 6, 7.
- Convenience wrappers -> Task 8.
- 128-slot cap handling / overflow reporting -> Task 4 (`pack_modules`), surfaced in Task 6.
- Master-track reach (Ozone lives on master) -> Task 5 (NEW; caught because `find_track_span` is regular-only).
- Live expose round-trip verification -> Tasks 2, 6, 9.
- Phase 2 (state blob / chain structure) and Phase 3 (skill + recommend integration, release) -> deliberately OUT of this plan (separate release cycles per the spec's phasing).
- Master Assistant -> out of scope (spec).

**Placeholder scan:** No TBD/TODO; every code step carries full code. Two flagged coupling points (master tag attributes in Task 5; exact role literals in Task 8) are called out with the concrete corrective action, not left vague.

**Type consistency:** `pack_modules` returns `{selected, dropped, overflow}` (Tasks 4, 6 agree). `find_param(pack, module, role, band, section)` signature consistent across Tasks 3, 7, 8. `parse_param_name` record keys consistent across Tasks 1, 3, 6, 7. Catalog param dict keys (`param_id, name, module, section, role, band, min, max`) consistent Tasks 3-8.

**Live vs offline:** Tasks 1, 3-5, 8 are offline/pure (subagent-friendly TDD). Tasks 2, 6, 7, 9 have live steps that MUST run in the main loop (Live + Claude Code restart), per project convention.
