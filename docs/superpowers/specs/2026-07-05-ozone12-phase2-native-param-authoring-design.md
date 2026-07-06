# Ozone 12 Phase 2 - native param authoring via the state blob - design

**Created**: 2026-07-05
**Status**: Design approved (pre-plan)
**Branch**: `feat/ozone12-phase2` (to be created at implementation)
**Predecessor**: Phase 1 (module-aware param control) shipped v0.29.0.

## Overview

Phase 1 gave module-aware control of every Ozone 12 *knob*, but only through
Ableton's Configure-slot param path, which carries two hard limits:

1. **128-slot cap** - Ozone exposes 873 Configurable params; only 128 can be
   Configured at once, so exposure is a curated per-module subset.
2. **Identity-normalization clamp** - Ozone reports every param as an
   identity-normalized `[0,1]` float (native == normalized), so the Phase 1
   convenience wrappers' Hz/dB arguments clamp to `[0,1]` instead of mapping
   true units.

Phase 2 removes both limits by authoring params **directly in Ozone's plugin
state blob** inside the `.als`. The spike (2026-07-05) proved that blob is a
16-byte header plus a zlib stream that decompresses to ~321 KB of plain,
pretty-printed JSON in iZotope's typed-dictionary format - fully readable and
writable, with real native values and friendly names for all params.

This is a **native batch-authoring** path that coexists with Phase 1's live
per-knob tools. It does NOT replace them. Chain add/remove/reorder remains out
of scope (deferred to a later phase).

## Spike findings (2026-07-05, Live 12.4 Suite, offline from a saved scratch set)

Dissected the master Ozone `<ProcessorState>` in
`ozone_idbase_probe.als`:

### Container format

```
[4B magic = DE 8A 68 00]
[4B version   (uint32 LE) = 4]
[4B field3    (uint32 LE)]      # = 4 + len(zlib payload)  == total_blob_len - 12
[4B raw_len   (uint32 LE)]      # = exact decompressed byte length
[ zlib stream (0x78 0x9C ...) ] # -> raw_len bytes of UTF-8 JSON
```

Verified: original blob is 12433 bytes; header `raw_len` = 321402 matches the
decompressed length exactly; `field3` = 12421 = 12433 - 12 = `4 + 12417`
(the raw_len field plus the 12417-byte zlib payload). **The encode rule is
`field3 = 4 + len(compressed)`, NOT `len(compressed)`** - a subtle point the
codec must honor, since Live's parser may validate it.

### Payload

The decompressed payload is UTF-8 JSON. iZotope's typed-dict format wraps every
value as `{"Type": <T>, "Value": <v>}`. Observed types: `Dictionary`, `UInt`,
`Float`, `Bool`, `String`, `Base64`. Top-level keys: `Context State`,
`DSP State`, `Major Version`, `Minor Version`.

All ~40 modules live under `DSP State/Value/DSP Elements/Value/<Module>/Value/`
with their full param set, each param a typed leaf. Module names are the
blob-native long forms: `Equalizer`, `Maximizer`, `Dynamics`, `Dynamic EQ`,
`Stereo Imager`, `Exciter`, `Vintage Compressor`, `Vintage EQ`,
`Vintage Limiter`, `Vintage Tape`, `Spectral Shaper`, `Master Rebalance`,
`Match Equalizer`, `Low End Focus`, `Impact`, `Stabilizer`, `Clarity`,
`Bass Control`, `Stem EQ`, `Unlimiter`, `Global`, etc. Example native leaves:
`Dynamics/Value/Sidechain HPF` (Float, real Hz), `Maximizer/Value/Character`
(UInt), per-module `Bypass` (Bool), `Processing Mode` (UInt).

### Round-trip proof (file level)

Decode -> change one Float leaf -> re-encode with the corrected header ->
splice inner-hex back into the `.als` -> re-gzip -> re-open -> re-extract ->
re-decode: the edited value survives and **every other key is byte-identical**.
The encode is lossless. iZotope's exact JSON whitespace does not need to be
reproduced (JSON is whitespace-insensitive; Ozone's parser accepts compact
output), which further lowers risk.

### What is NOT in the JSON

There is no array/list anywhere and no obvious ordered chain structure.
`DSP Elements` holds every module always (full state regardless of chain
membership); `ElementChain` is a name/version stub; `Selected Signal Chain
Module` is only the GUI cursor index. So the active-set + order is either
implicit or serialized inside a `Snapshot` Base64 binary - pinning it needs a
GUI-reorder-and-diff spike. **Chain structure is therefore deferred**; Phase 2
only reads/writes existing param leaves (never adds/removes keys).

## Decisions (from brainstorming)

- **Scope**: native param authoring via the blob. Chain add/remove/reorder is
  OUT (deferred; order-encoding still unknown).
- **Relationship to Phase 1**: coexist, non-breaking. Phase 1 live tools stay
  for instant single-knob tweaks on exposed modules. Phase 2 is native
  batch-author.
- **Batch-oriented**: blob writes require a full set save + patch + reload
  (seconds, disruptive), so `set_ozone_state` takes many params across many
  modules and does ONE reload.
- **No generated catalog**: the blob is self-describing (every leaf carries its
  `Type`), so validation and discovery read the live blob directly. No
  `ozone_state.json` catalog file is generated.

## Components

### 1. `ableton_mcp_max/ozone_state_utils.py` (new, pure, unit-tested)

Owns the container and the typed-dict JSON. Server-side only (the Remote Script
runs in Live's own Python and cannot import it). Functions (names indicative;
finalized in the plan):

- `decode(blob: bytes) -> DecodedState` - validate magic, parse header, zlib
  decompress, `json.loads`. Holds `version`, `raw` bytes, and the parsed `tree`.
- `encode(state, tree) -> bytes` - `json.dumps` (compact) -> zlib compress ->
  rebuild header with `field3 = 4 + len(zlib)` and `raw_len = len(json_bytes)`.
- `from_hex` / `to_hex` - inner-hex <-> bytes (uppercase, whitespace-stripped),
  mirroring `serum_state_codec`.
- `is_ozone_state(inner_hex) -> bool` - magic check, to reject non-Ozone
  devices with an explicit error.
- `module_leaves(tree, module) -> dict` - enumerate a module's param leaves as
  `{param_name: {"type": T, "value": v}}` for reads.
- `get_param(tree, module, param)` / `set_param(tree, module, param, value)` -
  address `DSP State/Value/DSP Elements/Value/<module>/Value/<param>/Value`;
  `set_param` coerces `value` to the leaf's existing `Type` (Float/Bool/UInt)
  and raises on a wrong/uncoercible type or a missing module/param key.
- `apply_changes(tree, changes) -> (applied, skipped)` - apply
  `{module: {param: value}}`; collect unknown-module / unknown-param /
  type-mismatch entries into `skipped` rather than failing the whole call.

Module-name normalization (Phase 1 short aliases like `MAX`, `DYNEQ` ->
blob-native long names) lives as a small map in `ableton_mcp_max/ozone_utils.py`
and is applied before addressing.

### 2. Server tools (`ableton_mcp_max/server.py`)

- **`get_ozone_state(track_index, device_index, track_type="master", module=None)`**
  - Save the set first (persist any un-saved live tweaks), resolve the `.als`
    path, locate the target Ozone's `<ProcessorState>`, decode, and return
    native param values + types for `module` (or a per-module summary for all
    modules when `module is None`). Reads native values for ANY module without
    Configure/exposure.
- **`set_ozone_state(track_index, device_index, track_type="master", changes={})`**
  - `changes` is `{module: {param: value}}`. Save the set, decode the blob,
    `apply_changes`, re-encode, splice the new inner-hex into the `.als`,
    `_reload_set`, and return `{applied: [...], skipped: [...], reloaded: bool}`.
    One reload for the whole batch.

Both accept `track_type` in `{regular, return, master}` and target the device
by `device_index` within the resolved track span - the same targeting Phase 1
and the VST/Serum tools use.

### 3. Reused infrastructure (no changes expected)

- `plugin_config_utils.locate_plugin_state(full_xml, track_start, track_end,
  device_index)` - finds the `<ProcessorState>` span.
- `als_automation_utils.find_master_track_span` / `find_return_track_span` /
  `find_track_span` - resolve the track span by `track_type` (the Live 11/12
  attribute-tolerant finders fixed in Phase 1).
- `_reload_set` - save-and-reopen-in-place; answers the stop-audio dialog. The
  proven Serum / arrangement-automation mechanism.
- `.als` path resolution (from `_expose_plugin_impl`) - finds the current set's
  file; surfaces a clear error if the set is untitled or saved outside the
  searched folders.

## Data flow

Intent/tool call -> normalize module names -> `save_set` (persist live state) ->
read `.als`, `find_<type>_track_span` -> `locate_plugin_state` (device_index) ->
`ozone_state_utils.decode` -> `apply_changes` (validate keys, coerce types) ->
`encode` (corrected header) -> splice inner-hex -> write `.als` -> `_reload_set`
-> return applied/skipped. Reads follow the same path up to `decode`, then return
the requested leaves.

## Error handling

- Every tool returns `{ok, data|error}` per project convention.
- Not-an-Ozone device (magic mismatch via `is_ozone_state`) -> explicit error.
- Unknown module / unknown param / wrong type -> reported in `skipped`, never a
  silent no-op; the rest of the batch still applies.
- Untitled set or `.als` path unresolved -> surface the path-resolution error
  (same limitation as `_expose_plugin_impl`).
- Live-disconnected -> surface the connection error; pure `ozone_state_utils`
  decode/encode still works offline.
- Blob writes read the LAST SAVED `.als`; the flow saves first so live tweaks
  are captured before patching. Reload replaces the whole plugin state - noted
  for callers.

## Testing

Offline pytest for `ozone_state_utils` against a committed real fixture (the
321 KB decompressed state captured in the spike, stored as a compressed test
asset):

- Header decode/encode round-trip: `decode(encode(...))` identity; the
  `field3 = 4 + len(zlib)` and `raw_len` rules; magic validation.
- Leaf get/set by `(module, param)` address.
- Type coercion (Float/Bool/UInt) and rejection of wrong/uncoercible types.
- `apply_changes` multi-module: applied vs skipped (unknown module, unknown
  param, type mismatch).
- Module-alias resolution (Phase 1 short names -> blob-native names).
- `is_ozone_state` accepts the Ozone magic, rejects Serum/other.
- Gates: `uv run python -c "import ableton_mcp_max.server"` + `py_compile`.

Live verification (manual, per project protocol):

- **Task 0 live gate (first task)**: patch one native value in the blob ->
  reload -> confirm Ozone accepts the set (no crash/recovery modal) and the
  value took (read back via `get_ozone_state` and/or the GUI). This is the one
  unproven step; low-risk given the identical Serum splice+reload precedent.
- A real multi-module `set_ozone_state` author survives reload; native Hz/dB
  values land un-clamped (contrast with Phase 1). Recorded in PROGRESS.md.

## Risks / unknowns

- **Live reload-acceptance** (Task 0 gate) - the only unproven step; the
  container format and file-level round-trip are proven, and the reload
  mechanism is the shipped Serum path. Low risk.
- **Whitespace/format tolerance** - Ozone must parse compact JSON. Very low
  risk (JSON is whitespace-insensitive); Task 0 confirms.
- **Multiple ProcessorState siblings** - `locate_plugin_state` selects by
  `device_index`; confirm the correct index for a master Ozone during Task 0
  (a scratch set may hold other plugins).

## Files to create/modify

- `ableton_mcp_max/ozone_state_utils.py` - new (pure container + typed-dict
  codec).
- `ableton_mcp_max/ozone_utils.py` - add the module-name alias map + normalizer.
- `ableton_mcp_max/server.py` - new `get_ozone_state` / `set_ozone_state`
  tools.
- `tests/` - new `ozone_state_utils` tests + a committed compressed real-state
  fixture.
- `docs/`, `README.md`, `commands/tool-index.md`, plugin/version files - the
  release step (tool count +2, doc regen, hardcoded-count hand-fixes, version
  bump, marketplace `ableton` ref bump).

## Out of scope (deferred)

- **Chain add/remove/reorder** - the order-encoding representation is still
  unknown (needs a GUI-reorder-and-diff spike). A separate later phase.
- **Master Assistant** - GUI-only AI target-matching; not a host param.

## Verification (ship gate)

- Offline tests green; `import` + `py_compile` gates pass.
- Task 0 live gate passes (blob edit survives reload, value took).
- A multi-module native author verified live with un-clamped units; recorded in
  PROGRESS.md.
- Full release chain: local `main` = `origin/main` = tag; marketplace `ableton`
  ref bumped; hardcoded doc counts updated by hand.
