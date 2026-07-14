---
layout: default
title: Export
parent: Tools
nav_order: 24
---

# Export
{: .no_toc }

Bounce the set's Main output to an audio file on disk - format, bit depth, sample rate, and bar range under program control - by driving Live's Export Audio/Video dialog (there is no LOM render API).

<details open markdown="block">
  <summary>Tools on this page</summary>
  {: .text-delta }
1. TOC
{:toc}
</details>

---

## render_audio

```python
render_audio(
    name: str,
    start_bar: Optional[int] = None,
    end_bar: Optional[int] = None,
    file_type: str = 'WAV',
    bit_depth: int = 24,
    sample_rate: int = 44100,
    normalize: bool = False,
    mp3: bool = False,
    mono: bool = False,
    include_returns: bool = True,
    analysis_file: bool = True,
    dither: str = 'No Dither',
    timeout: float = 600.0,
)
```

Bounce the set's Main output to an audio file on disk (there is no LOM
render API - this drives Live's Export Audio/Video dialog via System Events,
so Live needs Accessibility permission; it briefly focuses Live and switches
it to the Arrangement view).

name: the file name (not a path; may not contain '/' or ':'). Re-using a
  name overwrites the existing file (the panel's Replace prompt is confirmed).
start_bar / end_bar: 1-based bar range, end EXCLUSIVE (5..13 = 8 bars). Pass
  neither to render the whole song. The range is applied by setting the
  arrangement loop and selecting it - the dialog's own range sliders are not
  writable. The loop brace is restored afterwards, but Live is LEFT IN THE
  ARRANGEMENT VIEW and the arrangement TIME SELECTION is left on the rendered
  range (the LOM cannot restore a time selection).
file_type: WAV | AIFF | FLAC | MP3. bit_depth: 16 | 24 | 32.
sample_rate: 44100 | 48000 | 88200 | 96000 | 176400 | 192000.
mp3: also emit an MP3 alongside a PCM file_type.
dither: No Dither | Triangular | Rectangular | POW-r 1 | POW-r 2 | POW-r 3.
timeout: seconds to wait for the render to finish (a full track takes real
  time; the tool polls, it never sleeps a fixed amount).

The output DIRECTORY is Live's last-used export location and is not
controllable; 'path' is resolved afterwards via Spotlight and may be null
even on a successful render (the file exists, we just could not locate it).

Returns JSON {ok, data:{name, path, extra_paths, bytes, duration_s,
file_type, bit_depth, sample_rate, range, rendered}}.

