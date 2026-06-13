# ableton-mcp-max

A self-owned, extensible MCP server for Ableton Live, forked from
[ahujasid/ableton-mcp](https://github.com/ahujasid/ableton-mcp) and extended
toward broad Live Object Model coverage.

**Documentation:** [ringo380.github.io/ableton-mcp-max](https://ringo380.github.io/ableton-mcp-max/) - landing page, install guide, and reference for all 112 tools.

## Install
1. `bash scripts/install_remote_script.sh` - installs the Live Remote Script.
2. Restart Ableton Live; enable **AbletonMCP** under Settings → Link, Tempo & MIDI → Control Surface.
3. `bash scripts/register_mcp.sh` - registers the MCP server with Claude Code.
4. Restart Claude Code.

**Optional - master metering:** drag `m4l/MCP Audio Tap.amxd` onto the Master track
(Live Suite / Max for Live) to unlock loudness/true-peak metering. See `m4l/README.md`.
It feeds the `read_meter`/`measure_loudness` tools and the `analyze_set` mastering rules.

## Commands

- `/ableton:best-practices` - cross-cutting tool-usage etiquette (restart protocol, write-lag, MIDI extended API, connection triage).
- `/ableton:new-track` - best-practice workflow for establishing a new track via the MCP.
- `/ableton:add-to-track` - guided sequence for adding devices or clips to an existing track.
- `/ableton:analyze` - check the open set against best-practice rulesets and report findings by domain.

See `PROGRESS.md` for capability status and `docs/superpowers/specs/` for the design.
