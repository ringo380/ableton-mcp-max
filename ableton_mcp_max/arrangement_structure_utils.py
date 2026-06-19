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


def sections_from_cues(cue_list, song_end):
    """Derive section spans from a sorted list of cue dicts.

    cue_list: [{"name": str, "time": float}, ...] sorted by time.
    song_end: the end beat of the arrangement (last section ends here).

    Returns a list of {"name", "start_time", "end_time"}.
    Empty cue_list returns [].
    """
    if not cue_list:
        return []
    # Sort defensively in case caller didn't
    sorted_cues = sorted(cue_list, key=lambda c: c["time"])
    sections = []
    for i, cue in enumerate(sorted_cues):
        start = cue["time"]
        end = sorted_cues[i + 1]["time"] if i + 1 < len(sorted_cues) else song_end
        sections.append({"name": cue["name"], "start_time": start, "end_time": end})
    return sections


def _density_label(coverage):
    """Map a coverage fraction to a density label."""
    if coverage < 0.33:
        return "sparse"
    elif coverage < 0.67:
        return "medium"
    return "dense"


def _clip_overlap_beats(clip, start, end):
    """Beats of a clip that overlap [start, end)."""
    lo = max(clip["start_time"], start)
    hi = min(clip["end_time"], end)
    return max(0.0, hi - lo)


def infer_sections(clips_by_track, song_end):
    """Infer section boundaries from clip change-points across all tracks.

    clips_by_track: list of per-track clip lists; each clip has
                    {"start_time": float, "end_time": float}.
    song_end: end of the arrangement in beats.

    Collects all unique clip start/end times as potential boundaries,
    sorts them, filters to non-empty spans, and names them 'Section N'.
    Returns [] if there are no clips.
    """
    boundaries = set()
    for track_clips in clips_by_track:
        for c in track_clips:
            boundaries.add(c["start_time"])
            boundaries.add(c["end_time"])
    if not boundaries:
        return []
    # Ensure song_end is included as a boundary
    boundaries.add(song_end)
    sorted_b = sorted(boundaries)
    sections = []
    for i in range(len(sorted_b) - 1):
        start = sorted_b[i]
        end = sorted_b[i + 1]
        if end <= start:
            continue
        span_beats = end - start
        # Quick coverage estimate for density label
        covered = 0.0
        for track_clips in clips_by_track:
            for c in track_clips:
                covered += _clip_overlap_beats(c, start, end)
        raw_coverage = covered / span_beats if span_beats > 0 else 0.0
        coverage = min(1.0, raw_coverage)
        n = len(sections) + 1
        sections.append({
            "name": "Section %d" % n,
            "start_time": start,
            "end_time": end,
            "density_label": _density_label(coverage),
        })
    return sections


def section_facts(span, clips_by_track):
    """Compute per-section facts from clip geometry.

    span: {"start_time": float, "end_time": float}
    clips_by_track: list of per-track clip lists (each clip has
                    "start_time" and "end_time" in beats).

    Returns {"active_tracks": [track indices], "clip_count": int, "coverage": float}.
    coverage = average per-track coverage fraction (capped at 1.0).
    """
    start = span["start_time"]
    end = span["end_time"]
    span_beats = end - start
    active_tracks = []
    clip_count = 0
    total_coverage = 0.0
    for t_idx, track_clips in enumerate(clips_by_track):
        track_covered = 0.0
        track_active = False
        for c in track_clips:
            overlap = _clip_overlap_beats(c, start, end)
            if overlap > 0:
                track_active = True
                clip_count += 1
                track_covered += overlap
        if track_active:
            active_tracks.append(t_idx)
            per_track_cov = min(1.0, track_covered / span_beats) if span_beats > 0 else 0.0
            total_coverage += per_track_cov
    n_active = len(active_tracks)
    coverage = (total_coverage / n_active) if n_active > 0 else 0.0
    return {
        "active_tracks": active_tracks,
        "clip_count": clip_count,
        "coverage": coverage,
    }


def normalize_energy(sections):
    """Add 'energy' (0.0-1.0) to each section dict in place and return sections.

    Reads '_raw_energy' from each section (caller sets this as
    len(active_tracks) * coverage). Min-max normalizes across all sections.
    All-equal -> 0.0 for all. Modifies sections in place.
    """
    raw = [s.get("_raw_energy", 0.0) for s in sections]
    lo = min(raw)
    hi = max(raw)
    span = hi - lo
    for s, r in zip(sections, raw):
        s["energy"] = (r - lo) / span if span > 0 else 0.0
    return sections
