"""Server-side pure utilities for arrangement structure analysis and building.

No Live dependency - imported by server.py only.
"""


def bars_to_beats(bars, num, den):
    """Convert bar count to beats given a time signature.

    bars_to_beats(4, 4, 4) -> 16.0  (4/4: 4 beats per bar)
    bars_to_beats(2, 6, 8) -> 6.0   (6/8: 3 beats per bar)
    bars_to_beats(1, 3, 4) -> 3.0   (3/4: 3 beats per bar)
    """
    if num <= 0 or den <= 0:
        raise ValueError("Time signature numerator and denominator must be positive")
    beats_per_bar = num * (4.0 / den)
    return float(bars) * beats_per_bar


def compute_section_starts(sections, start_bar, num, den):
    """Compute cumulative start beats for each section.

    Returns a new list of dicts with 'start_beat' and 'length_beats' added
    (originals preserved). start_bar is 1-indexed (bar 1 = beat 0.0).

    sections = [{"length_bars": 8, ...}, {"length_bars": 16, ...}]
    compute_section_starts(sections, start_bar=1, num=4, den=4)
    -> [{"length_bars": 8, "start_beat": 0.0, "length_beats": 32.0, ...},
        {"length_bars": 16, "start_beat": 32.0, "length_beats": 64.0, ...}]
    """
    beats_per_bar = num * (4.0 / den)
    # bar 1 = beat 0.0; bar N = beat (N-1) * beats_per_bar
    cursor = (start_bar - 1) * beats_per_bar
    result = []
    for s in sections:
        lb = float(s["length_bars"])
        length_beats = lb * beats_per_bar
        out = dict(s)
        out["start_beat"] = cursor
        out["length_beats"] = length_beats
        result.append(out)
        cursor += length_beats
    return result


def validate_section_map(sections):
    """Validate a section map before any mutation.

    Raises ValueError with a descriptive message on the first problem found:
    - sections is empty or not a list
    - any section missing 'name' or 'length_bars'
    - name is not a non-empty string
    - length_bars is not a positive number
    - clips key present but not a list
    - any clip entry missing track_index or source_slot_index
    - track_index / source_slot_index not non-negative ints
    - repeat not 'fill' or a positive int
    """
    if not isinstance(sections, list) or len(sections) == 0:
        raise ValueError("sections must be a non-empty list")
    for i, s in enumerate(sections):
        if not isinstance(s, dict):
            raise ValueError("sections[%d] must be a dict" % i)
        name = s.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("sections[%d]['name'] must be a non-empty string" % i)
        lb = s.get("length_bars")
        if lb is None:
            raise ValueError("sections[%d] missing 'length_bars'" % i)
        try:
            lb_f = float(lb)
        except (TypeError, ValueError):
            raise ValueError("sections[%d]['length_bars'] must be a number" % i)
        if lb_f <= 0:
            raise ValueError(
                "sections[%d]['length_bars'] must be positive, got %s" % (i, lb))
        clips = s.get("clips")
        if clips is None:
            continue
        if not isinstance(clips, list):
            raise ValueError("sections[%d]['clips'] must be a list" % i)
        for j, c in enumerate(clips):
            if not isinstance(c, dict):
                raise ValueError(
                    "sections[%d]['clips'][%d] must be a dict" % (i, j))
            for key in ("track_index", "source_slot_index"):
                v = c.get(key)
                if v is None:
                    raise ValueError(
                        "sections[%d]['clips'][%d] missing '%s'" % (i, j, key))
                if not isinstance(v, int) or v < 0:
                    raise ValueError(
                        "sections[%d]['clips'][%d]['%s'] must be a "
                        "non-negative int" % (i, j, key))
            repeat = c.get("repeat", "fill")
            if repeat != "fill":
                if not isinstance(repeat, int) or repeat <= 0:
                    raise ValueError(
                        "sections[%d]['clips'][%d]['repeat'] must be 'fill' or "
                        "a positive int" % (i, j))


def tiling_plan(section_beats, clip_length, repeat):
    """Return a list of beat offsets at which to place the clip.

    repeat='fill': floor(section_beats / clip_length) copies at
                   0, clip_length, 2*clip_length, ...
                   A clip longer than the section yields [0.0] (one copy).
    repeat=N (int): exactly N copies regardless of section length.

    Raises ValueError if clip_length <= 0.
    """
    if clip_length <= 0:
        raise ValueError("clip_length must be positive, got %s" % clip_length)
    if repeat == "fill":
        n = max(1, int(section_beats / clip_length))
    elif isinstance(repeat, int) and repeat > 0:
        n = repeat
    else:
        raise ValueError(
            "repeat must be 'fill' or a positive int, got %r" % (repeat,))
    return [float(i) * clip_length for i in range(n)]


def sections_from_cues(cue_points, total_beats, default_name="Section"):
    """Derive sections from a list of cue point dicts.

    cue_points: list of dicts with at least 'time' (beat position) and
                optionally 'name'. Unsorted input is sorted by time.
    total_beats: end boundary of the last section.
    default_name: prefix used when a cue has no name.

    Returns a list of dicts with 'name', 'start_beat', 'length_beats'.
    Returns [] if cue_points is empty.
    """
    if not cue_points:
        return []
    sorted_cues = sorted(cue_points, key=lambda c: c["time"])
    result = []
    for idx, cue in enumerate(sorted_cues):
        start = cue["time"]
        end = sorted_cues[idx + 1]["time"] if idx + 1 < len(sorted_cues) else total_beats
        name = cue.get("name") or ("%s %d" % (default_name, idx + 1))
        result.append({
            "name": name,
            "start_beat": float(start),
            "length_beats": float(end - start),
        })
    return result


def infer_sections(clip_list, num, den, gap_bars=2):
    """Group arrangement clips into sections based on timing gaps.

    clip_list: list of dicts with 'start_beat' and 'length_beats'.
               Unsorted input is sorted by start_beat.
    num, den: time signature (used to convert gap threshold to beats).
    gap_bars: a silence gap >= this many bars starts a new section.

    Returns a list of section dicts:
      {"start_beat": float, "length_beats": float, "clip_count": int}
    Returns [] for empty input.
    """
    if not clip_list:
        return []
    gap_beats = bars_to_beats(gap_bars, num, den)
    clips = sorted(clip_list, key=lambda c: c["start_beat"])
    sections = []
    sec_start = clips[0]["start_beat"]
    sec_end = clips[0]["start_beat"] + clips[0]["length_beats"]
    count = 1
    for clip in clips[1:]:
        c_start = clip["start_beat"]
        c_end = c_start + clip["length_beats"]
        if c_start - sec_end >= gap_beats:
            sections.append({
                "start_beat": float(sec_start),
                "length_beats": float(sec_end - sec_start),
                "clip_count": count,
            })
            sec_start = c_start
            sec_end = c_end
            count = 1
        else:
            sec_end = max(sec_end, c_end)
            count += 1
    sections.append({
        "start_beat": float(sec_start),
        "length_beats": float(sec_end - sec_start),
        "clip_count": count,
    })
    return sections


def section_facts(section, num, den):
    """Return a summary dict for a single section.

    section: dict with at least 'start_beat' and 'length_beats'.
    num, den: time signature for bar conversion.

    Returns:
      {
        "start_beat": float,
        "length_beats": float,
        "start_bar": float,   # 1-indexed
        "length_bars": float,
      }
    """
    beats_per_bar = num * (4.0 / den)
    start = float(section["start_beat"])
    length = float(section["length_beats"])
    return {
        "start_beat": start,
        "length_beats": length,
        "start_bar": start / beats_per_bar + 1.0,
        "length_bars": length / beats_per_bar,
    }


def normalize_energy(values):
    """Normalize a list of numeric energy values to the [0.0, 1.0] range.

    If all values are identical (including a single-element list), returns
    a list of 0.0s (no meaningful range to normalize).
    Returns [] for empty input.
    """
    if not values:
        return []
    lo = min(values)
    hi = max(values)
    if hi == lo:
        return [0.0] * len(values)
    span = hi - lo
    return [(v - lo) / span for v in values]
