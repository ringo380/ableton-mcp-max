# Arrangement Intelligence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `get_arrangement_structure` and `build_arrangement` tools that read/write a song's section layout using cue points and arrangement clips.

**Architecture:** A new pure server-side module `arrangement_structure_utils.py` holds all bar/beat math, cue-span derivation, clip-layout inference, and tiling logic (fully unit-testable, no Live dependency). Two new `@mcp.tool()` functions in `server.py` under the existing `# === Arrangement ===` section compose existing `send_command` calls (no new Remote Script commands). `get_arrangement_structure` calls `get_transport`, `get_cue_points`, and `get_arrangement_clips` per track, then derives sections + facts server-side. `build_arrangement` validates input, computes section start beats, tiles Session clips onto the timeline via `duplicate_clip_to_arrangement`, and optionally writes locators via the existing `create_cue_point` orchestration.

**Tech Stack:** Python 3.8+, FastMCP, pytest. No new dependencies.

## Global Constraints

- Pure utils (`arrangement_structure_utils.py`) must have zero Live/MCP imports - no `import Live`, no `from ableton_mcp_max.server import ...`. Server-only.
- Remote Script (`remote_script/AbletonMCP/__init__.py`) must NOT be modified - both tools are server-side compositions of existing commands.
- Py2/3.7-safe syntax applies only to the Remote Script (unchanged here). Server utils use Python 3.8+.
- No f-strings in the Remote Script (unchanged). Server code may use f-strings.
- No ruff reformatting of unrelated code - only touch what is required.
- Test commands: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q`
- Server import check: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python -c "import ableton_mcp_max.server"`
- RS compile check: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python -m py_compile remote_script/AbletonMCP/__init__.py`
- Full suite baseline: 566 tests passed. Stay green.
- Bar convention: 1-indexed (bar 1 = beat 0.0), matching Live's UI.
- Beats per bar formula: `num * (4.0 / den)` where num/den come from `signature_numerator` / `signature_denominator` in `get_transport`.
- Tool count will go 126 -> 128. Hardcoded counts in `docs/index.md` and `README.md` must be updated.

---

### Task 1: Pure utils - bar/beat math and validation

**Files:**
- Create: `ableton_mcp_max/arrangement_structure_utils.py`
- Create: `tests/test_arrangement_structure_utils.py`

**Interfaces:**
- Produces:
  - `bars_to_beats(bars: float, num: int, den: int) -> float`
  - `compute_section_starts(sections: list[dict], start_bar: int, num: int, den: int) -> list[dict]` where each input dict has `length_bars` and each output dict adds `start_beat` and `length_beats`
  - `validate_section_map(sections: list[dict]) -> None` (raises `ValueError` with a clear message)
  - `tiling_plan(section_beats: float, clip_length: float, repeat) -> list[float]` where `repeat` is `"fill"` or a positive int; returns a list of beat offsets

- [ ] **Step 1: Create the utils module with `bars_to_beats` and `compute_section_starts`**

```python
# ableton_mcp_max/arrangement_structure_utils.py
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
```

- [ ] **Step 2: Write tests for `bars_to_beats` and `compute_section_starts`**

```python
# tests/test_arrangement_structure_utils.py
import pytest
from ableton_mcp_max.arrangement_structure_utils import (
    bars_to_beats,
    compute_section_starts,
    validate_section_map,
    tiling_plan,
    sections_from_cues,
    infer_sections,
    section_facts,
    normalize_energy,
)


# --- bars_to_beats --------------------------------------------------------

def test_bars_to_beats_4_4():
    assert bars_to_beats(4, 4, 4) == 16.0

def test_bars_to_beats_6_8():
    # 6/8: beats_per_bar = 6 * (4/8) = 3.0
    assert bars_to_beats(2, 6, 8) == 6.0

def test_bars_to_beats_3_4():
    assert bars_to_beats(1, 3, 4) == 3.0

def test_bars_to_beats_fractional():
    assert bars_to_beats(0.5, 4, 4) == 2.0

def test_bars_to_beats_invalid_num():
    with pytest.raises(ValueError):
        bars_to_beats(4, 0, 4)

def test_bars_to_beats_invalid_den():
    with pytest.raises(ValueError):
        bars_to_beats(4, 4, 0)


# --- compute_section_starts -----------------------------------------------

def test_compute_section_starts_basic_4_4():
    sections = [{"name": "Intro", "length_bars": 4},
                {"name": "Verse", "length_bars": 8}]
    result = compute_section_starts(sections, start_bar=1, num=4, den=4)
    assert result[0]["start_beat"] == 0.0
    assert result[0]["length_beats"] == 16.0
    assert result[1]["start_beat"] == 16.0
    assert result[1]["length_beats"] == 32.0

def test_compute_section_starts_start_bar_offset():
    # start_bar=3 means bar 3 = beat 8.0 in 4/4
    sections = [{"name": "A", "length_bars": 4}]
    result = compute_section_starts(sections, start_bar=3, num=4, den=4)
    assert result[0]["start_beat"] == 8.0

def test_compute_section_starts_6_8():
    sections = [{"name": "A", "length_bars": 2}]
    result = compute_section_starts(sections, start_bar=1, num=6, den=8)
    assert result[0]["length_beats"] == 6.0

def test_compute_section_starts_preserves_original_keys():
    sections = [{"name": "Intro", "length_bars": 4, "clips": []}]
    result = compute_section_starts(sections, start_bar=1, num=4, den=4)
    assert result[0]["clips"] == []
    assert result[0]["name"] == "Intro"

def test_compute_section_starts_does_not_mutate_input():
    sections = [{"length_bars": 4}]
    compute_section_starts(sections, start_bar=1, num=4, den=4)
    assert "start_beat" not in sections[0]
```

- [ ] **Step 3: Run those tests to confirm they FAIL (module not yet complete)**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_arrangement_structure_utils.py -q 2>&1 | head -20
```
Expected: ImportError or similar - functions not yet defined.

- [ ] **Step 4: Add `validate_section_map` and `tiling_plan` to the module**

Append to `ableton_mcp_max/arrangement_structure_utils.py`:

```python

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
```

- [ ] **Step 5: Write tests for `validate_section_map` and `tiling_plan`**

Append to `tests/test_arrangement_structure_utils.py`:

```python

# --- validate_section_map -------------------------------------------------

def test_validate_section_map_valid_minimal():
    validate_section_map([{"name": "A", "length_bars": 4}])  # no error

def test_validate_section_map_valid_with_clips():
    validate_section_map([{
        "name": "A", "length_bars": 4,
        "clips": [{"track_index": 0, "source_slot_index": 0, "repeat": "fill"}]
    }])

def test_validate_section_map_valid_repeat_int():
    validate_section_map([{
        "name": "A", "length_bars": 4,
        "clips": [{"track_index": 0, "source_slot_index": 0, "repeat": 2}]
    }])

def test_validate_section_map_empty_raises():
    with pytest.raises(ValueError, match="non-empty"):
        validate_section_map([])

def test_validate_section_map_not_list_raises():
    with pytest.raises(ValueError):
        validate_section_map("oops")

def test_validate_section_map_missing_name_raises():
    with pytest.raises(ValueError, match="name"):
        validate_section_map([{"length_bars": 4}])

def test_validate_section_map_empty_name_raises():
    with pytest.raises(ValueError, match="name"):
        validate_section_map([{"name": "  ", "length_bars": 4}])

def test_validate_section_map_missing_length_bars_raises():
    with pytest.raises(ValueError, match="length_bars"):
        validate_section_map([{"name": "A"}])

def test_validate_section_map_zero_length_bars_raises():
    with pytest.raises(ValueError, match="positive"):
        validate_section_map([{"name": "A", "length_bars": 0}])

def test_validate_section_map_negative_length_bars_raises():
    with pytest.raises(ValueError, match="positive"):
        validate_section_map([{"name": "A", "length_bars": -4}])

def test_validate_section_map_non_numeric_length_bars_raises():
    with pytest.raises(ValueError, match="number"):
        validate_section_map([{"name": "A", "length_bars": "eight"}])

def test_validate_section_map_clips_not_list_raises():
    with pytest.raises(ValueError, match="clips.*list"):
        validate_section_map([{"name": "A", "length_bars": 4, "clips": "nope"}])

def test_validate_section_map_clip_missing_track_index_raises():
    with pytest.raises(ValueError, match="track_index"):
        validate_section_map([{
            "name": "A", "length_bars": 4,
            "clips": [{"source_slot_index": 0}]
        }])

def test_validate_section_map_clip_negative_track_index_raises():
    with pytest.raises(ValueError, match="track_index"):
        validate_section_map([{
            "name": "A", "length_bars": 4,
            "clips": [{"track_index": -1, "source_slot_index": 0}]
        }])

def test_validate_section_map_bad_repeat_raises():
    with pytest.raises(ValueError, match="repeat"):
        validate_section_map([{
            "name": "A", "length_bars": 4,
            "clips": [{"track_index": 0, "source_slot_index": 0, "repeat": 0}]
        }])

def test_validate_section_map_repeat_float_raises():
    with pytest.raises(ValueError, match="repeat"):
        validate_section_map([{
            "name": "A", "length_bars": 4,
            "clips": [{"track_index": 0, "source_slot_index": 0, "repeat": 1.5}]
        }])


# --- tiling_plan ----------------------------------------------------------

def test_tiling_plan_fill_exact():
    # section = 16 beats, clip = 4 beats -> 4 copies
    assert tiling_plan(16.0, 4.0, "fill") == [0.0, 4.0, 8.0, 12.0]

def test_tiling_plan_fill_partial_no_trailing():
    # section = 10 beats, clip = 4 beats -> 2 copies (floor(10/4)=2)
    assert tiling_plan(10.0, 4.0, "fill") == [0.0, 4.0]

def test_tiling_plan_fill_clip_longer_than_section_one_copy():
    assert tiling_plan(4.0, 16.0, "fill") == [0.0]

def test_tiling_plan_fill_zero_section_still_one_copy():
    # edge: section_beats=0 -> max(1, floor(0/4))=1
    assert tiling_plan(0.0, 4.0, "fill") == [0.0]

def test_tiling_plan_integer_repeat():
    assert tiling_plan(16.0, 4.0, 3) == [0.0, 4.0, 8.0]

def test_tiling_plan_integer_repeat_overrun():
    # repeat=4, clip=8, section=16 -> 4 offsets even though last overruns
    assert tiling_plan(16.0, 8.0, 4) == [0.0, 8.0, 16.0, 24.0]

def test_tiling_plan_zero_clip_length_raises():
    with pytest.raises(ValueError, match="positive"):
        tiling_plan(16.0, 0.0, "fill")

def test_tiling_plan_negative_clip_length_raises():
    with pytest.raises(ValueError, match="positive"):
        tiling_plan(16.0, -4.0, "fill")

def test_tiling_plan_bad_repeat_raises():
    with pytest.raises(ValueError, match="repeat"):
        tiling_plan(16.0, 4.0, "half")
```

- [ ] **Step 6: Run all new tests - confirm they pass**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_arrangement_structure_utils.py -q 2>&1 | tail -5
```
Expected: all tests in the file pass (imports will still fail for the unwritten functions - that's fine because pytest collects the full file; we're confirming the written ones pass).

Actually, because the test file imports all functions at the top, run only the functions that exist so far by temporarily importing them explicitly:

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_arrangement_structure_utils.py -k "bars_to_beats or compute_section_starts or validate or tiling" -q 2>&1 | tail -5
```
Expected: 27 tests pass, 0 fail.

- [ ] **Step 7: Confirm full suite still passes**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q 2>&1 | tail -5
```
Expected: 566 passed (or ImportError on the new test file - acceptable at this stage since the read-side functions are not yet written).

- [ ] **Step 8: Commit**

```bash
git add ableton_mcp_max/arrangement_structure_utils.py tests/test_arrangement_structure_utils.py
git commit -m "feat(arrangement): bar/beat math + section-map validation + tiling logic"
```

---

### Task 2: Pure utils - section read helpers

**Files:**
- Modify: `ableton_mcp_max/arrangement_structure_utils.py`
- Modify: `tests/test_arrangement_structure_utils.py`

**Interfaces:**
- Consumes: none (pure math)
- Produces:
  - `sections_from_cues(cue_list: list[dict], song_end: float) -> list[dict]`
    - `cue_list`: list of `{"name": str, "time": float}` sorted by time
    - `song_end`: float beats (end of arrangement)
    - Returns: list of `{"name", "start_time", "end_time", "length_beats", "start_bar", "length_bars"}` (bars computed from 4/4 default; caller should pass num/den)
    - Actually: returns `{"name", "start_time", "end_time"}` - bar fields filled by caller via `compute_section_starts`
  - Revised signature: `sections_from_cues(cue_list, song_end) -> list[dict]` with keys `name`, `start_time`, `end_time`
  - `infer_sections(clips_by_track: list[list[dict]], song_end: float) -> list[dict]` with keys `name`, `start_time`, `end_time`, `density_label`
  - `section_facts(span: dict, clips_by_track: list[list[dict]]) -> dict` with keys `active_tracks`, `clip_count`, `coverage`
  - `normalize_energy(sections: list[dict]) -> list[dict]` adds `energy` key (0.0-1.0) to each; modifies in place and returns

- [ ] **Step 1: Write tests for the read helpers first**

Append to `tests/test_arrangement_structure_utils.py`:

```python

# --- sections_from_cues ---------------------------------------------------

def test_sections_from_cues_two_cues():
    cues = [{"name": "Intro", "time": 0.0},
            {"name": "Verse", "time": 16.0}]
    sections = sections_from_cues(cues, song_end=48.0)
    assert len(sections) == 2
    assert sections[0] == {"name": "Intro", "start_time": 0.0, "end_time": 16.0}
    assert sections[1] == {"name": "Verse", "start_time": 16.0, "end_time": 48.0}

def test_sections_from_cues_single_cue():
    cues = [{"name": "A", "time": 8.0}]
    sections = sections_from_cues(cues, song_end=32.0)
    assert len(sections) == 1
    assert sections[0]["start_time"] == 8.0
    assert sections[0]["end_time"] == 32.0

def test_sections_from_cues_cue_at_zero():
    cues = [{"name": "Start", "time": 0.0}, {"name": "End", "time": 32.0}]
    sections = sections_from_cues(cues, song_end=64.0)
    assert sections[0]["start_time"] == 0.0

def test_sections_from_cues_empty_returns_empty():
    assert sections_from_cues([], song_end=32.0) == []


# --- infer_sections -------------------------------------------------------

def test_infer_sections_two_tracks_same_boundary():
    # Both tracks change at beat 16: two sections [0,16) [16,32)
    clips_by_track = [
        [{"start_time": 0.0, "end_time": 16.0},
         {"start_time": 16.0, "end_time": 32.0}],
        [{"start_time": 0.0, "end_time": 16.0},
         {"start_time": 16.0, "end_time": 32.0}],
    ]
    sections = infer_sections(clips_by_track, song_end=32.0)
    assert len(sections) == 2
    assert sections[0]["start_time"] == 0.0
    assert sections[0]["end_time"] == 16.0
    assert sections[1]["start_time"] == 16.0
    assert sections[1]["name"] == "Section 2"

def test_infer_sections_naming():
    clips_by_track = [
        [{"start_time": 0.0, "end_time": 8.0},
         {"start_time": 8.0, "end_time": 16.0},
         {"start_time": 16.0, "end_time": 24.0}],
    ]
    sections = infer_sections(clips_by_track, song_end=24.0)
    names = [s["name"] for s in sections]
    assert names == ["Section 1", "Section 2", "Section 3"]

def test_infer_sections_empty_arrangement():
    assert infer_sections([], song_end=0.0) == []

def test_infer_sections_no_clips():
    assert infer_sections([[]], song_end=0.0) == []

def test_infer_sections_density_label_present():
    clips_by_track = [
        [{"start_time": 0.0, "end_time": 16.0}],
        [{"start_time": 0.0, "end_time": 16.0}],
    ]
    sections = infer_sections(clips_by_track, song_end=16.0)
    assert "density_label" in sections[0]
    assert sections[0]["density_label"] in ("sparse", "medium", "dense")


# --- section_facts --------------------------------------------------------

def test_section_facts_all_tracks_active():
    span = {"start_time": 0.0, "end_time": 16.0}
    clips_by_track = [
        [{"start_time": 0.0, "end_time": 16.0}],
        [{"start_time": 0.0, "end_time": 8.0}],
    ]
    facts = section_facts(span, clips_by_track)
    assert facts["active_tracks"] == [0, 1]
    assert facts["clip_count"] == 2
    # coverage: track 0 = 16/16=1.0, track 1 = 8/16=0.5, avg=0.75
    assert abs(facts["coverage"] - 0.75) < 1e-6

def test_section_facts_no_overlap():
    span = {"start_time": 32.0, "end_time": 48.0}
    clips_by_track = [
        [{"start_time": 0.0, "end_time": 16.0}],
    ]
    facts = section_facts(span, clips_by_track)
    assert facts["active_tracks"] == []
    assert facts["clip_count"] == 0
    assert facts["coverage"] == 0.0

def test_section_facts_coverage_capped_at_1():
    # Overlapping clips on same track could exceed 1.0 - must cap
    span = {"start_time": 0.0, "end_time": 8.0}
    clips_by_track = [
        [{"start_time": 0.0, "end_time": 8.0},
         {"start_time": 4.0, "end_time": 12.0}],
    ]
    facts = section_facts(span, clips_by_track)
    assert facts["coverage"] <= 1.0


# --- normalize_energy -----------------------------------------------------

def test_normalize_energy_range():
    sections = [
        {"active_tracks": [0, 1], "coverage": 0.5},
        {"active_tracks": [0], "coverage": 1.0},
        {"active_tracks": [], "coverage": 0.0},
    ]
    # Assign raw energy first (active_tracks * coverage)
    for s in sections:
        s["_raw_energy"] = len(s["active_tracks"]) * s["coverage"]
    result = normalize_energy(sections)
    energies = [s["energy"] for s in result]
    assert min(energies) == pytest.approx(0.0)
    assert max(energies) == pytest.approx(1.0)

def test_normalize_energy_single_section():
    sections = [{"active_tracks": [0], "coverage": 0.8}]
    sections[0]["_raw_energy"] = 0.8
    result = normalize_energy(sections)
    # Single section: all-equal -> uniform energy 0.0
    assert result[0]["energy"] == 0.0

def test_normalize_energy_all_equal():
    sections = [{"_raw_energy": 1.0}, {"_raw_energy": 1.0}]
    result = normalize_energy(sections)
    assert result[0]["energy"] == 0.0
    assert result[1]["energy"] == 0.0
```

- [ ] **Step 2: Run failing tests to confirm they fail**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_arrangement_structure_utils.py -k "sections_from_cues or infer_sections or section_facts or normalize_energy" -q 2>&1 | tail -5
```
Expected: ImportError or NameError (functions not yet defined).

- [ ] **Step 3: Implement `sections_from_cues`, `infer_sections`, `section_facts`, `normalize_energy`**

Append to `ableton_mcp_max/arrangement_structure_utils.py`:

```python

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
```

- [ ] **Step 4: Run the read-helper tests**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_arrangement_structure_utils.py -q 2>&1 | tail -5
```
Expected: all tests in the file pass (the full import at the top now resolves).

- [ ] **Step 5: Run the full suite**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q 2>&1 | tail -5
```
Expected: 566 + new tests = green.

- [ ] **Step 6: Commit**

```bash
git add ableton_mcp_max/arrangement_structure_utils.py tests/test_arrangement_structure_utils.py
git commit -m "feat(arrangement): section read helpers - cue spans, clip inference, facts, energy"
```

---

### Task 3: `get_arrangement_structure` tool

**Files:**
- Modify: `ableton_mcp_max/server.py` (add one `@mcp.tool()` in the `# === Arrangement ===` section, after `delete_arrangement_clip`)

**Interfaces:**
- Consumes from Task 2: `sections_from_cues`, `infer_sections`, `section_facts`, `normalize_energy`
- Consumes from Task 1: `bars_to_beats`, `compute_section_starts`
- Produces: `get_arrangement_structure(ctx) -> str` (MCP tool, no arguments)

**No Remote Script changes.** Uses: `get_transport`, `get_cue_points`, `get_session_info` (for track count), `get_arrangement_clips` per track.

- [ ] **Step 1: Find the insertion point**

```bash
grep -n "def delete_arrangement_clip\|# === Arrangement" ableton_mcp_max/server.py
```
The new tool goes after `delete_arrangement_clip` and before the next `# ===` section.

- [ ] **Step 2: Add the import at the top of server.py**

Find the block where utils are imported (search for `from ableton_mcp_max.arrangement_utils import`):

```bash
grep -n "from ableton_mcp_max.arrangement_utils\|from ableton_mcp_max.composition_utils" ableton_mcp_max/server.py
```

Add the new import on the line after the existing `arrangement_utils` import:

```python
from ableton_mcp_max.arrangement_structure_utils import (
    bars_to_beats,
    compute_section_starts,
    sections_from_cues,
    infer_sections,
    section_facts,
    normalize_energy,
    validate_section_map,
    tiling_plan,
)
```

- [ ] **Step 3: Implement `get_arrangement_structure` in server.py**

Find the `delete_arrangement_clip` function end and insert immediately after:

```python
@mcp.tool()
def get_arrangement_structure(ctx: Context) -> str:
    """Derive the song's section structure from the Arrangement timeline.

    Sections are identified in two ways:
    - If cue points (locators) exist: sections = spans between consecutive
      locators (last locator to arrangement end = final section). Section
      names come from the locator names. source = "cues".
    - If no cue points: sections are inferred from clip start/stop
      change-points across all tracks. Named "Section 1", "Section 2", etc.
      with a density_label ("sparse"/"medium"/"dense"). source = "inferred".

    Each section includes per-section facts: active_tracks (track indices
    with at least one clip overlapping the span), clip_count, coverage
    (average per-track clip-beats / span-beats, 0.0-1.0), and energy
    (active_tracks * coverage, min-max normalized 0.0-1.0 across sections).

    Returns:
    {
      time_signature: [num, den],
      song_end_bar: float,         # bar of the arrangement end (1-indexed)
      source: "cues" | "inferred",
      section_count: int,
      sections: [
        {name, start_bar, length_bars, start_time, end_time,
         active_tracks, clip_count, coverage, energy}
      ]
    }

    Note: bar fields use Ableton's 1-indexed convention (bar 1 = beat 0).
    """
    try:
        ableton = get_ableton_connection()

        # 1. Time signature
        transport = ableton.send_command("get_transport", {})
        num = int(transport.get("signature_numerator", 4))
        den = int(transport.get("signature_denominator", 4))
        beats_per_bar = num * (4.0 / den)

        # 2. Track count (for the clips loop)
        session = ableton.send_command("get_session_info", {})
        track_count = int(session.get("track_count", 0))

        # 3. Cue points
        cue_result = ableton.send_command("get_cue_points", {})
        cue_list = cue_result.get("cue_points", [])

        # 4. Arrangement clips per track
        clips_by_track = []
        for t in range(track_count):
            try:
                r = ableton.send_command(
                    "get_arrangement_clips", {"track_index": t})
                clips_by_track.append(r.get("clips", []))
            except Exception:
                clips_by_track.append([])

        # 5. Song end = max end_time across all clips (and last cue)
        all_ends = [c["end_time"] for track in clips_by_track for c in track]
        if cue_list:
            all_ends.append(max(c["time"] for c in cue_list))
        song_end = max(all_ends) if all_ends else 0.0

        # 6. Derive raw sections (name + start_time + end_time)
        if cue_list:
            raw_sections = sections_from_cues(cue_list, song_end)
            source = "cues"
        else:
            raw_sections = infer_sections(clips_by_track, song_end)
            source = "inferred"

        if not raw_sections:
            return _ok({
                "time_signature": [num, den],
                "song_end_bar": 1,
                "source": source,
                "section_count": 0,
                "sections": [],
            })

        # 7. Add bar fields and per-section facts
        result_sections = []
        for s in raw_sections:
            start_t = s["start_time"]
            end_t = s["end_time"]
            facts = section_facts({"start_time": start_t, "end_time": end_t},
                                  clips_by_track)
            # bar is 1-indexed: beat 0 = bar 1
            start_bar = 1.0 + start_t / beats_per_bar
            length_bars = (end_t - start_t) / beats_per_bar
            sec = {
                "name": s["name"],
                "start_bar": start_bar,
                "length_bars": length_bars,
                "start_time": start_t,
                "end_time": end_t,
                "active_tracks": facts["active_tracks"],
                "clip_count": facts["clip_count"],
                "coverage": facts["coverage"],
                "_raw_energy": len(facts["active_tracks"]) * facts["coverage"],
            }
            if "density_label" in s:
                sec["density_label"] = s["density_label"]
            result_sections.append(sec)

        normalize_energy(result_sections)

        # Remove internal _raw_energy key before returning
        for s in result_sections:
            s.pop("_raw_energy", None)

        song_end_bar = 1.0 + song_end / beats_per_bar

        return _ok({
            "time_signature": [num, den],
            "song_end_bar": song_end_bar,
            "source": source,
            "section_count": len(result_sections),
            "sections": result_sections,
        })
    except Exception as e:
        logger.error("Error getting arrangement structure: %s", e)
        return _err("Error getting arrangement structure: %s" % e)
```

- [ ] **Step 4: Verify the server imports cleanly**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python -c "import ableton_mcp_max.server; print('OK')"
```
Expected: `OK`

- [ ] **Step 5: Run full suite**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q 2>&1 | tail -5
```
Expected: same pass count as after Task 2 (no new tests in this task; coverage comes from the unit tests in Tasks 1-2).

- [ ] **Step 6: Commit**

```bash
git add ableton_mcp_max/server.py
git commit -m "feat(arrangement): get_arrangement_structure tool"
```

---

### Task 4: `build_arrangement` tool

**Files:**
- Modify: `ableton_mcp_max/server.py` (add one `@mcp.tool()` after `get_arrangement_structure`)

**Interfaces:**
- Consumes from Task 1: `validate_section_map`, `compute_section_starts`, `tiling_plan`
- Produces: `build_arrangement(ctx, sections, write_locators, replace, start_bar) -> str`

**Orchestration pattern** (server-side, no new RS command):
1. `validate_section_map` - raise before any mutation
2. `get_transport` - time signature
3. `compute_section_starts` - section start beats
4. If `replace=True`: clear existing arrangement clips on affected tracks
5. For each clip entry: `get_clip_info` -> length, `tiling_plan` -> offsets, `duplicate_clip_to_arrangement` per offset
6. If `write_locators=True`: `create_cue_point` per section start (using the existing server-side cue orchestration)

- [ ] **Step 1: Implement `build_arrangement` in server.py**

Add immediately after `get_arrangement_structure`:

```python
@mcp.tool()
def build_arrangement(
    ctx: Context,
    sections: List[dict],
    write_locators: bool = True,
    replace: bool = False,
    start_bar: int = 1,
) -> str:
    """Assemble an Arrangement from Session clips using an explicit section map.

    Computes section start beats from bar lengths and the live time signature,
    then tiles Session clips into each section via duplicate_clip_to_arrangement.
    Optionally writes named cue points (locators) at each section start so the
    structure is visible in Live and round-trips through get_arrangement_structure.

    Parameters:
    - sections: list of section dicts:
        {
          "name": "Intro",           # required, non-empty string
          "length_bars": 8,          # required, positive number
          "clips": [                 # optional; omit for a silent section
            {
              "track_index": 0,      # non-negative int
              "source_slot_index": 0,# non-negative int (Session slot)
              "repeat": "fill"       # "fill" (tile to fill) or int (exact count)
            }
          ]
        }
    - write_locators: write a cue point at each section start (default true).
      This lets get_arrangement_structure read the structure back via cues.
    - replace: before placing, delete all existing arrangement clips on every
      track referenced in the section map (idempotent re-builds). Default false.
    - start_bar: 1-indexed bar where the first section begins (default 1).

    Returns a summary of placed clips and locators. Always follow with a
    get_arrangement_structure call to verify (write-lag: returned counts may
    not reflect Live's final state).
    """
    try:
        validate_section_map(sections)
        ableton = get_ableton_connection()

        # Time signature
        transport = ableton.send_command("get_transport", {})
        num = int(transport.get("signature_numerator", 4))
        den = int(transport.get("signature_denominator", 4))

        # Compute section start beats
        computed = compute_section_starts(sections, int(start_bar), num, den)

        # Collect all track indices referenced across sections
        affected_tracks = set()
        for s in sections:
            for c in s.get("clips", []):
                affected_tracks.add(c["track_index"])

        # replace=True: clear existing arrangement clips on affected tracks
        if replace:
            for t in sorted(affected_tracks):
                try:
                    r = ableton.send_command(
                        "get_arrangement_clips", {"track_index": t})
                    existing = r.get("clips", [])
                    # Delete high-index-first to avoid re-indexing shift
                    for clip_entry in sorted(
                            existing, key=lambda x: x["index"], reverse=True):
                        ableton.send_command("delete_arrangement_clip", {
                            "track_index": t,
                            "clip_index": clip_entry["index"],
                        })
                except Exception:
                    pass  # track may have no arrangement clips - skip

        # Place clips section by section
        result_sections = []
        for s, cs in zip(sections, computed):
            section_start = cs["start_beat"]
            section_beats = cs["length_beats"]
            placed = []
            for clip_entry in s.get("clips", []):
                t = clip_entry["track_index"]
                slot = clip_entry["source_slot_index"]
                repeat = clip_entry.get("repeat", "fill")

                # Get clip length from the Session slot
                try:
                    info = ableton.send_command(
                        "get_clip_info",
                        {"track_index": t, "clip_index": slot})
                    clip_length = float(info.get("length", 0))
                except Exception as e:
                    raise ValueError(
                        "Cannot read clip info for track %d slot %d: %s"
                        % (t, slot, e))

                offsets = tiling_plan(section_beats, clip_length, repeat)
                for offset in offsets:
                    ableton.send_command("duplicate_clip_to_arrangement", {
                        "track_index": t,
                        "source_slot_index": slot,
                        "destination_time": section_start + offset,
                    })
                placed.append({
                    "track_index": t,
                    "source_slot_index": slot,
                    "count": len(offsets),
                    "first_time": section_start,
                })

            result_sections.append({
                "name": s["name"],
                "start_bar": 1.0 + section_start / (num * (4.0 / den)),
                "length_bars": s["length_bars"],
                "placed_clips": placed,
                "locator_written": False,  # filled in below if applicable
            })

        # Write locators if requested
        total_clips = sum(
            c["count"]
            for rs in result_sections
            for c in rs["placed_clips"]
        )
        if write_locators:
            for rs, cs in zip(result_sections, computed):
                beat = cs["start_beat"]
                try:
                    # Replicate the create_cue_point multi-command pattern:
                    # save playhead, move to section start, toggle cue, restore.
                    transport2 = ableton.send_command("get_transport", {})
                    original = transport2.get("current_song_time", 0.0)
                    ableton.send_command("set_song_position", {"time_beats": beat})
                    ableton.send_command("create_cue_at_playhead", {})
                    ableton.send_command("set_song_position", {"time_beats": original})
                    rs["locator_written"] = True
                except Exception:
                    rs["locator_written"] = False

        return _ok({
            "built": True,
            "time_signature": [num, den],
            "total_clips_placed": total_clips,
            "sections": result_sections,
            "note": "Follow with get_arrangement_structure to verify (write-lag).",
        })
    except Exception as e:
        logger.error("Error building arrangement: %s", e)
        return _err("Error building arrangement: %s" % e)
```

**Important note on the locator-writing step:** The `create_cue_at_playhead` RS command is the internal command called by `create_cue_point`. The build tool must replicate the same multi-step orchestration (`get_transport` -> `set_song_position` -> `create_cue_at_playhead` -> restore). Do NOT call the `create_cue_point` MCP tool from within another tool (tools are not re-entrant). The pattern above is correct.

- [ ] **Step 2: Verify server imports cleanly**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python -c "import ableton_mcp_max.server; print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Run full suite**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q 2>&1 | tail -5
```
Expected: same pass count as after Task 3 (no new unit tests for `build_arrangement` - it's end-to-end orchestration, covered by live smoke).

- [ ] **Step 4: Commit**

```bash
git add ableton_mcp_max/server.py
git commit -m "feat(arrangement): build_arrangement tool"
```

---

### Task 5: Docs regen, tool count, and release

**Files:**
- Modify: `docs/index.md` (5 hardcoded `126` -> `128`)
- Run: `scripts/gen_docs_site.py`, `scripts/build_tool_index.py` (auto-regen tools/ and index.md table)
- Modify: `README.md` (2 hardcoded counts)
- Modify: `PROGRESS.md` (record the new phase)
- Modify: `pyproject.toml`, `.claude-plugin/plugin.json`, `uv.lock` (version bump)

- [ ] **Step 1: Regen docs site and tool index**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python scripts/gen_docs_site.py && uv run python scripts/build_tool_index.py
```
Expected: no errors; `docs/tools/` files updated.

- [ ] **Step 2: Update hardcoded counts in docs/index.md**

Find all `126` occurrences and replace with `128`:

```bash
grep -n "126" docs/index.md
```

Edit `docs/index.md` - change every instance of `126` to `128` (5 spots: description meta tag, tagline paragraph, `stats__num` div, two body references).

- [ ] **Step 3: Update README.md counts**

```bash
grep -n "126" README.md
```

Edit `README.md` - change every `126` to `128`.

- [ ] **Step 4: Bump version to 0.11.0**

In `pyproject.toml`, change:
```toml
version = "0.10.0"
```
to:
```toml
version = "0.11.0"
```

In `.claude-plugin/plugin.json`, change:
```json
"version": "0.10.0"
```
to:
```json
"version": "0.11.0"
```

Then regenerate the lockfile:
```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv lock
```

- [ ] **Step 5: Verify final test suite + imports**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q 2>&1 | tail -5
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python -c "import ableton_mcp_max.server; print('OK')"
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python -m py_compile remote_script/AbletonMCP/__init__.py && echo "RS OK"
```
Expected: all tests green, `OK`, `RS OK`.

- [ ] **Step 6: Update PROGRESS.md**

Add a new section at the top of `PROGRESS.md`:

```markdown
## Arrangement intelligence: section map read/write (2026-06-18)
Roadmap item #2 of the "autonomous track production + closed analyze->act loop"
initiative. Adds 2 new tools (126 -> 128, new "Arrangement structure" area):

- **`get_arrangement_structure`**: derives section spans from cue points
  (primary) or clip change-point inference (fallback). Returns per-section facts:
  active tracks, clip count, coverage, and min-max normalized energy.
- **`build_arrangement`**: places Session clips onto the Arrangement timeline
  from an explicit section map (name + length_bars + clips list), tiles clips
  via `repeat: "fill"` or integer count, and optionally writes named cue
  locators so the structure round-trips through `get_arrangement_structure`.

New module `arrangement_structure_utils.py` holds all bar/beat math, inference,
and tiling logic (no Live dependency, fully unit-tested). No new Remote Script
commands - both tools compose existing `get_transport` / `get_cue_points` /
`get_arrangement_clips` / `duplicate_clip_to_arrangement` / `create_cue_point`
calls. Offline test suite: +N tests (566 -> NNN passed). Version: 0.10.0 ->
0.11.0. NEXT = live-verify vs Live 12 Suite (scratch tracks), then
`gh release create v0.11.0` and marketplace ref bump.
```

(Update the `N` values with the actual test count after running.)

- [ ] **Step 7: Commit**

```bash
git add docs/ README.md pyproject.toml .claude-plugin/plugin.json uv.lock PROGRESS.md
git commit -m "chore: docs + version bump 0.11.0 - arrangement intelligence (128 tools)"
```

---

## Live Verification (manual, after all tasks pass)

Perform these steps after a Claude Code restart (to pick up the new server) and with Live 12 running a blank set.

1. **Set up scratch tracks:**
   - `create_midi_track` x2 -> track indices 0 and 1
   - `generate_chord_progression(track_index=0, clip_index=0, progression=["I","IV","V","I"], bars=4)` -> Session slot 0 on track 0
   - `generate_drum_pattern(track_index=1, clip_index=0, bars=4)` -> Session slot 0 on track 1

2. **Build a 3-section arrangement:**
   ```json
   build_arrangement(sections=[
     {"name":"Intro","length_bars":4,"clips":[
       {"track_index":0,"source_slot_index":0,"repeat":"fill"},
       {"track_index":1,"source_slot_index":0,"repeat":"fill"}
     ]},
     {"name":"Main","length_bars":8,"clips":[
       {"track_index":0,"source_slot_index":0,"repeat":"fill"},
       {"track_index":1,"source_slot_index":0,"repeat":"fill"}
     ]},
     {"name":"Outro","length_bars":4,"clips":[
       {"track_index":0,"source_slot_index":0,"repeat":"fill"}
     ]}
   ], write_locators=True)
   ```
   Expected: `built: true`, `total_clips_placed >= 6`.

3. **Read back structure (cues path):**
   - `get_arrangement_structure` -> `source: "cues"`, `section_count: 3`, names match Intro/Main/Outro
   - Verify `length_bars` 4/8/4, energy ordering (Main should be highest).

4. **replace=True rebuild:**
   - Run `build_arrangement` again with `replace=True`, same sections
   - `get_arrangement_structure` -> same 3 sections, no duplicate clips

5. **Inferred path:**
   - `delete_cue_point` x3 to remove all locators
   - `get_arrangement_structure` -> `source: "inferred"`, sections named "Section 1/2/3"
   - Boundaries should match the clip layout (beat 0, 16, 48, 64 for 4/4 arrangement)

6. **Negative cases:**
   - `build_arrangement(sections=[])` -> error "non-empty"
   - `build_arrangement(sections=[{"name":"A","length_bars":4,"clips":[{"track_index":99,"source_slot_index":0}]}])` -> error when trying to get clip info (bad track)

7. **Self-clean:**
   - `delete_track` track 1 then track 0 (or the scratch track indices)
   - `delete_cue_point` any remaining cues
   - Verify `get_session_info` track_count returns to baseline

Record all results in `PROGRESS.md`.
