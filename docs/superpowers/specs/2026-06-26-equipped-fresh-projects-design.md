# Equipped Fresh Projects - Design

**Created**: 2026-06-26
**Status**: Approved (design); plan pending

## Overview

Make the `ableton` plugin install into any fresh Claude Code project - each a separate
music project - such that the session is fully equipped to use the tools well: optimal
analysis, mastering, mixing, MIDI arrangement, and sample use.

Today the plugin ships the **MCP server (tools)** plus **workflow commands**
(`commands/*.md`: produce, analyze, new-track, add-to-track, best-practices, stems,
restart, setup). But the *expertise* for using those tools well lives in private,
gitignored config (`CLAUDE.md`, `~/.claude/notes/ableton-mcp.md`). A fresh project -
the author's or a stranger's - gets the tools but not the judgment, and even the
author's private knowledge is **pull-only** (must invoke `best-practices`).

This work makes the production knowledge (a) **ship inside the plugin** so any installer
gets it, and (b) be **present without being asked for**, while keeping a single source
of truth so projects do not drift from the plugin.

Audience decision: **both** public plugin users and the author's own multi-project
workflow. Surfacing decision: **thin always-on core + deep on-trigger skills**. Skill
granularity: **7 focused skills**. Bootstrap artifacts: **all four** (brief, decisions
log, plans scaffold, sample inventory).

## Architecture

Three layers. Knowledge ships in the plugin (Layers 1-2); per-project *state* lives in
plain files in the project folder (Layer 3). The plugin is the single source of truth;
project files hold only project-specific content.

### Layer 1 - Always-on core (SessionStart hook)

- New `hooks/hooks.json` + a hook script (`hooks/scripts/orient.sh` or `.py`,
  `${CLAUDE_PLUGIN_ROOT}`-relative). On `SessionStart` the script:
  1. Detects whether the Ableton MCP server is configured for this project. If not,
     stays **silent** (zero noise in non-music projects).
  2. If present, prints a **distilled, public-safe core** (~40-60 lines): restart
     protocol, connection triage, read-state-first / don't-assume-track-0,
     write-lag -> verify-with-separate-read, hot-swap-replaces, undo-is-global,
     extended-MIDI-API-not-legacy, device-tool `track_type` asymmetry, "load scratch
     devices onto an empty track."
  3. If `project-brief.md` exists in the cwd, appends a one-line pointer: "Music project
     detected - read `project-brief.md`, `decisions.md`, `samples.md` before acting."
- This is the only always-on token cost. It is the curated extract of the private notes,
  sanitized for public ship: no AI-tells, no machine-specific absolute paths, no
  author-private gotchas (dev/build details stay in private notes).

### Layer 2 - Seven on-trigger skills (`skills/` dir)

Each is a `SKILL.md` (frontmatter + body), trigger-tuned, kept under ~500 lines, with
reference files for deep tables (progressive disclosure). Skills auto-load only when a
relevant task arises - cheap and scalable.

1. **ableton-mixing** - gain staging, balance, panning, sends/returns, headroom; tools:
   `measure_mix`, `balance_mix`, `gain_stage_track`, `adjust_track_gain`, `check_clipping`,
   `read_meter`, `read_track_meter`.
2. **ableton-mastering** - LUFS targets per platform (reference file), limiting,
   master-tap metering, reference matching; tools: `measure_loudness`, master-chain
   device tools (`get_device_parameters`/`set_device_parameter` with `track_type=master`).
3. **ableton-sound-design** - preset/instrument selection, Wavetable/Simpler/rack
   backdoor tools, macro mapping, layering; tools: `create_wavetable_preset`,
   `create_simpler_instrument`, rack `inspect/clone/rename/zones/add_rack_macro_mappings`.
4. **ableton-arrangement** - structure, energy/tension, scenes, cue points, automation;
   tools: `build_arrangement`, `get_arrangement_structure`, scene/cue tools,
   `set_arrangement_automation`.
5. **ableton-midi-composition** - `generate_chord_progression`/`generate_bassline`/
   `generate_melody`/`generate_drum_pattern`, `humanize_clip`/`swing_clip`/
   `quantize_clip`/`quantize_clip_to_scale`, the extended-note-API rules, groove pool.
6. **ableton-sample-use** - `search_samples`, `load_audio_clip`, drum racks
   (`load_drum_kit`/`populate_drum_rack`/`load_sample_to_drum_pad`), stem separation,
   warping.
7. **ableton-analysis** - the `analyze_set` -> measure -> `detect_key` workflow and
   remediation reporting; tools: `analyze_set`, `apply_findings`, `measure_mix`,
   `measure_loudness`, `detect_key`.

Existing **commands stay** as user-facing entry points. Skills are the shared expertise
that both commands and ad-hoc work draw on. Each relevant command gains a line:
"consult the relevant `ableton-*` skill."

### Layer 3 - Per-project bootstrap (`/ableton:init-project`)

A new command scaffolds the music-project folder:

- `project-brief.md` - genre, key, tempo, references, target loudness, mix/master intent
  (template with prompts). Read by `produce`/`analyze` and pointed at by the Layer-1 hook.
- `decisions.md` - append-only session log (tracks added, mix moves, mastering choices);
  `produce`/`analyze` append to it so a new session resumes with full context.
- `samples.md` - inventory / pointers to samples, stems, and bounced references, so
  sample-use tools know the palette.
- `.claude/plans/` + a plan template (matches the existing plan-file workflow).

**No generated `CLAUDE.md`** - deliberately. The global gitignore swallows `CLAUDE.md`
(it would silently vanish from git) and the file is an AI-tell on public projects. The
Layer-1 hook is what makes the brief "always read," so a `CLAUDE.md` is unnecessary.

## Data Flow

`SessionStart` hook (core + brief pointer) -> Claude reads `project-brief.md` /
`decisions.md` / `samples.md` -> an ad-hoc task or a command auto-triggers the right
`ableton-*` skill -> the command appends outcomes to `decisions.md`. Single source of
truth = the plugin; project files hold only project-specific state.

## Source-of-Truth & Maintenance

The seven skills + the hook core become the canonical home for the production knowledge
currently scattered across the author's private `CLAUDE.md` and
`~/.claude/notes/ableton-mcp.md`. The private notes remain for dev/build gotchas
(restart-to-reload, AbletonDev vs cached plugin, release chain); the *production*
expertise migrates into shippable skills. No duplication into per-project files, so
projects never drift from the plugin.

## Error Handling / Edge Cases

- Non-music project (no Ableton MCP configured): hook is silent.
- Music project with no brief yet: hook prints core only; `/ableton:init-project` is the
  remedy and is mentioned in the core.
- `/ableton:init-project` run twice: must not clobber an existing `project-brief.md` /
  `decisions.md` / `samples.md` - detect and skip (or offer to append/refresh), never
  overwrite user content.
- Skill description budget: 7 new skill descriptions must fit the listing budget; keep
  them tight and verify with `/doctor`.

## Testing / Verification

- **Hook**: unit-testable (MCP-present -> prints core; absent -> silent; brief present ->
  pointer). Add to the offline gate.
- **Skills**: `claude plugin validate` + `/doctor` description-budget check.
- **Bootstrap**: run `/ableton:init-project` in a temp dir; assert the four artifacts
  exist; re-run and assert no clobber.
- **Live (one end-to-end pass)**: init a scratch project, confirm the hook fires, confirm
  a mixing task auto-loads `ableton-mixing`.

## Files to Modify / Create

- `hooks/hooks.json` - new; register the SessionStart hook.
- `hooks/scripts/orient.*` - new; the core + project-detection logic.
- `skills/ableton-mixing/SKILL.md` (+ reference files) - new.
- `skills/ableton-mastering/SKILL.md` (+ LUFS reference) - new.
- `skills/ableton-sound-design/SKILL.md` - new.
- `skills/ableton-arrangement/SKILL.md` - new.
- `skills/ableton-midi-composition/SKILL.md` - new.
- `skills/ableton-sample-use/SKILL.md` - new.
- `skills/ableton-analysis/SKILL.md` - new.
- `commands/init-project.md` - new bootstrap command.
- `commands/*.md` (produce, analyze, new-track, add-to-track) - add "consult the relevant
  `ableton-*` skill" + read/append project files where relevant.
- `pyproject.toml` + `.claude-plugin/plugin.json` + `uv.lock` - version bump (v0.24.0).
- README/docs count regen via the existing doc scripts; hand-bump hardcoded counts.

## Ship Impact

Plugin-internal only (`hooks/`, `skills/`, `commands/`). Minor bump v0.24.0 + the usual
release chain: tag -> marketplace `ref` bump -> README/docs regen.

## Out of Scope (YAGNI)

- No new MCP tools.
- No generated per-project `CLAUDE.md`.
- No automatic migration of every private note; only the production-relevant subset.
- No UI/visual companion.
