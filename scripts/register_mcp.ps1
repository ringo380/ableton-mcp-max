# Registers ableton-mcp-max with Claude Code (local scope) on Windows.
# Windows counterpart of register_mcp.sh.
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path

Write-Host 'Registering AbletonMCPMax...'
claude mcp add AbletonMCPMax -- uv run --directory $repo ableton-mcp-max

Write-Host ''
Write-Host 'To remove the old server, run:  claude mcp remove AbletonMCP'
Write-Host 'Then restart Claude Code so the new tools load.'
exit 0
