---
layout: default
title: Remediation
parent: Tools
nav_order: 20
---

# Remediation
{: .no_toc }

Translate analysis findings into applied mix corrections: shift faders by dB, auto-stage a track to a target LUFS via its MCP Tap, balance all tapped tracks in one coherent pass, and execute a structured correction plan from analyze_set findings.

<details open markdown="block">
  <summary>Tools on this page</summary>
  {: .text-delta }
1. TOC
{:toc}
</details>

---

## adjust_track_gain

```python
adjust_track_gain(track_index: int, delta_db: float, track_type: str = 'regular')
```

Shift a track's fader by a signed dB amount without playback.

Reads the current volume knob value, converts using Live's 40x log taper
(unity = 0.85), applies delta_db, clamps to [-70, +6] dB, and writes the
new value back via set_mixer_property. No tap or playback required.

Parameters:
- track_index: index of the track (ignored for master; pass 0)
- delta_db: signed dB shift; positive = louder, negative = quieter
- track_type: "regular" (default), "return", or "master"

Returns JSON {ok, data:{track_index, delta_db, volume_before, volume_after,
db_before, db_after}}.

## gain_stage_track

```python
gain_stage_track(
    track_index: int,
    target_db: float = -18.0,
    window_s: float = 4.0,
    max_iterations: int = 3,
    track_type: str = 'regular',
)
```

Play the set, measure the track's LUFS via its MCP Tap, and iteratively
converge the fader to target_db.

IMPORTANT - on a regular/return track the MCP Tap is PRE-FADER (it sits in the
device chain, ahead of the mixer fader), so moving the fader does NOT change
what the tap reads: the loop measures the instrument + device-chain level, not
the post-fader output, and re-measuring will show the same value (it may report
not-converged). Use this as an instrument-level gain-stage (the first-pass
correction is still a valid trim toward target), or run it on the MASTER
(track_type='master', the post-fader program output) for true loudness
convergence.

Requires an MCP Tap device deployed on the target track (via deploy_taps).
Plays the arrangement for window_s seconds each iteration, integrates the
buffered tap blocks into LUFS, computes the correction, and applies it via
the fader. Repeats up to max_iterations times or until within 1 dB of target.

Parameters:
- track_index: index of the regular/return/master track to stage
- target_db: target integrated LUFS (default -18.0, a standard gain-staging level)
- window_s: playback capture window per iteration in seconds (default 4.0)
- max_iterations: maximum correction cycles (default 3)
- track_type: "regular" (default), "return", or "master"

Returns JSON {ok, data:{track_index, target_db, before_db, after_db,
correction_db, converged, iterations, volume_before, volume_after}}.
{ok:false,error} if no tap is connected for this track.

## balance_mix

```python
balance_mix(
    reference_track_index: int,
    window_s: float = 8.0,
    target_offsets: list = None,
    tracks: list = None,
)
```

Single coherent measure pass + batch-apply level corrections.

Runs one measure_mix-style playback window across all connected taps,
then adjusts each track's fader so its integrated LUFS matches the
reference track (plus any per-track offset_db you specify). Tracks within
1 dB of their target are skipped. All corrections are applied individually
(not batched) so each adjust_track_gain call validates its own target.

IMPORTANT - per-track taps are PRE-FADER (instrument + device-chain level,
ahead of the mixer fader). The correction math is still right for OUTPUT
balance: it adds each track's pre-fader gap onto its fader so output =
pre_fader + fader matches the reference - but ONLY if the reference track's
fader is left as the anchor, and the result CANNOT be re-verified by
re-measuring the same per-track taps (their readings are invariant to the
fader). To confirm the balance landed, deploy a master tap and read the
post-fader program output (measure_mix data.master).

Parameters:
- reference_track_index: track whose LUFS is the balance baseline
- window_s: capture length in seconds (default 8.0)
- target_offsets: optional list of {track_index, offset_db} specifying
  how many dB above/below the reference each track should sit
- tracks: optional list of track indices to correct (subset of tapped tracks)

Returns JSON {ok, data:{reference_track_index, reference_db, window_s,
adjustments:[{track_index, name, before_db, delta_db, skipped}]}}.

## apply_findings

```python
apply_findings(
    findings: list,
    dry_run: bool = True,
    severity_filter: list = None,
    focus: list = None,
)
```

Translate analyze_set findings into a correction plan and optionally apply it.

Takes the ``findings`` list from analyze_set output (or a merged list) and
executes the mechanically-fixable ones. Findings with an ``action`` dict
(added by analyze_set's generate_actions enrichment) that match the
severity_filter are applied; others are reported as skipped with a reason.

IMPORTANT: dry_run defaults to True - the plan is returned without mutating
Live. Always inspect the plan before passing dry_run=False.

Parameters:
- findings: list of finding dicts from analyze_set data.findings (must
  have been produced with action enrichment - i.e. from this server v0.12+)
- dry_run: when True (default), return the plan without applying changes
- severity_filter: list of severities to include (default ["fail", "warn"])
- focus: optional list of finding ids to restrict to

Returns JSON {ok, data:{dry_run, plan:[{finding_id, severity, action, status,
[error]}], planned_count, skipped_count, skipped_reasons}}.

