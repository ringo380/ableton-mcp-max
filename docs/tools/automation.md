---
layout: default
title: Automation
parent: Tools
nav_order: 13
---

# Automation
{: .no_toc }

Read and write clip automation envelopes for any automatable parameter.

<details open markdown="block">
  <summary>Tools on this page</summary>
  {: .text-delta }
1. TOC
{:toc}
</details>

---

## get_automation

```python
get_automation(
    track_index: int,
    clip_index: int,
    target_type: str = 'device',
    device_index: int = 0,
    parameter: Union[int, str] = 0,
    mixer_property: str = '',
    send_index: int = -1,
    clip_location: str = 'session',
    from_time: float = 0.0,
    time_span: float = -1.0,
    resolution: int = 16,
)
```

Read a parameter's automation envelope in a clip as evenly-spaced samples
(the Live API cannot enumerate breakpoints, only sample value_at_time).

Parameters:
- track_index, clip_index: locate the clip
- clip_location: "session" (default) or "arrangement"
- target_type: "device" (default) or "mixer"
  - device: device_index + parameter (name or index; rack macros included)
  - mixer: mixer_property in {volume, pan, send} (+ send_index for send)
- from_time/time_span: sample window in beats (time_span<0 -> whole clip)
- resolution: number of samples (>=1)
Returns has_envelope plus a samples=[{time,value}] list.

## set_automation

```python
set_automation(
    track_index: int,
    clip_index: int,
    target_type: str = 'device',
    device_index: int = 0,
    parameter: Union[int, str] = 0,
    mixer_property: str = '',
    send_index: int = -1,
    clip_location: str = 'session',
    points: List[Dict[str, Any]] = None,
    time: float = None,
    value: float = None,
    duration: float = 0.0,
)
```

Write automation breakpoints into a clip (creating the envelope if absent).

Provide EITHER a single point (time + value, optional duration) OR a
`points` list of {time, value, duration?}. duration=0 inserts a single
breakpoint; duration>0 inserts a flat step of that length. Values are
clamped to the parameter's range by Live.

Targeting is identical to get_automation (clip_location, target_type,
device/mixer fields).

## create_automation_envelope

```python
create_automation_envelope(
    track_index: int,
    clip_index: int,
    target_type: str = 'device',
    device_index: int = 0,
    parameter: Union[int, str] = 0,
    mixer_property: str = '',
    send_index: int = -1,
    clip_location: str = 'session',
)
```

Create an empty automation envelope for a parameter in a clip (no-op if one
already exists; `created` reports which). Targeting is identical to
get_automation. Note: set_automation already creates envelopes lazily; use
this only when you want an empty lane without writing points.

## clear_automation

```python
clear_automation(
    track_index: int,
    clip_index: int,
    target_type: str = 'device',
    device_index: int = 0,
    parameter: Union[int, str] = 0,
    mixer_property: str = '',
    send_index: int = -1,
    clip_location: str = 'session',
    from_time: float = None,
    time_span: float = None,
)
```

Clear a parameter's automation in a clip. Pass BOTH from_time and time_span
to clear only that range; omit both to remove the parameter's whole envelope.

Targeting is identical to get_automation.

## clear_all_automation

```python
clear_all_automation(track_index: int, clip_index: int, clip_location: str = 'session')
```

Remove every automation envelope in a clip (clip.clear_all_envelopes()).

## re_enable_automation

```python
re_enable_automation()
```

Re-enable automation that was overridden by manual control changes.

