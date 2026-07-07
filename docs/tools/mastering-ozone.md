---
layout: default
title: Mastering (Ozone)
parent: Tools
nav_order: 7
---

# Mastering (Ozone)
{: .no_toc }

Module-aware control of an iZotope Ozone 12 instance on the master track. Ozone exposes 873 host params but Ableton Configures at most 128 at once, so expose a chosen module's params into the Configure slots (patching the .als and reloading in place), then read/set them per module: EQ bands, Maximizer, Dynamics bands, and any module's params or bypass.

<details open markdown="block">
  <summary>Tools on this page</summary>
  {: .text-delta }
1. TOC
{:toc}
</details>

---

## get_ozone_modules

```python
get_ozone_modules(track_index: int, device_index: int = 0, track_type: str = 'master')
```

List an Ozone 12 instance's modules with exposed/bypassed state.

Reads the device's currently-exposed LOM params (get_device_parameters) and
reports, per Ozone module, whether any of its params are exposed and whether
its Bypass is engaged. Ozone 12 lives on the master by default.

## expose_ozone_modules

```python
expose_ozone_modules(
    track_index: int,
    modules: list,
    device_index: int = 0,
    track_type: str = 'master',
    reload: bool = True,
)
```

Configure the given Ozone 12 modules' params as settable LOM params.

Ozone exposes 873 params but Ableton Configures at most 128 at once; this
fills the device's Configure slots with the requested modules' params (in
order), reloads the set in place, and reports overflow. The set must be saved
first (save_set_as). modules: list of module keys (e.g. ["EQ","MAX","IMG"]);
see get_ozone_modules for keys.

## get_ozone_module

```python
get_ozone_module(
    track_index: int,
    module: str,
    device_index: int = 0,
    track_type: str = 'master',
)
```

Read the currently-exposed params of one Ozone 12 module (native + normalized).

## set_ozone_module_param

```python
set_ozone_module_param(
    track_index: int,
    module: str,
    role: str,
    value: float,
    band: int = None,
    section: str = None,
    native: bool = True,
    device_index: int = 0,
    track_type: str = 'master',
)
```

Set one Ozone 12 module param. role/band/section identify the param (see
get_ozone_module); value is native units by default (native=False for 0-1).
The param must be exposed first (expose_ozone_modules).

## set_ozone_module_enabled

```python
set_ozone_module_enabled(
    track_index: int,
    module: str,
    on: bool,
    device_index: int = 0,
    track_type: str = 'master',
)
```

Enable/disable an Ozone 12 module via its Bypass param (on=True -> not
bypassed). The module's Bypass must be exposed (expose_ozone_modules).

## set_ozone_eq_band

```python
set_ozone_eq_band(
    track_index: int,
    band: int,
    freq: float = None,
    gain: float = None,
    q: float = None,
    enable: float = None,
    section: str = 'stereo_main',
    device_index: int = 0,
    track_type: str = 'master',
)
```

Set an Ozone 12 EQ band (freq Hz / gain dB / q / enable) in one call.
The EQ module must be exposed first (expose_ozone_modules ["EQ"]).

## set_ozone_maximizer

```python
set_ozone_maximizer(
    track_index: int,
    threshold: float = None,
    ceiling: float = None,
    character: float = None,
    device_index: int = 0,
    track_type: str = 'master',
)
```

Set Ozone 12 Maximizer controls (threshold via input gain, output ceiling,
character). Maximizer must be exposed first (expose_ozone_modules ["MAX"]).

## set_ozone_dynamics_band

```python
set_ozone_dynamics_band(
    track_index: int,
    band: int,
    comp_threshold: float = None,
    comp_ratio: float = None,
    comp_attack: float = None,
    comp_release: float = None,
    section: str = 'stereo_main',
    device_index: int = 0,
    track_type: str = 'master',
)
```

Set an Ozone 12 Dynamics band's compressor controls in one call. Dynamics
must be exposed first (expose_ozone_modules ["DYN"]).

## get_ozone_state

```python
get_ozone_state(
    track_index: int,
    device_index: int = 0,
    track_type: str = 'master',
    module: str = None,
)
```

Read Ozone 12 params directly from the plugin state blob (native values).

Unlike get_ozone_module, this needs NO Configure/exposure and returns REAL
native units (Hz/dB, not clamped 0-1) for ANY module. Saves the set, then
decodes the device's ProcessorState from the .als on disk (no reload).

Parameters:
- track_index: track holding the Ozone 12 instance.
- device_index: which plugin device on the track (0 = first).
- track_type: 'master' (default), 'return', or 'regular'.
- module: a module name (blob-native like 'Maximizer', or a Phase 1 key like
  'MAX'). Omit for a per-module summary of the whole instance.

Returns JSON {ok, data:{set_path, module, params:[{name,type,value}]}} for one
module, or {ok, data:{set_path, modules:[{name,param_count,bypass}]}} for all.

## set_ozone_state

```python
set_ozone_state(
    track_index: int,
    changes: dict,
    device_index: int = 0,
    track_type: str = 'master',
    reload: bool = True,
)
```

Author Ozone 12 params in native units by patching the state blob.

Batch authoring: `changes` sets many params across many modules in ONE
save+patch+reload. Native units land un-clamped (unlike the Phase 1 wrappers),
with no 128-slot cap. Only changes existing params (never adds modules);
unknown module/param or a wrong type is reported in `skipped`, not silently
dropped. The set must be saved to a real file first (save_set_as).

Parameters:
- track_index: track holding the Ozone 12 instance.
- changes: {module: {param: value}}. module is blob-native ('Maximizer',
  'Dynamic EQ') or a Phase 1 key ('MAX','DYNEQ'). value is native and typed
  per the param (Float dB/Hz, Bool bypass, UInt mode); see get_ozone_state.
- device_index: which plugin device on the track (0 = first).
- track_type: 'master' (default), 'return', or 'regular'.
- reload: reload the set in place after patching (default True).

Returns JSON {ok, data:{set_path, reloaded, applied:[...], skipped:[...]}}.

## recommend_master

```python
recommend_master(
    intent: str,
    target: float = None,
    true_peak: float = -1.0,
    prefer_reuse: bool = True,
)
```

Propose an Ozone 12 mastering chain from a free-text intent + loudness
target. Picks a character bucket (transparent/warm/loud_club/punchy/bright)
and resolves the LUFS target (explicit arg > platform keyword like
spotify/apple/club > default -14). Returns a chain dict in set_ozone_state's
shape. Best-effort: if a saved master/Ozone preset in the catalog matches,
proposes reuse instead. PROPOSE ONLY - pass the returned chain to
apply_master to write it. Returns {ok, data:{intent, parsed, target,
true_peak, chain, decision, top_matches, reason, next}}.

## apply_master

```python
apply_master(
    chain: dict,
    track_index: int = 0,
    device_index: int = 0,
    track_type: str = 'master',
    deploy_tap: bool = True,
)
```

Apply a mastering chain (from recommend_master) to an Ozone 12 instance in
one shot, then set up the live trim loop. Writes the chain via set_ozone_state
(one reload, un-clamped native values), exposes the Maximizer so the skill can
nudge ceiling/gain without further reloads, and deploys a master tap so
measure_loudness has post-fader audio. Errors clearly if the target device is
not Ozone 12. Returns {ok, data:{applied, skipped, reloaded, exposed, tap,
target, next}}. deploy_tap=False skips the tap (loop then runs un-metered).

