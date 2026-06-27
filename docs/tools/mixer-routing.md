---
layout: default
title: Mixer & Routing
parent: Tools
nav_order: 7
---

# Mixer & Routing
{: .no_toc }

Volume, pan, sends, and input/output routing for every track type.

<details open markdown="block">
  <summary>Tools on this page</summary>
  {: .text-delta }
1. TOC
{:toc}
</details>

---

## get_mixer

```python
get_mixer(track_index: int, track_type: str = 'regular')
```

Read mixer state (volume, pan, mute, solo, arm, sends, crossfade assign)
for a track. Fields are present only where the track type supports them.

Parameters:
- track_index: index of the track (ignored for master; pass 0)
- track_type: "regular" (default), "return", or "master"

## set_mixer_property

```python
set_mixer_property(
    track_index: int,
    property: str,
    value: float,
    track_type: str = 'regular',
    send_index: int = -1,
)
```

Set a single mixer property on a track.

Parameters:
- track_index: index of the track (ignored for master; pass 0)
- property: one of volume, pan, mute, solo, arm, send, crossfade_assign
  (aliases accepted: panning, vol, xfade, ...)
- value: continuous params (volume/pan/send) are clamped to range;
  mute/solo/arm take 0/1; crossfade_assign takes 0=A, 1=None, 2=B
- track_type: "regular" (default), "return", or "master"
- send_index: required when property="send" (index of the return-track send)

## get_routing

```python
get_routing(track_index: int, track_type: str = 'regular')
```

Read input/output routing and input monitoring for a track. Each routing
endpoint reports its current value and the list of available choices.
Fields are present only where the track type supports them (return/master
expose output routing only; no input or monitoring).

Parameters:
- track_index: index of the track (ignored for master; pass 0)
- track_type: "regular" (default), "return", or "master"

## set_routing

```python
set_routing(
    track_index: int,
    property: str,
    value: Union[int, str],
    track_type: str = 'regular',
)
```

Set an input/output routing endpoint or input monitoring on a track.

Parameters:
- track_index: index of the track (ignored for master; pass 0)
- property: input_type, input_channel, output_type, output_channel, or monitor
- value: for routing props, the target's display_name (str, case-insensitive)
  or integer identifier (see get_routing for available choices); for monitor,
  an int (0=In, 1=Auto, 2=Off)
- track_type: "regular" (default), "return", or "master"
  (return/master support output_type/output_channel only)

