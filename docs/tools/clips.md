---
layout: default
title: Clips
parent: Tools
nav_order: 3
---

# Clips
{: .no_toc }

Create and manage session clips: properties, loop, quantize, launch, and stop.

<details open markdown="block">
  <summary>Tools on this page</summary>
  {: .text-delta }
1. TOC
{:toc}
</details>

---

## create_clip

```python
create_clip(track_index: int, clip_index: int, length: float = 4.0)
```

Create a new MIDI clip in the specified track and clip slot.

Parameters:
- track_index: The index of the track to create the clip in
- clip_index: The index of the clip slot to create the clip in
- length: The length of the clip in beats (default: 4.0)

## set_clip_name

```python
set_clip_name(track_index: int, clip_index: int, name: str)
```

Set the name of a clip.

Parameters:
- track_index: The index of the track containing the clip
- clip_index: The index of the clip slot containing the clip
- name: The new name for the clip

## get_clip_info

```python
get_clip_info(track_index: int, clip_index: int)
```

Read properties of a clip. Audio-only fields (warping, warp_mode, gain,
gain_display_string, pitch_coarse, pitch_fine) appear only on audio clips.

Parameters:
- track_index: index of the track containing the clip
- clip_index: index of the clip slot containing the clip

## set_clip_property

```python
set_clip_property(
    track_index: int,
    clip_index: int,
    property: str,
    value: Union[int, float, str, bool],
    clip_location: str = 'session',
)
```

Set a single clip property. Audio-only properties are rejected on MIDI clips.

Parameters:
- track_index / clip_index: locate the clip
- clip_location: "session" (default; clip_index is the clip slot) or
  "arrangement" (clip_index indexes get_arrangement_clips). Moving an
  arrangement clip's start_marker shifts which part of the audio plays at
  the clip's position without adding warp markers.
- property: one of looping, loop_start, loop_end, start_marker, end_marker,
  signature_numerator, signature_denominator, warping, warp_mode, gain,
  pitch_coarse, pitch_fine, and the launch settings launch_mode,
  launch_quantization, legato, velocity_amount (valid on MIDI and audio).
  Aliases accepted: loop, pitch, detune, warp, launchmode, launchquant, velamount, ...
- value: bools take 0/1/true/false; gain is 0.0-1.0 (clamped); pitch_coarse
  is -48..48 semitones, pitch_fine -50..50 cents (clamped); launch_mode (int
  0=Trigger,1=Gate,2=Toggle,3=Repeat) and launch_quantization (int) are enum
  indices; legato is a bool; velocity_amount is a float; others are
  floats/ints. To edit the loop window safely use set_clip_loop instead.

## set_clip_loop

```python
set_clip_loop(
    track_index: int,
    clip_index: int,
    loop_start: float,
    loop_end: float,
    looping: int = -1,
)
```

Set a clip's loop window (both edges written in the correct order to avoid an
invalid intermediate state) and optionally toggle looping.

Parameters:
- track_index / clip_index: locate the clip
- loop_start / loop_end: loop bounds in beats (loop_end must exceed loop_start)
- looping: -1 (default) leaves looping unchanged; 0 disables, 1 enables

## quantize_clip

```python
quantize_clip(track_index: int, clip_index: int, grid: str, amount: float = 1.0)
```

Quantize the notes of a MIDI clip to a grid (MIDI clips only).

Parameters:
- track_index / clip_index: locate the clip
- grid: one of none, 1/4, 1/8, 1/8t, 1/8+1/8t, 1/16, 1/16t,
  1/16+1/16t, 1/32
- amount: quantization strength 0.0-1.0 (default 1.0 = full snap)

## duplicate_clip

```python
duplicate_clip(track_index: int, clip_index: int, target_clip_index: int = -1)
```

Duplicate a clip into another clip slot on the same track (no scene inserted).

Parameters:
- track_index / clip_index: locate the source clip
- target_clip_index: destination slot; -1 (default) = clip_index + 1. The
  target slot must be empty.

## delete_clip

```python
delete_clip(track_index: int, clip_index: int)
```

Delete the clip in a clip slot (the slot itself remains, now empty).

Parameters:
- track_index / clip_index: locate the clip

## fire_clip

```python
fire_clip(track_index: int, clip_index: int)
```

Start playing a clip.

Parameters:
- track_index: The index of the track containing the clip
- clip_index: The index of the clip slot containing the clip

## stop_clip

```python
stop_clip(track_index: int, clip_index: int)
```

Stop playing a clip.

Parameters:
- track_index: The index of the track containing the clip
- clip_index: The index of the clip slot containing the clip

## set_clip_trigger_quantization

```python
set_clip_trigger_quantization(value: Union[int, str])
```

Set the global Session clip-launch quantization.

Parameters:
- value: an int 0-13 (Live.Song.Quantization) or a name: none, 8_bars,
  4_bars, 2_bars, 1_bar, 1/2, 1/2t, 1/4, 1/4t, 1/8, 1/8t, 1/16, 1/16t, 1/32.

Note: confirm via get_transport (song-property-write lag).

