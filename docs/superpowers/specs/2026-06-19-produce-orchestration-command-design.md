# `/ableton:produce` orchestration command — design

**Date:** 2026-06-19
**Sub-project:** #4b of the autonomous-track-production initiative (final piece).
**Depends on:** #1 composition, #2 arrangement, #3 closed-loop remediation, #4a sample sourcing — all shipped (v0.13.0, 136 tools).
**Status:** Approved (brainstorm complete; ready for implementation plan).

## Summary

A new Claude Code plugin command `commands/produce.md` that orchestrates the full
autonomous track-production pipeline: from an empty (or near-empty) Live set to an
arranged, mixed, and mastered track. It is **pure prose** — a workflow that chains
existing MCP tools and the composition / arrangement / remediation / sample-sourcing
layers. It adds **no server tool and no Remote Script change**; tool count and version
of the MCP server are unaffected by this sub-project (the only artifact is the command
file plus the docs/site regen that any command addition triggers).

The command runs each stage autonomously but **checkpoints at stage boundaries**: it
does the stage's work, prints a short summary, auto-fires playback so the result is
immediately audible, and pauses for the user to `continue / adjust / redo` before
moving on. This is deliberately *not* fully-auto (no blind run to a finished master)
and *not* per-write (no confirmation on every clip) — stage granularity is the
redirect unit.

## Non-goals / honest limits (surface these in the command)

- **No audio-content matching** — sample selection is name/path based (per #4a). The
  command picks samples by keyword, not by listening.
- **Signal mix/master needs taps** — `balance_mix` and the master loudness pass are
  only signal-accurate when MCP Tap devices are loaded (per `analyze.md`). Without
  taps the command degrades to configuration-only and says so; it never invents
  dB/LUFS numbers.
- **Generated parts are algorithmic starting points** — the composition tools produce
  musically-sensible but deterministic material; the checkpoint loop is how the user
  shapes it toward intent.
- **Scope is one track/idea** — empty set → one arranged song structure. Not a
  multi-song project, not stem export, not third-party plugin automation.

## Front matter

```yaml
---
description: Autonomously produce a full track in Ableton Live — brief → foundation → parts → arrangement → mix → master — pausing at each stage to audition and redirect.
allowed-tools: ["Bash", "Read", "AskUserQuestion"]
---
```

`AskUserQuestion` is needed for the Brief-stage gap-fill and is in the allowed list.
`Read` is needed to load rulesets during the Master stage (delegated to `analyze.md`'s
documented flow) and is harmless to include.

## Stage model

Six stages. Every stage except Brief follows the same checkpoint protocol:

1. Do the stage's work autonomously (stop-and-report on a hard failure — see Failure
   posture).
2. Print a short summary of what changed (tracks/clips/sections/levels touched).
3. **Auto-fire** the relevant playback so the result is already audible: fire the
   loop scene (Foundation/Parts), start the arrangement at the right point
   (Arrangement), or play a representative section (Mix/Master).
4. Pause and present `continue / adjust / redo`:
   - `continue` → stop playback, advance to the next stage.
   - `adjust` → take the user's note, rework *within this stage*, re-checkpoint.
   - `redo` → redo this stage from scratch (clean its outputs first), re-checkpoint.

### Stage 1 — Brief
- Parse `$ARGUMENTS` for: genre/style, mood/reference words, key, tempo, length/
  structure, sample keywords.
- Fill gaps from the **inline genre table** (below): unknown tempo → genre default;
  unknown structure → genre template; mood → density/energy/LUFS targets; unknown key
  → read the set scale via composition tools' `get_song_scale` behavior, else a
  genre-sensible default.
- Present **one consolidated `AskUserQuestion`** only for choices that genuinely change
  output and could not be defaulted safely (e.g. genre when truly unstated, target
  length). Do not interrogate field-by-field.
- Print the **resolved plan** (genre, key, tempo, structure, sample plan, mix/master
  targets) and confirm before building. No playback in this stage (nothing exists yet).

### Stage 2 — Foundation
- Set tempo (`set_tempo`).
- Create the tracks the genre template calls for and load instruments
  (`create_midi_track` / `create_audio_track` / `load_instrument_or_effect` /
  `load_drum_kit`) — defer the per-tool mechanics and HOT-SWAP gotcha to
  `/ableton:new-track`.
- Source keyword-driven samples: `search_samples` → `load_drum_kit` /
  `populate_drum_rack` / `load_audio_clip` per #4a. iCloud materialization and
  feasibility gates are handled inside those tools.
- Checkpoint: fire the scene with whatever is loaded.

### Stage 3 — Parts
- Generate clips per track via the composition tools, keyed to the brief's key/scale:
  `generate_chord_progression`, `generate_bassline`, `generate_melody`,
  `generate_drum_pattern`.
- Use the extended-note API only (the composition tools already do; never legacy
  set_notes — see `/ableton:best-practices`).
- Checkpoint: fire the full loop scene.

### Stage 4 — Arrangement
- Derive a section map (name + length_bars + clips) from the genre **structure
  template** scaled to the brief's length.
- `build_arrangement(... write_locators=True)` to place Session clips onto the
  timeline; locators let the structure round-trip through
  `get_arrangement_structure`.
- Checkpoint: play the arrangement from the top.

### Stage 5 — Mix
- **Tap gate:** if taps are not loaded, OFFER to deploy them (`deploy_taps`) and
  continue with real signal work; if the user declines, proceed configuration-only and
  clearly mark the mix as un-metered (never fabricate levels).
- `balance_mix` / `gain_stage_track` / `adjust_track_gain` against the brief's targets.
- Defer the metering rationale and "Needs metering" framing to `/ableton:analyze`.
- Checkpoint: play a representative (densest) section.

### Stage 6 — Master
- `analyze_set` (with `measure=True` if taps are present) focused on mastering, then
  `apply_findings` for the deterministic master-bus corrections against the genre LUFS
  target. Judgment-required findings are reported, not auto-applied.
- Checkpoint: final playback + a summary of the finished track (tracks, structure,
  measured/target loudness, what was and wasn't auto-applied).

## Inline genre table

A compact markdown table in `produce.md`, ~6–10 genres × columns
`{tempo, structure template, density/energy, LUFS target}`, plus an explicit note:
"for any genre not listed, derive sensible values from these anchors using your own
judgment." Curated anchor genres (final list chosen during implementation; indicative):
house, techno, hip-hop / lo-fi, drum & bass, ambient, pop, trap. Structure templates
are expressed as section maps compatible with `build_arrangement`
(e.g. `Intro 8 / Build 8 / Drop 16 / Break 8 / Drop 16 / Outro 8`).

## Reuse vs inline

`produce.md` stays lean: each stage names the work and the **orchestration-specific**
gotchas only (stage sequencing, the tap gate, write-lag verification between stages),
and references the sibling commands for tool mechanics:
- `/ableton:new-track` — track creation, instrument loading, HOT-SWAP warning.
- `/ableton:analyze` — the analyze/measure/metering flow used by Mix and Master.
- `/ableton:best-practices` — restart protocol, write-lag, connection triage, undo
  scope, extended-note API.

This mirrors how the existing commands already cross-reference each other and avoids
duplicating (and drifting from) the per-tool guidance.

## Failure posture

- **Stop-and-report on a hard failure within a stage** — surface the tool's `error`
  and stop; do not blunder into the next stage on a broken foundation.
- **Connection triage** — the first MCP call after a restart can fail while the server
  reconnects; retry once, then triage per `/ableton:best-practices`.
- **Verify writes with follow-up reads** — Live applies many writes asynchronously;
  never trust a tool's own success string for state the next stage depends on
  (tempo, track presence, clip notes, arrangement clips). Read back before advancing.
- **Cleanup** — the goal is a kept track, not a scratch test, so partial outputs are
  left in place for the user to keep or discard; the command does not auto-delete on
  failure (that would be destructive to in-progress work). It reports what exists.

## Testing & verification

- **No new unit-testable code** — this sub-project adds a prose command only. The
  offline gate (pytest + py_compile + server import) is unaffected; tool count and
  version do not change.
- **Docs/site regen** — adding a command triggers the standard regen
  (`scripts/build_tool_index.py` / `scripts/gen_docs_site.py` as applicable) and a
  `commands/tool-index.md` / README refresh; the command must appear in the plugin's
  command list. The `docs/index.md` hardcoded counts are tool/category counts, which do
  not change here — confirm they stay correct.
- **Live verification (manual, per project rule)** — run `/ableton:produce` end-to-end
  against a blank set on the dev machine (Live 12.4): confirm each stage builds, the
  auto-fire audition plays, the checkpoint pause/`adjust`/`redo`/`continue` loop works,
  the tap gate behaves both with and without taps, and the final set is a coherent
  arranged/mixed/mastered track. Record results in `PROGRESS.md`.

## Packaging / ship

Standard plugin command addition + release: the command is a committed ship artifact
(`commands/produce.md`). Bump version in the three files (`pyproject.toml`,
`.claude-plugin/plugin.json`, `uv.lock` via `uv lock`), regen docs, commit, tag a
release, bump the marketplace `ableton` `ref`, rebuild the marketplace README, push.
(A command-only release still gets a version bump for the marketplace ref to move.)
