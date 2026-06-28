---
layout: default
title: Plugins (VST/AU)
parent: Tools
nav_order: 6
---

# Plugins (VST/AU)
{: .no_toc }

Expose and control third-party VST3/AU plugin parameters via the Configure-slot backdoor: probe a plugin's full parameter list, then Configure a curated param-map pack so its knobs become settable, automatable LOM parameters. For Serum 2, also author the FX racks (read, set params, bypass, insert, remove, reorder) by patching the plugin-state blob in the .als.

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

