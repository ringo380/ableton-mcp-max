# ableton-mcp-max

A self-owned, extensible MCP server for Ableton Live, forked from
[ahujasid/ableton-mcp](https://github.com/ahujasid/ableton-mcp) and extended
toward broad Live Object Model coverage.

**Documentation:** [ringo380.github.io/ableton-mcp-max](https://ringo380.github.io/ableton-mcp-max/) - landing page, install guide, and reference for all 188 tools.

## Install
Runs on macOS and Windows (Live 11 or 12). Needs [uv](https://docs.astral.sh/uv/).

1. Install the Live Remote Script:
   - macOS: `bash scripts/install_remote_script.sh`
   - Windows: `powershell -ExecutionPolicy Bypass -File scripts\install_remote_script.ps1`
2. Restart Ableton Live; enable **AbletonMCP** under Settings → Link, Tempo & MIDI → Control Surface (Settings is under the Live menu on macOS, the Options menu on Windows).
3. Register the MCP server with Claude Code:
   - macOS: `bash scripts/register_mcp.sh`
   - Windows: `powershell -ExecutionPolicy Bypass -File scripts\register_mcp.ps1`
4. Restart Claude Code.

The tools that drive Live's own windows (`save_set`, `save_set_as`, `render_audio`,
`restart_live`, `set_arrangement_automation`) use System Events on macOS (Live needs
Accessibility permission) and Live's native menu, UI Automation and the stock Save
dialog on Windows. On Windows they briefly bring Live's Save dialog to the front to
type a file name.

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

## License

Free for noncommercial use under the
[PolyForm Noncommercial License 1.0.0](LICENSE) - personal study, hobby
projects, private entertainment, research, and use by nonprofits and
educational institutions.

**Commercial use requires a paid license.** That includes producing music you
sell or license, client or contract work, use inside a business, and bundling
this software into a commercial product or service. Commercial licenses are
offered by Robworks Software LLC - to arrange one, email licensing@robworks.info.

Releases up to and including v0.33.0 were published under the MIT License and
remain available under those terms. This project is a fork of
[ahujasid/ableton-mcp](https://github.com/ahujasid/ableton-mcp); see
[THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).
