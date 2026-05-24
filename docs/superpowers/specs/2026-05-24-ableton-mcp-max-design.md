# ableton-mcp-max — Design Spec

**Created**: 2026-05-24
**Status**: Approved — pending implementation plan
**Location**: `~/git/ableton-mcp-max`

## Overview

A standalone, self-owned Model Context Protocol (MCP) server that exposes Ableton
Live's capabilities to Claude, built by forking the ahujasid/ableton-mcp project and
extending it phase-by-phase toward broad coverage of the Live Object Model (LOM).

The immediate motivation: the current ahujasid MCP can create MIDI, manage tracks, and
load devices, but **cannot read or set instrument/device parameters** (e.g. Wavetable
filter cutoff, unison, oscillator settings). This project adds that and then expands
outward across the LOM in tracked phases.

### Goals
- Own both halves (MCP server + Live Remote Script) — no runtime dependency on the
  published `ableton-mcp` PyPI package.
- Preserve 100% of the existing tool surface (parity) so nothing regresses.
- Add device-parameter control first, then expand by capability domain.
- Maintain a persistent, session-durable progress tracker so work is never lost across
  Claude Code sessions.
- Local-first; structured so it *could* be published to GitHub/PyPI later without rework.

### Non-Goals (for now)
- Public release polish (CI, PyPI publish, contribution docs) — deferred.
- Change-listener / push-notification observation of Live state (Phase 7 stretch; awkward
  in a request/response MCP).
- Audio-clip warp-marker editing beyond basic clip properties (revisit in/after Phase 3).

## Architecture

Unchanged from the ahujasid base, which is sound:

```
Claude (MCP client)
   │  (MCP stdio)
   ▼
server.py  (FastMCP, run via uvx/python)
   │  JSON commands over TCP localhost:9877
   ▼
Remote Script "AbletonMCP"  (control surface running INSIDE Live)
   │  Live Object Model (LOM) calls; mutations scheduled on Live's main thread
   ▼
Ableton Live 11
```

- **MCP server** declares each tool with `@mcp.tool()` and calls
  `send_command(command_type, params)` which round-trips JSON over the socket.
- **Remote Script** receives commands in `_process_command` (an if/elif dispatch on
  command type), executes against the LOM, and returns JSON. Read commands run inline;
  state mutations are scheduled onto Live's main thread (the base already does this).

**Extension pattern (identical for every new capability):**
1. Add a `@mcp.tool()` function in the server (in the appropriate `tools/` domain module).
2. Add a dispatch branch + handler in the Remote Script (in the appropriate
   `handlers/` domain module).
3. Reinstall the Remote Script, restart Live, reconnect Claude Code.

### Replacement strategy
- Install our Remote Script **in place under the same folder name `AbletonMCP`** and the
  same port (9877) so the user's existing Live control-surface selection keeps working
  after one restart.
- Back up the original ahujasid Remote Script before overwriting.
- Swap the registered MCP server from `uvx ableton-mcp` to our local project.
- Only one server binds 9877 at a time; this is a clean swap, not a coexistence.

## Repo Layout

```
ableton-mcp-max/
├── PROGRESS.md              # phase tracker — SINGLE SOURCE OF TRUTH for completion state
├── README.md
├── pyproject.toml           # package metadata; console entry point for the server
├── ableton_mcp_max/
│   ├── __init__.py
│   ├── server.py            # FastMCP entry + connection mgmt
│   └── tools/               # tools grouped by domain
│       ├── session.py
│       ├── device.py
│       ├── mixer.py
│       ├── clip.py
│       └── ...
├── remote_script/
│   └── AbletonMCP/
│       ├── __init__.py      # control surface, socket server, _process_command dispatch
│       └── handlers/        # one module per domain (device, mixer, clip, ...)
├── scripts/
│   └── install_remote_script.sh   # copy into Live's MIDI Remote Scripts + chown to user
└── docs/superpowers/specs/
```

Tools and handlers are split by domain to keep each file small, single-purpose, and
reliable to edit.

## Phased Capability Roadmap

Ordered by value. Each phase is independently usable the moment it lands. Completion is
tracked per-phase and per-tool in `PROGRESS.md`.

### Phase 0 — Foundation
- New repo; vendor `server.py` and Remote Script `__init__.py` from ahujasid.
- Refactor into the domain-module layout (parity-preserving — no behavior change).
- `install_remote_script.sh` that copies the script into Live and `chown`s it to the
  user (avoids the root-owned-folder gotcha that hides the script from Live's scan).
- Register the new MCP server with Claude Code; back up + replace the old Remote Script;
  deregister `uvx ableton-mcp`.
- Verify all 16 existing tools still work (parity smoke test).
- Scaffold `PROGRESS.md`.

### Phase 1 — Device & Parameter Control (immediate unblock)
- `get_device_parameters(track_index, device_index)` → list of
  `{index, name, value, min, max, is_quantized, value_items?}`.
- `set_device_parameter(track_index, device_index, parameter (name or index), value)`.
- `get_device_info` / richer device listing (class, params count).
- Live verification: dial the "I Remember" Wavetable patch directly
  (filter cutoff/resonance, unison amount/voices, envelope times, osc gains).
- Document per-device which controls are reachable (continuous params yes; some menu
  selections such as the loaded wavetable waveform may not be LOM-exposed).

### Phase 2 — Mixer & Routing
- Get/set volume, pan, mute, solo, arm per track; sends to returns; master track.
- Crossfader assign; return tracks; input/output routing + monitor state.

### Phase 3 — Clip & MIDI Editing (deep)
- Read notes from a clip; replace/remove notes; clip properties (loop start/end, looping,
  warp mode, gain, pitch); quantize; duplicate/delete clips.

### Phase 4 — Devices & Racks
- Add/delete/move/enable-disable devices; rack macros & chains; preset selection.

### Phase 5 — Scenes, Transport, Arrangement
- Create/fire/delete scenes; locators; arrangement record; loop region; metronome;
  time signature; song position.

### Phase 6 — Automation Envelopes
- Read/write automation for parameters in clips and the arrangement.

### Phase 7 — Change Listeners (stretch)
- Observation/notifications of Live state changes. Flagged as possibly out-of-scope for a
  request/response MCP; revisit only if a concrete need appears.

## Progress Tracking (durability requirement)

`PROGRESS.md` is the authoritative, in-repo record of what is done. It contains:
- A phase table (status: Not started / In progress / Done) with the date each phase
  completed.
- Per-tool checkboxes within each phase.
- A short "current focus / next action" line at the top so any future session can resume
  instantly.

A project-memory pointer (`~/.claude/projects/.../memory/`) references this file's path so
future Claude Code sessions are routed to it immediately.

## Testing Strategy (honest)

The Live API cannot be exercised without Live running, so:
- **Offline unit tests** for pure logic only (URI parsing, value scaling/normalization,
  parameter name→index resolution).
- **Per-phase live smoke-test checklists** executed through the MCP against the user's
  open Live set; results recorded in `PROGRESS.md`. No claimed coverage we don't have.

## Risks / Open Questions
- **LOM parameter exposure varies by device** — resolved empirically by `get_device_parameters`
  in Phase 1; documented per device.
- **Quantized/list parameters** (e.g. filter type) need value-by-index handling, not raw
  floats — `set_device_parameter` must handle both continuous and quantized params.
- **Main-thread scheduling** for mutations must be preserved exactly as the base does it,
  or Live can crash/deadlock on cross-thread LOM writes.
- **Remote Script Python** runs under Live's embedded Python (3.7-era), not the system
  Python — handlers must avoid newer syntax.
