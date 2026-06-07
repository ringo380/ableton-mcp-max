---
layout: default
title: Browser & Presets
parent: Tools
nav_order: 11
---

# Browser & Presets
{: .no_toc }

Walk the browser, load presets and drum kits, and generate presets via the preset-XML backdoor.

<details open markdown="block">
  <summary>Tools on this page</summary>
  {: .text-delta }
1. TOC
{:toc}
</details>

---

## get_browser_tree

```python
get_browser_tree(category_type: str = 'all')
```

Get a hierarchical tree of browser categories from Ableton.

Parameters:
- category_type: Type of categories to get ('all', 'instruments', 'sounds', 'drums', 'audio_effects', 'midi_effects')

## get_browser_items_at_path

```python
get_browser_items_at_path(path: str)
```

Get browser items at a specific path in Ableton's browser.

Parameters:
- path: Path in the format "category/folder/subfolder"
        where category is one of the available browser categories in Ableton

## load_drum_kit

```python
load_drum_kit(track_index: int, rack_uri: str, kit_path: str)
```

Load a drum rack and then load a specific drum kit into it.

Parameters:
- track_index: The index of the track to load on
- rack_uri: The URI of the drum rack to load (e.g., 'Drums/Drum Rack')
- kit_path: Path to the drum kit inside the browser (e.g., 'drums/acoustic/kit1')

## list_device_presets

```python
list_device_presets(path: str, max_depth: int = 6, limit: int = 100)
```

Recursively list loadable presets under a browser path.

Use this to discover presets for a device/category without knowing their
cryptic URIs, then load one with load_preset (pass a preset's `name` or its
`relative_path` — load_preset searches subfolders, so either works).

Parameters:
- path: Browser path like 'instruments/Wavetable' or 'audio_effects/Reverb'
        (same grammar as get_browser_items_at_path; category is one of
        instruments, sounds, drums, audio_effects, midi_effects).
- max_depth: How many levels of subfolders to descend (default 6).
- limit: Max presets to return (default 100). Factory devices can expose
        hundreds; the result is truncated past this to stay within size
        limits — narrow `path` to a subfolder or raise `limit` for more.

Returns JSON {path, count, returned, truncated, presets:[{name,
relative_path, uri}, ...]}. `count` is the full total; `presets` holds at
most `limit` of them.

## load_preset

```python
load_preset(track_index: int, path: str, name: str = None)
```

Load a preset onto a track by readable name/path (no URI required).

Works for any loadable browser item, including instrument/effect presets
(.adv) and rack/group presets (.adg). Loading onto a track that already
holds an instrument HOT-SWAPS (replaces) it, matching Live's behavior.

Parameters:
- track_index: The index of the (regular) track to load onto.
- path: If `name` is given, the folder to search (e.g.
        'instruments/Wavetable') — subfolders are searched recursively. If
        `name` is omitted, the full path to a single preset (e.g.
        'instruments/Wavetable/Ambient & Evolving/Dark Swarm.adg').
- name: Optional preset name OR relative_path (as shown by
        list_device_presets) to match under `path`. Matched exact, then
        case-insensitive, then unique substring, across name and
        relative_path. Note factory preset names include their file
        extension (e.g. 'Dark Swarm.adg').

Tip: run list_device_presets first, then pass a preset's `name` or
`relative_path` here (it resolves nested presets, so either works).

## list_wavetable_tables

```python
list_wavetable_tables()
```

List the factory Wavetable oscillator tables available by name, plus the
unison-mode legend — the inputs for create_wavetable_preset.

The oscillator wavetable selection, unison mode, and unison voice count are
NOT in Wavetable's automatable parameter list, so they can't be set with
set_device_parameter. create_wavetable_preset reaches them by writing a
preset; this tool tells you the valid table names to pass it.

Returns JSON {count, tables:[...], unison_modes:{name:int}, voices:[min,max]}.

## create_wavetable_preset

```python
create_wavetable_preset(
    name: str,
    table1: str,
    table2: str = None,
    unison_mode: str = 'classic',
    voices: int = 7,
    amount: float = 0.85,
    osc1_pos: float = None,
    osc2_pos: float = None,
    osc2_on: bool = True,
    track_index: int = None,
)
```

Generate a Wavetable preset (.adv) in the User Library and optionally load it.

This is the ONLY way to set Wavetable's oscillator table selection, unison
mode, and unison voice count via MCP — those controls are absent from the
automatable parameter API. The preset is built by patching Live's factory
default, so everything else stays at default and the automatable params
(osc detune/pos, unison amount, filter, envelopes) remain tweakable
afterwards with set_device_parameter.

Parameters
- name: preset name (becomes '<name>.adv' under User Library; no slashes).
- table1: factory wavetable for Osc 1 (see list_wavetable_tables, e.g.
        'Basic Shapes', 'Quad Saw', 'Logue Saw').
- table2: factory wavetable for Osc 2 (defaults to table1).
- unison_mode: name or int 0..6 — None, Classic (supersaw), Shimmer, Noise,
        Phase Sync, Position Spread, Random Note. Default 'classic'.
- voices: unison voice count 2..8 (default 7).
- amount: unison amount 0.0..1.0 (default 0.85).
- osc1_pos / osc2_pos: optional wave position 0.0..1.0 (left at default if omitted).
- osc2_on: enable Osc 2 (default True, for a 2-osc supersaw).
- track_index: if given, attempt to load the new preset onto that track.

Loading note: Live only sees a brand-new preset file after it re-indexes
the User Library (on launch, or a browser refresh) — so a first-time load
may report "written but not yet loadable". Once the name is indexed,
re-running this tool overwrites the same file and loads fresh immediately.

Returns JSON {written, path, settings, loaded, note}.

## create_simpler_instrument

```python
create_simpler_instrument(
    name: str,
    sample_path: str,
    root_key: int = 60,
    track_index: int = None,
)
```

Create a Simpler preset that loads a chosen audio file, and optionally load it.

The sample a Simpler plays is NOT in Live's automatable parameter API, so a
preset is the only way to set it via MCP. This writes a Simpler .adv into
the User Library referencing `sample_path` (Live relinks + recomputes on
load). Everything else about Simpler (filter type, ADSR, LFO, warp via the
UI) is automatable afterwards with set_device_parameter.

Parameters
- name: preset name (becomes '<name>.adv' under User Library; no slashes).
- sample_path: absolute path to a .wav or .aif/.aiff file. Other formats are
        rejected (their frame count can't be read, which would yield a
        silent zero-length sample) — convert to WAV/AIFF first.
- root_key: MIDI note the sample plays at unpitched (default 60 = C3).
- track_index: if given, load the new preset onto that track.

Returns JSON {written, path, sample, frames, sample_rate, loaded, note}.

## inspect_rack_preset

```python
inspect_rack_preset(template: str)
```

Inspect a rack preset (.adg) and report its macros and chain zones.

Reads a rack by path (a factory rack under Core Library/Racks/...) or by
name (a factory rack name, or a preset already in your User Library) and
returns its structure — the inputs you need for rename_rack_macros and
set_rack_zones. Reads only; nothing is written or loaded.

Macros are reported 1-based (matching set_rack_macro); chains 0-based
(matching get_rack_chains). key_zone/velocity_zone are null on audio-effect
and midi-effect racks (those chains have only a chain_selector_zone).

Parameters:
- template: a .adg path/glob, OR a factory/User-Library rack name.

Returns JSON {rack_type, num_visible_macros, macros:[...16...], chains:[...]}.

## clone_rack

```python
clone_rack(template: str, name: str)
```

Copy a rack preset into your User Library as a new working preset.

Racks have no blank/default template, so the rack-preset pipeline starts by
cloning an existing rack (factory or User Library). The clone becomes the
working preset that rename_rack_macros / set_rack_zones edit in place; load
the finished result later with load_preset using the returned browser_path.

The User Library category and device-folder are derived from the rack type
(instrument -> Instruments/Instrument Rack, audio_effect -> Audio Effects/
Audio Effect Rack, midi_effect -> MIDI Effects/MIDI Effect Rack, drum ->
Drums/Drum Rack).

Parameters:
- template: source rack — a .adg path/glob, or a factory/User-Library name.
- name: new preset name (becomes '<name>.adg'; no slashes or leading dot).

Returns JSON {written, path, browser_path, summary:{...inspect shape...}}.

## rename_rack_macros

```python
rename_rack_macros(
    name: str,
    macro_names: dict = None,
    macro_colors: dict = None,
    macro_defaults: dict = None,
)
```

Rename / recolor / set defaults for a User Library rack's macros, in place.

Operates on a rack preset previously created by clone_rack (the working
preset). Only the macros you list are changed; the rest keep their values.
Macro display names are NOT settable via the LOM — this preset edit is the
only MCP route. Macros are addressed 1-based (matching set_rack_macro).

Parameters:
- name: the User Library rack preset name (from clone_rack).
- macro_names: object {macro_number: "Display Name"} (no double-quote).
- macro_colors: object {macro_number: color_int} (-1..69; -1 = no color).
- macro_defaults: object {macro_number: default_float} (0..127).

The file is overwritten in place, so it reloads fresh with load_preset
without re-indexing. Returns JSON {written, path, macros:[...16...]}.

## set_rack_zones

```python
set_rack_zones(name: str, zones: list)
```

Set chain key / velocity / chain-selector zones on a User Library rack.

Operates in place on a rack created by clone_rack. Chain zones are not
settable via the LOM — this preset edit is the only MCP route. Chains are
addressed 0-based (matching get_rack_chains). key and velocity are rejected
for audio-effect / midi-effect racks (those chains only have a
chain_selector zone).

Each entry in `zones` is an object:
  {"chain": 0,
   "key": [0, 60]                 // shorthand [min,max], OR a full object:
   "velocity": {"min":0,"max":127,"crossfade_min":0,"crossfade_max":127},
   "chain_selector": [0, 63]}
Provide only the zones you want to change. Validation enforces 0..127 and
min <= crossfade_min <= crossfade_max <= max.

Returns JSON {written, path, chains:[...]}.

## add_rack_macro_mappings

```python
add_rack_macro_mappings(name: str, mappings: list)
```

Map rack macros to device parameters on a User Library rack, in place.

Macro->parameter mappings are NOT settable via the LOM — this preset edit is
the only MCP route. Operates on a rack created by clone_rack (the working
preset). Macros are addressed 1-based (matching set_rack_macro); chains
0-based (matching get_rack_chains).

Each entry in `mappings` is an object:
  {"macro": 1, "chain": 0, "device": 0, "parameter": "Gain"}
- macro: 1..16 macro number.
- parameter: the parameter's XML tag name within the device (e.g. "Gain",
        "Volume"). Use inspect-style trial or Live's device to find tag names;
        an invalid name returns an error listing the device's available tags.
- device address — either the flat single-level form:
    - chain: 0-based chain index.
    - device: 0-based device index within that chain.
  OR, to target a parameter inside a NESTED rack-in-rack, a "path" array of
  {chain, device} steps that descend one rack level each (the nested rack's
  type is auto-detected and may differ from the outer rack's). The flat form
  is equivalent to a one-step path. Example (chain 0 -> device 1 is a rack ->
  its chain 0 -> device 0):
    {"macro": 1,
     "path": [{"chain": 0, "device": 1}, {"chain": 0, "device": 0}],
     "parameter": "Frequency"}
  Supplying both "path" and flat chain/device is rejected as ambiguous.
- range (optional): {"min": <float>, "max": <float>} to make the macro sweep a
        SUB-range of the parameter instead of its full range. min/max are in
        the parameter's NATIVE units (the same units as get_device_parameters'
        min/max/value — e.g. linear amplitude, Hz, dB), NOT 0..127. Setting
        min > max INVERTS the mapping (macro-up drives the param down). Omit
        for the default full-range mapping.

Mappings are default full-range unless `range` is given. Re-mapping a
parameter replaces its existing mapping; several parameters may share one
macro. Load the result with load_preset, then verify by moving the macro
(set_rack_macro) and reading the device parameter.

Returns JSON {written, path, mappings:[...]}.

