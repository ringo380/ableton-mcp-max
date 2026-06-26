# Equipped Fresh Projects Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the `ableton` plugin equip any fresh Claude Code music project with always-on tool-usage etiquette, seven on-trigger production skills, and a per-project bootstrap.

**Architecture:** Three layers shipped inside the plugin. Layer 1 is a SessionStart hook that prints a distilled etiquette core (and a project-file pointer) only in music contexts. Layer 2 is a `skills/` library of seven domain skills that auto-load on relevant tasks. Layer 3 is an `/ableton:init-project` command backed by a testable scaffold script that writes per-project state files. The plugin stays the single source of truth; project files hold only project-specific state.

**Tech Stack:** Python 3.13 (uv-managed, pytest offline gate), Claude Code plugin hooks (`hooks/hooks.json` + `${CLAUDE_PLUGIN_ROOT}` scripts), plugin skills (`SKILL.md` frontmatter), command markdown.

## Global Constraints

- Embedded Remote Script stays Py2/3.7-safe; **this work touches host-side only** (hooks, skills, commands, scripts run under the plugin's uv env / shell) - no Remote Script changes.
- Run tests with `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q` (the `/usr/bin` clobber drops the pyenv `uv` shim).
- Offline gate per CLAUDE.md: pytest + `uv run python -c "import ableton_mcp_max.server"` + `py_compile` the handler. Do NOT reformat existing files to ruff style.
- **No AI attribution** anywhere (commit messages, command/skill text, docs) - public repo. No `CLAUDE.md` generated into projects (global gitignore swallows it; AI-tell).
- Use only the standard hyphen `-` in all authored content. No em/en dashes.
- New scripts live under `scripts/` (Python) following existing test patterns in `tests/`.
- Command frontmatter pattern (from `commands/setup.md`): `description:`, optional `disable-model-invocation: true`, `allowed-tools: [...]`.
- Skill description budget is finite: keep each `description` tight; verify with `/doctor` after adding all seven.
- Version bump target: **v0.24.0** across `pyproject.toml` + `.claude-plugin/plugin.json` + `uv lock`.

---

### Task 1: SessionStart hook - etiquette core + project detection

**Files:**
- Create: `scripts/orient_hook.py`
- Create: `hooks/scripts/orient.sh` (thin launcher → runs `orient_hook.py` via uv)
- Create: `hooks/hooks.json`
- Test: `tests/test_orient_hook.py`

**Interfaces:**
- Produces: `build_orientation(brief_exists: bool, live_running: bool) -> str` in `scripts/orient_hook.py` - returns the text to print (empty string when neither condition holds). `main()` reads cwd + runs `pgrep` and prints `build_orientation(...)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_orient_hook.py
import importlib.util, pathlib
spec = importlib.util.spec_from_file_location(
    "orient_hook",
    pathlib.Path(__file__).resolve().parent.parent / "scripts" / "orient_hook.py",
)
orient_hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(orient_hook)


def test_silent_when_no_music_context():
    assert orient_hook.build_orientation(brief_exists=False, live_running=False) == ""


def test_core_printed_when_live_running():
    out = orient_hook.build_orientation(brief_exists=False, live_running=True)
    assert "extended" in out.lower()          # MIDI extended-API rule present
    assert "track_type" in out                # device-tool asymmetry present
    assert "project-brief.md" not in out      # no pointer without a brief


def test_brief_pointer_appended_when_brief_exists():
    out = orient_hook.build_orientation(brief_exists=True, live_running=False)
    assert "project-brief.md" in out
    assert "decisions.md" in out
    assert "samples.md" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_orient_hook.py -q`
Expected: FAIL (`No such file or directory` / module load error - `scripts/orient_hook.py` does not exist yet).

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/orient_hook.py
"""SessionStart orientation for the ableton plugin.

Prints a distilled tool-usage core when a music context is detected
(Ableton Live running, or a project-brief.md in the cwd), plus a pointer
to per-project state files. Silent otherwise.
"""
import os
import pathlib
import shutil
import subprocess
import sys

CORE = """\
Ableton MCP active. Cardinal rules for driving Live reliably:
- Every tool returns {ok, data|error}; check `ok`, never string-sniff for "Error".
- Re-read state every session: get_session_info + get_track_info first. The open set
  changes between sessions - never carry a track index forward.
- Write-lag: song-level writes (transport/record/loop/tempo/scenes) apply async; the
  returned confirmation is often the pre-write value. Verify with a SEPARATE read. After
  undo/redo, structural reads can be stale for one call - read twice.
- MIDI notes: use the extended API only (add_notes_to_clip / replace_clip_notes /
  modify_clip_notes / remove_clip_notes). Never legacy set_notes/remove_notes (blocking
  modal -> socket timeout). quantize_clip is safe.
- Loading devices HOT-SWAPS: load_instrument_or_effect / load_preset / load_drum_kit
  REPLACE the track's instrument. Experiment on an empty track, delete_device after.
- Device-tool asymmetry: get_device_parameters / set_device_parameter are regular-track
  only; get_device_info / get_rack_macros / set_rack_macro / set_chain_property /
  set_device_on / delete_device take track_type and reach return/master devices.
- Return/master/group tracks have no .arm; group tracks have no monitoring. Probe optional
  endpoints defensively. No LOM call creates a group track (UI-only).
- undo is GLOBAL (it undoes user hand-edits too).
- "Could not connect to Ableton" right after a restart: just retry while the server
  reconnects. Run /ableton:setup if it persists.
- For deep how-to (mixing, mastering, sound design, arrangement, MIDI, samples, analysis)
  the ableton-* skills auto-load when you start that kind of task.
"""

BRIEF_POINTER = """\
Music project detected. Before acting, read project-brief.md (creative goal),
decisions.md (what's been done), and samples.md (audio palette). Append outcomes to
decisions.md as you work. Run /ableton:init-project to (re)scaffold these.
"""


def build_orientation(brief_exists: bool, live_running: bool) -> str:
    if not brief_exists and not live_running:
        return ""
    out = CORE
    if brief_exists:
        out = out + "\n" + BRIEF_POINTER
    return out


def _live_running() -> bool:
    if shutil.which("pgrep") is None:
        return False
    try:
        return (
            subprocess.run(
                ["pgrep", "-f", "Ableton Live"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            ).returncode
            == 0
        )
    except Exception:
        return False


def main() -> None:
    cwd = pathlib.Path(os.getcwd())
    brief_exists = (cwd / "project-brief.md").is_file()
    text = build_orientation(brief_exists=brief_exists, live_running=_live_running())
    if text:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_orient_hook.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Create the hook launcher**

```bash
# hooks/scripts/orient.sh
#!/usr/bin/env bash
# SessionStart orientation launcher for the ableton plugin.
exec uv run --directory "$CLAUDE_PLUGIN_ROOT" python "$CLAUDE_PLUGIN_ROOT/scripts/orient_hook.py"
```

Then: `chmod +x hooks/scripts/orient.sh`

- [ ] **Step 6: Register the hook**

```json
// hooks/hooks.json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/orient.sh"
          }
        ]
      }
    ]
  }
}
```

- [ ] **Step 7: Smoke-test the launcher in a music context**

Run: `cd /tmp && touch project-brief.md && CLAUDE_PLUGIN_ROOT="$OLDPWD" bash "$OLDPWD/hooks/scripts/orient.sh"; rm -f /tmp/project-brief.md`
Expected: prints the CORE text followed by the BRIEF_POINTER.

- [ ] **Step 8: Commit**

```bash
git add scripts/orient_hook.py hooks/scripts/orient.sh hooks/hooks.json tests/test_orient_hook.py
git commit -m "feat(hook): SessionStart etiquette core + music-project detection"
```

---

### Tasks 2-8: The seven on-trigger skills

Each skill is a markdown `SKILL.md` - there is no unit test; the verification is
`claude plugin validate` (manifest still valid), `/doctor` (descriptions fit budget,
checked once after all seven in Task 8), and a content checklist. Each skill body MUST:
name the exact tools it governs, state the domain gotchas, and end with a short
checklist. Pull verbatim gotchas from `commands/best-practices.md` where relevant; do NOT
duplicate the full etiquette core (the hook owns that) - link to it conceptually.

Keep each `SKILL.md` under ~500 lines; push deep tables into a sibling reference file.

> **Skill `description:` writing rule:** lead with what the skill IS, then a trigger
> phrase ("Use when ..."). Keep under ~200 chars so all seven fit the listing budget.

---

### Task 2: Skill - ableton-mixing

**Files:**
- Create: `skills/ableton-mixing/SKILL.md`

- [ ] **Step 1: Write `skills/ableton-mixing/SKILL.md`**

````markdown
---
name: ableton-mixing
description: Balancing levels, gain staging, panning, sends/returns, and headroom in an Ableton Live set. Use when mixing, balancing tracks, fixing levels, setting up reverb/delay sends, or chasing headroom/clipping.
---

# Ableton mixing

Goal: a balanced, headroom-safe mix before mastering. Work from measurement, not guesswork.

## Tools
- Measure first: `measure_mix` (per-track levels/balance snapshot), `read_meter` /
  `read_track_meter` (live metering), `check_clipping` (find tracks/master over 0 dBFS).
- Act: `gain_stage_track` and `adjust_track_gain` (trim toward target headroom),
  `balance_mix` (rebalance toward a reference distribution), `set_mixer_property`
  (volume/pan/sends), `get_mixer` / `get_routing` (inspect).
- Sends/returns: create reverb/delay on a return track (`create_return_track` +
  `load_instrument_or_effect` with `track_type='return'`), then dial `sends[i]` via
  `set_mixer_property`. Reach return-device params with the `track_type`-aware device tools.

## Principles
- Target ~ -6 dBFS of headroom on the master before the limiter; no track should pin the
  meter. Stage gain BEFORE EQ/compression so downstream devices see sane levels.
- Pan for width, not for fixing masking - carve with EQ first.
- Reverb/delay belong on returns (shared, CPU-cheap), not as inserts on every track.

## Gotchas
- Device-tool asymmetry: `get_device_parameters`/`set_device_parameter` are regular-track
  only; use the `track_type`-aware tools for return/master devices.
- Mixer writes can lag their read-back - confirm with a separate `get_mixer`.
- Re-read `get_session_info` first; track indices change between sessions.

## Checklist
- [ ] Measured the mix (`measure_mix` / `check_clipping`) before touching faders.
- [ ] No clipping on tracks or master; ~ -6 dBFS master headroom preserved.
- [ ] Time-based FX on returns, not duplicated as inserts.
- [ ] Logged the moves to decisions.md.
````

- [ ] **Step 2: Validate the manifest still parses**

Run: `/Users/ryanrobson/.local/bin/claude plugin validate .`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add skills/ableton-mixing/SKILL.md
git commit -m "feat(skill): ableton-mixing"
```

---

### Task 3: Skill - ableton-mastering

**Files:**
- Create: `skills/ableton-mastering/SKILL.md`
- Create: `skills/ableton-mastering/loudness-targets.md`

- [ ] **Step 1: Write `skills/ableton-mastering/loudness-targets.md`**

```markdown
# Streaming loudness targets (integrated LUFS / true-peak ceiling)

- Spotify / Amazon / YouTube: -14 LUFS, -1 dBTP
- Apple Music: -16 LUFS, -1 dBTP
- Club / DJ / loud masters: -8 to -6 LUFS (true-peak still <= -1 dBTP)
- Always leave >= 1 dB true-peak headroom to survive lossy encoding.
```

- [ ] **Step 2: Write `skills/ableton-mastering/SKILL.md`**

````markdown
---
name: ableton-mastering
description: Finalizing a mix to a target loudness with limiting, metering, and reference matching on the Ableton master chain. Use when mastering, hitting a LUFS target, taming true-peaks, or matching a reference loudness.
---

# Ableton mastering

Goal: hit a platform loudness target while preserving dynamics and avoiding true-peak
clipping. Master only a clean, headroom-safe mix.

## Tools
- Measure: `measure_loudness` (integrated LUFS / peaks), `check_clipping`,
  the master audio tap for metering.
- Master chain: inspect/adjust with the `track_type='master'` device tools
  (`get_device_info`, `get_device_parameters`/`set_device_parameter` are regular-only -
  use `get_rack_macros`/`set_chain_property`/`set_device_on` for the master rack/limiter).
- Load master devices with `load_instrument_or_effect` / `load_preset` (`track_type='master'`).

## Principles
- Read `loudness-targets.md` and pick the target from the project brief (default -14 LUFS,
  -1 dBTP if unstated).
- Gain into the limiter, do not slam it; aim for <= 3 dB gain reduction on peaks.
- Re-measure after every change - master by the meter, then by ear against a reference.

## Gotchas
- `measure_loudness` needs audio actually playing through the master.
- Master-device raw param read/write is not available via `set_device_parameter`; drive
  the limiter through the rack/chain tools.

## Checklist
- [ ] Target read from brief (or default applied + noted).
- [ ] Integrated LUFS within ~1 LU of target; true-peak <= -1 dBTP.
- [ ] Compared against a reference track.
- [ ] Logged target + final readings to decisions.md.
````

- [ ] **Step 3: Validate + commit**

```bash
/Users/ryanrobson/.local/bin/claude plugin validate .
git add skills/ableton-mastering/
git commit -m "feat(skill): ableton-mastering"
```

---

### Task 4: Skill - ableton-sound-design

**Files:**
- Create: `skills/ableton-sound-design/SKILL.md`

- [ ] **Step 1: Write `skills/ableton-sound-design/SKILL.md`**

````markdown
---
name: ableton-sound-design
description: Designing instrument and effect sounds in Ableton Live - preset selection, Wavetable/Simpler patches, rack macros, and layering. Use when designing a sound, building a patch, choosing/creating presets, or mapping rack macros.
---

# Ableton sound design

Goal: a fit-for-purpose instrument/effect sound, repeatable via presets and rack macros.

## Tools
- Discover/load: `get_browser_tree` / `get_browser_items_at_path`, `list_device_presets`,
  `load_instrument_or_effect`, `load_preset`.
- Probe a live instance FIRST with `get_device_parameters` - most choosers ARE automatable
  (filter type, osc wave, ADSR) so just `set_device_parameter`.
- Backdoor (genuinely hidden state only): `create_wavetable_preset` (table + unison),
  `create_simpler_instrument` (sample ref), `list_wavetable_tables`.
- Racks: `inspect_rack_preset`, `clone_rack`, `rename_rack_macros`, `set_rack_zones`,
  `add_rack_macro_mappings`, `get_rack_macros` / `set_rack_macro`.

## Principles
- Reach for the backdoor only for hidden state (sample refs, wavetable selection, macro
  mappings). Everything automatable goes through `set_device_parameter`.
- Map the controls that matter to rack macros (1..16) so a sound stays playable/automatable.
- Layer for thickness (e.g. sub + body + air), then carve overlap with EQ.

## Gotchas
- Loading HOT-SWAPS - design on an empty/scratch track, never over a patch you need.
- Verify a macro mapping by reloading and reading `get_rack_macros`: a single-mapped
  unnamed macro auto-renames to its target param (proof it bound).

## Checklist
- [ ] Probed params before assuming a backdoor was needed.
- [ ] Key controls mapped to macros.
- [ ] Saved/loaded as a preset where reuse matters.
````

- [ ] **Step 2: Validate + commit**

```bash
/Users/ryanrobson/.local/bin/claude plugin validate .
git add skills/ableton-sound-design/SKILL.md
git commit -m "feat(skill): ableton-sound-design"
```

---

### Task 5: Skill - ableton-arrangement

**Files:**
- Create: `skills/ableton-arrangement/SKILL.md`

- [ ] **Step 1: Write `skills/ableton-arrangement/SKILL.md`**

````markdown
---
name: ableton-arrangement
description: Building song structure and energy in the Ableton arrangement - sections, scenes, cue points, transitions, and timeline automation. Use when arranging a track, building sections (intro/drop/breakdown), adding automation, or shaping energy over time.
---

# Ableton arrangement

Goal: a full-length arrangement with deliberate energy and clean transitions.

## Tools
- Structure: `build_arrangement`, `get_arrangement_structure`, `get_arrangement_clips`,
  `duplicate_clip_to_arrangement`, `delete_arrangement_clip`, `set_arrangement_loop`.
- Scenes/cues: `create_scene` / `duplicate_scene` / `capture_and_insert_scene`,
  `create_cue_point` / `jump_to_cue`.
- Automation: `set_arrangement_automation` (timeline envelopes), `get_automation` /
  `set_automation` (clip envelopes, regular tracks).

## Principles
- Map sections to a target energy curve from the brief (intro -> build -> drop ->
  breakdown -> outro). Use cue points as section markers.
- Transitions sell the arrangement: automate filter sweeps, risers, and mute/unmute at
  section boundaries.
- Build with session clips, then commit to the arrangement.

## Gotchas
- Arrangement automation writes via the value-probe backdoor; on Live 12 envelopes need
  point Ids or a corrupt load - the tool handles this, but reload to confirm round-trip.
- Clip-envelope reads are sampled only (no breakpoint enumeration); sample slightly inside
  a step (the exact left edge returns the pre-step value).

## Checklist
- [ ] Sections match the brief's energy intent; cue points placed.
- [ ] Transitions automated at boundaries.
- [ ] Logged the structure to decisions.md.
````

- [ ] **Step 2: Validate + commit**

```bash
/Users/ryanrobson/.local/bin/claude plugin validate .
git add skills/ableton-arrangement/SKILL.md
git commit -m "feat(skill): ableton-arrangement"
```

---

### Task 6: Skill - ableton-midi-composition

**Files:**
- Create: `skills/ableton-midi-composition/SKILL.md`

- [ ] **Step 1: Write `skills/ableton-midi-composition/SKILL.md`**

````markdown
---
name: ableton-midi-composition
description: Writing and editing MIDI in Ableton Live - chords, basslines, melodies, drum patterns, plus humanize/swing/quantize/scale and groove. Use when composing MIDI, generating chords/bass/melody/drums, quantizing, humanizing, or applying groove.
---

# Ableton MIDI composition

Goal: musical, in-key MIDI parts with human feel.

## Tools
- Generate: `generate_chord_progression`, `generate_bassline`, `generate_melody`,
  `generate_drum_pattern`.
- Edit notes (extended API): `add_notes_to_clip`, `replace_clip_notes`,
  `modify_clip_notes`, `remove_clip_notes`, `get_clip_notes`.
- Feel: `humanize_clip`, `swing_clip`, `quantize_clip`, `quantize_clip_to_scale`,
  `arpeggiate_clip`, `harmonize_clip`. Scale: `set_song_scale`.
- Groove: `get_groove_pool`, `assign_groove_to_clip`, `set_groove_amount`,
  `load_groove_to_pool`, `search_grooves`, `set_swing_amount`.

## Principles
- Set the song key/scale from the brief; `quantize_clip_to_scale` to keep parts in key.
- Compose, then humanize - tiny timing/velocity variance beats dead-grid MIDI.
- Edit notes in place by `note_id` (`modify_clip_notes`), not remove + re-add.

## Gotchas
- NEVER legacy set_notes/remove_notes (blocking modal -> socket timeout). Extended API only.
- Groove vs swing are distinct: `set_swing_amount` only affects FUTURE quantize ops;
  `swing_clip` bakes swing into existing notes; `assign_groove_to_clip` applies a pool
  groove non-destructively (scaled by `set_groove_amount`). A groove must already be in the
  pool to assign it.

## Checklist
- [ ] Parts in the project key/scale.
- [ ] Humanized; not dead-grid.
- [ ] Used the extended note API throughout.
````

- [ ] **Step 2: Validate + commit**

```bash
/Users/ryanrobson/.local/bin/claude plugin validate .
git add skills/ableton-midi-composition/SKILL.md
git commit -m "feat(skill): ableton-midi-composition"
```

---

### Task 7: Skill - ableton-sample-use

**Files:**
- Create: `skills/ableton-sample-use/SKILL.md`

- [ ] **Step 1: Write `skills/ableton-sample-use/SKILL.md`**

````markdown
---
name: ableton-sample-use
description: Working with audio samples in Ableton Live - finding/loading clips, building drum racks, warping, and stem separation. Use when adding samples, loading audio, building a drum kit, chopping/warping audio, or separating stems.
---

# Ableton sample use

Goal: the right audio in the right place, warped and gain-staged to fit.

## Tools
- Find/load: `search_samples`, `load_audio_clip`.
- Drums: `load_drum_kit`, `populate_drum_rack`, `load_sample_to_drum_pad`.
- Stems: `separate_stems_to_arrangement` (Demucs unmix onto arrangement tracks).
- Pointers: read `samples.md` for the project's sample/stem/reference locations.

## Principles
- Consult `samples.md` first - use the project's curated palette before hunting factory content.
- Warp loops to the set tempo; one-shots usually unwarped.
- Gain-stage loaded audio into the mix like any other track (see ableton-mixing).

## Gotchas
- Sample/drum loads HOT-SWAP onto the target - load onto an empty track for experiments.
- Stem separation lays each stem on its own arrangement track; expect auto-warp quirks -
  verify clip lengths after.
- Loud factory one-shots can clip - check with `check_clipping` after loading.

## Checklist
- [ ] Checked samples.md before sourcing new audio.
- [ ] Loops warped to tempo.
- [ ] No clipping introduced by loaded audio.
````

- [ ] **Step 2: Validate + commit**

```bash
/Users/ryanrobson/.local/bin/claude plugin validate .
git add skills/ableton-sample-use/SKILL.md
git commit -m "feat(skill): ableton-sample-use"
```

---

### Task 8: Skill - ableton-analysis (+ budget check for all seven)

**Files:**
- Create: `skills/ableton-analysis/SKILL.md`

- [ ] **Step 1: Write `skills/ableton-analysis/SKILL.md`**

````markdown
---
name: ableton-analysis
description: Auditing an Ableton Live set against best-practice rulesets and producing a remediation report - mix balance, loudness, key, health. Use when analyzing/reviewing a set, diagnosing mix issues, detecting key, or checking a project's health.
---

# Ableton analysis

Goal: an evidence-based read of the set and a prioritized remediation list.

## Tools
- `analyze_set` (curated rulesets -> findings), `apply_findings` (act on them).
- Measure: `measure_mix`, `measure_loudness`, `check_clipping`, `detect_key`
  (`source='auto'|'midi'|'audio'`).
- Inspect: `get_session_info`, `get_track_info`, `get_mixer`, `get_arrangement_structure`.

## Principles
- Read state first (`get_session_info` + `get_track_info`) - never assume track 0.
- Lead with measurements (`measure_mix` / `measure_loudness` / `check_clipping`), then
  rulesets, then a sectioned report ordered by severity.
- `detect_key` is content-based; cross-check against `matches_live` and the brief's key.

## Gotchas
- Reads can lag writes and undo/redo - re-read to confirm before reporting.
- Large readers cap with `limit` and report `truncated` - widen the path/limit if cut off.

## Checklist
- [ ] State re-read at start.
- [ ] Findings backed by measurements, ordered by severity.
- [ ] Report appended to decisions.md.
````

- [ ] **Step 2: Validate manifest**

Run: `/Users/ryanrobson/.local/bin/claude plugin validate .`
Expected: PASS.

- [ ] **Step 3: Description-budget check (all seven present)**

Ask the user to run `/doctor` in a fresh session and confirm none of the seven
`ableton-*` skill descriptions are dropped/truncated. If any are flagged, tighten the
offending `description:` lines (shorten to the IS + "Use when ..." trigger) and re-check.

- [ ] **Step 4: Commit**

```bash
git add skills/ableton-analysis/SKILL.md
git commit -m "feat(skill): ableton-analysis"
```

---

### Task 9: Per-project bootstrap - scaffold script + command

**Files:**
- Create: `scripts/init_project.py`
- Create: `commands/init-project.md`
- Test: `tests/test_init_project.py`

**Interfaces:**
- Produces: `scaffold(root: pathlib.Path) -> dict` in `scripts/init_project.py` - creates
  `project-brief.md`, `decisions.md`, `samples.md`, and `.claude/plans/` (with a
  `_template.md`) under `root`, NEVER overwriting an existing file. Returns
  `{"created": [...], "skipped": [...]}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_init_project.py
import importlib.util, pathlib
spec = importlib.util.spec_from_file_location(
    "init_project",
    pathlib.Path(__file__).resolve().parent.parent / "scripts" / "init_project.py",
)
init_project = importlib.util.module_from_spec(spec)
spec.loader.exec_module(init_project)


def test_scaffold_creates_all_artifacts(tmp_path):
    res = init_project.scaffold(tmp_path)
    assert (tmp_path / "project-brief.md").is_file()
    assert (tmp_path / "decisions.md").is_file()
    assert (tmp_path / "samples.md").is_file()
    assert (tmp_path / ".claude" / "plans" / "_template.md").is_file()
    assert set(res["skipped"]) == set()
    assert "project-brief.md" in res["created"]


def test_scaffold_no_clobber(tmp_path):
    (tmp_path / "project-brief.md").write_text("MY NOTES", encoding="utf-8")
    res = init_project.scaffold(tmp_path)
    assert (tmp_path / "project-brief.md").read_text(encoding="utf-8") == "MY NOTES"
    assert "project-brief.md" in res["skipped"]
    assert "project-brief.md" not in res["created"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_init_project.py -q`
Expected: FAIL (module not found - `scripts/init_project.py` does not exist).

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/init_project.py
"""Scaffold per-project state files for an Ableton music project.

Creates project-brief.md, decisions.md, samples.md, and .claude/plans/_template.md.
Never overwrites an existing file (no-clobber).
"""
import pathlib

BRIEF = """\
# Project brief

- Title:
- Genre / reference artists:
- Key / scale:
- Tempo (BPM):
- Target loudness (e.g. -14 LUFS / -1 dBTP):
- Mood / energy intent:
- Reference tracks (paths or links):
- Mix intent (what should sit forward, width, low-end plan):
- Master intent (loud club vs streaming-safe):
"""

DECISIONS = """\
# Decisions log

Append-only. Each session: what changed (tracks, parts, mix moves, master settings) and why.

## Session log
"""

SAMPLES = """\
# Sample inventory

Where this project's audio lives, so sample tools use the right palette.

- Drum one-shots:
- Loops:
- Vocals / stems:
- Bounced references:
"""

PLAN_TEMPLATE = """\
# [Title]
**Created**: YYYY-MM-DD
**Status**: In Progress | Complete | Abandoned

## Overview
## Tasks
- [ ] ...

## Verification
"""

FILES = {
    "project-brief.md": BRIEF,
    "decisions.md": DECISIONS,
    "samples.md": SAMPLES,
}


def scaffold(root: pathlib.Path) -> dict:
    root = pathlib.Path(root)
    created, skipped = [], []
    for name, content in FILES.items():
        target = root / name
        if target.exists():
            skipped.append(name)
        else:
            target.write_text(content, encoding="utf-8")
            created.append(name)
    plans_dir = root / ".claude" / "plans"
    plans_dir.mkdir(parents=True, exist_ok=True)
    tmpl = plans_dir / "_template.md"
    if tmpl.exists():
        skipped.append(".claude/plans/_template.md")
    else:
        tmpl.write_text(PLAN_TEMPLATE, encoding="utf-8")
        created.append(".claude/plans/_template.md")
    return {"created": created, "skipped": skipped}


def main() -> None:
    import os

    res = scaffold(pathlib.Path(os.getcwd()))
    for n in res["created"]:
        print("created " + n)
    for n in res["skipped"]:
        print("skipped (exists) " + n)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_init_project.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Write the command wrapper**

```markdown
<!-- commands/init-project.md -->
---
description: Scaffold a fresh Ableton music project - brief, decisions log, sample inventory, and a plans dir - then help fill the brief.
disable-model-invocation: true
allowed-tools: ["Bash", "Read", "Edit"]
---

# /ableton:init-project

Set up the current folder as an Ableton music project so every session is equipped.

## Scaffold the state files

Run the scaffold script (no-clobber - it never overwrites your edits):

```bash
uv run --directory "$CLAUDE_PLUGIN_ROOT" python "$CLAUDE_PLUGIN_ROOT/scripts/init_project.py"
```

This creates (if absent): `project-brief.md`, `decisions.md`, `samples.md`, and
`.claude/plans/_template.md`.

## Fill the brief

Open `project-brief.md` and interview the user to fill it in: title, genre/references,
key/scale, tempo, target loudness, mood, reference tracks, mix intent, master intent.
Write their answers into the file with the Edit tool. Leave fields blank rather than guessing.

## Point samples.md at the audio

Ask where the project's samples, loops, stems, and reference bounces live, and record those
locations in `samples.md`.

## Done

Tell the user: future sessions in this folder auto-detect the brief (via the SessionStart
hook) and read it before acting. Use `/ableton:produce` to start building, `/ableton:analyze`
to audit. Append decisions to `decisions.md` as you go.
```

- [ ] **Step 6: Validate + commit**

```bash
/Users/ryanrobson/.local/bin/claude plugin validate .
git add scripts/init_project.py commands/init-project.md tests/test_init_project.py
git commit -m "feat(command): /ableton:init-project bootstrap + scaffold script"
```

---

### Task 10: Wire existing commands to skills + project files

**Files:**
- Modify: `commands/produce.md`
- Modify: `commands/analyze.md`
- Modify: `commands/new-track.md`
- Modify: `commands/add-to-track.md`

- [ ] **Step 1: Add a project-context preamble to `produce.md` and `analyze.md`**

Near the top of each (after the frontmatter/intro), insert:

```markdown
## Project context (read first)

If `project-brief.md` exists in the project folder, read it (and `decisions.md`,
`samples.md`) before acting - it carries the creative goal, history, and sample palette.
If it does not exist, suggest `/ableton:init-project`. Append what you do to `decisions.md`.
```

- [ ] **Step 2: Add a skill pointer to each of the four commands**

Insert one line where the command starts doing domain work:

- `produce.md`: "Lean on the `ableton-*` skills as each stage comes up (sound-design, midi-composition, arrangement, mixing, mastering) - they auto-load; consult them for tool choice and gotchas."
- `analyze.md`: "Consult the `ableton-analysis` skill for the measure-first workflow and ruleset reporting."
- `new-track.md`: "Consult `ableton-sound-design` and `ableton-midi-composition` when building the track's instrument and parts."
- `add-to-track.md`: "Consult the relevant `ableton-*` skill (mixing, sound-design, midi-composition) for the change at hand."

- [ ] **Step 3: Verify commands still parse**

Run: `/Users/ryanrobson/.local/bin/claude plugin validate .`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add commands/produce.md commands/analyze.md commands/new-track.md commands/add-to-track.md
git commit -m "docs(commands): wire produce/analyze/new-track/add-to-track to skills + project files"
```

---

### Task 11: Version bump, docs regen, offline gate

**Files:**
- Modify: `pyproject.toml:3` (version)
- Modify: `.claude-plugin/plugin.json` (version + description mention of skills)
- Modify: `uv.lock` (via `uv lock`)
- Modify: `README.md`, `docs/index.md` (hardcoded counts/blurbs as needed)

- [ ] **Step 1: Bump version to 0.24.0**

Edit `pyproject.toml` line 3: `version = "0.24.0"`.
Edit `.claude-plugin/plugin.json`: `"version": "0.24.0"`, and extend the `description` to
mention "guided best-practice skills (mixing, mastering, sound design, arrangement, MIDI,
samples, analysis) and a per-project bootstrap."

- [ ] **Step 2: Sync the lockfile**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv lock`
Expected: `uv.lock` updated to version 0.24.0 (no dependency changes).

- [ ] **Step 3: Regenerate docs**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python scripts/build_tool_index.py && uv run python scripts/gen_docs_site.py`
Expected: tool index/docs regenerated. Tool COUNT is unchanged (no new `@mcp.tool()`),
so the hardcoded counts in `README.md:7` and `docs/index.md` do NOT need bumping - but
skim both for a skills/commands mention worth adding. Update by hand only if you add a line.

- [ ] **Step 4: Run the full offline gate**

Run:
```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python -c "import ableton_mcp_max.server; print('server import OK')"
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python -m py_compile remote_script/AbletonMCP/__init__.py
```
Expected: all pass (new `test_orient_hook.py` + `test_init_project.py` included), server
import OK, py_compile clean.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml .claude-plugin/plugin.json uv.lock README.md docs/
git commit -m "chore: v0.24.0 - ship orientation hook, 7 skills, init-project bootstrap"
```

---

### Task 12: Live verification (manual, one end-to-end pass)

**Files:** none (verification only).

- [ ] **Step 1: Scaffold a scratch project**

In a fresh temp folder, run `/ableton:init-project`; confirm the four artifacts appear and
the brief interview runs. Re-run it; confirm no-clobber (your edits survive).

- [ ] **Step 2: Confirm the hook fires**

With Ableton Live running, start a new Claude Code session in that folder; confirm the
SessionStart orientation prints the core + the project-brief pointer. In an unrelated repo
(no brief, Live closed), confirm it stays silent.

- [ ] **Step 3: Confirm a skill auto-loads**

Ask for a mixing task ("balance the levels on the open set"); confirm `ableton-mixing`
auto-loads and the workflow follows measure-first. Spot-check one more (e.g. mastering).

- [ ] **Step 4: Record results**

Note outcomes in PROGRESS.md (per project convention). If all pass, the feature is ready
for the release chain (tag v0.24.0 -> marketplace `ref` bump -> push).

---

## Self-Review

**Spec coverage:**
- Layer 1 (hook core + project detection) -> Task 1. ✓
- Layer 2 (7 skills) -> Tasks 2-8 (mixing, mastering, sound-design, arrangement,
  midi-composition, sample-use, analysis). ✓
- Layer 3 (bootstrap: brief, decisions, samples, plans scaffold) -> Task 9. ✓
- Commands consult skills + read/append project files -> Task 10. ✓
- No generated CLAUDE.md -> honored (Task 9 writes plain files only). ✓
- Hook silent in non-music projects -> Task 1 `build_orientation` + test. ✓
- init-project no-clobber -> Task 9 `test_scaffold_no_clobber`. ✓
- Description budget check -> Task 8 Step 3. ✓
- Testing/verification (hook unit, scaffold unit, validate, live pass) -> Tasks 1, 9, 12. ✓
- Version bump + release impact -> Task 11 (+ release chain noted in Task 12). ✓

**Placeholder scan:** No "TBD"/"handle edge cases"/"write tests for the above" - all code
and test bodies are concrete. Skill bodies are full markdown, not stubs. ✓

**Type consistency:** `build_orientation(brief_exists, live_running) -> str` (Task 1) and
`scaffold(root) -> {"created", "skipped"}` (Task 9) are used consistently in their tests
and command wrappers. Skill `name:` slugs (`ableton-mixing` ... `ableton-analysis`) match
the command pointers in Task 10. ✓

**Decisions locked from spec review:** hook in Python (testable); init-project re-run =
skip-with-notice (no-clobber, reported in `skipped`).
