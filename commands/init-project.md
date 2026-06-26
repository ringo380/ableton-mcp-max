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
