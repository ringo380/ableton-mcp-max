# ableton-mcp-max — Phase 6: Automation Envelopes (Design)

**Created:** 2026-05-25
**Status:** Approved (design) — pending implementation plan

## Goal

Let Claude read and write parameter automation in Ableton clips: device
parameters, rack macros, and mixer volume/pan/sends, in both session and
arrangement clips.

## Architecture

Same two halves over localhost:9877 as all prior phases:
- `ableton_mcp_max/server.py` — new `@mcp.tool()`s. The server resolves all
  names/indices and sends already-resolved identifiers downstream.
- `remote_script/AbletonMCP/__init__.py` — reads run inline in `_process_command`;
  mutations go in BOTH the `elif command_type in [...]` modifying list AND a branch
  in `main_thread_task`. The handler fetches live `Clip` / `DeviceParameter` /
  `AutomationEnvelope` objects and applies.
- `ableton_mcp_max/automation_utils.py` — new pure, unit-tested helper module
  (imported by server.py only; the Remote Script runs in Live's own interpreter and
  cannot import it).

## The hard LOM constraints (these drive the whole design)

1. **No breakpoint enumeration.** `Live.Clip.AutomationEnvelope` exposes only:
   - `value_at_time(time)` — sample one time
   - `insert_step(time, duration, value)` — `duration=0` inserts a single
     breakpoint; `duration>0` inserts a flat segment
   - `clear_range(time, duration)`
   - `clear()`
   There is no API to list existing breakpoints. **Reads are therefore sampled.**
2. **Envelopes are per-clip**, reached through the clip:
   - `Clip.automation_envelope(parameter)` → `AutomationEnvelope` or `None`
   - `Clip.create_automation_envelope(parameter)` → `AutomationEnvelope`
   - `Clip.clear_envelope(parameter)` — remove one parameter's envelope
   - `Clip.clear_all_envelopes()` — remove all of the clip's envelopes
   "Arrangement automation" in the LOM sense means automation **inside arrangement
   clips**, not the free track-level lanes (those are not LOM-addressable).
3. **Everything automatable is a `DeviceParameter`** — device parameters, rack
   macros (a rack *is* a device; each macro is a `DeviceParameter` on it), and
   mixer `volume` / `panning` / `sends[i]` on `track.mixer_device`. So macro
   automation folds into the device target — no separate code path.

## Targeting (shared across all tools)

**Clip target:**
- `track_index: int`
- `clip_index: int` — session: index into `track.clip_slots`; arrangement: index
  into `track.arrangement_clips`
- `clip_location: str = "session"` — `"session"` → `clip_slots[i].clip`;
  `"arrangement"` → `arrangement_clips[i]`

**Parameter target:**
- `target_type: str = "device"`
  - `"device"` → `device_index: int` + `parameter: int|str` (name or index;
    macros included). Name→index resolved server-side via the existing
    `get_device_parameters` round-trip + `param_utils.resolve_parameter_index`,
    exactly as `set_device_parameter` already does. The handler receives a
    resolved `parameter_index`.
  - `"mixer"` → `mixer_property: str` ∈ {volume, pan, send} (aliases via
    `mixer_utils`) + `send_index: int = -1` (required for `send`). The handler
    maps to `mixer_device.volume` / `.panning` / `.sends[send_index]`.

## Tool set (5)

### 1. `get_automation` (read — inline)
```
get_automation(track_index, clip_index, target_type="device",
               device_index=0, parameter=None,
               mixer_property=None, send_index=-1,
               clip_location="session",
               from_time=0.0, time_span=-1.0, resolution=16) -> str
```
Returns `{clip_location, track_index, clip_index, target info, has_envelope,
samples: [{time, value}, ...]}`.
- `has_envelope` = `clip.automation_envelope(param) is not None`.
- If an envelope exists: `resolution` evenly-spaced `value_at_time` samples across
  `[from_time, from_time+time_span)`. `time_span<0` → use `clip.length`.
- If no envelope: `has_envelope=false`, `samples=[]`.

### 2. `set_automation` (write — main-thread mutation)
```
set_automation(track_index, clip_index, target_type="device",
               device_index=0, parameter=None,
               mixer_property=None, send_index=-1,
               clip_location="session",
               points=None, time=None, value=None, duration=0.0) -> str
```
- Resolves the `DeviceParameter`, **lazily creates** the envelope if
  `automation_envelope(param)` is `None` (via `create_automation_envelope`), then
  loops `insert_step(time, duration, value)` once per point.
- Accepts **either** a single `{time, value, duration}` (top-level args) **or**
  `points=[{time, value, duration?}, ...]` for a batch curve in one main-thread task.
- **`duration` semantics (corrected after live verification):** Live's `insert_step`
  writes a FLAT segment `[time, time+duration)` and `duration=0` is a no-op (there are
  no linear ramps in the LOM). So the handler **auto-tiles** any `duration<=0`: a point
  holds until the next point's time (the last point fills to `clip.length`; tiny
  fallback if that gap is non-positive). A bare value-only point therefore holds across
  the clip, and a bare `points` list draws a staircase. Server validates via
  `automation_utils.normalize_breakpoints` before sending.
- Returns `{... target info, points_written}`.

### 3. `clear_automation` (write — main-thread mutation)
```
clear_automation(track_index, clip_index, target_type="device",
                 device_index=0, parameter=None,
                 mixer_property=None, send_index=-1,
                 clip_location="session",
                 from_time=None, time_span=None) -> str
```
- Range given (`from_time` + `time_span`) → `envelope.clear_range(from_time, time_span)`.
- Both omitted → `clip.clear_envelope(param)` (removes that parameter's envelope).
- Returns `{... target info, cleared: "range"|"envelope"}`.

### 4. `create_automation_envelope` (write — main-thread mutation)
```
create_automation_envelope(track_index, clip_index, target_type="device",
                           device_index=0, parameter=None,
                           mixer_property=None, send_index=-1,
                           clip_location="session") -> str
```
- Explicit empty-envelope creation (`clip.create_automation_envelope(param)`).
  Returns `{... target info, created: bool}` (`created=false` if one already existed).

### 5. `clear_all_automation` (write — main-thread mutation)
```
clear_all_automation(track_index, clip_index, clip_location="session") -> str
```
- `clip.clear_all_envelopes()`. Returns `{clip_location, track_index, clip_index, cleared_all: true}`.

`get_automation` runs inline in `_process_command`; tools 2–5 are added to the
modifying-command list and given `main_thread_task` branches.

## `automation_utils.py` (pure, unit-tested)

- `normalize_clip_location(s)` → `"session"|"arrangement"` (case-insensitive; raises on other).
- `normalize_target_type(s)` → `"device"|"mixer"` (raises on other).
- `normalize_mixer_target(prop, send_index)` → canonical `{volume|pan|send}` (reuse
  `mixer_utils` aliases); enforces `send_index>=0` when `prop=="send"`.
- `coerce_resolution(n)` → int clamped to `>=1`.
- `coerce_time(t)`, `coerce_duration(d)` → float `>=0` (raise on negative).
- `coerce_value(v)` → float.
- `normalize_breakpoints(points, time, value, duration)` → validated
  `[{time, value, duration}, ...]`: accepts the single-point form or a list; raises
  on an empty result, missing time/value, or negative time/duration.

Device parameter name→index resolution stays in `param_utils` (server does the
`get_device_parameters` round-trip). Per the project's architecture rule, the
Remote Script receives only resolved values.

## Testing

**Offline (`tests/test_automation_utils.py`):**
- location/target normalization (canonical, case-insensitive, bad input raises);
- mixer target normalization incl. `send` requiring `send_index`;
- resolution clamp (`0`/negative → `1`);
- time/duration negative → raise;
- `normalize_breakpoints`: single form, list form, empty → raise, missing field → raise.

**Live smoke (recorded in PROGRESS.md):**
- sampled read of a known automated param (`has_envelope=true`, sensible samples);
- read with no envelope (`has_envelope=false`, `samples=[]`);
- write single breakpoint, re-sample to confirm value;
- write a batch curve (`points`), re-sample at several times to confirm shape;
- `clear_automation` range vs full-envelope clear;
- `create_automation_envelope` then read (`has_envelope` flips true);
- `clear_all_automation` wipes the clip;
- **macro automation** (device target on a rack, parameter = a macro);
- **mixer volume automation** (`target_type="mixer"`);
- **arrangement-clip indexing** (`clip_location="arrangement"`) — riskiest new path;
- negative cases: bad `clip_location`, `send` without `send_index`, empty `points`.
- Restore/clean any envelopes created during testing.

## Flagged unknowns — verify live, do not assume

- `Track.arrangement_clips` existence and indexing shape in Live 11.
- Whether `insert_step` auto-creates the envelope, or `create_automation_envelope`
  is required first — `set_automation` creates defensively regardless.
- `value_at_time` / `insert_step` time units (expected: beats) and whether they
  differ between session and arrangement clips.
- Whether session-clip mixer automation behaves identically to device automation.
- Return-value lag (per the project gotcha): verify writes with a separate
  `get_automation` read, never trust the returned confirmation dict.

## Out of scope (Phase 6)

- Free arrangement track-lane automation outside clips (not LOM-addressable).
- Breakpoint enumeration / exact-curve export (no LOM API; sampling only).
- Automation of song-global params (tempo automation lane, etc.).
