---
name: ableton-mastering
description: Finalizing a mix to a target loudness with an Ozone 12 chain, limiting, metering, and reference matching on the Ableton master. Use when mastering, hitting a LUFS target, taming true-peaks, or matching a reference loudness.
---

# Ableton mastering

Goal: hit a platform loudness target while preserving dynamics and avoiding
true-peak clipping. Master only a clean, headroom-safe mix, with Ozone 12 on the
master.

## Flow
1. Read the loudness target from the project brief. If unstated, default
   -14 LUFS / -1 dBTP and note it. See `loudness-targets.md`.
2. `recommend_master(intent, target)` -> a proposed Ozone chain (character
   bucket + target). Show the user the decision, chain summary, and target.
   PROPOSE ONLY - it writes nothing.
3. `apply_master(chain)` -> writes the chain (one reload), exposes the
   Maximizer, and deploys a master tap. If it errors "not an Ozone 12 plugin",
   tell the user to load Ozone 12 on the master first.
4. Trim loop (<= 4 iterations), all live (no reloads):
   - Jump to the densest section, `start_playback`, then `measure_loudness`.
   - If integrated LUFS is within 1 LU of target AND true-peak <= ceiling, stop.
   - Otherwise nudge `set_ozone_maximizer` live: raise `threshold` (input gain)
     to get louder; lower `ceiling` or back off gain to tame true-peak.
   - Re-measure. After 4 iterations, report the best reading and the gap.
5. `check_clipping` and confirm true-peak <= ceiling.
6. Log the target, the applied chain, and the final readings to `decisions.md`.

## Tools
- Propose/apply: `recommend_master`, `apply_master`.
- Live trim (no reload): `set_ozone_maximizer` (threshold/ceiling/character).
- Measure: `measure_loudness` (integrated LUFS / peaks), `check_clipping`.
- Direct Ozone param authoring when needed: `get_ozone_state` /
  `set_ozone_state` (native units, un-clamped) - but NOT inside the trim loop
  (they reload the set and stop playback).

## Principles
- Gain into the limiter; do not slam it. Aim for <= 3 dB gain reduction.
- Master by the meter, then by ear against a reference.
- Re-measure after every change.

## Gotchas
- `measure_loudness` needs audio actually playing through a master tap
  (apply_master deploys one; without it the loop runs un-metered - say so).
- The live `set_ozone_maximizer` path does NOT reload; use it in the loop.
  `set_ozone_state` DOES reload (stops playback) - use it only at apply time.
- Ozone-12-only: there is no native-limiter fallback in this flow.
- After `apply_master`, check `data.exposed` for an `error`: if the Maximizer
  failed to expose, the live `set_ozone_maximizer` trim loop cannot run - fall
  back to authoring the Maximizer via `set_ozone_state` (reloads) or report it.

## Checklist
- [ ] Target read from brief (or default applied + noted).
- [ ] recommend_master proposal shown before applying.
- [ ] Integrated LUFS within ~1 LU of target; true-peak <= -1 dBTP.
- [ ] Compared against a reference track.
- [ ] Logged target + chain + final readings to decisions.md.
