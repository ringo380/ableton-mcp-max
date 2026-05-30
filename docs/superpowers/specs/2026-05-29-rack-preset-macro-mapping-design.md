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

### FINDINGS (experiment run 2026-05-29) — encoding cracked

The expected id-based encoding was **wrong**. The real encoding is far simpler and there are
**no ids involved at all** (every `AutomationTarget`/`ModulationTarget Id` stays `0`, in both
the test rack and factory racks — the only non-zero ids in factory racks are `MacroSnapshot`
and preset-ref bookkeeping, unrelated to mappings).

A macro→parameter mapping is a **self-contained `<KeyMidi>` block injected into the target
parameter element** (right after its `<LomId>`, before `<Manual>`):

```xml
<KeyMidi>
  <PersistentKeyString Value="" />
  <IsNote Value="false" />
  <Channel Value="16" />            <!-- constant: the macro sentinel (real MIDI ch = 0..15) -->
  <NoteOrController Value="N" />     <!-- THE macro index, 0-based: Macro 1 => 0, Macro 8 => 7 -->
  <LowerRangeNote Value="-1" />
  <UpperRangeNote Value="-1" />
  <ControllerMapMode Value="0" />
</KeyMidi>
```

Evidence: mapping **Macro 1 → Utility Gain** added exactly this block to `<Gain>` with
`NoteOrController=0`. Factory "Basic Bass Amp" (12 macros) corroborates: all 16 of its mapped
params carry `Channel=16` `KeyMidi` blocks whose `NoteOrController` is the controlling macro
index (Bass→1, Middle→2, Treble→3, Presence→4, Volume→5, Gain→6/7, MicPos→8, MicType→9, …),
and **multiple params can share one macro** (several params on index 11 = one "Drive" macro).

Key properties that make this clean:
- No id management, no registry, no cross-reference — the block is fully local to the param.
- The macro is identified purely by **0-based index** in `NoteOrController`.
- Many-to-one (one macro → several params) = repeat the block on each param with the same index.
- **Default (full-range) mapping needs no range edit** — the param's existing
  `<MidiControllerRange>` is its intrinsic range, unchanged by mapping (confirmed: identical
  in mapped vs unmapped). The macro's `<Manual>` value updates to reflect the target, but that
  is a value, not structural, and is not required for the mapping to function on load.

**Unknowns deferred to a v2** (not needed for a useful v1):
- **Custom / inverted mapping ranges** (macro sweeps a param sub-range) — not exercised; the
  test used Live's default full-range map. Where a custom range is stored is still unconfirmed.
- Whether `ControllerMapMode` ever varies (always `0` in all observed data).

### v2 FINDINGS (range save-diff, 2026-05-29) — custom/inverted ranges cracked

Controlled save-diff (`MCP_RangeTest_default` vs `_custom` vs `_inverted`, Utility Gain mapped to
Macro 1, dragged to −12→0 dB then inverted). The custom range is stored in the **target param's own
`<MidiControllerRange><Min>/<Max>`** — the same block v1 deliberately left untouched. Specifically
the mapped `<Gain>` is:

```xml
<Gain>
  <LomId Value="0" />
  <KeyMidi> … <Channel Value="16"/> <NoteOrController Value="0"/> … </KeyMidi>   <!-- unchanged across all 3 -->
  <Manual Value="1" />
  <MidiControllerRange>
    <Min Value="0" />              <!-- default = param's intrinsic native min -->
    <Max Value="56.2341309" />    <!-- default = param's intrinsic native max (+35 dB as linear amp) -->
  </MidiControllerRange>
  <AutomationTarget Id="0">…</AutomationTarget>
  <ModulationTarget Id="0">…</ModulationTarget>
</Gain>
```

Confirmed:
- **(a)** the ONLY param-level delta is `<MidiControllerRange><Min>/<Max>`.
- **(b)** values are in the param's **NATIVE stored units** (Gain = linear amplitude: `0`=−∞dB,
  `1.0`=0dB, `56.2341309`=+35dB), NOT 0..127 and NOT necessarily dB. Custom −12→0 dB →
  `Min=0.2511886358` (10^(−12/20)), `Max=1`. (The sibling `LegacyGain` MidiControllerRange is
  `-35..35` because that param is stored in dB — units are per-parameter.)
- **(c)** **inversion = swap Min/Max** (`Min=1`, `Max=0.2511886358`). No separate invert flag.
- **(d)** `<KeyMidi>` byte-identical (range is NOT in KeyMidi); `ControllerMapMode` stays `0`.
- **(e)** `<MidiControllerRange>` **always exists** on an automatable param and defaults to the
  full native range → a default (full-range) map leaves it untouched (why v1 saw it "unchanged");
  a custom range REPLACES Min/Max in place (no synthesis ever needed).

The bookkeeping deltas in the diff (`FilePresetRef` to the prior save, `UserName`,
`IsBranchesListVisible`, the macro `<Manual>` knob position, `DeviceId Name`) are save-time noise,
not part of the mapping encoding.

### Go / no-go gate — DECISION: **GO (cleanly patchable)**

The encoding is a self-contained, id-free, index-addressed XML insertion — the
"cleanly patchable" branch. Build `add_rack_macro_mappings` (v1 = default full-range mappings;
custom ranges deferred to v2 pending a follow-up diff).

(For the record, the other two branches — *fragile* and *infeasible* — do not apply: there is
no id collision risk and the synthesis is deterministic.)

### `add_rack_macro_mappings(name, mappings)` (v1 — confirmed encoding)

- `mappings`: list of
  ```json
  {"macro": 1, "chain": 0, "device": 0, "parameter": "Gain"}
  ```
  - `macro` 1-based (→ stored as `NoteOrController = macro - 1`),
  - `chain` 0-based (resolve via the depth-aware branch scanner from Phase A),
  - `device` = device index within the chain's `<DeviceChain>` (0-based),
  - `parameter` = the parameter's XML tag name (e.g. `Gain`, `Volume`) within that device.
- **No `min`/`max` in v1** — mappings are default full-range (the param's intrinsic
  `<MidiControllerRange>` is untouched). Custom/inverted ranges are a v2 once their storage is
  confirmed by a follow-up diff.
- Implementation: for each mapping, locate chain → device → the parameter element, then inject
  the `<KeyMidi>` block (Section 3 Findings) right after that param's `<LomId>`, with
  `NoteOrController = macro - 1`. Idempotency: if the param already has a `<KeyMidi>`, replace
  its `NoteOrController` rather than inserting a duplicate.
- Validation: macro 1–16; chain in range; device in range; parameter tag must exist in the
  device (else clear error). Many-to-one allowed (same macro on several params).
- Patches the named working preset in place; returns `{written, path, mappings: [...]}`.
- Pure helper `patch_macro_mappings(xml, rack_type, mappings)` in `rack_preset_utils.py`,
  unit-tested offline (inject → re-find KeyMidi → assert `Channel=16`, `NoteOrController=N-1`;
  many-to-one; idempotent replace; bad param/chain/device rejection). Live-verify by loading a
  patched rack and confirming the macro audibly/visibly drives the param in Live.

### v2 (custom/inverted ranges + nested rack addressing) — shipped v0.4.0

Same tool/signature; the per-mapping dict grows (backward compatible):
- **`range` (optional)**: `{"min": <float>, "max": <float>}` in the param's NATIVE units
  (see v2 FINDINGS above). `min > max` inverts; omit for full-range. Implemented by
  `_set_controller_range(param_el, lo, hi)` replacing `<Min>/<Max>` in the param's
  `<MidiControllerRange>` (the same substitution style as `patch_chain_zone`).
- **`path` (optional)**: an array of `{chain, device}` steps for nested rack-in-rack addressing,
  replacing the flat `chain`/`device` (which stays valid = a one-step path). Implemented by a
  recursive `_descend_to_device` / `_locate_param_by_path`; each non-final step's device must be a
  rack, its branch_tag auto-detected via `detect_rack_type` (may differ from the outer's).
  Supplying both `path` and flat `chain`/`device` is rejected.

#### Nested-rack XML structure (live-verified 2026-05-29 — corrected a v2 bug)

Confirmed against real factory racks (e.g. `Basic Heavy Guitar Amp.adg` — a nested Audio Effect
Rack at chain0/device2 wrapping a Cabinet; Drum Rack pads wrapping Instrument Racks). A nested rack
in a chain's `<DevicePresets>` is **NOT** an `<AbletonDevicePreset>`. It is a separate wrapper:

```
<DevicePresets>
  <AbletonDevicePreset>…plain device…</AbletonDevicePreset>     <!-- device 0 -->
  <AbletonDevicePreset>…plain device…</AbletonDevicePreset>     <!-- device 1 -->
  <GroupDevicePreset>                                           <!-- device 2 = a NESTED RACK -->
    <Device><AudioEffectGroupDevice>…</AudioEffectGroupDevice></Device>
    <BranchPresets>…the nested rack's chains…</BranchPresets>   <!-- SIBLING of <Device>, not inside it -->
    <ReturnBranchPresets>…</ReturnBranchPresets>
  </GroupDevicePreset>
</DevicePresets>
```

Two consequences the implementation MUST honor (both were initially wrong — the synthetic test
fixture had invented an `<AbletonDevicePreset>`-wrapped nested rack with `<BranchPresets>` *inside*
the device element, which Live never emits; the bug surfaced only in live testing when a real
`path` map returned "device index 2 out of range — chain 0 has 2 devices"):
1. **Device enumeration counts BOTH `<AbletonDevicePreset>` and `<GroupDevicePreset>`**, in
   document order, so `device` indices match `get_rack_chains`.
2. **Descent continues into the `<GroupDevicePreset>`'s `<BranchPresets>` sibling**, not into the
   `<Device>` element. The nested rack's branch_tag is detected from the GroupDevice element inside
   `<Device>`. (`top_branches` over the `<BranchPresets>` block finds the nested chains.)

Regression guard: `test_real_factory_nested_descent_reaches_inner_device` descends a genuine factory
nested rack (skipif when Live isn't installed), so reverting to `AbletonDevicePreset`-only fails.

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
