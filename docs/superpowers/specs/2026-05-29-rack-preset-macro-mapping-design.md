# Rack Preset — Macro Mapping & Zones (Design)

**Date:** 2026-05-29
**Status:** Draft — design approved (Sections 1–3), pending plan
**Initiative:** preset-patch backdoor (task #5, the flagship)

## Motivation

Live's LOM exposes a rack's macro *values* (`get_rack_macros` / `set_rack_macro`) and
chain *names/properties* (`get_rack_chains` / `set_chain_property`), but **not**:

- **Macro names / colors / defaults** — the macro's `set_device_parameter`-able value is
  reachable, but renaming "Macro 1" → "Filter Freq" is not in the LOM.
- **Chain key / velocity / chain-selector zones** — instrument-rack chain split points
  (KeyRange/VelocityRange) and the chain-selector range are UI-only.
- **Macro → parameter mappings** — wiring Macro 1 to "Chain 0 ▸ Utility ▸ Gain" is the
  defining feature of a rack and has no LOM write path at all.

All three live only in the gzipped rack preset XML (`.adg`). This task extends the
established preset-patch backdoor (Wavetable `.adv`, Simpler `.adv` already shipped) to
racks, using the same pattern: patch a known-good template preset → write to the User
Library → load via the browser (hot-swap).

### LOM probe results (why a backdoor is required)

| Need | LOM? | Route |
|------|------|-------|
| Macro value | yes | `set_rack_macro` (already shipped) |
| Macro name / color / default | no | preset XML attribute (trivially patchable) |
| Chain key / velocity / selector zone | no | preset XML structured block (patchable) |
| Macro → param mapping | no | preset XML — **encoding not statically recoverable** (Phase B, gated) |

## Decisions (locked during brainstorming)

1. **Scope:** everything in one phased spec — names/colors/defaults + zones land first
   (Phase A), macro→param mapping is a clearly-gated later step (Phase B), pending a
   controlled save-diff experiment.
2. **Approach:** separate granular composable tools (not a single `create_rack` tool).
3. **Composition:** pipeline on a working preset — tools read + repatch a named User
   Library preset in place; edits accumulate on one working `.adg`, loaded once at the end.

## The `.adg` rack structure (probed)

Probed against factory `Core Library/Racks/Instrument Racks/Strings/Synthetic Strings.adg`
(16 macros) and user `Audio Effect Rack/LEAD VOCAL SAUCE.adg`:

- Root `<GroupDevicePreset>`; a device-type child names the rack kind:
  - `InstrumentGroupDevice` → instrument rack
  - `AudioEffectGroupDevice` → audio-effect rack
  - `MidiEffectGroupDevice` → midi-effect rack
  - `DrumGroupDevice` → drum rack
- Macros: `<MacroControls.0>`…`<MacroControls.15>` (the value block, with `<Manual>`),
  plus per-index `<MacroDisplayNames.N Value="..."/>`, `<MacroColor.N Value="..."/>`,
  `<MacroDefaults.N Value="..."/>`. `<NumVisibleMacroControls Value="N"/>` = visible count.
- Chains live under the device child; each chain carries name + (instrument/drum only)
  `<KeyRange>`/`<VelocityRange>` and a chain-selector range. Audio-effect / midi-effect
  chains expose **only** a chain-selector range (`<BranchSelectorRange>`), no key/velocity.
- All zone blocks have four ints: `Min`, `Max`, `CrossfadeMin`, `CrossfadeMax`.

### The macro-mapping encoding finding (drives the Phase B gate)

In `.adg`/`.adv` files **every** `<AutomationTarget Id="…">` / `<ModulationTarget Id="…">`
serializes to `Id="0"`; macro IDs are never cross-referenced; there is no mapping-registry
tag. So a macro→parameter mapping is **not statically recoverable** from a saved `.adg`
alone. (Project `.als` files, by contrast, keep unique non-zero IDs — the zeroing is
specific to preset serialization.) Determining the real encoding requires a controlled
save-diff inside Live — hence Phase B is gated on an experiment (Section 3).

---

## Section 1 — Tool set (approved overview)

Five tools, pipeline-on-a-working-preset. All operate on a User Library rack preset by
name; reads and Phase A writes are pure file I/O + XML patching (server-side); load reuses
the existing `load_preset` tool.

| Tool | Phase | Purpose |
|------|-------|---------|
| `inspect_rack_preset(template)` | A | Read a rack `.adg` → structured summary (type, macros, chains, zones). |
| `clone_rack(template, name)` | A | Copy a template rack into the User Library under `name` (the working preset). |
| `rename_rack_macros(name, ...)` | A | Patch macro display names / colors / defaults in place. |
| `set_rack_zones(name, zones)` | A | Patch chain key / velocity / chain-selector zones in place. |
| `add_rack_macro_mappings(name, mappings)` | B (gated) | Add macro→parameter mappings. |

Typical pipeline:
`clone_rack` → `rename_rack_macros` → `set_rack_zones` → (`add_rack_macro_mappings`) →
`load_preset` (load the finished working `.adg` onto a track).

---

## Section 2 — Phase A data shapes (approved)

### Addressing conventions

- **Macros are 1-based** in tool arguments (matching the shipped `set_rack_macro`, which
  takes macro index 1–16). The XML tag index is 0-based (`MacroControls.0` = macro 1); the
  utils layer maps `macro_number → xml_index = macro_number - 1`.
- **Chains are 0-based** in tool arguments (matching `get_rack_chains`, which returns
  `chain_index` 0-based). The Nth `<...Chain>`/branch block in document order = chain N.

### `inspect_rack_preset(template: str)`

`template` identifies a rack `.adg` to read. A new `_read_rack_template(template)` server
helper resolves it in two modes: (a) an **absolute / glob path** (a factory rack, e.g. under
`Core Library/Racks/...` — note this is NOT `Defaults/`, so `_read_default_adv` does not
apply; this needs its own glob+gunzip) or (b) a **User Library name** (resolved via
`_user_library_dir()` + `Presets/<category>/<device_folder>`, the working-preset read side
shared with `_read_user_preset`). Reads + gunzips the `.adg`, returns:

```json
{
  "rack_type": "instrument" | "audio_effect" | "midi_effect" | "drum",
  "num_visible_macros": 4,
  "macros": [
    {"macro": 1, "name": "Filter Freq", "color": 0, "default": 63.5},
    ...                                              // always 16 entries
  ],
  "chains": [
    {
      "chain": 0,
      "name": "Sub",
      "key_zone":      {"min": 0, "max": 60,  "crossfade_min": 0, "crossfade_max": 0},
      "velocity_zone": {"min": 0, "max": 127, "crossfade_min": 0, "crossfade_max": 0},
      "chain_selector_zone": {"min": 0, "max": 127, "crossfade_min": 0, "crossfade_max": 0}
    },
    ...
  ]
}
```

- `key_zone` / `velocity_zone` are `null` on `audio_effect` / `midi_effect` racks
  (those chains carry only `chain_selector_zone`).
- `macros` always returns all 16 (Live stores all 16 regardless of `num_visible_macros`).

### `clone_rack(template: str, name: str)`

Copies a template rack into the User Library under `name`, establishing the working preset
the rest of the pipeline edits. (No empty/default rack exists to build from, so we clone.)

- Category + device-folder for the destination are derived from `rack_type`:

  | rack_type | category | device_folder |
  |-----------|----------|---------------|
  | instrument | Instruments | Instrument Rack |
  | audio_effect | Audio Effects | Audio Effect Rack |
  | midi_effect | MIDI Effects | MIDI Effect Rack |
  | drum | Drums | Drum Rack |

- Returns the `inspect_rack_preset` summary of the clone **plus**
  `{written: true, path, browser_path}`.
- `name` validated by `validate_preset_name` (no slashes / leading dot / double-quote).

### `rename_rack_macros(name, macro_names, macro_colors=None, macro_defaults=None)`

Patches macro metadata on the named working preset in place (read → patch → rewrite).

- `macro_names`: JSON object keyed by macro number (1-based) → string (no `"`).
  e.g. `{"1": "Filter Freq", "2": "Drive"}`. Only listed macros are changed.
- `macro_colors` (optional): object keyed by macro number → int ≥ 0 (Live color index).
- `macro_defaults` (optional): object keyed by macro number → float 0–127.
- Unlisted macros keep their current values. Validation: macro numbers 1–16; names via the
  preset-name double-quote guard (a display name may contain spaces but not `"`).
- Returns `{written, path, macros: [...updated 16-entry list...]}`.

### `set_rack_zones(name, zones)`

Patches chain zones on the named working preset in place.

- `zones`: list of entries, each:
  ```json
  {"chain": 0,
   "key": [0, 60],                  // shorthand [min, max]  OR full object
   "velocity": {"min": 0, "max": 127, "crossfade_min": 0, "crossfade_max": 0},
   "chain_selector": [0, 63]}
  ```
- `key` / `velocity` / `chain_selector` each optional; only provided zones are patched.
- Shorthand `[min, max]` expands to `{min, max, crossfade_min: min, crossfade_max: max}`
  (no crossfade). Full object form lets the caller set crossfade edges.
- **Validation:** all four ints in range (key/selector 0–127, velocity 0–127); and
  `min ≤ crossfade_min ≤ crossfade_max ≤ max`.
- **Rejected** with a clear error if `key`/`velocity` is supplied for an `audio_effect` or
  `midi_effect` rack (those chains have no key/velocity zone) — checked against the rack
  type read from the preset.
- Returns `{written, path, chains: [...updated chain list...]}`.

### Loading

No new load tool. The finished working `.adg` loads via the **existing** `load_preset(
track_index, path, name)` using the `browser_path` `clone_rack` reported (or
`user_library/Presets/<category>/<device_folder>`). Same indexing caveat as Wavetable/
Simpler: a brand-new filename may need a browser re-index before its first load; overwrites
of an indexed name load immediately.

---

## Section 3 — Phase B: macro → parameter mappings (gated)

Phase B is **not** built until a controlled save-diff experiment determines the real
encoding. The static finding (all IDs zeroed, no registry) means we cannot reverse-engineer
the mapping from existing files; we must observe Live writing one.

### The save-diff experiment (user-performed, one-time)

1. In Live, load a simple rack with one device on chain 0 (e.g. Utility).
2. Map **Macro 1 → Utility ▸ Gain** by hand (UI macro-map mode).
3. Save the rack to the User Library as `MCP_MapTest_mapped`.
4. Remove the mapping; save again as `MCP_MapTest_unmapped`.
5. I gunzip both and diff the XML to locate exactly what a mapping adds/changes.

Expected diff surface (to confirm): a `<ControllerTargets>` / `<MacroControls.N>` entry
gains a non-zero target id, plus a paired target block under the mapped device parameter
referencing that id, plus a min/max range pair. The experiment determines whether ids must
be globally unique within the file, how the device-parameter side is addressed, and whether
chain/device traversal order matters.

### Go / no-go gate (three branches)

- **Cleanly patchable** — mapping is a self-contained, well-structured XML insertion with
  predictable ids → build `add_rack_macro_mappings` as specced below.
- **Fragile** — encoding works but is brittle (id collisions, order-dependent, easy to
  corrupt the preset) → ship a *narrower* version (e.g. single-device, single-chain only)
  with loud caveats, or defer.
- **Infeasible** — encoding can't be reliably synthesized server-side → do NOT build the
  write tool; document the limitation and stop at Phase A. (Phase A still delivers real
  value: named/colored macros + zones on cloned racks.)

### Tentative `add_rack_macro_mappings(name, mappings)` (pending gate)

- `mappings`: list of
  ```json
  {"macro": 1, "chain": 0, "device": 0, "parameter": "Gain", "min": 0.0, "max": 1.0}
  ```
  - `macro` 1-based, `chain` 0-based, `device` = device index within the chain (0-based),
    `parameter` = parameter name (resolved/validated against the device's parameters),
    `min`/`max` = mapped range in the parameter's own units.
- Patches the named working preset in place; returns `{written, path, mappings: [...]}`.
- Exact field set + validation finalized after the experiment.

---

## Files

- `ableton_mcp_max/rack_preset_utils.py` (new) — pure XML logic on the `preset_patch`
  core: `summarize_rack_adg(xml)`, `detect_rack_type(xml)`, `patch_macro_names/colors/
  defaults`, `patch_chain_zones`, zone/macro validators, addressing maps. Phase B adds
  `patch_macro_mappings` (only if the gate passes).
- `ableton_mcp_max/server.py` — add `_read_user_preset(browser_path, name, ext)` (read +
  gunzip an existing User Library preset, the pipeline's read side) and
  `_read_rack_template(template)` (factory-path OR User-Library-name resolver for
  `inspect_rack_preset` / `clone_rack`); add the 4 Phase A `@mcp.tool()` defs (+ Phase B
  tool if gated in). Reuse `_write_user_preset`, `_load_user_preset`, `_user_library_dir`,
  `validate_preset_name`.
- `tests/test_rack_preset_utils.py` (new) — offline unit tests over fixture `.adg` XML:
  type detection, summary shape, each patch (round-trips through summarize), zone validation
  (range + crossfade ordering + audio/midi-effect rejection), addressing (1-based macro /
  0-based chain), name double-quote guard.

## Testing & verification

- **Offline:** `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run
  --with pytest pytest -q`; server import + `py_compile`. No Remote Script change, so no
  handler compile needed and **no Live bounce** — this is server.py-only.
- **Live (manual):** `inspect_rack_preset` a known factory rack; `clone_rack` it;
  `rename_rack_macros` + `set_rack_zones`; `load_preset` the result onto a scratch track;
  verify with `get_rack_macros` / `get_rack_chains` and visually in Live. Clean up the
  scratch track (`delete_track`) and the test User Library preset after.
- Record results in PROGRESS.md (and update the preset-patch initiative note: task #5).

## Risks & notes

- **Restart protocol:** server.py + utils only → restart Claude Code to reload; new tools
  arrive as deferred tools (load via `ToolSearch select:mcp__AbletonDev__<name>`). No Remote
  Script edit → no install script, no Live quit.
- **Browser indexing lag** (same as Wavetable/Simpler): first-time load of a new filename
  may need a User Library re-index; surface the existing "written but not yet loadable" note.
- **Regex patching on large files:** user racks can be ~500KB; `preset_patch` helpers are
  regex-on-string. Macro/zone tags are unique-enough per index; use `scope()` to disambiguate
  repeated chain blocks (target the Nth chain) rather than a global `set_attr`.
- **Phase B is genuinely uncertain** — do not promise the mapping tool until the experiment
  resolves the gate. Phase A stands on its own.
