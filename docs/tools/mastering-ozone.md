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

