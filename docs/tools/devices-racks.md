---
layout: default
title: Devices & Racks
parent: Tools
nav_order: 5
---

# Devices & Racks
{: .no_toc }

Inspect and drive devices, rack macros, and chains; load instruments and effects.

<details open markdown="block">
  <summary>Tools on this page</summary>
  {: .text-delta }
1. TOC
{:toc}
</details>

---

## get_device_parameters

```python
get_device_parameters(track_index: int, device_index: int)
```

List all automatable parameters of a device on a track, with current
value, min, max, whether it's quantized, and (for quantized params) the
list of selectable value items.

Parameters:
- track_index: index of the track
- device_index: index of the device on that track (0 = first device)

## set_device_parameter

```python
set_device_parameter(
    track_index: int,
    device_index: int,
    parameter: Union[int, str],
    value: float,
)
```

Set a single device/instrument parameter.

Parameters:
- track_index: index of the track
- device_index: index of the device on that track
- parameter: parameter index (int) OR parameter name (str, case-insensitive)
- value: target value (clamped to the parameter's min/max). For quantized
  parameters, pass the integer index of the desired value item.

## get_device_info

```python
get_device_info(track_index: int, device_index: int, track_type: str = 'regular')
```

Get detailed info about a device: class, type, on/off state, whether it is
a rack (can_have_chains) or drum rack (can_have_drum_pads), and a summary of
its macros and chains when it is a rack.

Parameters:
- track_index: index of the track
- device_index: index of the device on that track (0 = first device)
- track_type: 'regular' (default), 'return', or 'master'

## delete_device

```python
delete_device(track_index: int, device_index: int, track_type: str = 'regular')
```

Delete a device from a track. Remaining devices re-index downward.

Parameters:
- track_index: index of the track
- device_index: index of the device to delete
- track_type: 'regular' (default), 'return', or 'master'

## set_device_on

```python
set_device_on(
    track_index: int,
    device_index: int,
    on: Union[bool, int, str],
    track_type: str = 'regular',
)
```

Enable or disable a device (writes its 'Device On' parameter).

Parameters:
- track_index: index of the track
- device_index: index of the device
- on: true/false (also accepts on/off, 1/0, yes/no)
- track_type: 'regular' (default), 'return', or 'master'

## get_rack_macros

```python
get_rack_macros(track_index: int, device_index: int, track_type: str = 'regular')
```

List the macro controls of a rack device, each with its name, current value,
min, max, and the underlying device-parameter index.

Parameters:
- track_index: index of the track
- device_index: index of the rack device
- track_type: 'regular' (default), 'return', or 'master'

## set_rack_macro

```python
set_rack_macro(
    track_index: int,
    device_index: int,
    macro: Union[int, str],
    value: float,
    track_type: str = 'regular',
)
```

Set a rack macro control value.

Parameters:
- track_index: index of the track
- device_index: index of the rack device
- macro: macro number (1-based int, e.g. 3) OR macro name (e.g. 'Macro 3')
- value: target value (clamped to the macro's min/max, typically 0..127)
- track_type: 'regular' (default), 'return', or 'master'

## get_rack_chains

```python
get_rack_chains(track_index: int, device_index: int, track_type: str = 'regular')
```

List the chains of a rack device, each with its name, mute/solo state, and
the devices it contains.

Parameters:
- track_index: index of the track
- device_index: index of the rack device
- track_type: 'regular' (default), 'return', or 'master'

## set_chain_property

```python
set_chain_property(
    track_index: int,
    device_index: int,
    chain_index: int,
    property: str,
    value: Union[bool, int, float, str],
    track_type: str = 'regular',
)
```

Set a property on one chain of a rack device.

Parameters:
- track_index: index of the track
- device_index: index of the rack device
- chain_index: index of the chain within the rack (0 = first)
- property: 'mute' or 'solo' (bool) or 'volume' / 'panning' (float, clamped)
- value: bool for mute/solo; float for volume/panning
- track_type: 'regular' (default), 'return', or 'master'

## load_instrument_or_effect

```python
load_instrument_or_effect(track_index: int, uri: str)
```

Load an instrument or effect onto a track using its URI.

Parameters:
- track_index: The index of the track to load the instrument on
- uri: The URI of the instrument or effect to load (e.g., 'query:Synths#Instrument%20Rack:Bass:FileId_5116')

