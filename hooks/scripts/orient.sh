#!/usr/bin/env bash
# SessionStart orientation launcher for the ableton plugin.
# Capture the session cwd before uv --directory changes it.
exec env ORIENT_PWD="$PWD" uv run --directory "$CLAUDE_PLUGIN_ROOT" python "$CLAUDE_PLUGIN_ROOT/scripts/orient_hook.py"
