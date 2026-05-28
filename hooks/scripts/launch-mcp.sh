#!/bin/sh
# ableton-mcp-max plugin launcher.
#
# Runs the bundled FastMCP server (ableton_mcp_max.server:main) via `uv`,
# resolving the project's virtualenv inside this plugin's clone directory.
# The server speaks stdio JSON-RPC to the MCP host and connects to Ableton
# Live's Remote Script over localhost:9877 (see /ableton:setup).
#
# All diagnostics go to stderr so they never corrupt the stdout JSON-RPC channel.

set -u

# CLAUDE_PLUGIN_ROOT is set by Claude Code when invoking plugin scripts.
# Fall back to this script's own location for manual / alt-host invocation.
: "${CLAUDE_PLUGIN_ROOT:=$(cd "$(dirname "$0")/../.." 2>/dev/null && pwd)}"

if ! command -v uv >/dev/null 2>&1; then
    echo "[ableton-mcp-max] 'uv' not found on PATH. Install it: https://docs.astral.sh/uv/" 1>&2
    exit 127
fi

# `uv run` creates/syncs the venv on first launch from pyproject.toml + uv.lock.
exec uv run --directory "$CLAUDE_PLUGIN_ROOT" ableton-mcp-max "$@"
