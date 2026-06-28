# Serum 2 FX Control (Release 2) - Design

**Created**: 2026-06-28
**Status**: In Progress

## Overview

Release 1 (v0.24.0) exposed and controlled Serum 2's automatable parameters via the
Configure-slot `.als` backdoor. FX racks are deliberately left out of that path: Serum does
not expose its FX (Reverb/Delay/EQ/Comp/Chorus/etc.) to the VST3 host parameter list, so they
can never be Configured or LOM-automated.

Release 2 reaches the FX racks by a different route. Serum's plugin state, stored inside the
Live set, is the same `XferJson -> zstd -> CBOR` container as a `.SerumPreset` file, and the
full FX chain lives in that tree. By decoding the state blob, mutating the FX tree, re-encoding,
and reloading the set in place, we can author the complete FX chain: set FX parameters, toggle
bypass, insert/remove/reorder FX in any of the three racks.

### Scope

**Full rack authoring**: read FX state; set FX parameters; enable/bypass FX; reorder FX within
a rack; insert and remove FX of any catalog type. Values are native by default (Serum's own
units), with an optional `normalized` 0-1 mode where the factory scan yields a reliable range.

### Key limitation (must be documented in every tool docstring)

This is **state authoring, not live automation**. FX parameters set this way are baked into the
plugin state and take effect on set reload. They do NOT become LOM-automatable knobs reachable
by `set_device_parameter` (Serum does not expose them to the host). Each mutation costs one set
save + reload, which interrupts playback. Read (`get_serum_fx`) is free (no reload).

## Confirmed feasibility facts

- The `.als` `<ProcessorState>` and `<ControllerState>` are hex-encoded `XferJson` containers:
  8-byte `XferJson` magic, 1 pad, uint64 metadata-JSON length, plaintext metadata JSON, an
  8-byte pre-blob header, then a zstd blob (`28 b5 2f fd`) that decompresses to the full CBOR
  state tree.
- The metadata `"hash"` field is `md5(zstd_blob)` (verified). It is fully reproducible on
  re-encode, so no opaque validation blocks us.
- **Both** `ProcessorState` (component `processor`) and `ControllerState` (component
  `controller`) contain the FX tree. Both must be patched consistently. The `Vst3Preset`
  wrapper also embeds state; whether it must match is settled by live verification (see Risks).
- FX live in the CBOR tree as `FXRack0`, `FXRack1`, `FXRack2`. Each rack is
  `{FX: [ ... ], displayName, plainParams}`. Each FX entry is
  `{type: <int>, <WrapperKey>: {plainParams: {kParam*: <native float>}}}` (some FX also carry a
  sibling `kUIParamMixOrGain`). Observed wrappers: type 3 `FXChorus`, 4 `FXDelay`, 5 `FXComp`,
  7 `FXEQ`, 12 `FXUtils`.
- `plainParams` is **sparse**: only non-default values are serialized. Omitting a key means
  Serum's default. Setting a parameter means injecting/overwriting its `kParam*` key.
- 791 factory `.SerumPreset` files exist under
  `/Library/Audio/Presets/Xfer Records/Serum 2 Presets/Presets/` to batch-scan for the catalog.
- No `NextPointeeId` handling is needed (FX preset target ids are 0, unlike the Configure path).

## Delivery model

Approach A (in-place `.als` ProcessorState/ControllerState patch + reload), the same proven
mechanism Release 1 used for Configure exposure. Rejected alternatives: authoring a standalone
`.SerumPreset` file (no MCP/LOM path drives Serum's internal browser to load it); rack `.adg`
embedding (nests Serum in a rack, needs deferred chain-aware param access). The rack `.adg`
no-reload path remains a possible later fast-follow.

## Architecture

### New pure modules (server-imported, unit-tested)

1. **`ableton_mcp_max/serum_state_codec.py`** - the XferJson container codec.
   - `decode(blob_bytes) -> (meta: dict, tree: object)`: parse magic/length/metadata, locate the
     zstd blob, decompress, `cbor2.loads`.
   - `encode(meta: dict, tree: object) -> bytes`: `cbor2.dumps`, zstd-compress, recompute
     `meta["hash"] = md5(zstd_blob)`, rebuild the 8-byte pre-blob header and container framing.
   - Hex helpers for the `.als` representation.
   - Depends on `zstandard` and `cbor2` (added to `pyproject.toml` + `uv.lock`).

2. **`ableton_mcp_max/serum_fx_utils.py`** - pure FX-tree logic over a decoded CBOR tree. No IO.
   - `list_fx(tree) -> [{rack, slot, type, name, enabled, params}]`
   - `get_fx_params(tree, rack, slot) -> {kparam: native}`
   - `set_fx_param(tree, rack, slot, kparam, native)`
   - `insert_fx(tree, rack, index, fx_type)` (uses the catalog default template)
   - `remove_fx(tree, rack, slot)`
   - `reorder_fx(tree, rack, from_index, to_index)`
   - `set_fx_enabled(tree, rack, slot, on)`
   - All validate against the catalog and rack/slot bounds before mutating; raise on bad input.

3. **`ableton_mcp_max/param_maps/serum2_fx.json`** - the FX catalog, a durable committed artifact:
   `{fx_type: {name, wrapper_key, params: [{kparam, native_min, native_max, unit?}],
   default_template: {kParam*: native}}}`. Built once by the scan script below.

### New script

- **`scripts/build_serum_fx_catalog.py`** - decodes the 791 factory presets via
  `serum_state_codec`, unions all FX types, wrapper keys, `kParam*` names, and observed value
  ranges, and writes `serum2_fx.json`. Rerunnable. Gaps (params/types factory presets never use)
  are filled by hand if live testing reveals any.

### Server-side (`server.py`), mirroring `_expose_plugin_impl`

- `_locate_plugin_state(xml, track_start, track_end, device_index) -> {processor: (s,e),
  controller: (s,e)}` - a navigator sibling to `plugin_config_utils.locate_param_list` that
  returns the hex-blob spans of the device's `<ProcessorState>` and `<ControllerState>`.
  Rejects a non-plugin / non-Serum device (metadata `product == "Serum2"`).
- `_serum_fx_impl(...)` behind the existing `read_als` / `write_als` / `reload_impl` seams:
  `save_set -> read .als (.bak backup) -> decode both blobs -> apply the FX mutation to each
  tree -> re-encode each -> splice hex back into both spans -> write_als -> _reload_set`.

### Tool surface (5 new `@mcp.tool()`s, "Plugins (VST/AU)" category)

| Tool | Reload? | Purpose |
|------|---------|---------|
| `get_serum_fx` | no | List racks/slots: fx type + name, enabled, current params (decode the saved `.als`) |
| `set_serum_fx_param` | yes | Set one `kParam` (native; optional `normalized`) on a rack/slot |
| `insert_serum_fx` | yes | Insert a catalog FX type into a rack at an index |
| `remove_serum_fx` | yes | Remove a rack/slot |
| `reorder_serum_fx` | yes | Move (and bypass via `set_fx_enabled`) FX within a rack |

`get_serum_fx` does a `save_set` then decodes the on-disk `.als` (no reload). Each mutator does
one save + reload. Tool count: 150 -> 155.

All take `track_index`, `device_index=0`, `track_type="regular"`, `reload=True`, consistent with
`expose_plugin_parameters`.

## Data flow (a mutation)

1. Tool validates args against the catalog (`serum_fx_utils` raises on unknown type/kparam/range
   or out-of-bounds rack/slot) before any IO.
2. `save_set("")` so the on-disk `.als` matches the live device.
3. `read_als` (back up to `.bak`), `_locate_plugin_state` returns processor + controller spans.
4. For each blob: `serum_state_codec.decode` -> apply the same `serum_fx_utils` mutation ->
   `serum_state_codec.encode` -> hex.
5. Splice both hex blobs back, `write_als`.
6. `_reload_set` in place; return `{ok, reloaded, rack, slot, ...}`.

## Error handling

- Device is not Serum 2 (metadata check) -> error, no write.
- Unknown `fx_type` / unknown `kParam` for the type / native value outside observed range /
  rack or slot out of range / rack full or empty -> reject pre-write, return the valid options.
- `.als` backed up to `.bak` before write; reload failure returns `reloaded:false` (same contract
  as `expose_plugin_parameters`).

## Risks and unknowns (settled by live verification)

- **Which blob drives the reloaded sound** - processor, controller, or the `Vst3Preset` wrapper.
  REVISED 2026-06-28 from real-data finding: ProcessorState and ControllerState store FX in
  DIFFERENT, incompatible schemas (processor `{type, FXWrapper:{plainParams}}`; controller
  `{defaultPlainValues:{kParam*}, kUIParamMixOrGain}` - no type/wrapper). So "patch both
  consistently" is not viable; the implementation patches ProcessorState only (the real FX
  state). Live verification (Task 7) confirms whether the sound + Serum GUI update from
  processor-only; if not, add a controller `defaultPlainValues`-by-name updater and/or
  `Vst3Preset`. This is the make-or-break live check.
- **zstd recompression** is not byte-identical. Mitigation: codec gate requires
  `decode(encode(decode(x))) == decode(x)` (CBOR-tree equality) across all 791 presets, and a
  no-op mutation must produce a Serum-loadable blob.
- **Observed ranges** from the factory scan may understate true native min/max for params that
  presets never push to extremes. Mitigation: native is the source of truth; `normalized` is
  offered only where a range is reliable; range validation warns rather than hard-fails at the
  edges (final policy decided during implementation).

## Testing

- **Offline gate** (`uv run pytest`, server import, RS `py_compile` - RS is unchanged, all
  host-side):
  - `serum_state_codec` roundtrip over all 791 factory presets (CBOR-tree equality).
  - `serum_fx_utils` mutation unit tests on synthetic trees + real decoded samples.
  - `_locate_plugin_state` navigator tests (skips mixer/nested-rack state, rejects non-Serum).
  - `serum2_fx.json` load/validate test.
- **Live** (Live 12.4 Suite, AbletonDev working-tree tools): load a factory Serum preset that has
  FX -> `get_serum_fx` lists them -> `set_serum_fx_param` (e.g. Reverb/Utility Wet) -> reload ->
  confirm the sound changes and the Serum GUI reflects it -> `insert_serum_fx` a Delay -> confirm
  -> clean up. Settles the processor/controller/Vst3Preset question.

## Files to create / modify

- `ableton_mcp_max/serum_state_codec.py` - new (XferJson codec).
- `ableton_mcp_max/serum_fx_utils.py` - new (FX-tree logic).
- `ableton_mcp_max/param_maps/serum2_fx.json` - new (catalog artifact).
- `scripts/build_serum_fx_catalog.py` - new (factory scan).
- `ableton_mcp_max/server.py` - `_locate_plugin_state`, `_serum_fx_impl`, 5 tools.
- `pyproject.toml` + `uv.lock` - add `zstandard`, `cbor2`.
- `tests/` - codec, fx-utils, navigator, catalog tests.
- Docs/version/marketplace on ship (counts hand-bumped in `docs/index.md` and `README.md`).

## Ship

Version bump (`pyproject.toml` + `.claude-plugin/plugin.json` + `uv lock`), docs regen
(`scripts/gen_docs_site.py` + `scripts/build_tool_index.py`) plus hand-bump of the hardcoded
tool/category counts in `docs/index.md` and `README.md`, `gh release create`, marketplace
`ableton` ref bump + `node scripts/build-readme.js`.
