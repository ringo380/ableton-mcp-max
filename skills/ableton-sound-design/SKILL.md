---
name: ableton-sound-design
description: Designing instrument and effect sounds in Ableton Live - preset selection, Wavetable/Simpler patches, rack macros, and layering. Use when designing a sound, building a patch, choosing/creating presets, or mapping rack macros.
---

# Ableton sound design

Goal: a fit-for-purpose instrument/effect sound, repeatable via presets and rack macros.

## Tools
- Discover/load: `get_browser_tree` / `get_browser_items_at_path`, `list_device_presets`,
  `load_instrument_or_effect`, `load_preset`.
- Probe a live instance FIRST with `get_device_parameters` - most choosers ARE automatable
  (filter type, osc wave, ADSR) so just `set_device_parameter`.
- Backdoor (genuinely hidden state only): `create_wavetable_preset` (table + unison),
  `create_simpler_instrument` (sample ref), `list_wavetable_tables`.
- Racks: `inspect_rack_preset`, `clone_rack`, `rename_rack_macros`, `set_rack_zones`,
  `add_rack_macro_mappings`, `get_rack_macros` / `set_rack_macro`.

## Choosing the engine
- Before loading a synth for a described sound, call `recommend_instrument` with
  a free-text intent (role + genre + character, e.g. "gritty evolving reese bass
  for dnb"). It ranks the engines and returns a `top.domain` to feed
  `recommend_asset`.
- Default to native (Wavetable / Operator / Analog) for subs, generic pads, and
  FM keys - lighter, recall-safe, no 3rd-party dependency. Wavetable (native)
  covers most wavetable needs.
- Escalate to Serum only for wavetable morphing, heavy unison, complex mod, or
  reese/growl - or when the user names Serum.
- Prefer Simpler/Sampler for acoustic/realistic tones or when a specific sample
  is the source; Drum Rack for percussion.
- Flow: `recommend_instrument` (pick engine) -> `recommend_asset(domain)`
  (reuse-vs-create) -> `create_from_plan` or load a preset.

## Principles
- Reach for the backdoor only for hidden state (sample refs, wavetable selection, macro
  mappings). Everything automatable goes through `set_device_parameter`.
- Map the controls that matter to rack macros (1..16) so a sound stays playable/automatable.
- Layer for thickness (e.g. sub + body + air), then carve overlap with EQ.

## Gotchas
- Loading HOT-SWAPS - design on an empty/scratch track, never over a patch you need.
- Verify a macro mapping by reloading and reading `get_rack_macros`: a single-mapped
  unnamed macro auto-renames to its target param (proof it bound).

## Checklist
- [ ] Probed params before assuming a backdoor was needed.
- [ ] Key controls mapped to macros.
- [ ] Saved/loaded as a preset where reuse matters.
