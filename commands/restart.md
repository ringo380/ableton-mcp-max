---
description: Gracefully quit and relaunch Ableton Live via the MCP, prompting before discarding any unsaved changes - for an automated Live bounce after a Remote Script change.
allowed-tools: ["Bash"]
---

# /ableton:restart

Bounce Ableton Live cleanly and automatically - quit, relaunch, and wait for the control surface to reconnect - without the crash-recovery prompt that a hard `kill` would cause. Use this after reinstalling the Remote Script (an `.amxd`/handler change), or any time you want a fresh Live with the surface reconnected.

> Load the tool if deferred: `ToolSearch select:mcp__AbletonMCPMax__restart_live`

## Why a command (not just the tool)

The Live Object Model exposes **no save-state flag and no save API**, so we cannot know in advance whether the open set has unsaved changes - Live only reveals it by showing a "Save changes before quitting?" dialog. Discarding unsaved work is irreversible, so this command **asks you first**, then calls the tool with your decision. The tool only actually acts on that decision if the set turns out to be dirty.

## Workflow

### 1. Confirm intent + save policy (ALWAYS ask first)

Use **AskUserQuestion** before doing anything:

> "Restart Ableton Live now? If the open set has unsaved changes, how should I handle them?"
> - **Save and restart** - overwrite the existing set, then bounce. (Only works if the set already has a file; an Untitled set has no path.)
> - **Discard and restart** - lose unsaved changes, then bounce. *Irreversible.*
> - **Cancel** - do nothing.

If **Cancel**, stop here.

### 2. Run the bounce

Call `restart_live`:
- **Discard and restart** → `restart_live(save="discard")`
- **Save and restart** → `restart_live(save="save")`

The tool fires the Apple `quit` event, detects whether a save dialog appeared (i.e. the set was dirty), answers it per your choice (⌘⌫ Don't Save / Return Save), waits for Live to exit, relaunches it, and waits up to ~90s for the control surface to rebind port 9877.

### 3. Report the result

Read the returned JSON `data`:
- `was_dirty` - whether the set actually had unsaved changes.
- `quit` / `relaunched` / `surface_up` - the bounce outcome.
- If `quit` is **false** with an error about an **Untitled set / file path**: the user chose Save on a set that has never been saved, so Live opened a Save-As path dialog the tool can't fill. Tell the user to **save the set by hand once** (give it a name), then re-run - or re-run choosing Discard.
- If `surface_up` is **false**: Live relaunched but the surface hasn't bound 9877 yet (slow cold boot, or the control surface got deselected). Tell the user to check **Settings → Link, Tempo & MIDI → Control Surface = AbletonMCP**.

### 4. Remind about the Claude Code restart (if relevant)

This restarts **Ableton only**. The MCP server cannot restart its own process, so:
- A **Remote Script** change (`remote_script/...`/`.amxd`) is fully handled by reinstalling the script + this bounce - no Claude Code restart needed.
- A **`server.py` / `*_utils.py`** change still needs the **user to restart Claude Code** (the MCP server loads at session start). Say so explicitly if the edit touched the host side.

## Notes

- `restart_live` targets whichever Live is listening on 9877 (the one the MCP talks to), so it bounces the correct version on a multi-version machine.
- Answering the save dialog uses macOS System Events; if it ever silently fails to quit, the host may need Accessibility permission for the controlling process - the tool reports `quit: false` in that case.
