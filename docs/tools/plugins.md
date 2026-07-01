---
layout: default
title: Plugins (VST/AU)
parent: Tools
nav_order: 6
---

# Plugins (VST/AU)
{: .no_toc }

Expose and control third-party VST3/AU plugin parameters via the Configure-slot backdoor: probe a plugin's full parameter list, then Configure a curated param-map pack so its knobs become settable, automatable LOM parameters. For Serum 2, also author the FX racks (read, set params, bypass, insert, remove, reorder) and synthesize a full instrument patch from scratch - oscillators (params, mode, wavetable), filters, envelopes, LFOs, macros, and the mod matrix - by patching the plugin-state blob in the .als and reloading in place.

<details open markdown="block">
  <summary>Tools on this page</summary>
  {: .text-delta }
1. TOC
{:toc}
</details>

---

## probe_plugin_parameters

```python
probe_plugin_parameters(
    track_index: int,
    device_index: int,
    track_type: str = 'regular',
)
```

Read the FULL parameter-name list of a third-party VST/AU plugin device
(e.g. Serum 2) - the names Live can Configure, not just the automatable
subset visible in get_device_parameters.

A freshly loaded plugin exposes only 'Device On' as a LOM DeviceParameter;
its real knobs are reachable only after they are 'Configured'. This probe
returns every parameter name the plugin reports, so a param-map pack can be
generated and used to expose a chosen subset via expose_plugin_parameters.

Parameters:
- track_index: index of the track (ignored for master)
- device_index: index of the plugin device on that track (0 = first device)
- track_type: 'regular' (default), 'return', or 'master'

Returns JSON: device_name, class_name, parameter_count, names (ordered list;
the Configure-slot id for names[i] is id_base + i), bank_indices.

## expose_plugin_parameters

```python
expose_plugin_parameters(
    track_index: int,
    device_index: int = 0,
    pack: str = 'serum2',
    track_type: str = 'regular',
    reload: bool = True,
)
```

Expose a third-party VST/AU plugin's parameters as live, settable LOM
DeviceParameters by Configuring them via the .als backdoor.

A freshly loaded plugin (e.g. Serum 2) exposes ONLY 'Device On' to the LOM;
its real knobs become controllable only after they are 'Configured', and Live
has no API for that. This tool fills the plugin device's empty Configure slots
from a committed param-map pack, then reloads the set in place. Afterward the
exposed params are reachable by the normal get_device_parameters /
set_device_parameter (and automatable / arrangement-automatable).

The set MUST be saved to a real file first (an Untitled set errors — use
save_set_as). Live is briefly focused for the in-place reload (~5s); one MCP
call right after may transiently fail and self-heal. Regular tracks only in v1
(VST/AU instruments load on regular tracks).

Parameters:
- track_index: the track holding the plugin (regular Midi/Audio, doc order).
- device_index: device on that track (0 = first). Must be the VST/AU plugin.
- pack: param-map pack name under param_maps/ (default 'serum2'); its params
  (each a real plugin ParameterId + name) fill the Configure slots, capped at
  the 128-slot pool — any overflow is dropped and reported.
- track_type: 'regular' only in v1.
- reload: reload the set in place when done (default True). False leaves the
  patched .als on disk (reload Live yourself to see the exposed params).

Returns JSON {ok, data:{set_path, exposed_count, dropped_count, method,
reloaded, error?}}. exposed_count is how many params were Configured (fit in
the empty slots); dropped_count is pack params that didn't fit.

## get_serum_fx

```python
get_serum_fx(track_index: int, device_index: int = 0)
```

List the FX in a Serum 2 instance's three FX racks (read-only).

Saves the set, then decodes the device's plugin state from the .als on disk
(no reload). Returns JSON {ok, data:{set_path, fx:[{rack, slot, type, name,
enabled, params}]}}. params are native Serum units. State authoring only -
FX are NOT LOM-automatable knobs; use set_serum_fx_param etc. to change them.

Parameters:
- track_index: track holding the Serum 2 instance.
- device_index: which VST/AU plugin device on the track (0 = first plugin), not chain position.

## set_serum_fx_param

```python
set_serum_fx_param(
    track_index: int,
    rack: int,
    slot: int,
    kparam: str,
    value: float,
    device_index: int = 0,
    reload: bool = True,
)
```

Set one Serum FX parameter (native units) on rack (0-2) / slot.

Patches the plugin state in the .als and reloads the set in place. value is a
native Serum value (e.g. kParamWet in %, kParamFreq in Hz); validated against
the catalog's observed range. State authoring - not a live LOM knob.

Parameters:
- track_index: track holding the Serum 2 instance.
- rack: FX rack index (0, 1, or 2).
- slot: slot within the rack (0-based).
- kparam: Serum internal parameter key (e.g. "kParamWet").
- value: native Serum value; validated against catalog min/max.
- device_index: which VST/AU plugin device on the track (0 = first plugin), not chain position.
- reload: reload the set in Live after patching (default True).

Returns JSON {ok, data:{reloaded, set_path}}.

## insert_serum_fx

```python
insert_serum_fx(
    track_index: int,
    rack: int,
    index: int,
    fx_type: int,
    device_index: int = 0,
    reload: bool = True,
)
```

Insert an FX of catalog fx_type into a Serum rack (0-2) at index.

fx_type ints come from get_serum_fx / the serum2_fx catalog. New FX uses
Serum defaults (empty plainParams). State authoring (not a live LOM knob);
patches the .als and reloads the set.

Parameters:
- track_index: track holding the Serum 2 instance.
- rack: FX rack index (0, 1, or 2).
- index: position to insert at (0 = before all existing FX).
- fx_type: integer FX type from the catalog (see get_serum_fx).
- device_index: which VST/AU plugin device on the track (0 = first plugin), not chain position.
- reload: reload the set in Live after patching (default True).

Returns JSON {ok, data:{reloaded, set_path}}.

## remove_serum_fx

```python
remove_serum_fx(
    track_index: int,
    rack: int,
    slot: int,
    device_index: int = 0,
    reload: bool = True,
)
```

Remove the FX at rack (0-2) / slot from a Serum instance.

State authoring (not a live LOM knob); patches the .als and reloads the set.

Parameters:
- track_index: track holding the Serum 2 instance.
- rack: FX rack index (0, 1, or 2).
- slot: slot within the rack to remove (0-based).
- device_index: which VST/AU plugin device on the track (0 = first plugin), not chain position.
- reload: reload the set in Live after patching (default True).

Returns JSON {ok, data:{reloaded, set_path}}.

## reorder_serum_fx

```python
reorder_serum_fx(
    track_index: int,
    rack: int,
    from_index: int,
    to_index: int = 0,
    bypass: bool = None,
    device_index: int = 0,
    reload: bool = True,
)
```

Move an FX within a Serum rack (0-2), or toggle its bypass state.

If bypass is None (default), moves the FX at from_index to to_index within
the rack. If bypass is provided, instead toggles the FX at from_index:
bypass=True disables it (kParamEnable=0), bypass=False re-enables it.
State authoring (not a live LOM knob); patches the .als and reloads the set.

Parameters:
- track_index: track holding the Serum 2 instance.
- rack: FX rack index (0, 1, or 2).
- from_index: source slot (or slot to bypass when bypass is not None).
- to_index: destination slot for reorder (ignored when bypass is provided).
- bypass: if not None, enable/disable the FX instead of reordering.
- device_index: which VST/AU plugin device on the track (0 = first plugin), not chain position.
- reload: reload the set in Live after patching (default True).

Returns JSON {ok, data:{reloaded, set_path}}.

## get_serum_patch

```python
get_serum_patch(track_index: int, device_index: int = 0)
```

Read a Serum 2 instance's full instrument state (read-only).

Saves the set, decodes the device's ProcessorState from disk (no reload), and
returns a per-module summary. State authoring view - not LOM knobs.

Parameters:
- track_index: track holding the Serum 2 instance.
- device_index: which VST/AU plugin device on the track (0 = first plugin).

Returns JSON {ok, data:{set_path, oscillators, filters, envelopes, lfos, macros}}.

## set_serum_oscillator

```python
set_serum_oscillator(
    track_index: int,
    osc: int,
    params: dict = None,
    mode: str = None,
    device_index: int = 0,
    reload: bool = True,
)
```

Set Serum oscillator params (native units) and/or its mode.

Patches plugin state in the .als and reloads in place. params keys are friendly
names or raw kParam* keys; values are native, range-validated against the
catalog. mode (when given) selects the oscillator engine: 'wavetable' (default),
'multisample', 'sample', 'granular', 'spectral'.

Parameters:
- track_index: track holding the Serum 2 instance.
- osc: oscillator index (0-4).
- params: {name: native_value} dict (optional).
- mode: oscillator mode name (optional).
- device_index: which VST/AU plugin device on the track (0 = first plugin).
- reload: reload the set after patching (default True).

Returns JSON {ok, data:{reloaded, set_path}}.

## set_serum_filter

```python
set_serum_filter(
    track_index: int,
    filt: int,
    params: dict = None,
    device_index: int = 0,
    reload: bool = True,
)
```

Set Serum filter params (native units).

Patches plugin state in the .als and reloads in place. params keys are friendly
names or raw kParam* keys; values are native, range-validated against the
catalog.

Parameters:
- track_index: track holding the Serum 2 instance.
- filt: filter index.
- params: {name: native_value} dict (optional).
- device_index: which VST/AU plugin device on the track (0 = first plugin).
- reload: reload the set after patching (default True).

Returns JSON {ok, data:{reloaded, set_path}}.

## set_serum_envelope

```python
set_serum_envelope(
    track_index: int,
    env: int,
    params: dict = None,
    device_index: int = 0,
    reload: bool = True,
)
```

Set Serum envelope params (native units).

Patches plugin state in the .als and reloads in place. params keys are friendly
names or raw kParam* keys; values are native, range-validated against the
catalog.

Parameters:
- track_index: track holding the Serum 2 instance.
- env: envelope index.
- params: {name: native_value} dict (optional).
- device_index: which VST/AU plugin device on the track (0 = first plugin).
- reload: reload the set after patching (default True).

Returns JSON {ok, data:{reloaded, set_path}}.

## set_serum_lfo

```python
set_serum_lfo(
    track_index: int,
    lfo: int,
    params: dict = None,
    device_index: int = 0,
    reload: bool = True,
)
```

Set Serum LFO params (native units).

Patches plugin state in the .als and reloads in place. params keys are friendly
names or raw kParam* keys; values are native, range-validated against the
catalog.

Parameters:
- track_index: track holding the Serum 2 instance.
- lfo: LFO index.
- params: {name: native_value} dict (optional).
- device_index: which VST/AU plugin device on the track (0 = first plugin).
- reload: reload the set after patching (default True).

Returns JSON {ok, data:{reloaded, set_path}}.

## set_serum_macro

```python
set_serum_macro(
    track_index: int,
    macro: int,
    value: float,
    name: str = None,
    device_index: int = 0,
    reload: bool = True,
)
```

Set a Serum macro value (0-100) and optionally its name.

Parameters:
- track_index: track holding the Serum 2 instance.
- macro: macro index (0-7).
- value: macro value 0-100.
- name: optional macro label.
- device_index: which VST/AU plugin device on the track (0 = first plugin).
- reload: reload the set after patching (default True).

Returns JSON {ok, data:{reloaded, set_path}}.

## set_serum_wavetable

```python
set_serum_wavetable(
    track_index: int,
    osc: int,
    table: str,
    device_index: int = 0,
    reload: bool = True,
)
```

Point a Serum oscillator at a wavetable file and put it in WaveTable mode.

Writes the table path into Oscillator{osc}.WTOsc{osc}.relativePathToWT (relative
to Serum's table library, e.g. 'S2 Tables/Default Shapes.wav') and clears the
oscillator mode to WaveTable (the default). Serum loads + recomputes the table on
reload. State authoring - the table must exist in Serum's library.

Parameters:
- track_index: track holding the Serum 2 instance.
- osc: oscillator index (0-4).
- table: wavetable path relative to Serum's table library.
- device_index: which VST/AU plugin device on the track (0 = first plugin).
- reload: reload the set after patching (default True).

Returns JSON {ok, data:{reloaded, set_path}}.

## add_serum_mod_route

```python
add_serum_mod_route(
    track_index: int,
    source,
    dest_module: str,
    dest_index: int,
    dest_param: str,
    amount: float,
    device_index: int = 0,
    reload: bool = True,
)
```

Add a Serum mod-matrix route into a free ModSlot.

source is a raw integer mod-source id OR a configured friendly name from the
catalog mod_sources table (36 mapped via the live GUI oracle): env1-env4,
lfo1-lfo4, macro1-macro8, plus modwheel, aftertouch, polyaftertouch, pitchbend,
fixed, velocity, note, releasevelo, activevoices, voiceindex, voicemod1,
voicemod2, noteonrand1, noteonrand2, noteonranddiscrete, noteonalt, noteonalt2,
and the MPE sources mpex/mpey/mpez. Any unmapped source still works by raw int
id. dest is
structural: dest_module ('oscillator'|'filter'|'envelope'|
'lfo'|'wt'|'macro'|'global'), dest_index (instance), dest_param (friendly or
kParam*). amount is native (typically 0-100). Patches state + reloads in place.

Parameters:
- track_index: track holding the Serum 2 instance.
- source: int source id (or friendly name once configured).
- dest_module: destination module type.
- dest_index: destination instance index.
- dest_param: destination parameter (friendly or kParam*).
- amount: modulation amount (native).
- device_index: which VST/AU plugin device on the track (0 = first plugin).
- reload: reload the set after patching (default True).

Returns JSON {ok, data:{reloaded, set_path}}.

## clear_serum_mod_route

```python
clear_serum_mod_route(
    track_index: int,
    dest_module: str,
    dest_index: int,
    dest_param: str,
    device_index: int = 0,
    reload: bool = True,
)
```

Clear an existing Serum mod-matrix route targeting a destination param.

dest is structural: dest_module ('oscillator'|'filter'|'envelope'|'lfo'|'wt'|
'macro'|'global'), dest_index (instance), dest_param (friendly or kParam*).
Patches state + reloads in place.

Parameters:
- track_index: track holding the Serum 2 instance.
- dest_module: destination module type.
- dest_index: destination instance index.
- dest_param: destination parameter (friendly or kParam*).
- device_index: which VST/AU plugin device on the track (0 = first plugin).
- reload: reload the set after patching (default True).

Returns JSON {ok, data:{reloaded, set_path}}.

## create_serum_patch

```python
create_serum_patch(
    track_index: int,
    spec: dict,
    device_index: int = 0,
    reload: bool = True,
)
```

Build a Serum 2 patch from a single declarative spec in one reload.

spec sections (all optional; absent = untouched):
  oscillators: [{index, mode?, params?}]   filters:   [{index, params}]
  envelopes:   [{index, params}]           lfos:      [{index, params}]
  macros:      [{index, value, name?}]     wavetables:[{index, table}]
  mod_routes:  [{source, dest_module, dest_index, dest_param, amount}]
  fx:          [{rack, slot, kparam, value}]   (Serum FX setters)
Params are native, range-validated. Applies everything to one decoded tree then
reloads once.

Parameters:
- track_index: track holding the Serum 2 instance.
- spec: the patch description dict.
- device_index: which VST/AU plugin device on the track (0 = first plugin).
- reload: reload the set after patching (default True).

Returns JSON {ok, data:{reloaded, set_path, applied}}.

