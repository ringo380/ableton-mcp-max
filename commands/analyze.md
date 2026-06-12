---
description: Analyze the open Ableton Live set against curated best-practice rulesets (mixing, mastering, sound design, health) and produce a sectioned, remediation-oriented report.
allowed-tools: ["Bash", "Read"]
---

# /ableton:analyze

Check the open Live set against the curated rulesets and report findings by domain.

> Load tools if deferred: `ToolSearch select:mcp__AbletonMCPMax__analyze_set`

**Argument:** optional focus - `all` (default), `mixing`, `mastering`, `sound_design`, `health`.

## Honest scope

The Live Object Model exposes **structure and parameter values, not audio signal**.
So this analysis checks configuration (limiter present, gain-stage sanity, device
counts, routing, clip hygiene, leftover solo/mute, instrument presence). It does
**not** measure loudness, true-peak headroom, or frequency masking - those are
listed under "Needs metering" and must be checked by ear/meters in Live. Never
invent dB/LUFS numbers.

## Steps

1. **Connection triage.** The first MCP call after a restart can fail while the
   server reconnects - retry once. If it persists, confirm Live is running and port
   9877 is listening (see `/ableton:best-practices`).
2. **Call the tool, once.** Call `analyze_set(focus=<arg or "all">)`. Do NOT hand-loop
   the read tools - the tool gathers the whole set in one round-trip. Check `ok`
   first; on `ok:false`, surface the `error` and stop.
3. **Load rationale.** `Read` the relevant `ableton_mcp_max/rulesets/<domain>.json`
   for the full `rationale`/`remediation`/`source` of any rule you report, and the
   text of every `manual_rules` entry. The tool returns ids/titles; the JSON has the
   "why".
4. **Judge the manual rules.** For each `manual_rules` entry, reason over the returned
   `snapshot` to give a real assessment (e.g. inspect reverb device presence on a
   track and its tempo) - don't just echo the checklist item.
5. **Write the report** (below). Order: Fails -> Warnings -> Manual -> Needs metering
   -> Passed (count only). Scope sections to `focus`. The report is **read-only** - it
   recommends; it never mutates the set.

## Report format

```
# Track Health Report - <set summary> @ <tempo> BPM
## Fails (<n>)
- [<domain>] <evidence> - <remediation> (<source>)
## Warnings (<n>)
- [<domain>] <evidence> - <remediation>
## Manual checks - judgment (<n>)
- [<domain>] <title>: <your assessment from the snapshot> - <rationale>
## Needs metering - not yet measurable (<n>)
- [<domain>] <title> - requires audio metering (future audio-tap device).
## Passed (<n>)   (expand on request)
```
