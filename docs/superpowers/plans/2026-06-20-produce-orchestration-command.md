# `/ableton:produce` Orchestration Command Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a prose plugin command `commands/produce.md` that orchestrates the full autonomous track-production pipeline (empty set → arranged, mixed, mastered track) with stage-boundary checkpoints.

**Architecture:** Pure prose command — no server tool, no Remote Script change, no Python. It chains existing MCP tools (composition / arrangement / remediation / sample-sourcing layers) and references the sibling commands (`new-track`, `analyze`, `best-practices`) for tool mechanics, carrying only orchestration logic itself. Six stages, each auto-run then paused for audition/redirect.

**Tech Stack:** Markdown command file with YAML front matter; Claude Code plugin command auto-discovery; existing AbletonMCPMax tools.

**Spec:** `docs/superpowers/specs/2026-06-19-produce-orchestration-command-design.md`

## Global Constraints

- **No AI attribution** in commits, the command file, or any shipped artifact (public repo).
- **Only the standard hyphen `-`** in all prose — no em/en-dashes.
- **No server/RS code change** — this sub-project adds a command file only; tool count stays **136**, category count stays **20**, the `docs/index.md` hardcoded counts MUST stay unchanged.
- **Offline gate unchanged and must stay green:** `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q` + `uv run python -c "import ableton_mcp_max.server"`.
- **Front matter** exactly: `description:` (one line, no dashes) + `allowed-tools: ["Bash", "Read", "AskUserQuestion"]`.
- **Prose-command pattern** (match `commands/new-track.md` / `analyze.md`): `# /ableton:produce` H1, a leading "load tools if deferred" `ToolSearch` hint, concise gotcha-encoding sections, cross-references to sibling commands rather than duplicated mechanics.
- **gh account** must be `ringo380`; **plugin/marketplace** repo is `ringo380/robworks-claude-code-plugins`, plugin name `ableton`.

---

### Task 1: Author `commands/produce.md` (full command)

**Files:**
- Create: `commands/produce.md`
- Read for pattern (do not modify): `commands/new-track.md`, `commands/analyze.md`, `commands/best-practices.md`

**Interfaces:**
- Consumes: existing MCP tools by name only (no signatures change) — `set_tempo`, `create_midi_track`, `create_audio_track`, `load_instrument_or_effect`, `load_drum_kit`, `search_samples`, `populate_drum_rack`, `load_audio_clip`, `generate_chord_progression`, `generate_bassline`, `generate_melody`, `generate_drum_pattern`, `create_scene`, `fire_scene`, `build_arrangement`, `get_arrangement_structure`, `start_playback`/`stop_playback`/`set_song_position`, `list_taps`, `get_audio_tap_status`, `deploy_taps`, `balance_mix`, `gain_stage_track`, `adjust_track_gain`, `analyze_set`, `apply_findings`, `get_session_info`, `get_transport`, `get_track_info`.
- Produces: the command itself (a user/model-invokable `/ableton:produce`). No code interface for later tasks.

- [ ] **Step 1: Write the front matter and intro**

Create `commands/produce.md` starting with:

```markdown
---
description: Autonomously produce a full track in Ableton Live - brief, foundation, parts, arrangement, mix, master - pausing at each stage to audition and redirect.
allowed-tools: ["Bash", "Read", "AskUserQuestion"]
---

# /ableton:produce

Build a complete track from an empty (or near-empty) Live set: brief -> foundation -> parts -> arrangement -> mix -> master. Each stage runs automatically, then PAUSES so you can hear it and redirect before the next stage. This is not a blind one-shot to a finished master, and not a confirm-every-write crawl - the stage boundary is the redirect unit.

> If MCP tools aren't loaded yet, fetch the core set: `ToolSearch select:mcp__AbletonMCPMax__get_session_info,mcp__AbletonMCPMax__set_tempo,mcp__AbletonMCPMax__create_midi_track,mcp__AbletonMCPMax__load_instrument_or_effect,mcp__AbletonMCPMax__generate_chord_progression,mcp__AbletonMCPMax__build_arrangement,mcp__AbletonMCPMax__balance_mix,mcp__AbletonMCPMax__analyze_set` (load others per stage as needed).

**Argument:** free text brief, e.g. `/ableton:produce lofi hip hop, 84 bpm, dreamy, 2 minutes`. Anything omitted is filled from the genre table below.

## Honest limits (state these to the user up front)

- Sample selection is by name/path keyword, not by listening - no audio-content matching.
- Real mix/master levels need MCP Tap devices loaded; without taps the mix/master pass is configuration-only and is marked un-metered (never invent dB/LUFS).
- Generated parts are musically-sensible but algorithmic starting points - the checkpoint loop is how you shape them.
- Scope is one track/idea: empty set -> one arranged structure. Not multi-song, not stem export.
```

- [ ] **Step 2: Write the checkpoint protocol section**

Append:

```markdown
## Checkpoint protocol (every stage except Brief)

1. Do the stage's work autonomously. On a HARD failure (a tool returns `{"ok": false}` that blocks the stage), STOP and report the `error` - do not start the next stage on a broken foundation.
2. Print a short summary of what changed (tracks / clips / sections / levels touched).
3. AUTO-FIRE playback so the result is already audible: `fire_scene` the loop (Foundation/Parts), `set_song_position(0)` + `start_playback` (Arrangement), or play the densest section (Mix/Master).
4. Pause and offer `continue / adjust / redo`:
   - `continue` -> `stop_playback`, advance.
   - `adjust` -> take the note, rework WITHIN this stage, re-checkpoint.
   - `redo` -> clear this stage's outputs and redo it, re-checkpoint.

Verify writes before advancing: Live applies many writes asynchronously, so re-read state a stage depends on (`get_transport` for tempo, `get_session_info` for tracks, `get_arrangement_clips` for the timeline) rather than trusting a tool's own success string. See `/ableton:best-practices` (write-lag, connection triage, undo scope).
```

- [ ] **Step 3: Write the genre table**

Append a compact table (final anchor values are the implementer's call; these are the columns and an example set):

```markdown
## Genre defaults

Fill any brief gap from this table; for a genre not listed, derive sensible values from these anchors using your judgment. Structure templates are section maps for `build_arrangement` (scale lengths to the requested total).

| Genre | Tempo | Structure template (bars) | Density / energy | Master LUFS target |
|-------|-------|---------------------------|------------------|--------------------|
| House | 122-126 | Intro 16 / Build 16 / Drop 32 / Break 16 / Drop 32 / Outro 16 | driving, 4-on-floor | -8 |
| Techno | 128-134 | Intro 16 / Build 16 / Main 32 / Break 16 / Main 32 / Outro 16 | hypnotic, sparse-to-dense | -7 |
| Hip-hop / lo-fi | 80-92 | Intro 4 / Verse 16 / Hook 8 / Verse 16 / Hook 8 / Outro 4 | laid-back, swung | -10 |
| Drum & bass | 170-176 | Intro 16 / Build 8 / Drop 32 / Break 16 / Drop 32 / Outro 16 | fast, breakbeat | -7 |
| Ambient | 60-90 | Intro 16 / Evolve 32 / Peak 16 / Resolve 16 | slow, evolving pads | -14 |
| Pop | 100-120 | Intro 4 / Verse 16 / Chorus 8 / Verse 16 / Chorus 8 / Bridge 8 / Chorus 8 / Outro 4 | vocal-forward | -9 |
| Trap | 130-150 (half-time feel) | Intro 8 / Verse 16 / Hook 8 / Verse 16 / Hook 8 / Outro 8 | 808-heavy, hi-hat rolls | -8 |
```

- [ ] **Step 4: Write the six stage sections**

Append one section per stage. Each names the work + orchestration gotchas and references siblings for mechanics (do NOT duplicate tool mechanics):

```markdown
## Stage 1 - Brief

1. Re-read the set: `get_session_info` (never assume a track layout - see `/ableton:best-practices`).
2. Parse the argument for genre/style, mood/reference words, key, tempo, length/structure, sample keywords.
3. Fill gaps from the genre table: unknown tempo -> genre default; unknown structure -> genre template scaled to the requested length; mood words -> nudge density/energy and the LUFS target; unknown key -> read the set scale (composition tools expose the song scale) else a genre-sensible default.
4. Ask ONE consolidated `AskUserQuestion` ONLY for choices that genuinely change output and can't be safely defaulted (typically: genre if truly unstated, and total length). Do not interrogate field-by-field.
5. Print the resolved plan (genre, key, tempo, structure, sample plan, mix/master targets) and confirm before building. No playback in this stage.

## Stage 2 - Foundation

- `set_tempo`; verify with a separate `get_transport` (write-lag).
- Create the tracks the template calls for and load instruments - see `/ableton:new-track` for creation + the HOT-SWAP warning (loading replaces an existing instrument; build on empty tracks).
- Source keyword-driven samples: `search_samples` -> `load_drum_kit` / `populate_drum_rack` (drums) / `load_audio_clip` (loops). iCloud materialization and feasibility gates live inside those tools.
- Checkpoint: `fire_scene` on the row holding the loaded material.

## Stage 3 - Parts

- Generate clips per track, keyed to the brief's key/scale: `generate_chord_progression`, `generate_bassline`, `generate_melody`, `generate_drum_pattern`. These use the safe extended-note API (never legacy set_notes - see `/ableton:best-practices`).
- Ensure a scene exists for the loop row (`create_scene` if needed).
- Checkpoint: `fire_scene` on the full loop.

## Stage 4 - Arrangement

- Build the section map from the genre structure template scaled to the brief's length (name + length_bars + clips per section).
- `build_arrangement(..., write_locators=True)` to place Session clips on the timeline; locators let it round-trip through `get_arrangement_structure` (Live auto-names locators sequentially, not by section - expected).
- Verify with `get_arrangement_clips` before advancing.
- Checkpoint: `set_song_position(0)` + `start_playback`.

## Stage 5 - Mix

- TAP GATE: check `list_taps` / `get_audio_tap_status`. If no taps are connected, OFFER to `deploy_taps` and continue with real signal work; if the user declines, proceed configuration-only and clearly mark the mix as un-metered (never fabricate levels).
- `balance_mix` / `gain_stage_track` / `adjust_track_gain` toward the brief's targets. See `/ableton:analyze` for the metering rationale and the "Needs metering" framing.
- Checkpoint: play the densest section (`set_song_position` to that section's start + `start_playback`).

## Stage 6 - Master

- `analyze_set(focus="mastering", measure=<True if taps present>)`, then `apply_findings` for the deterministic master-bus corrections against the genre LUFS target. Report judgment-required findings; do not auto-apply them.
- Checkpoint: final playback from the top + a closing summary (tracks, structure, measured vs target loudness, what was and wasn't auto-applied).

## Failure and cleanup

- Stop-and-report on the first blocking `{"ok": false}` within a stage; surface the `error`, don't advance.
- First-call-after-restart "Could not connect" is usually the reconnect race - retry once, then triage per `/ableton:best-practices`.
- The goal is a kept track, so partial outputs are left in place on failure for the user to keep or discard - the command does not auto-delete in-progress work.
```

- [ ] **Step 5: Lint for dashes and validate the command file**

Run:

```bash
PATH=/usr/bin:/bin:/usr/sbin:/sbin /usr/bin/grep -nP '[\x{2010}-\x{2015}\x{2212}]' commands/produce.md && echo "DASH FOUND - fix" || echo "dash-clean"
/Users/ryanrobson/.local/bin/claude plugin validate . 2>&1 | tail -5
```

Expected: `dash-clean`, and validation `PASS` (or no errors reported for the command).

- [ ] **Step 6: Confirm the offline gate is untouched**

Run:

```bash
cd /Users/ryanrobson/git/ableton-mcp-max && PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q 2>&1 | tail -3
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python -c "import ableton_mcp_max.server; print('import OK')"
```

Expected: full suite passes (699 tests, unchanged), `import OK`.

- [ ] **Step 7: Commit**

```bash
git add commands/produce.md
git commit -m "feat: add /ableton:produce orchestration command"
```

---

### Task 2: Docs regen + count integrity check

**Files:**
- Possibly regenerate (only if they enumerate commands): `commands/tool-index.md`, `docs/tools/index.md`
- Verify unchanged: `docs/index.md` (hardcoded tool/category counts)

**Interfaces:**
- Consumes: Task 1's `commands/produce.md`.
- Produces: a consistent docs tree (no count drift).

- [ ] **Step 1: Run the docs/index regen scripts**

```bash
cd /Users/ryanrobson/git/ableton-mcp-max && PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python scripts/build_tool_index.py && PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python scripts/gen_docs_site.py
```

- [ ] **Step 2: Verify counts did not change**

The command adds NO `@mcp.tool()`, so tool count must remain 136 and categories 20.

```bash
git diff --stat docs/ commands/tool-index.md
PATH=/usr/bin:/bin /usr/bin/grep -n "136\|20 " docs/index.md | head
```

Expected: `git diff --stat` shows NO changes to `commands/tool-index.md` or `docs/tools/*` (the tool catalogue is unaffected); `docs/index.md` still shows 136 tools / 20 categories. If any tool-count doc changed, STOP - something is wrong (this task adds no tool).

- [ ] **Step 3: Commit only if something legitimately regenerated**

If `git status` is clean after regen, skip the commit (nothing to do). Otherwise, if a regen touched a file legitimately:

```bash
git add docs/ commands/tool-index.md
git commit -m "docs: regen after adding produce command"
```

---

### Task 3: Live end-to-end verification

**Files:**
- Modify: `PROGRESS.md` (record results)

**Interfaces:**
- Consumes: the installed command + a running Live (12.4) with the AbletonDev or cached `ableton` MCP server connected.
- Produces: verification evidence in `PROGRESS.md`.

> This task is MANUAL (project rule: Live verification is hands-on). It runs in the main session, not a subagent - subagents hit stream-idle timeouts on long Live calls.

- [ ] **Step 1: Restart Claude Code so the new command loads**

Commands load at session start. After committing Task 1, restart Claude Code (user action) so `/ableton:produce` is invocable. Confirm Live is running and 9877 is listening (`lsof -nP -iTCP:9877 -sTCP:LISTEN`).

- [ ] **Step 2: Run the pipeline against a blank set**

Invoke `/ableton:produce techno, 130 bpm, 90 seconds` against a blank/default set. Walk all six stages. At each checkpoint confirm: the summary is accurate, auto-fire playback actually starts, and `continue` advances / `adjust` reworks / `redo` redoes. Use `adjust` at least once (e.g. at Parts) to confirm in-stage rework, and `redo` at least once.

- [ ] **Step 3: Exercise the tap gate both ways**

Reach Stage 5 once with NO taps loaded -> confirm it OFFERS `deploy_taps` and, on decline, proceeds config-only and marks the mix un-metered (no invented numbers). Then (taps deployed) confirm `balance_mix` / `analyze_set(measure=True)` produce real signal findings.

- [ ] **Step 4: Confirm the finished set**

After Stage 6: `get_session_info` + `get_arrangement_structure` show a coherent arranged structure with locators; the master pass reported measured-vs-target loudness. Confirm the set is a complete arranged/mixed/mastered track.

- [ ] **Step 5: Record results and commit**

Add a `## /ableton:produce orchestration command (#4b)` section to `PROGRESS.md` with the date, what was verified (per-stage, checkpoint loop, tap gate both ways), and any caveats found.

```bash
git add PROGRESS.md
git commit -m "docs: record /ableton:produce live verification"
```

---

### Task 4: Ship (version bump + release + marketplace ref)

**Files:**
- Modify: `pyproject.toml` (version), `.claude-plugin/plugin.json` (version), `uv.lock` (via `uv lock`)
- External repo: `ringo380/robworks-claude-code-plugins` (`marketplace.json` ref + README rebuild)

**Interfaces:**
- Consumes: a verified, committed command (Tasks 1-3).
- Produces: a published `vX.Y.Z` release with the command, marketplace `ableton` ref bumped.

> Do this only after the user confirms live verification passed.

- [ ] **Step 1: Pick the next version**

Confirm the latest shipped tag and that no unreleased commits predate it:

```bash
gh release list --limit 3
git log $(git describe --tags --abbrev=0)..origin/main --oneline
```

Current in-tree version is 0.13.0 (already shipped with sample sourcing). A command-only change ships as the next patch/minor - default **0.14.0** (new user-facing feature). Verify gh account first: `gh api user --jq .login` must be `ringo380`.

- [ ] **Step 2: Bump the three version locations**

Set `version = "0.14.0"` in `pyproject.toml` and `"version": "0.14.0"` in `.claude-plugin/plugin.json`, then:

```bash
cd /Users/ryanrobson/git/ableton-mcp-max && PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv lock
git add pyproject.toml .claude-plugin/plugin.json uv.lock
git commit -m "chore: version bump 0.13.0 -> 0.14.0 - produce orchestration command"
```

- [ ] **Step 3: Push, tag, release**

```bash
git push origin main
gh release create v0.14.0 --title v0.14.0 --notes "Add /ableton:produce orchestration command: autonomous brief -> foundation -> parts -> arrangement -> mix -> master with stage checkpoints."
```

- [ ] **Step 4: Bump the marketplace ref + rebuild README**

In `ringo380/robworks-claude-code-plugins`: set the `ableton` entry `ref` to `v0.14.0`, then `node scripts/build-readme.js`, commit, push. (See the `robworks-plugin-marketplace` note for the exact flow.)

- [ ] **Step 5: Verify the shipped chain**

```bash
git ls-remote --tags origin v0.14.0
git log origin/main..HEAD --oneline   # expect empty (both repos)
```

Confirm local `main` = `origin/main` = `git ls-remote` tag commit, and the marketplace `ableton` ref = v0.14.0. Update `PROGRESS.md` + memory `resume-state` to mark #4b shipped (the autonomous-track-production roadmap fully complete).

---

## Self-Review

**Spec coverage:**
- 6-stage model + checkpoint protocol -> Task 1 Steps 2,4. ✓
- Brief intake (parse + defaults + one AskUserQuestion + confirm) -> Task 1 Step 4 Stage 1. ✓
- Inline genre table -> Task 1 Step 3. ✓
- Auto-fire audition -> Task 1 Step 2 (protocol) + each stage's checkpoint line. ✓
- Reference siblings, inline orchestration -> Task 1 Step 4 (every stage references new-track/analyze/best-practices). ✓
- Tap gate (offer deploy, else un-metered) -> Task 1 Step 4 Stage 5. ✓
- Failure posture + write-lag verification -> Task 1 Steps 2,4 ("Failure and cleanup", verify-before-advance). ✓
- No code change / counts unchanged -> Task 2. ✓
- Live verification (per stage, checkpoint loop, tap gate both ways) -> Task 3. ✓
- Packaging / command-only release -> Task 4. ✓
- Honest limits surfaced -> Task 1 Step 1. ✓

**Placeholder scan:** Genre-table anchor values are concrete (not "TBD"); the "implementer's call to finalize" note is a legitimate latitude, not a missing requirement. No "add error handling"-style placeholders. ✓

**Type consistency:** No code types in this plan; tool names referenced match the shipped MCP tool list (verified against the deferred-tool roster). Version string `0.14.0` is consistent across Task 4 steps. ✓
