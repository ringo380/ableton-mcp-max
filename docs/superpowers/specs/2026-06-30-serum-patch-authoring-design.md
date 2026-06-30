# Serum full-instrument patch authoring (Release 3) - design

**Created**: 2026-06-30
**Status**: In Progress

## Overview

Author a complete Serum 2 patch from scratch by writing the whole Serum CBOR state
tree into the live `.als` - oscillators (params + mode + wavetable), filters,
envelopes, LFOs, the mod matrix, and macros. This extends the shipped Serum work:

- **Release 1 (v0.24.0)** - expose/control the 128 Configurable, host-automatable
  params (`expose_plugin_parameters`, `set_device_parameter`).
- **Release 2 (~v0.25.0, FX path)** - author Serum FX racks by patching the
  `<ProcessorState>` XferJson blob in the live `.als` + reload in place
  (`get_serum_fx` / `set_serum_fx_param` / `insert_serum_fx` / `remove_serum_fx` /
  `reorder_serum_fx`). FX are NOT host params, so this is state authoring.

Release 3 applies the same `<ProcessorState>`-patch mechanism to the rest of the
instrument: everything except FX, which Release 2 already covers and which Release 3
reuses.

### Why this is feasible (established facts)

- `serum_state_codec.decode/encode` already roundtrips the full XferJson container
  (magic + meta-JSON + zstd-CBOR), recomputing `meta["hash"]` on encode. Verified
  CBOR-tree-equal over all 791 factory presets.
- The `.SerumPreset` CBOR == the `.als` `<ProcessorState>` hex blob (same container).
- Release 2 proved that patching `<ProcessorState>` ONLY + reload-in-place reaches
  the live plugin; Serum reconciles processor-only structural changes and does not
  override from the unpatched `<ControllerState>`/`<Vst3Preset>`. No controller or
  Vst3Preset patching is required.
- `plainParams` is **sparse**: a node holds only non-default `kParam*` values.
  "From scratch" therefore means: patch a fresh/init Serum blob and set the params
  you want; absence of a key implies the Serum default.

### Decoded-tree facts (from `.vst-harvest-local/serum_preset_decoded.json`)

- Module nodes: `Oscillator0-4`, `VoiceFilter0/1`, `Env0-3`, `LFO0-9`,
  `ModSlot0-63`, `Macro0-7`, plus `FXRack0-2` (Release 2).
- `Oscillator{n}` is multi-mode: `Oscillator{n}.plainParams` holds high-level osc
  params (`kParamType` = mode select WT/Sample/Granular/Spectral/MultiSample,
  `kParamVolume`, `kParamPan`); each mode has its own sub-state node
  (`WTOsc{n}`, `MultiSampleOsc{n}`, `SampleOsc{n}`, `GranularOsc{n}`,
  `SpectralOsc{n}`).
- `VoiceFilter{n}.plainParams` = `kParam*` (empty when filter is off/default).
- `Env{n}.plainParams` = `kParam*` (e.g. `kParamCurve1-3`; ADSR values present only
  when non-default).
- `LFO{n}` = `{curveData, pathData, plainParams}`.
- `Macro{n}` = `{name, plainParams:{kParamValue}}`.
- `ModSlot{n}` = `{source:[moduleID, idx], plainParams:{kParamAmount}}` + the
  documented `destModuleID/destModuleParamID/destModuleParamName/destModuleTypeString`
  Rosetta (present in routed slots).

## Architecture

Reuse the Release 2 read/mutate scaffolding verbatim:

1. Resolve the live `.als` path (`_serum_fx_resolve_path` pattern).
2. Locate the Serum `<ProcessorState>` blob (`plugin_config_utils.locate_plugin_state`
   + `is_serum_state`).
3. `serum_state_codec.decode` → CBOR tree.
4. Patch tree nodes (new pure logic).
5. `serum_state_codec.encode` → write blob back into the `.als`.
6. Reload in place (the existing reload path; answers the stop-audio dialog).

New code:

- **`ableton_mcp_max/serum_patch_utils.py`** (pure, imported by `server.py` only,
  unit-tested) - per-module read/write on the decoded CBOR tree. Knows the module
  node names and how to read/write sparse `kParam*` values, the oscillator-mode
  enum, and mod-source/dest resolution. Mirrors `serum_fx_utils.py`. No I/O.
- **`ableton_mcp_max/param_maps/serum2_patch.json`** - friendly-name catalog:
  `{module_type → {friendly_param → {kparam, native_min, native_max, default}}}`,
  the oscillator-mode enum, and the mod-source / mod-dest ID tables. Same shape
  philosophy as `serum2_fx.json`. Friendly names are the tool API; raw `kParam*`
  stays internal. Ranges/defaults are derived from a factory-preset scan.

Each module group is an isolated unit: `serum_patch_utils` exposes one
read function and one set function per module type, each taking the decoded tree
and returning the mutated tree (or a friendly summary for reads). The server tools
are thin wrappers that decode → call the util → encode → reload, identical in
structure to the Release 2 FX tools.

## Tools

Granular (each: read blob → patch one module in the decoded tree → encode → one
reload; built on the shared `_serum_*_impl` scaffolding):

- `get_serum_patch(track_index, device_index=0)` - read the current tree as a
  friendly per-module summary. No reload.
- `set_serum_oscillator(track_index, device_index, osc, params={}, mode=None)` -
  set osc-level params (volume/pan/etc.) and optionally select the oscillator mode.
- `set_serum_filter(track_index, device_index, filter, params={})`
- `set_serum_envelope(track_index, device_index, env, params={})`
- `set_serum_lfo(track_index, device_index, lfo, params={})`
- `set_serum_macro(track_index, device_index, macro, value, name=None)`
- `add_serum_mod_route(track_index, device_index, source, dest, amount)` - allocate
  a free `ModSlot`, set source/dest/amount.
- `clear_serum_mod_route(track_index, device_index, source, dest)` - clear the
  matching `ModSlot`.
- `set_serum_wavetable(track_index, device_index, osc, table)` - **gated on the
  spike result** (see Risks). Approach decided by the spike.

Declarative:

- `create_serum_patch(track_index, device_index, spec)` - one dict describing the
  whole patch (oscillators, filters, envs, lfos, macros, mod routes, and FX by
  delegating to the Release 2 FX setters). Applies the whole spec to a single
  decoded tree, then reloads **once**.

Shared-core requirement: the per-module patch logic in `serum_patch_utils` operates
on an in-memory tree so `create_serum_patch` can apply many changes against one
decode/encode/reload cycle. Granular tools each do their own single decode/reload.

### `create_serum_patch` spec schema (initial)

```
{
  "oscillators": [{"index": 0, "mode": "wt", "params": {...}, "wavetable": "..."}],
  "filters":     [{"index": 0, "params": {...}}],
  "envelopes":   [{"index": 0, "params": {...}}],
  "lfos":        [{"index": 0, "params": {...}}],
  "macros":      [{"index": 0, "value": 50.0, "name": "CUTOFF"}],
  "mod_routes":  [{"source": "...", "dest": "...", "amount": 40.0}],
  "fx":          [...]   // delegates to Release 2 FX setters
}
```

All top-level keys optional; an absent section leaves that module group untouched.
Unknown friendly param names are rejected (returned in a `dropped` list), never
silently ignored - consistent with `expose_plugin_parameters`.

## Implementation order

1. **Spike** - decode a factory WT-based preset to confirm exactly how the
   wavetable is stored (path reference vs embedded binary). The spike result picks
   the `set_serum_wavetable` approach; if embedded-binary surgery is too risky,
   wavetable selection degrades to "reference an existing factory/user table by
   name" and full embed is deferred. The other four module groups ship regardless.
   The spike also verifies the mod-matrix dest Rosetta against several real presets
   before `add_serum_mod_route` is built.
2. `serum_patch_utils.py` + unit tests (osc/filter/env/lfo/macro/mod read+set on a
   real decoded tree).
3. `serum2_patch.json` catalog from a factory-preset scan (native ranges/defaults,
   mode enum, mod-source/dest tables).
4. Granular server tools + the shared in-memory patch core.
5. `create_serum_patch` declarative composer (one reload).
6. `set_serum_wavetable` per the spike outcome.
7. Live verify on Live 12.4 (AbletonDev / subprocess-import of the working-tree
   server on 9877 - no Claude Code restart needed), then docs regen + hand-bump
   tool/category counts (`docs/index.md`, `README.md`), version bump
   (`pyproject.toml` + `.claude-plugin/plugin.json` + `uv lock`), PR/merge,
   `gh release`, marketplace `ableton` ref bump + `build-readme`.

## Files to Modify / Create

- `ableton_mcp_max/serum_patch_utils.py` - new pure per-module patch logic.
- `ableton_mcp_max/param_maps/serum2_patch.json` - new friendly-name catalog.
- `ableton_mcp_max/server.py` - new `@mcp.tool()` functions; reuse the
  `_serum_fx_resolve_path` / `_serum_fx_read_impl` / `_serum_fx_mutate_impl`
  scaffolding (generalize names if needed).
- `tests/` - unit tests for `serum_patch_utils` + a 791-preset roundtrip-gate test.
- Docs: `docs/tools/*`, `docs/tools/index.md`, `commands/tool-index.md` (regen),
  plus hand-bumped counts in `docs/index.md` and `README.md`.

## Testing & verification

- Offline: roundtrip-gate every mutation over all 791 factory presets - decode,
  patch one node, encode, decode again, assert CBOR-tree-equal except the patched
  node (Release 2's gold standard). `kParam` ranges/defaults validated against the
  catalog. `uv run --with pytest pytest -q` + server import + `py_compile` of the
  Remote Script (unchanged here).
- Live: build a patch from scratch on a fresh Serum instance on a scratch track via
  AbletonDev (or subprocess-import of the working-tree server), reload, confirm with
  `get_serum_patch` and by audition that the params/mode/mod-routes survived the
  reload. Restore baseline (delete scratch device, save).

## Risks

- **Wavetable storage (primary)** - unconfirmed; handled by the opening spike +
  degrade-to-path-ref fallback. Wavetable selection must not block the other four
  module groups.
- **Mod-matrix dest encoding** - the `destModuleID/ParamID` Rosetta must be verified
  against several real routed presets before `add_serum_mod_route` is built; the
  spike/util phase covers this.
- **Sparse-default semantics** - authoring relies on the catalog's per-param
  defaults to know what "from scratch" means; defaults are derived from the factory
  scan and validated, not guessed.
- **Processor-only sufficiency** - already proven in Release 2 (Wet survived a real
  reload with no controller patch); Release 3 assumes the same and re-verifies live.
