---
layout: default
title: Home
nav_order: 1
description: "Control Ableton Live 11 from Claude with 117 MCP tools."
permalink: /
---

<div class="hero" markdown="0">
  <div class="hero__eyebrow">Claude Code plugin · MCP server</div>
  <h1 class="hero__title">ableton-mcp-max</h1>
  <p class="hero__tagline">Drive Ableton Live 11 straight from Claude. 117 tools spanning tracks,
  clips, MIDI, devices, mixing, automation, arrangement, scenes, transport, and full
  preset generation - built on the Live Object Model with preset-XML backdoors for the
  controls Live keeps hidden.</p>
  <div class="stats">
    <div><div class="stats__num">117</div><div class="stats__label">Tools</div></div>
    <div><div class="stats__num">15</div><div class="stats__label">Categories</div></div>
    <div><div class="stats__num">Live 11</div><div class="stats__label">Target</div></div>
    <div><div class="stats__num">MIT</div><div class="stats__label">License</div></div>
  </div>
</div>

[Browse all 117 tools](./tools/){: .btn .btn-primary .mr-2 }
[Get it on the marketplace](https://github.com/ringo380/robworks-claude-code-plugins){: .btn }

---

## Install

The fastest path is the **Robworks marketplace** as a Claude Code plugin.

### 1. Add the marketplace and install the plugin

In Claude Code:

```
/plugin marketplace add ringo380/robworks-claude-code-plugins
/plugin install ableton@robworks-claude-code-plugins
```

The plugin bundles the MCP server and registers it automatically over stdio (it talks to
Live on `localhost:9877`). You still need to put the **Remote Script** half inside Live -
the next step does that for you.

### 2. Run guided setup

```
/ableton:setup
```

This installs the Live Remote Script, warms the server, and walks you through enabling the
Control Surface. It expects [`uv`](https://docs.astral.sh/uv/) installed and Ableton Live 11.

### 3. Enable the Control Surface in Live

In Ableton: **Settings → Link, Tempo & MIDI → Control Surface → AbletonMCP**. Restart Live
if it was already open (Live only scans Remote Scripts at launch). Live is now listening on
`localhost:9877`.

### 4. Verify

Ask Claude to call `get_session_info`. A JSON blob with track / scene / tempo info means
both halves are connected. The first call right after enabling the surface can fail while
the server reconnects - just retry once.

> **Manual install (without the plugin):** clone
> [the repo](https://github.com/ringo380/ableton-mcp-max), run
> `bash scripts/install_remote_script.sh`, enable the Control Surface, run
> `bash scripts/register_mcp.sh`, then restart Claude Code.

---

## What you can do

- **Tracks & session** - create / duplicate / delete tracks, fold groups, drive selection and the detail view, undo/redo.
- **Clips & MIDI** - create clips, edit notes with the Live 11 extended note API, loop, quantize, launch, and stop.
- **Devices & racks** - read and set device parameters, rack macros, and chains; load instruments and effects.
- **Mixer & routing** - volume, pan, sends, and input/output routing for every track type.
- **Automation** - read and write clip automation envelopes for any automatable parameter.
- **Arrangement** - cue points, the arrangement loop, and timeline clips.
- **Transport** - tempo, groove, metronome, recording, punch, and the playhead.
- **Presets** - generate Wavetable and Simpler presets and patch racks (macros, zones, mappings) through the preset-XML backdoor - reaching controls the LOM doesn't expose.

[See the full tool reference →](./tools/){: .btn .btn-primary }

---

## How it works

Two halves talk over `localhost:9877`:

- A **FastMCP server** (Python, launched by Claude Code) exposes the 117 `@mcp.tool()` functions.
- A **Remote Script** running inside Live's own Python applies them against the Live Object Model.

Values are resolved, normalized, and clamped on the server, so the Remote Script just applies
already-canonical commands. Controls that the LOM marks read-only or doesn't expose at all
(sample refs, wavetables, macro mappings) are reached by patching factory preset `.adv`/`.adg`
XML and loading the result through the browser.

---

_Not affiliated with or endorsed by Ableton AG. "Ableton" and "Live" are trademarks of Ableton AG._
