# ableton-mcp-max

A self-owned, extensible MCP server for Ableton Live, forked from
[ahujasid/ableton-mcp](https://github.com/ahujasid/ableton-mcp) and extended
toward broad Live Object Model coverage.

**Documentation:** [ringo380.github.io/ableton-mcp-max](https://ringo380.github.io/ableton-mcp-max/) - landing page, install guide, and reference for all 187 tools.

## Install
1. `bash scripts/install_remote_script.sh` - installs the Live Remote Script.
2. Restart Ableton Live; enable **AbletonMCP** under Settings → Link, Tempo & MIDI → Control Surface.
3. `bash scripts/register_mcp.sh` - registers the MCP server with Claude Code.
4. Restart Claude Code.

**Optional - per-track + master metering:** drag `m4l/MCP Tap.amxd` into Live's
browser (onto User Library) once - a plain file-copy isn't indexed by the browser
- then `deploy_taps` (or drag it) onto tracks - and the Master - to unlock
loudness/true-peak/spectrum/stereo metering (Live Suite / Max for Live). See
`m4l/README.md`. The taps stream into a registry that feeds `read_track_meter`/
`measure_loudness`/`measure_mix`, the `analyze_set` mastering rules, and the
signal-backed cross-track mixing rules via `analyze_set(measure=True)`. (Replaces
the v0.7.0 master-only `MCP Audio Tap`.)

## Commands

- `/ableton:best-practices` - cross-cutting tool-usage etiquette (restart protocol, write-lag, MIDI extended API, connection triage).
- `/ableton:new-track` - best-practice workflow for establishing a new track via the MCP.
- `/ableton:add-to-track` - guided sequence for adding devices or clips to an existing track.
- `/ableton:analyze` - check the open set against best-practice rulesets and report findings by domain.

See `PROGRESS.md` for capability status and `docs/superpowers/specs/` for the design.

## Stem separation prerequisites

The `separate_stems_to_arrangement` tool (and the `/ableton:stems` command) shell
out to external command-line tools that are NOT bundled with the MCP server:

- Demucs (source separation), on your PATH:
  - `pip3 install --break-system-packages demucs`
  - This installs the `demucs` CLI into your Homebrew Python and onto PATH.
- librosa (tempo + key detection), in Homebrew Python:
  - `pip3 install --break-system-packages librosa`
  - macOS note: the analysis step runs under `/opt/homebrew/bin/python3`, so
    librosa must be installed there (not `/usr/bin/python3`).

If `demucs` is missing, the tool returns a clear error. If librosa is missing,
stem layout still runs but tempo / key detection is skipped.

Separated stems are written under the Live User Library
(`Samples/Stems/<model>/<name>/`) so Live's browser can index and load them, and
they persist there - the Arrangement clips reference those files on disk. To keep
a set fully self-contained, use Live's Collect All and Save afterward.
