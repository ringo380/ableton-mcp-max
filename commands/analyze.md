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
By default this analysis checks configuration only (limiter present, gain-stage
sanity, device counts, routing, clip hygiene, leftover solo/mute, instrument
presence); loudness, true-peak headroom, frequency masking, and stereo correlation
are listed under "Needs metering".

Those signal-backed checks become real **only** when MCP Tap devices are loaded and
you run `analyze_set(measure=True)` - that plays the set briefly to capture audio.
Without taps (or with `measure=False`, the default), never invent dB/LUFS numbers;
leave them deferred. The default call is read-only and never plays the set.

## Steps

1. **Connection triage.** The first MCP call after a restart can fail while the
   server reconnects - retry once. If it persists, confirm Live is running and port
   9877 is listening (see `/ableton:best-practices`).
2. **Call the tool, once.** Call `analyze_set(focus=<arg or "all">)`. Do NOT hand-loop
   the read tools - the tool gathers the whole set in one round-trip. Check `ok`
   first; on `ok:false`, surface the `error` and stop.
   - **Optional measure pass:** if metering matters, first check `list_taps` /
     `get_audio_tap_status`. If taps are connected, OFFER to call
     `analyze_set(measure=True)` (warn that it plays the set for ~15 s). With taps,
     `data.mix_signal` carries real per-track signals + cross-track findings
     (masking / loudness balance / per-track headroom / stereo correlation), and the
     four `mixing.*` signal rules promote out of "Needs metering". Report those under
     a **Mix signal** section using the real numbers - still never invent values.
     - **Per-track taps are PRE-FADER** (the tap is a device; the mixer fader sits
       after the device chain), so a track's LUFS reflects its instrument +
       device-chain level, NOT the post-fader output - a fader move does not change
       it. Frame a `loudness_balance` finding as "this instrument is quiet," not
       "this fader is low." The only post-fader / program reference is the MASTER
       tap, reported under `data.mix_signal.master` (`deploy_taps` auto-adds one by
       default); use it for true program loudness and to confirm an output balance.
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
## Mix signal (only with measure=True + taps)
- [mixing] <finding from data.mix_signal, e.g. "Kick vs Bass overlap 0.99"> - <remediation>
## Needs metering - not yet measurable (<n>)
- [<domain>] <title> - requires MCP Tap devices + analyze_set(measure=True).
## Passed (<n>)   (expand on request)
```
