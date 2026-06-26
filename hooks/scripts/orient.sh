#!/usr/bin/env bash
# SessionStart orientation launcher for the ableton plugin.
# Capture the session cwd before uv --directory changes it.
# A SessionStart hook must never fail the session: swallow any error and exit 0
# (uv missing, the script crashing, or a closed output pipe must all be harmless).
env ORIENT_PWD="$PWD" uv run --directory "$CLAUDE_PLUGIN_ROOT" python "$CLAUDE_PLUGIN_ROOT/scripts/orient_hook.py" || true
exit 0
