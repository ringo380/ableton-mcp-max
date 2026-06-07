---
layout: default
title: Tracks
parent: Tools
nav_order: 2
---

# Tracks
{: .no_toc }

Create, name, fold, duplicate, and delete tracks - plus global undo/redo.

<details open markdown="block">
  <summary>Tools on this page</summary>
  {: .text-delta }
1. TOC
{:toc}
</details>

---

## get_track_info

```python
get_track_info(track_index: int)
```

Get detailed information about a specific track in Ableton.

Parameters:
- track_index: The index of the track to get information about

## set_track_name

```python
set_track_name(track_index: int, name: str)
```

Set the name of a track.

Parameters:
- track_index: The index of the track to rename
- name: The new name for the track

## set_track_fold

```python
set_track_fold(track_index: int, folded: Union[bool, int, str])
```

Fold or unfold a group track (collapse/expand its contained tracks).

Parameters:
- track_index: index of the (regular) track; must be a group track (foldable)
- folded: true to fold (collapse), false to unfold (true/false, on/off, 1/0)

Rejected cleanly if the track is not a group track.

## create_midi_track

```python
create_midi_track(index: int = -1)
```

Create a new MIDI track in the Ableton session.

Parameters:
- index: The index to insert the track at (-1 = end of list)

## create_audio_track

```python
create_audio_track(index: int = -1)
```

Create a new audio track.

Parameters:
- index: Insert position (-1 = end of list)

## create_return_track

```python
create_return_track()
```

Create a new return track (added at the end of the return-track list).

## delete_track

```python
delete_track(index: int)
```

Delete the regular (audio/MIDI) track at the given index. Remaining tracks
re-index; re-read get_session_info afterward.

Parameters:
- index: The index of the track to delete

## delete_return_track

```python
delete_return_track(index: int)
```

Delete the return track at the given index. Remaining return tracks
re-index; re-read get_session_info afterward.

Parameters:
- index: The index of the return track to delete

## duplicate_track

```python
duplicate_track(index: int)
```

Duplicate the regular track at the given index. Live inserts the copy and
selects it; the returned new_index is the copy's position.

Parameters:
- index: The index of the track to duplicate

## undo

```python
undo()
```

Undo the last action. WARNING: this walks Live's GLOBAL undo stack — it can
undo actions the user performed by hand, not just MCP changes. No-op (clean
result) if there is nothing to undo.

## redo

```python
redo()
```

Redo the last undone action. Operates on Live's global undo stack. No-op
(clean result) if there is nothing to redo.

