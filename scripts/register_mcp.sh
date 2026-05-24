#!/usr/bin/env bash
# Registers ableton-mcp-max with Claude Code (local/project scope) and
# prints how to remove the old ahujasid server.
set -u
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "Registering AbletonMCPMax..."
claude mcp add AbletonMCPMax -- uv run --directory "$REPO_DIR" ableton-mcp-max

echo
echo "To remove the old server, run:  claude mcp remove AbletonMCP"
echo "Then restart Claude Code so the new tools load."
exit 0
