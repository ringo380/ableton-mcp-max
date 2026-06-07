---
layout: default
title: Session & View
parent: Tools
nav_order: 1
---

# Session & View
{: .no_toc }

Read the live set, move the selection, and steer what Live shows on screen.

<details open markdown="block">
  <summary>Tools on this page</summary>
  {: .text-delta }
1. TOC
{:toc}
</details>

---

## get_session_info

```python
get_session_info()
```

Get detailed information about the current Ableton session

## get_view_selection

```python
get_view_selection()
```

Read the current Live view selection: selected track (index/name/type),
selected scene (index), whether a detail clip is shown, and the highlighted
Session clip slot (track + scene coordinates).

## set_selected_track

```python
set_selected_track(track_index: int, track_type: str = 'regular')
```

Select a track in the Session/Arrangement view.

Parameters:
- track_index: index within its collection (0-based)
- track_type: "regular" (default), "return", or "master" (master ignores index)

## set_selected_scene

```python
set_selected_scene(scene_index: int)
```

Select a scene in the Session view.

Parameters:
- scene_index: index of the scene (0-based)

## set_detail_clip

```python
set_detail_clip(track_index: int, clip_slot_index: int)
```

Show a Session clip in Live's Detail (clip) view.

Parameters:
- track_index: index of the (regular) track
- clip_slot_index: index of the clip slot; the slot must contain a clip

## set_highlighted_clip_slot

```python
set_highlighted_clip_slot(track_index: int, scene_index: int)
```

Highlight a Session clip slot (defined by a regular track + scene).

Parameters:
- track_index: index of the (regular) track
- scene_index: index of the scene (the clip slot row)

