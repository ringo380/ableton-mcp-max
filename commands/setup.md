---
description: Guided first-run setup for the ableton plugin — sync deps, install the Live Remote Script, select the Control Surface, and verify the connection.
disable-model-invocation: true
allowed-tools: ["Bash", "Read"]
---

# /ableton:setup

Take the user from "plugin enabled" to "issuing Ableton Live commands from Claude Code" in one session. Works on **macOS and Windows** - each step below gives both; run the one for the user's OS.

This plugin has **two halves** that both must be in place:

1. **The MCP server** (bundled in this plugin) — launches automatically over stdio. It speaks to Live over `localhost:9877`.
2. **The Remote Script** inside Ableton Live — the other end of that socket. It is NOT installed automatically; this command installs it and walks you through enabling it.

> The native "Authenticate" button in the `/mcp` dialog only applies to HTTP/OAuth-transport servers. This server is stdio, so this command is the supported setup flow. If MCP tools error with "Could not connect to Ableton", the Remote Script half isn't running yet — work through the steps below.

## Pre-flight

1. Confirm `uv` is installed (the server launcher needs it):
   ```bash
   command -v uv || echo "MISSING — install from https://docs.astral.sh/uv/"
   ```

2. Confirm Ableton Live (11 or 12) is present:
   - macOS:
     ```bash
     ls -d /Applications/Ableton*Live*.app 2>/dev/null || echo "Ableton Live not found at the default path — ask the user where Live is installed."
     ```
   - Windows:
     ```bash
     ls -d "/c/ProgramData/Ableton/Live"* 2>/dev/null || echo "Ableton Live not found under C:\ProgramData\Ableton - ask the user where Live is installed."
     ```

3. Warm the server venv so the first MCP call doesn't time out (creates/syncs the venv from `uv.lock`):
   ```bash
   uv run --directory "$CLAUDE_PLUGIN_ROOT" python -c "import ableton_mcp_max.server; print('server import OK')"
   ```

## Install the Remote Script

The repo ships an installer per OS. Each copies the Remote Script into every installed Live's `MIDI Remote Scripts` folder and backs up any existing install (outside that folder - Live would try to import a backup).

- macOS - `install_remote_script.sh` also fixes ownership (Live silently skips root-owned script folders). It prompts for `sudo` (writes into the app bundle):
  ```bash
  bash "$CLAUDE_PLUGIN_ROOT/scripts/install_remote_script.sh"
  ```
- Windows - installs into `C:\ProgramData\Ableton\Live <edition>\Resources\MIDI Remote Scripts\AbletonMCP`:
  ```bash
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$CLAUDE_PLUGIN_ROOT/scripts/install_remote_script.ps1"
  ```

On success it prints the destination path.

## Enable the Control Surface (manual — user does this in Live)

Tell the user to:

1. Open **Ableton Live** (or quit + reopen if it was already running — Live only scans Remote Scripts at launch).
2. Open the settings: **Live > Settings** on macOS, **Options > Settings** on Windows, then the **Link, Tempo & MIDI** tab (named "Link/MIDI" in some versions).
3. Under **Control Surface**, pick **AbletonMCP** from the dropdown. Leave Input/Output as None (the script uses a socket, not MIDI ports).
4. Live is now listening on `localhost:9877`.

## Verify

Run a smoke check through the MCP server (load the tool first if deferred: `ToolSearch select:mcp__AbletonMCPMax__get_session_info`):

- Call `get_session_info`. A JSON blob with track/scene/tempo info means both halves are connected.
- The **first** call right after enabling the surface (or after any Claude Code restart) can fail while the server reconnects — just retry once.

If it still fails:
- macOS:
  ```bash
  pgrep -fl "Ableton Live" || echo "Live is not running"
  lsof -nP -iTCP:9877 -sTCP:LISTEN || echo "Nothing listening on 9877 — Control Surface not selected, or Live needs a restart"
  ```
  Remote Script load errors are logged in `~/Library/Preferences/Ableton/Live 1[12]*/Log.txt` (grep for `AbletonMCP` or `Traceback`).
- Windows:
  ```bash
  tasklist //FI "IMAGENAME eq Ableton Live*" || echo "Live is not running"
  netstat -ano | grep ":9877 " || echo "Nothing listening on 9877 - Control Surface not selected, or Live needs a restart"
  ```
  Remote Script load errors are logged in `%APPDATA%\Ableton\Live <version>\Preferences\Log.txt` (grep for `AbletonMCP` or `Traceback`).

## Done

Once `get_session_info` returns, point the user at `/ableton:new-track`, `/ableton:add-to-track`, and `/ableton:best-practices` for workflow guidance.
