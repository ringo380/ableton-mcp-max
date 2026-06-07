---
layout: default
title: Listeners
parent: Tools
nav_order: 12
---

# Listeners
{: .no_toc }

Subscribe to real-time Live Object Model changes and poll for events.

<details open markdown="block">
  <summary>Tools on this page</summary>
  {: .text-delta }
1. TOC
{:toc}
</details>

---

## register_listener

```python
register_listener(
    scope: str,
    property: str,
    track_index: int = None,
    track_type: str = 'regular',
    device_index: int = None,
    parameter: Union[int, str] = None,
    clip_index: int = None,
    scene_index: int = None,
)
```

Attach a change listener to a Live object and start buffering its events.
Returns a listener_id to use with poll_changes / unregister_listener.

scope + property:
- transport: is_playing, current_song_time, tempo, metronome, record_mode,
  session_record, loop  (current_song_time fires continuously during
  playback — expect high event volume / dropped counts).
- mixer (needs track_index, optional track_type regular|return|master):
  volume, pan, mute, solo, arm  (arm is regular-track only).
- clip: playing_status, name, notes, has_clip (need track_index + clip_index);
  selected_scene (no selectors — observes the song view).
- device: value (needs track_index, device_index, parameter name-or-index).

Events are read on demand via poll_changes; nothing is pushed.

## poll_changes

```python
poll_changes(listener_id: str = None, max_events: int = None)
```

Drain buffered change events. Omit listener_id to drain all listeners;
pass one to drain just that listener. max_events caps the count returned
per listener (oldest first); omit for all pending.

Each event: {listener_id, target, property, value, seq}. Per-listener
`dropped` counts events evicted because the buffer overflowed since the
last poll (poll often if a target is high-volume).

## unregister_listener

```python
unregister_listener(listener_id: str = None)
```

Detach a listener and discard its buffer. Omit listener_id to remove ALL
active listeners. Always detach listeners you no longer need.

## list_listeners

```python
list_listeners()
```

List active change listeners with each one's target plus its buffer's
pending and dropped event counts.

