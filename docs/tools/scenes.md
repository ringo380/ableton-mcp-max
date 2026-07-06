---
layout: default
title: Scenes
parent: Tools
nav_order: 9
---

# Scenes
{: .no_toc }

Create, launch, rename, and capture scenes in the Session view.

<details open markdown="block">
  <summary>Tools on this page</summary>
  {: .text-delta }
1. TOC
{:toc}
</details>

---

## get_scenes

```python
get_scenes()
```

List all scenes in the session (index, name, color, tempo, time signature,
is_empty, is_triggered).

## fire_scene

```python
fire_scene(scene_index: int)
```

Launch a scene (fires every clip in that session row).

Parameters:
- scene_index: The index of the scene to fire

## create_scene

```python
create_scene(scene_index: int = None, index: int = None)
```

Create a new scene.

Parameters:
- scene_index: Position to insert at; -1 (default) appends at the end.
  (`index` is accepted as a legacy alias.)

## delete_scene

```python
delete_scene(scene_index: int)
```

Delete a scene.

Parameters:
- scene_index: The index of the scene to delete

## duplicate_scene

```python
duplicate_scene(scene_index: int)
```

Duplicate a scene (the copy is inserted directly after it).

Parameters:
- scene_index: The index of the scene to duplicate

## set_scene_name

```python
set_scene_name(scene_index: int, name: str)
```

Rename a scene.

Parameters:
- scene_index: The index of the scene
- name: The new name

## set_scene_property

```python
set_scene_property(scene_index: int, property: str, value: Union[int, float, str])
```

Set a scene property.

Parameters:
- scene_index: The index of the scene
- property: One of 'color', 'tempo', 'tempo_enabled', 'time_signature'
  (aliases accepted: colour, bpm, tempo_on, time_sig/signature)
- value: color int; tempo BPM (clamped 20-999); tempo_enabled on/off;
  time_signature as 'num/den' (e.g. '6/8')

## capture_and_insert_scene

```python
capture_and_insert_scene(mode: str = 'all')
```

Capture the currently playing clips and insert them as a new scene after the
selected scene. Needs clips currently playing.

Parameters:
- mode: "all" (the only Live.Song.CaptureMode value).

Note: confirm the new scene via get_scenes (song-property-write lag). Raises a
runtime error if creating the scene would exceed Live's limitations.

