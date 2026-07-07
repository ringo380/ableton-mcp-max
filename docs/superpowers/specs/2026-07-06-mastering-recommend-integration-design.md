# Mastering Recommend Integration - Design

**Date:** 2026-07-06
**Status:** Approved (design), pending implementation plan
**Phase:** Phase 3 (follows Ozone 12 Phase 2 native param authoring, shipped v0.30.0)

## Goal

Give the mastering workflow the same recommend-then-apply intelligence the
instrument workflow already has: a free-text intent plus a loudness target
produces a proposed Ozone 12 mastering chain, applies it in one shot, then
converges on the target loudness via a live measure/nudge loop. Surface it
through a rewritten `ableton-mastering` skill and the `/ableton:produce`
Master stage.

## Scope

**In scope**
- New MCP tool `recommend_master` (PROPOSE-ONLY decision engine).
- New MCP tool `apply_master` (one-shot: write chain, expose Maximizer, deploy master tap).
- Rewrite of `skills/ableton-mastering/SKILL.md` to drive the new tools and the trim loop.
- Wire the new flow into the `/ableton:produce` Master stage.

**Explicit non-goals (future phases)**
- Native-Ableton-limiter fallback when Ozone 12 is absent. Phase 3 is
  Ozone-12-centric: `apply_master` detects Ozone and errors with guidance
  when it is missing; it does not build a native chain.
- Ozone chain add/remove/reorder (module order is not in the state blob;
  deferred, per Phase 2).
- A dedicated on-disk Ozone-preset scanner. The catalog layer is best-effort
  over the existing `device_preset` catalog only.

## Architecture

```
recommend_master(intent, target)     PROPOSE-ONLY decision engine -> chain dict
        |                             (profile-first; catalog-check layered on)
        v
apply_master(chain)                   one-shot: set_ozone_state(chain) [reload],
        |                             expose Maximizer, deploy master tap
        v
ableton-mastering skill (rewritten)   LLM drives measure->nudge->re-measure loop
        |                             via measure_loudness + set_ozone_maximizer
        v
/ableton:produce Master stage         calls recommend_master + apply_master, then loop
```

Design principles, consistent with the existing codebase:
- Pure resolution/scoring lives in a server-imported `*_utils`-style module
  (`master_select.py` + `master_profiles.py`), unit-tested offline. This
  mirrors `instrument_select.py` feeding `recommend_instrument`.
- MCP tools stay deterministic and testable. The judgment loop (is the
  loudness close enough? nudge which way?) lives in the skill, where the LLM
  can adapt - the same division `/ableton:produce` already uses.
- `recommend_master` emits a `changes` dict in the **exact shape
  `set_ozone_state` accepts** (`{"MAX": {...}, "EQ": {...}, "Dynamics":
  {...}}`), so `apply_master` is a thin pass-through, not a translator.

## Component 1: recommend_master

**Signature**
```python
recommend_master(ctx, intent: str, target: float = None,
                 true_peak: float = -1.0, prefer_reuse: bool = True) -> str
```

**New pure modules**
- `master_profiles.py` - the curated character->chain table (data + a
  `build_chain(bucket, target, true_peak)` function that emits a
  `set_ozone_state`-shaped `changes` dict).
- `master_select.py` - intent parsing, target resolution, profile selection,
  result assembly. No Live/IO; pure functions.

**Behavior**
1. **Parse** `intent` into a character bucket and optional platform keyword.
   Character buckets (starting set of five):
   - `transparent` - minimal tonal shaping, gentle glue, clean ceiling.
   - `warm` - low-shelf lift, slight high-shelf tame.
   - `loud_club` - aggressive Maximizer, tighter dynamics, low-end control.
   - `punchy` - dynamics-forward (transient emphasis), moderate ceiling push.
   - `bright` - high-shelf lift, presence.
   Bucket is chosen by keyword scoring; default `transparent` when no
   keyword matches.
2. **Resolve target** (integrated LUFS): explicit `target` arg > platform
   keyword in intent (spotify/amazon/youtube -14, apple -16, club -8) >
   default -14. `true_peak` defaults -1.0 dBTP.
3. **Profile -> chain**: `master_profiles.build_chain` maps the bucket to
   concrete Ozone module params, scaling the Maximizer `Target Loudness [dB]`
   and ceiling to the resolved target/true_peak. Emitted as a
   `changes` dict keyed by Ozone module alias (`MAX`/`EQ`/`Dynamics`), each
   an inner `{param_name: value}` dict.
4. **Catalog layer (best-effort)**: query the existing `device_preset`
   catalog for a saved master/Ozone preset matching `intent`. On a strong
   match and `prefer_reuse=True`, include a `reuse` option in `top_matches`
   and set `decision:"reuse"`; otherwise `decision:"create"` with the profile
   chain. Degrades cleanly when the catalog is unavailable / Live
   disconnected (profile chain still returned).
5. **PROPOSE ONLY** - never writes.

**Return**
```
{ok, data: {
   intent, parsed: {bucket, platform, keywords},
   target, true_peak,
   chain,                 # set_ozone_state-shaped changes dict
   decision,              # "create" | "reuse"
   top_matches,           # catalog reuse candidates (may be [])
   reason,
   next                   # "Pass chain to apply_master to write it."
}}
```

**Param-name spike (planning-time, not spec):** before writing the profile
table, dump a real `get_ozone_state` from an Ozone 12 instance to lock the
exact EQ-band / Dynamics / Maximizer param key strings the profiles emit, so
every emitted key is a valid blob key. Confirmed real key example from Phase
2: Maximizer `Target Loudness [dB]`, Dynamics `Sidechain HPF`.

## Component 2: apply_master

**Signature**
```python
apply_master(ctx, chain: dict, track_index: int = None,
             device_index: int = 0, deploy_tap: bool = True) -> str
```
`track_index=None` resolves to the master track.

**Behavior**
1. **Detect Ozone** on the target device via the existing `is_ozone_state`
   guard on the decoded ProcessorState. If absent, return
   `{ok:false, error:"device N on track M is not an Ozone 12 plugin; load
   Ozone 12 on the master first"}`.
2. **Write** the chain: `set_ozone_state(changes=chain)` - one set save+reload,
   un-clamped native values. Surfaces `applied`/`skipped` from that call.
3. **Expose Maximizer**: `expose_ozone_modules(["MAX"])` so the live trim loop
   can nudge ceiling/gain with no further reloads. (Second reload; one-time
   setup cost. The subsequent loop is reload-free.)
4. **Deploy master tap** when `deploy_tap=True` and no master tap is present:
   `deploy_taps(include_master=True)`, so `measure_loudness` has post-fader
   audio. Skip if one already exists.
5. **Return**
```
{ok, data: {
   applied,               # from set_ozone_state
   skipped,
   exposed,               # Maximizer expose result
   tap: {status, ...},    # deployed | already_present | skipped
   target_lufs, true_peak,
   next: "run the trim loop: play the densest section, measure_loudness,
          nudge set_ozone_maximizer toward target"
}}
```

All judgment stays upstream (recommend) or downstream (skill loop). This tool
only sets up.

## Component 3: ableton-mastering skill rewrite

Replace `skills/ableton-mastering/SKILL.md`. New flow:
1. Read the loudness target from the project brief; if unstated, default
   -14 LUFS / -1 dBTP and note it. Keep the existing `loudness-targets.md`
   reference table.
2. `recommend_master(intent, target)` -> propose the chain; show the user the
   decision, chain summary, and target.
3. `apply_master(chain)` -> write + expose + tap.
4. **Trim loop (<= 4 iterations):** jump to the densest section,
   `start_playback`, `measure_loudness`. If `|integrated_LUFS - target| > 1
   LU` or `true_peak > ceiling`, nudge `set_ozone_maximizer` live (raise gain
   to increase loudness; lower ceiling / back off gain to tame true-peak),
   re-measure. Stop at target +/- 1 LU with true-peak within ceiling, or at
   4 iterations (report the best reading and the remaining gap).
5. `check_clipping` and verify true-peak <= ceiling.
6. Log target + final readings + the chain applied to `decisions.md`.

Gotchas retained/added: `measure_loudness` needs audio playing through a
master tap; the live `set_ozone_maximizer` path (Configure) does not reload,
so it is correct for the loop, whereas `set_ozone_state` reloads and must not
be used inside the loop.

## Component 4: /ableton:produce Master stage wire-in

Replace the current configuration-only master pass:
1. Pull the genre's LUFS target from the produce genre table (or the brief).
2. `recommend_master(brief_text, target)` -> chain.
3. `apply_master(chain)`.
4. Run the trim loop (as in the skill), then checkpoint - auto-fire the
   densest section (the stage already auto-fires playback).
5. **Degrade path (honest limits):** if Ozone is absent or no master tap can
   be deployed, fall back to the existing configuration-only master pass and
   mark the result un-metered - never invent dB/LUFS. Preserve the existing
   Master-stage honest-limit language.

## Error handling

- Every tool returns `{ok, data|error}`; callers check `ok`, never
  string-sniff.
- `recommend_master` never writes and never hard-fails on a disconnected
  catalog - it returns the profile chain with `top_matches: []`.
- `apply_master` returns actionable errors: not-Ozone, expose failed, tap
  failed. A tap failure is non-fatal (return `ok:true` with
  `tap.status:"failed"` and a note) so the chain write still counts; the skill
  then reports the loop cannot run un-metered.

## Testing

**Offline unit tests (pure, no Live):**
- `master_select`: intent -> bucket keyword scoring (each of the five
  buckets + default), platform-keyword target override, explicit-arg target
  precedence, true_peak default, result-shape assembly.
- `master_profiles`: each bucket -> a `changes` dict whose keys are valid
  Ozone module aliases and whose param keys match the locked blob key strings;
  Maximizer target/ceiling scale with the resolved target/true_peak.
- Catalog degrade: recommend returns the profile chain with empty
  `top_matches` when the catalog is unavailable.
- Same offline gate as the rest of the repo: `uv run --with pytest pytest -q`,
  `uv run python -c "import ableton_mcp_max.server"`.

**Live gate (release, manual):** recommend -> apply against real Ozone 12 on
the master -> one trim-loop pass; verify the chain writes un-clamped, the
Maximizer exposes, a master tap is present, and `measure_loudness` moves
toward the target across a nudge.

## Deliverable summary

- New pure modules: `master_profiles.py`, `master_select.py`.
- New MCP tools: `recommend_master`, `apply_master` (tool count 182 -> 184).
- Rewritten `skills/ableton-mastering/SKILL.md`.
- Updated `/ableton:produce` Master stage.
- No new dependencies. Docs/hardcoded-count bumps handled at release
  (docs/index.md 5 spots + README.md:7 + tool-index regen).
