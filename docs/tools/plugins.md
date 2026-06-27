---
layout: default
title: Plugins (VST/AU)
parent: Tools
nav_order: 6
---

# Plugins (VST/AU)
{: .no_toc }

Expose and control third-party VST3/AU plugin parameters via the Configure-slot backdoor: probe a plugin's full parameter list, then Configure a curated param-map pack so its knobs become settable, automatable LOM parameters.

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

