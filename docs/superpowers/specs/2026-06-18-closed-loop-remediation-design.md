# Closed-loop remediation

**Created:** 2026-06-18
**Status:** Design

## Summary

Sub-project **#3** of the autonomous track production initiative (#0 master/return,
#1 composition, #2 arrangement intelligence, **#3 closed-loop remediation**, #4
`/ableton:produce` skill).

Closes the analyze->act->verify loop by adding tools that translate analysis
findings into applied corrections and confirm convergence. Four new tools, one
new pure module, and a backward-compatible `action` field on existing findings.
Zero Remote Script changes - purely server-side, no Live restart needed during
development.

## Motivation

After v0.11.0, the server has strong **read/analyze** capabilities (`analyze_set`,
`measure_mix`, `measure_loudness`, `get_arrangement_structure`) and general-purpose
**write** primitives (`set_mixer_property`, `set_device_parameter`, `batch`). The
gap is the **act layer** between them:

- `analyze_set` findings carry a human-readable `remediation` string but no
  machine-parseable action. An agent must read the text, infer the tool call, and
  hope it guesses correctly.
- Adjusting a fader by a measured dB requires knowing Live's non-linear volume
  taper (`db = 40 * log10(v / 0.85)`) - already in `analysis_utils.live_volume_to_db`
  but no inverse exists and no tool applies a dB delta atomically.
- The "play, measure, adjust, re-measure" loop is doable via individual tool calls
  but is error-prone and verbose. The produce skill (#4) needs it as a reliable
  single call.

## Scope

**4 new tools (128 -> 132, new "Remediation" category, 18 total):**

1. `adjust_track_gain` - shift a track's fader by a signed dB amount (no playback)
2. `gain_stage_track` - play + measure LUFS (tap required) + compute + apply + verify
3. `balance_mix` - coherent multi-track measurement + relative level correction
4. `apply_findings` - translate `analyze_set` findings into a correction plan, optionally execute

**One new pure module:** `remediation_utils.py` (volume dB math, action generation,
plan validation)

**One backward-compatible finding enhancement:** `action` field added to findings
that have a mechanically-deterministic fix (see Finding actions below).

**No Remote Script changes.** All tools orchestrate existing server primitives.
Version bump: 0.11.0 -> 0.12.0.

## Finding actions

`analyze_set` findings currently have a text `remediation` field. The enhancement
adds an optional `action` dict for findings where the fix is deterministic:

```json
{
  "id": "mixing.fader_headroom",
  "status": "fail",
  "severity": "warn",
  "evidence": "Track 2 fader at 0.91 (clip risk)",
  "remediation": "Gain-stage below 0 dB; raise the source gain instead.",
  "action": {
    "tool": "set_mixer_property",
    "params": {"track_index": 2, "property": "volume", "value": 0.79},
    "reason": "0.91 -> 0.79 (-3 dB headroom target)"
  }
}
```

`action` is absent (not null) when the fix requires human judgment. Fixable
finding ids and their generated action type:

| Finding id | Action type | Notes |
|---|---|---|
| `health.no_leftover_solo` | `set_mixer_property` solo=0 | per-entity, one action per soloed track |
| `mixing.fader_headroom` | `set_mixer_property` volume | clamp to -3 dBFS headroom target |
| `mixing.loudness_balance` | `adjust_track_gain` | shift buried track up by below_db/2 (conservative) |
| `mixing.stereo_correlation` | - | no deterministic fix; needs EQ/instrument change |
| `mixing.spectral_masking` | - | no deterministic fix |
| `mixing.reverb_balance` | - | no deterministic fix |
| `mastering.loudness_target` | `gain_stage_track` | requires tap; auto-stages master to target LUFS |
| `mastering.true_peak` | `set_mixer_property` volume | lower master fader by excess dBTP |
| `mastering.limiter_present` | - | can't know which limiter the user wants |
| `mastering.master_processing` | - | needs human intent |
| `health.track_named` | - | rename requires human judgment |
| `health.device_count` | - | needs human judgment |

Action generation lives in `remediation_utils.generate_actions(findings, snapshot)`.
The `snapshot` arg provides volume values and entity metadata needed to compute
params. Called at the end of `analyze_set` to enrich the output - no new RS calls.

## Tool designs

### `adjust_track_gain`

```
adjust_track_gain(track_index, delta_db, track_type="regular") -> {ok, data}
```

Shift a track's fader by `delta_db` dB. Positive = louder, negative = quieter.
No playback required.

Flow:
1. Call `get_mixer` to read current `volume` value.
2. `current_db = live_volume_to_db(volume)` (from `analysis_utils`).
3. `new_db = clamp(current_db + delta_db, _DB_FLOOR, 6.0)`.
4. `new_volume = db_to_live_volume(new_db)` (new inverse in `remediation_utils`).
5. Call `set_mixer_property(track_index, "volume", new_volume, track_type)`.

Returns:
```json
{
  "track_index": 2,
  "delta_db": -3.0,
  "volume_before": 0.91,
  "volume_after": 0.76,
  "db_before": 1.4,
  "db_after": -1.6
}
```

**Volume math** (already in `analysis_utils._UNITY = 0.85`):
- `live_volume_to_db(v) = 40 * log10(v / 0.85)` (existing)
- `db_to_live_volume(db) = clamp(0.85 * 10^(db/40), 0, 1)` (new inverse)
- The 40x multiplier (not 20x) is Live's squared-power taper; verified against the
  existing function which was written from empirical measurement.

Errors: track not found, track_type mismatch.

### `gain_stage_track`

```
gain_stage_track(
    track_index,
    target_db = -18.0,
    window_s = 4.0,
    max_iterations = 3,
    track_type = "regular"
) -> {ok, data}
```

Play the set, measure the track's LUFS via its M4L tap, compute the correction
needed to reach `target_db`, apply it, and verify by re-measuring. Iterates up
to `max_iterations` times or until the track is within 1 dB of `target_db`.

Requires a tap deployed on the target track (via `deploy_taps`). Errors cleanly
if no tap is connected for that track index.

Flow per iteration:
1. Reset tap buffer for the target track (`_tap_registry.state.reset(uuid)`).
2. Play `window_s` seconds (`_run_measure_playback`).
3. Integrate buffer to LUFS (`_integrate_buffer`).
4. `delta_db = target_db - integrated_lufs`.
5. If `|delta_db| < 1.0`: converged, stop.
6. Call `adjust_track_gain(track_index, delta_db, track_type)`.
7. Repeat.

Returns:
```json
{
  "track_index": 1,
  "target_db": -18.0,
  "before_db": -12.4,
  "after_db": -18.1,
  "correction_db": -5.6,
  "converged": true,
  "iterations": 2,
  "volume_before": 0.91,
  "volume_after": 0.61
}
```

Non-converged (oscillating or limited by `max_iterations`) returns `converged:
false` with the final reading - the caller (agent or produce skill) decides whether
to retry or accept.

**Default target -18.0 dBLUFS** is a standard gain-staging target (leaves headroom
for the mix bus). For mastering loudness (`mastering.loudness_target` finding), the
caller passes the project's target (e.g. -14 LUFS).

### `balance_mix`

```
balance_mix(
    reference_track_index,
    window_s = 8.0,
    target_offsets = None,
    tracks = None
) -> {ok, data}
```

Single coherent measurement pass across all tapped tracks, then apply level
corrections to position each track relative to the reference.

`target_offsets`: optional list of `{track_index, offset_db}`. Default: balance
all tapped tracks to within 12 dB of the reference (matching `loudness_balance`'s
spread).

`tracks`: optional list of track indices to correct (subset of tapped tracks).

Flow:
1. `measure_mix(window_s)` -> per-track LUFS signals.
2. `reference_lufs = signals[reference_track_index].integrated_lufs`.
3. For each track in the correction set: `delta_db = (reference_lufs + offset_db) - track_lufs`.
4. Skip tracks within 1 dB of their target.
5. Batch-apply corrections via `batch` (single round-trip).
6. Return per-track before/after.

Returns:
```json
{
  "reference_track_index": 0,
  "reference_db": -14.2,
  "window_s": 8.0,
  "adjustments": [
    {"track_index": 1, "name": "Bass", "before_db": -22.1, "after_db": -14.2, "delta_db": 7.9},
    {"track_index": 2, "name": "Lead", "before_db": -13.8, "after_db": -14.2, "delta_db": -0.4, "skipped": true}
  ]
}
```

Does NOT re-measure after applying (the `gain_stage_track` loop is for per-track
convergence; `balance_mix` is a single-pass coarse correction). The produce skill
can follow up with `measure_mix` if verification is needed.

### `apply_findings`

```
apply_findings(
    findings,
    dry_run = True,
    severity_filter = ["fail", "warn"],
    focus = None
) -> {ok, data}
```

Takes the `findings` list from `analyze_set` (or `measure_mix`) output and
executes the fixable ones. `dry_run=True` (default) returns the plan without
mutating Live - always show the plan before applying.

`focus`: optional list of finding ids to restrict to (e.g. `["mixing.fader_headroom",
"health.no_leftover_solo"]`).

Flow:
1. Filter findings by `severity_filter` and `focus`.
2. Keep only findings with an `action` field AND `status` != "pass".
3. Deduplicate actions on the same target (last action wins).
4. Sequence: solo clears first (health), then fader adjustments (mixing/mastering).
5. If `dry_run=False`: execute via `batch`, return per-action results.

Returns:
```json
{
  "dry_run": true,
  "plan": [
    {
      "finding_id": "health.no_leftover_solo",
      "severity": "fail",
      "action": {"tool": "set_mixer_property", "params": {"track_index": 3, "property": "solo", "value": 0}},
      "status": "planned"
    },
    {
      "finding_id": "mixing.fader_headroom",
      "severity": "warn",
      "action": {"tool": "set_mixer_property", "params": {"track_index": 2, "property": "volume", "value": 0.76}},
      "status": "planned"
    }
  ],
  "planned_count": 2,
  "skipped_count": 3,
  "skipped_reasons": {"mixing.spectral_masking": "no deterministic action", "mastering.limiter_present": "no deterministic action", "mixing.stereo_correlation": "no deterministic action"}
}
```

When `dry_run=False`, each plan entry gets `status: "applied" | "error"` and an
optional `error` field.

**Important**: findings that require a tap (e.g. `mastering.loudness_target`) are
skipped in `apply_findings` and logged to `skipped_reasons` with "requires tap
measurement". The produce skill handles those via `gain_stage_track` directly.

## Module: `remediation_utils.py`

Pure, no Live dependency (import-safe on the server):

```python
# Volume math (inverse of analysis_utils.live_volume_to_db)
_UNITY = 0.85
_DB_FLOOR = -70.0
_DB_CEIL = 6.0

def db_to_live_volume(db: float) -> float:
    """Inverse of live_volume_to_db: dB -> Live volume knob value [0..1]."""
    ...

# Action generation
def generate_actions(findings: list, snapshot: dict) -> list:
    """Enrich findings with deterministic action dicts. Returns augmented list."""
    ...

# Plan validation
def build_correction_plan(findings: list, severity_filter: list, focus: list) -> dict:
    """Filter, deduplicate, and sequence fixable findings into an execution plan."""
    ...

# Balance math
def compute_balance_deltas(signals: list, reference_idx: int, target_offsets: list) -> list:
    """Given per-track LUFS signals, return per-track delta_db corrections."""
    ...
```

## Testing

All logic in `remediation_utils.py` is offline-testable. New test file:
`tests/test_remediation_utils.py`:

- Volume roundtrip: `db_to_live_volume(live_volume_to_db(v)) == v` for v in
  [0.0, 0.5, 0.85, 1.0]; inverse at floor/ceiling.
- `generate_actions`: synthetic findings list (with known track indices and
  volume values in snapshot) -> expected action dicts for fixable ids, absent for
  non-fixable.
- `build_correction_plan`: filter by severity, focus, dedup, sequence.
- `compute_balance_deltas`: reference at -14 LUFS, track at -22 LUFS with offset
  +0 -> delta = +8 dB; within-tolerance track -> skipped.
- `apply_findings` dry_run: mock findings -> plan matches expected.

No live-test automation for `gain_stage_track`/`balance_mix` (require playback +
tap). Live verification in PROGRESS.md after implementation.

Offline test target: 618 -> ~650 passed.

## Out of scope

- Auto-EQ to fix spectral masking (no LOM EQ-band write path for complex curves)
- Device creation for missing limiter/compressor (requires user intent)
- Track deletion or muting (too destructive for auto-apply)
- Arrangement-level gain automation (could follow in a later spec)
- Any Remote Script changes

## Version and release

Version 0.11.0 -> 0.12.0. Single PR `feat/closed-loop-remediation`. No RS
install required. Tool count 128 -> 132. New "Remediation" category in
`gen_docs_site.py` group map. Hero counts in `docs/index.md` need manual update.

Marketplace publish flow is the same as prior releases (bump 3 version files ->
`uv lock` -> commit -> `gh release create v0.12.0` -> bump marketplace ref ->
`node scripts/build-readme.js` -> push marketplace repo).
