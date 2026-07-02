# Ozone 12 deep mastering support - design

**Created**: 2026-07-01
**Status**: In Progress
**Branch**: `feat/ozone12-support`

## Overview

Add deep, module-aware control of iZotope **Ozone 12** (the flagship mastering
suite) to the ableton-mcp-max MCP, mirroring the Serum-support arc. Ozone lives
on the master (or a return) track; the MCP already reaches master/return device
params via `track_type`. The goal is to expose, read, set, enable/disable, and
(gated) author the internal module chain of an Ozone 12 instance.

This is the second third-party plugin brought under the generic plugin-exposure
engine built for Serum. The plugin-agnostic mechanism is reused; the new work is
a per-plugin catalog/pack, a pure module model, module-aware tools, and a gated
state-blob spike for chain-structure authoring.

## Feasibility gate (RUN 2026-07-01, Live 12.4 Suite - PASSED)

Probed live against `Ozone 12.vst3` loaded on a scratch track:

- Loads as a single `PluginDevice`. Fresh LOM baseline = **1 param** (`Device On`)
  until Configured - identical to Serum.
- `probe_plugin_parameters` returns **873 Configurable parameters**, cleanly named
  and grouped by module prefix. Confirmed module prefixes (~22 modules):
  `EQ`, `EQ2`, `IMG` (Imager), `MAX` (Maximizer), `DYN` (Dynamics),
  `DYNEQ` (Dynamic EQ), `EXC` (Exciter), `VCOMP`/`VEQ`/`VLIM`/`VTAPE`
  (Vintage Comp/EQ/Limiter/Tape), `SPSHPR` (Spectral Shaper), `MREBAL`
  (Master Rebalance), `MATCH EQ`, `LEF` (Low End Focus), `IMP` (Impact),
  `STBL` (Stabilizer), `CLA` (Clarity), `BAS` (Bass Control), `STEMEQ` (Stem EQ),
  `UNLIMITER`, `GAIN`, plus per-module `Bypass` and a top-level `Global Bypass`.
- Name shape is structured and self-describing: `MODULE: Section Param N`
  (e.g. `EQ: Stereo/Main Frequency 3`, `MAX: Output Level`,
  `DYN: Stereo/Main Band 2 Comp Threshold`). Section is `Stereo/Main` vs `Aux`.
- Per the probe contract, the Configure-slot id is **index-based**
  (`id = id_base + probe_index`). Unlike Serum, **no oracle / reverse-engineering
  of ids is needed** - the pack generates directly from the probe.

**Consequence:** full-suite parameter control needs no proprietary blob crack.
The generic engine + a generated pack drives every module's knobs. Only chain
*structure* authoring remains hard (see Phase 2).

## Decisions (from brainstorming)

- **Scope**: Deep, module-aware authoring (not thin pack).
- **Architecture**: Gated hybrid - full-suite internal-module control first
  (now proven green), state-blob crack for chain structure as a gated branch with
  a component-plugin fallback.
- **Deep scope**: include chain-structure authoring (Phase 2), not just params.
- **Phase 1 catalog scope**: catalog **all 873** params up front (one-time scan).
- **Phase 1 tool granularity**: include the heavy-hitter convenience wrappers
  (EQ band / Maximizer / Dynamics band) from the start, alongside the generic
  `set_ozone_module_param`.
- **Out of scope**: Master Assistant (GUI-only AI target-matching; not a host
  param, not automatable).

## Design constraint: 128-slot cap vs 873 params

Ableton's Configure pool is **128 slots**; Ozone exposes 873 params. All 873
cannot be exposed at once. Resolved via **on-demand, per-module exposure**: the
caller names the modules in play, and `ozone_utils` packs the chosen modules'
params into the 128-slot budget, reporting anything that overflows. The catalog
holds all 873 (for lookup/validation); exposure is a curated subset per session.

## Components

### 1. `ableton_mcp_max/ozone_param_catalog.py` + `param_maps/ozone12.json`
Generated catalog of all 873 params. Per entry: module key, friendly module name,
section (`stereo_main`|`aux`), role (freq/gain/q/threshold/attack/release/mix/
amount/enable/bypass/mode/...), band index (nullable), probe index (= Configure
id offset), and native units/min/max where derivable. Built by a scan script
(pattern: `build_serum_patch_catalog.py`) plus a live `get_device_parameters`
pass after exposure to capture real min/max/quantized/value_items.

### 2. `ableton_mcp_max/ozone_utils.py` (pure, server-side, unit-tested)
- Name parser: `MODULE: [Stereo/Main|Aux] <role> [band]` -> structured record.
- Module registry: the ~22 modules, each with its param schema and friendly name.
- Budget packer: given a requested module set, select the ≤128 slots to Configure;
  return the plan and flag overflow.
- Value mapping: LOM normalized 0-1 <-> native units per param (from catalog).
- Imported by `server.py` only (Remote Script cannot import it; server sends
  already-resolved values, per project convention).

### 3. Module-aware server tools (Phase 1)
- `get_ozone_modules(track_index, device_index, track_type)` - list modules with
  present/bypassed state + a summary; identifies the device is Ozone 12.
- `expose_ozone_modules(..., modules=[...])` - Configure the chosen modules'
  params on-demand within the 128 budget, reload, return exposed/dropped counts
  and any overflow. (Extends/parallels `expose_plugin_parameters`.)
- `get_ozone_module(..., module)` - read a module's current param values.
- `set_ozone_module_param(..., module, param, value)` - set one param (native
  units; validated against catalog).
- `set_ozone_module_enabled(..., module, on)` - per-module Bypass.
- Convenience wrappers: `set_ozone_eq_band(..., band, freq/gain/q/shape/enable)`,
  `set_ozone_maximizer(..., threshold/ceiling/character/...)`,
  `set_ozone_dynamics_band(..., band, threshold/ratio/attack/release/...)`.

### 4. Chain-structure authoring (Phase 2, gated)
- **Task 0 spike**: on a scratch track, load Ozone, `save_set_as` a scratch set,
  parse the Ozone `<ProcessorState>` (and `ControllerState`) blob. Determine
  format: XferJson/CBOR-like (as Serum), plain, or opaque binary. Reuse
  `plugin_config_utils.locate_plugin_state` to find spans.
- **If crackable**: `ozone_state_codec.py` + `add_ozone_module` /
  `remove_ozone_module` / `reorder_ozone_modules` via .als-patch + reload (the
  Serum Release-2/3 mechanism: patch ProcessorState in the live `.als`, reload in
  place; honor `<NextPointeeId>` discipline if target ids appear).
- **If it walls (fallback)**: build the mastering chain from the standalone
  **Ozone 12 component plugins** (`Ozone 12 Equalizer`, `... Maximizer`, etc.)
  as separate ordered Ableton devices, controlled by the same generic engine +
  per-component packs. Documented explicitly so the feature ships regardless.

### 5. Integration (Phase 3)
Wire Ozone into the `ableton-mastering` skill and `recommend_asset` / mastering
flow as a first-class mastering target; docs regen; version bump; marketplace
`ableton` ref bump.

## Data flow

Intent/tool call -> `ozone_utils` resolves module + param -> catalog gives native
range + probe index -> (expose if that module isn't Configured yet) -> server
sends resolved native/normalized value -> `get/set_device_parameter` on the
master `PluginDevice`. Chain-structure ops: server patches the `.als`
ProcessorState + reload (Phase 2).

## Phasing (each independently shippable)

1. **Phase 1 (all-green)**: catalog + pack + `ozone_utils` + module-aware
   param/enable tools + on-demand expose. Live-verify the expose round-trip on
   Ozone (fill slots -> reload -> settable; set a param moves the GUI knob;
   per-module Bypass toggles). Complete deep param control on its own.
2. **Phase 2 (gated)**: state-blob spike -> chain add/remove/reorder, or the
   component fallback.
3. **Phase 3**: skill + recommend integration, docs, version bump, marketplace.

## Error handling

- Every tool returns `{ok, data|error}` per project convention.
- Not-an-Ozone-device -> explicit error (check device name/class, like
  `is_serum_state`).
- Overflow past 128 slots -> return a clear plan + `dropped`/`overflow` list,
  never silently truncate.
- Live-disconnected -> surface the connection error; pure catalog lookups still
  work offline.
- Song/device write-lag: verify sets via a separate follow-up read, per project
  gotchas.

## Testing

- Offline pytest for `ozone_utils`: name parsing (all role/section/band shapes),
  budget packing (selection <=128, overflow reporting), value normalization.
- Catalog load/validate regression (shape check on `ozone12.json`, like the
  `serum2.json` test).
- `uv run python -c "import ableton_mcp_max.server"` + `py_compile` gates.
- Manual live-verify per project protocol: expose round-trip, set-param-moves-knob,
  per-module bypass, and (Phase 2) chain patch survives reload. Record in
  PROGRESS.md.

## Risks / unknowns

- **Expose ParameterId base on Ozone** - index-based per the probe contract, but
  confirm the exact `id_base` live during Phase 1 build (same device path as
  Serum, so low risk).
- **128-budget packing UX** - which modules fit together; needs sensible defaults.
- **State-blob format** - the Phase 2 gate; may crack (CBOR-like) or wall (opaque
  binary). Fallback defined.
- **Native units / min-max** - some params (enable/mode/shape) are quantized
  enums; capture value_items via a live `get_device_parameters` pass post-expose.

## Files to create/modify

- `ableton_mcp_max/ozone_param_catalog.py` - new (generated catalog loader).
- `ableton_mcp_max/param_maps/ozone12.json` - new (generated pack).
- `ableton_mcp_max/ozone_utils.py` - new (pure module model).
- `ableton_mcp_max/ozone_state_codec.py` - new, Phase 2 (if blob cracks).
- `ableton_mcp_max/server.py` - new `@mcp.tool()` module-aware tools.
- `scripts/build_ozone_catalog.py` - new (scan/generate catalog).
- Tests under the existing test suite for `ozone_utils` + catalog.
- `docs/`, `README.md`, plugin/version files - Phase 3.

## Verification

- Phase 1: offline tests green; live expose round-trip + a param moves Ozone's
  knob; per-module bypass verified; recorded in PROGRESS.md.
- Phase 2: chain add/remove/reorder survives a reload (or fallback shipped).
- Phase 3: full release chain verified (local = origin = tag; marketplace ref
  bumped); docs counts updated by hand where hardcoded.
