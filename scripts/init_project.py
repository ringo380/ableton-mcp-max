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
