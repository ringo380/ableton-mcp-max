---
layout: default
title: Samples
parent: Tools
nav_order: 21
---

# Samples
{: .no_toc }

Discover audio samples in Live's User Library and factory packs and load them as audio clips, single drum-rack pads, or full drum kits: search by name with automatic loop/one-shot/kit/instrument classification, and load with transparent iCloud materialization. Also includes stem separation - split a full mix into instrument stems and lay them onto the Arrangement timeline.

<details open markdown="block">
  <summary>Tools on this page</summary>
  {: .text-delta }
1. TOC
{:toc}
</details>

---

## search_samples

```python
search_samples(query: str, kinds: list = None, limit: int = 40, sources: list = None)
```

Search Live's sample library by name and return classified, ranked hits.

Filesystem-walks the User Library and/or factory Core Library sample trees,
matching `query` (space-separated terms, OR) against each file's name and
folder, classifying each hit (loop / one_shot / kit / instrument), and
returning the top `limit` by match score. READ-only: it never downloads --
it only FLAGS files that are undownloaded iCloud placeholders so a later
load knows to materialize them.

Parameters:
- query: space-separated search terms (OR). Empty string matches everything.
- kinds: restrict to these classifications (default all four:
  ["loop","one_shot","kit","instrument"]).
- limit: max results to return (default 40).
- sources: which trees to walk: ["factory","user"] (default both).

Returns JSON {ok, data:{count, returned, truncated, items:[{name, path,
uri, kind, source, folder, is_icloud_placeholder}]}}. `count` is total
matches; `items` holds at most `limit`, highest score first. `uri` is None
(loaders take `sample_path`, not a browser URI).

## load_audio_clip

```python
load_audio_clip(
    track_index: int,
    clip_index: int,
    sample_path: str,
    track_type: str = 'regular',
)
```

Load an audio sample (typically a loop) into an audio clip slot.

Materializes the file from iCloud if needed, resolves its browser URI, selects
the target slot, and loads it (Live creates an audio clip in that slot). Reads
the file header to report the clip's refined kind (a long one-shot is reported
as a loop).

Parameters:
- track_index: index of the audio track.
- clip_index: clip slot index on that track.
- sample_path: absolute path to the sample (as returned by search_samples).
- track_type: "regular" (default). Audio clips are a regular-track concept.

Returns JSON {ok, data:{track_index, clip_index, sample, uri, frames,
sample_rate, kind, loaded}}.

## load_sample_to_drum_pad

```python
load_sample_to_drum_pad(track_index: int, pad_note: int, sample_path: str)
```

Load a one-shot sample onto a single Drum Rack pad.

Materializes the file from iCloud if needed, resolves its browser URI, selects
the pad for `pad_note` (MIDI note, e.g. 36 = C1) on the track's Drum Rack, and
loads the sample so it lands on that pad.

Parameters:
- track_index: index of the track holding the Drum Rack.
- pad_note: MIDI note number of the target pad.
- sample_path: absolute path to the one-shot (as returned by search_samples).

Returns JSON {ok, data:{track_index, pad_note, sample, uri, loaded}}.

## populate_drum_rack

```python
populate_drum_rack(track_index: int, mapping: list)
```

Load many one-shot samples onto many Drum Rack pads in one call.

Loops load_sample_to_drum_pad over `mapping`. Does NOT abort on the first
failure -- each entry's result is reported so partial failures are visible.

Parameters:
- track_index: index of the track holding the Drum Rack.
- mapping: list of {pad_note, sample_path}.

Returns JSON {ok, data:{track_index, loaded_count, results:[{pad_note,
sample_path, status:"loaded"|"error", error?}]}}.

## separate_stems_to_arrangement

```python
separate_stems_to_arrangement(
    audio_path: str,
    model: str = 'htdemucs',
    fresh: bool = False,
    detect_tempo: bool = True,
    detect_key: bool = True,
    device: str = 'auto',
)
```

Split an audio file into stems and lay each onto its own Arrangement track.

Uses the Demucs CLI to separate `audio_path` into stems, optionally detects
the source tempo + key (librosa, via scripts/analyze_audio.py) and applies
them to the open set, then creates one audio track per stem and places each
stem at bar 1 of the Arrangement timeline (Warp OFF, so full-song stems stay
phase-locked). Session view is used only as transient staging; the end state
has empty session slots.

Stems are written under the Live User Library (Samples/Stems/<model>/<name>)
so Live's browser indexes them and they can be loaded; they persist there
(the Arrangement clips reference these files on disk).

Prerequisites: the `demucs` CLI on PATH and (for tempo/key) librosa in brew
Python. See the README "Stem separation" prerequisites; a clear error is
returned when demucs is missing and analysis degrades gracefully without
librosa.

Parameters:
- audio_path: absolute path to the mixed audio file.
- model: "htdemucs" (4-stem, default), "htdemucs_6s" (6-stem), or "two_stems".
- fresh: when True, bounce Live to a blank set FIRST (discards the open set).
  The CALLER must confirm with the user before passing fresh=True.
- detect_tempo / detect_key: analyze the source and set tempo / song scale.
- device: "auto" (mps on Apple Silicon, else cpu), "cpu", or "mps".

Returns JSON {ok, data:{audio, model, device, tempo, key, scale,
tempo_detected, key_detected, fresh, stems:[{name, track_index, path,
loaded}]}}.

