# VST/AU Plugin Support - Design

**Created**: 2026-06-26
**Status**: In Progress

## Overview

Add support for controlling third-party instrument/effect plugins (VST3/AU) through the
MCP, introduced one plugin at a time ("we now support X!"). The first target is
**Serum 2**.

The capability the user wants per plugin:

1. **Drive its knobs** - read and set the plugin's parameters live and interactively.
2. **Navigate its preset library** - browse, recall, and audition patches.
3. **Author patches** - design sounds by setting the exposed parameters directly.

The deliverable is a **generic exposure engine** (built once) plus a **per-plugin
param-map pack** (Serum 2 first). Each new supported plugin is a new pack plus curation,
not new mechanism - which is what makes the one-at-a-time cadence cheap and repeatable.

## Feasibility findings (live probe, 2026-06-26, Live 12 Suite)

These are the empirical results that this design is built on. They were captured against a
real Serum 2 instance on track 0.

### The wall: plugins expose almost nothing to the LOM by default

- `device.parameters` for Serum 2 returns exactly **one** parameter: `Device On`. This is
  true for **both** the AU (`AuPluginDevice`) and the VST3 (`PluginDevice`) builds - it is
  not an AU-vs-VST3 quirk; Serum simply does not publish its parameter surface to Live's
  host-automation list.
- Live only exposes a plugin's parameters after the user manually adds them in **Configure**
  mode (the Configure tab in the device view). **There is no LOM API to enter Configure or
  to add parameters to the exposed list** (verified against the Live 11 LOM doc: the only
  parameter-mutation surface is `DeviceParameter` objects inside `device.parameters`, and the
  bank methods index into that same list).
- Corroboration: the commercial "Serumify 2" control-surface script (remotify.io) requires
  the user to manually Configure params "up to 128 parameters." Even a shipping product hits
  this wall - and its 128 cap matches the slot-pool size we found (below) exactly.

### The opening: the Configure list lives in patchable XML

A saved `.als` containing a Serum 2 device records a `<ParameterList>` with a **pre-allocated
pool of 128 `<PluginFloatParameter>` slots**. An empty (unconfigured) slot looks like:

```xml
<PluginFloatParameter Id="0">
  <ParameterName Value="" />
  <ParameterId Value="-1" />              <!-- -1 = unassigned slot -->
  <VisualIndex Value="1073741823" />      <!-- 0x3FFFFFFF = not shown -->
  <ParameterValue>
    <Manual Value="0.1234567687" />       <!-- sentinel "uninitialized" magic value -->
    ...
  </ParameterValue>
</PluginFloatParameter>
```

A **save-diff** (user Configured four Filter 1 knobs, then saved) revealed the encoding of a
filled slot:

| ParameterId | ParameterName  | Manual    | VisualIndex |
|-------------|----------------|-----------|-------------|
| 2000003     | Filter 1 Freq  | 1547.45   | 0           |
| 2000005     | Filter 1 Drive | 21.56     | 1           |
| 2000004     | Filter 1 Res   | 24.18     | 2           |
| 2000006     | Filter 1 Var   | 21.40     | 3           |

To expose a parameter, fill an empty slot with:

- **`ParameterId`** - the plugin's real VST3 parameter id. For Serum 2 these are **structured
  and contiguous** (Filter 1 block = 2000003-2000006), which strongly suggests the id space is
  enumerable (working hypothesis: `id = 2000000 + plugin_param_index`; to be confirmed in M1).
- **`ParameterName`** - the human-readable name.
- **`Manual`** - the value in the parameter's **native units** (Hz, etc.), not normalized 0-1.
  This matches the existing arrangement-automation value-probe rule: native-unit params round
  trip cleanly; normalized params (Volume/Pan) are the exception that needs care.
- **`VisualIndex`** - sequential display order (0, 1, 2, ...).

After reload, each filled slot becomes an ordinary LOM `DeviceParameter`, so the existing
`get_device_parameters` / `set_device_parameter` tools (already confirmed working on
`PluginDevice`) handle all control and authoring with no new control surface.

### Library navigation primitives

`PluginDevice` exposes two properties the current tools do not yet wrap:

- `presets` - "the list of presets the plugin offers"
- `selected_preset_index` - settable index of the current preset

If Serum 2 populates these, patch selection is programmatic and direct. Whether it does is
unconfirmed (M3). The always-available fallback is recall via Ableton `.adv` wrappers, which
embed the plugin's binary state.

## Mechanism

The exposure step is the **Configure-list XML backdoor**: fill `<PluginFloatParameter>` slots
from a param-map pack, exactly the established preset-XML backdoor pattern used for Wavetable,
Simpler, and rack macro mappings. This is a one-time **unlock** of which knobs are visible to
the LOM - it is not per-change. Once exposed, control is direct, live, and interactive through
the normal parameter tools.

## Delivery model

**The Task 0 spike corrected the original plan.** Live 12 will NOT produce a VST3 `.adv` (both
Save-Preset and drag-to-browser yield a `.vstpreset` = plugin binary state only, no Live
`<ParameterList>`), and a hand-synthesized `.adv` failed to load. **So the original "ship a
pre-exposed `.adv`" model is dead for VST3 plugins.** The two viable models, and the chosen
phasing:

**Release 1 - Option A: patch the live set (`.als`).** The engine saves the set, patches the
plugin device's `<ParameterList>` (fills empty `<PluginFloatParameter>` slots from the param-map
pack, allocating target ids from `<NextPointeeId>` and advancing it), then reloads the set. Serum
stays a **top-level track device**, so exposed params are directly reachable by the existing
`get_device_parameters` / `set_device_parameter` tools - **no new tooling**. This is **proven
end-to-end** (Task 0). Cost: one set save+reload per Serum instance at expose time (mild
mid-session friction; `Cmd+S` is clean for an already-saved set, the modal risk is only on
Untitled sets).

**Release 2 (fast-follow) - Option B: pre-exposed rack `.adg`.** A rack `.adg` DOES carry the
exposure (stored compactly as `<PluginParameterSettings>`: Index/VisualIndex/ParameterId/Type)
plus the plugin state, and loads via the browser with **no set reload**. The catch: the plugin
sits nested in the rack chain, so reaching its params needs **chain-aware param access** that the
current tools lack (they only index `track.devices`). Release 2 ships the pre-exposed Serum rack
preset + new nested-device get/set param access, removing Release 1's reload friction. Deferred
deliberately so Release 1 ships fast on the proven path.

In both models, ongoing knob control is identical: direct live `set_device_parameter`. They
differ only in how the one-time exposure happens (per-instance live-set patch vs. a shipped
preset).

## Components

Following the project's established pattern (server.py `@mcp.tool()` + Remote Script handler +
pure server-side `*_utils.py`):

- **`plugin_config_utils.py`** (server-side pure, on the `preset_patch.py` core) - encode a
  filled `<PluginFloatParameter>` slot; parse a device's `<ParameterList>`; build/curate the
  exposed set. Offline-tested with synthetic and real `.adv`/`.als` fixtures (with
  `re.DOTALL`, per the preset-XML regex gotcha).
- **Param-map packs** (e.g. `param_maps/serum2.json`) - static `ParameterId <-> name`
  (+ category for curation/grouping). One per supported plugin, shipped with the plugin.
- **Discovery probe** (Remote Script command `probe_plugin_parameters` -> `get_parameter_names()`
  / `get_bank_parameters()`) - reads the live plugin's full name list; the server derives the
  id map and writes a pack. Dev-time, run once per plugin.
- **`expose_plugin_parameters` tool** - builds the exposed device from a pack and loads it.
- **Library navigation** (`get_plugin_presets` / `select_plugin_preset`) - wraps `presets` /
  `selected_preset_index`, pending the M3 populate check; `.adv` recall via existing load.
- **Existing tools** (`get_device_parameters`, `set_device_parameter`) - unchanged; they do all
  control and authoring once params are exposed.

## Milestones / build order

- **M0 - GATE (make-or-break spike).** Hand-craft an `.adv` with one *externally*-written
  exposed param (a known Serum id, e.g. 2000007), load it, and confirm the LOM both **shows**
  it in `device.parameters` and lets us **set** it live. This is the one thing manual Configure
  cannot prove. Also decides Option B vs A (does hot-swap preserve patch state). If this fails,
  stop and rethink before building anything.
- **M1.** Discovery probe; confirm the `id = base + index` hypothesis; generate the Serum 2
  param-map pack.
- **M2.** `plugin_config_utils` + `expose_plugin_parameters` + offline tests.
- **M3.** Library navigation - probe whether `presets` / `selected_preset_index` populate for
  Serum 2; build the wrapper tools or fall back to `.adv` recall.
- **M4.** Curation (friendly names / grouping from the pack), docs, ship as a plugin version.

## Risks and open questions

- **M0 round-trip is the gate** - the entire initiative depends on an externally-patched slot
  being honored on reload and becoming a settable `DeviceParameter`.
- **Hot-swap vs live-patch** - whether loading the exposed `.adv` preserves the sound decides
  Option B vs A.
- **128-slot pool cap** - confirmed by both the XML and the Serumify product. If Serum exposes
  more than 128 params, we curate to the ~128 most useful and `log()` what was dropped (no
  silent truncation).
- **Hidden state** - the wavetable *file* selection and mod-matrix routing may live only in
  Serum's binary chunk, not as host parameters. Authoring reaches the full host-param knob
  surface; wavetable choice specifically is TBD in M1 discovery.
- **`Manual` units** - native-unit params round-trip cleanly (proven); quantized/normalized
  params need explicit handling in the encoder.
- **`ParameterId` enumeration** - the `id = base + index` hypothesis must hold (or be mapped)
  for clean discovery; if ids are sparse, the probe falls back to brute-force id-range probing
  via the backdoor.

## Files to create/modify

- `ableton_mcp_max/plugin_config_utils.py` - new (slot encode/parse, on `preset_patch.py`).
- `ableton_mcp_max/param_maps/serum2.json` - new (param-map pack).
- `ableton_mcp_max/server.py` - new tools: `probe_plugin_parameters`, `expose_plugin_parameters`,
  `get_plugin_presets`, `select_plugin_preset`.
- `remote_script/AbletonMCP/__init__.py` - new read handler(s): `probe_plugin_parameters`
  (and preset read/select if used).
- `tests/` - offline tests for `plugin_config_utils` (synthetic + real-file round-trip).

## Verification

- Offline: `uv run --with pytest pytest -q`, `uv run python -c "import ableton_mcp_max.server"`,
  `uv run python -m py_compile remote_script/AbletonMCP/__init__.py`.
- Live: M0 round-trip; expose Serum 2, set several params via `set_device_parameter`, confirm
  audible/readable change; round-trip a pack-built `.adv`. Record results in PROGRESS.md.
