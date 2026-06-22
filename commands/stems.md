---
description: Separate an audio file into stems and lay each onto its own Arrangement track in Ableton Live.
---

# /ableton:stems

Separate the audio file at `$ARGUMENTS` into stems with Demucs, detect its tempo
and key, set those on the open Live set, and place each stem on its own audio
track at bar 1 of the Arrangement (Warp OFF).

> Load the tool if deferred: `ToolSearch select:mcp__AbletonMCPMax__separate_stems_to_arrangement`

## Workflow

### 1. Resolve the audio path

Parse `$ARGUMENTS` for the first token as the audio file path. If no path is given,
ask the user for one.

### 2. Determine fresh mode and confirm if needed

Check whether the user passed `fresh` as an argument, or they explicitly requested a brand-new set.
If **fresh mode is on**:
- **WARN the user:** Fresh mode bounces Live to a blank set and **DISCARDS the currently open set's unsaved changes.** This is irreversible.
- **ASK for explicit confirmation:** "Are you sure? This will discard unsaved changes and restart Live with a blank set. Please make sure Live is ready, then confirm to proceed."
- **Only call the tool if the user confirms.** If they cancel, stop here.

If fresh mode is off, proceed directly to the tool call (stems are appended to the open set).

### 3. Call the stem separation tool

Call `mcp__AbletonMCPMax__separate_stems_to_arrangement` (or the AbletonDev equivalent during development) with:
- `audio_path` - the resolved path
- `model` - default to `htdemucs` (the user can override via argument if needed)
- `fresh` - `true` if fresh mode confirmed, `false` otherwise

### 4. Report the result

Read the returned JSON:
- Report the **detected tempo** and **detected key** of the audio.
- Report the **model used** (e.g. htdemucs).
- Report the **list of stem tracks created** (e.g. vocals, drums, bass, other).
- If any stem shows `loaded: false` or an error, surface it prominently. Common cases:
  - Demucs not installed - point the user to the README under "Stem separation" prerequisites (demucs CLI, librosa).
  - Audio file not found or unsupported format - prompt the user to verify the path and format.

## Notes

- Demucs separation can take a few minutes for a full song. That runs before any Ableton call, so the Live connection will not time out.
- Prerequisites (demucs CLI, librosa) are documented in the README under "Stem separation".
