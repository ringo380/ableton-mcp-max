# Track Analysis Rulesets - Design

**Created**: 2026-06-11
**Status**: Approved (ready for implementation plan)

## Overview

Add a track/set analysis feature to the `ableton` plugin that checks an open Live 11
set against curated best-practice guidelines across four domains - **mixing,
mastering, sound design, and overall track health** - and produces a sectioned,
remediation-oriented report.

Guidelines are distilled once from authoritative sources into versioned, cited
ruleset files shipped in the repo (no per-run web fetching). Rules are declarative
**data**, not Python code: a generic predicate evaluator runs the deterministic
("auto") rules against a one-shot snapshot of the set, while a Claude Code skill
orchestrates the call and layers judgment + remediation on top.

### Hard constraint: no audio signal data

The LOM (and therefore our read tools) exposes track **structure and parameter
values** but **no audio signal** - there is no peak/RMS/LUFS/spectrum reading
available (the known field-wide gap; a future Max-for-Live audio-tap device would
fill it). Therefore:

- v1 ships **config-based** checks: limiter present on master, gain-stage sanity
  (fader > 0 dB), device order (EQ before compressor), device-count/CPU heuristics,
  routing sanity, clip hygiene (named/warped), leftover mute/solo, send structure,
  naming.
- Checks that need real metering (integrated loudness, true-peak headroom in dB,
  inter-track frequency masking, phase) are **not faked**. They are modelled as
  `deferred` rules and surfaced under a "Needs metering - not yet measurable"
  report section. The snapshot schema reserves a `signal` slot so the future
  audio-tap device drops in without a schema break.

## Decisions (from brainstorming)

1. **Ruleset source:** curated static ruleset files, versioned in the repo, with
   citations. Re-digested only on deliberate update. No live web-fetch.
2. **Engine shape:** both - MCP tool computes objective metrics/findings; the skill
   layers curated guidelines + judgment.
3. **Analysis scope:** whole set (all tracks + returns + master) with per-track
   drilldown; optional focus on one domain.
4. **Signal gap:** config-based checks now; report/ruleset schema carries placeholder
   slots for a future M4L audio-tap (`signal_required` rules + `signal` snapshot block).
5. **Domain scope:** all four domains, selectable via a `focus` arg
   (`all` | `mixing` | `mastering` | `sound_design` | `health`, default `all`); each
   domain is its own ruleset file; report is sectioned by domain.

## Architecture & components

```
ableton_mcp_max/
  rulesets/
    mixing.json          # declarative rule objects
    mastering.json
    sound_design.json
    health.json
    sources.md           # citations / attribution for curated guidance
  ruleset_utils.py       # load + schema-validate ruleset files (pure, unit-tested)
  analysis_utils.py      # snapshot normalize + declarative predicate evaluator (pure, tested)
  server.py              # new @mcp.tool() analyze_set -> {snapshot, findings, deferred}
remote_script/AbletonMCP/__init__.py
                         # new read handler get_analysis_snapshot (one-round-trip set walk)
commands/
  analyze.md             # /ableton:analyze skill: calls tool, loads rulesets, writes report
```

`ruleset_utils.py` and `analysis_utils.py` are imported by **server.py only** (the
Remote Script runs in Live's own Python and cannot import them) - consistent with the
existing `*_utils.py` convention.

### Data flow

`/ableton:analyze [focus]`
→ skill calls `analyze_set(focus)` tool
→ server sends one `get_analysis_snapshot` read to the Remote Script
→ Live walks the whole set once (tracks, returns, master, devices, clips, routing,
   transport) and returns a raw payload
→ server normalizes it (`analysis_utils`), loads the relevant ruleset(s)
   (`ruleset_utils`), runs the `auto` rules via the predicate evaluator
→ returns `{snapshot, findings, manual_rules, deferred_rules, summary}` in the uniform
   `{ok, data}` envelope
→ skill `Read`s the ruleset JSON for rationale/citations + `manual` rule text, reasons
   over the snapshot for `manual` items, composes a domain-sectioned human report.

**Why a dedicated remote read** (vs looping existing read tools): one socket
round-trip for the whole set instead of dozens - fast, low token cost, and the
per-track walk is natural in Live's own process.

## Rule data model

Each rule is a declarative object. One source of truth; the Python evaluator runs the
`auto` ones, the skill surfaces `manual`/`deferred` ones with rationale.

```jsonc
{
  "id": "master.limiter_present",
  "domain": "mastering",
  "title": "Master bus has a limiter to catch peaks",
  "severity": "fail",            // fail | warn | info
  "mode": "auto",                // auto | manual | deferred
  "signal_required": false,      // true -> parked for future audio-tap; engine skips
  "check": {                     // declarative predicate; present iff mode == auto
    "field": "master.devices[*].class",
    "op": "includes",
    "value": "Limiter"
  },
  "evidence_template": "Master chain: {master.device_names}",
  "rationale": "A limiter on the master prevents peak overs before export.",
  "remediation": "Add a Limiter as the last device on the Master track; ceiling ~-1 dB.",
  "source": "sources.md#mastering-headroom"
}
```

### Modes

- `auto` - engine produces a reproducible `pass`/`warn`/`fail` with evidence.
- `manual` - engine can't judge (e.g. "is this reverb tail musically appropriate?");
  the skill surfaces it as a checklist item with rationale and reasons over the
  snapshot to give a real assessment.
- `deferred` (`signal_required: true`) - needs real metering; engine skips it; report
  lists it under "Needs metering - not yet measurable".

### Predicate evaluator (`analysis_utils.py`)

Fixed op vocabulary over dotted snapshot paths (supports `[*]` wildcard for list
projection):

- comparison: `equals`, `gt`, `lt`, `gte`, `lte`
- membership/existence: `includes`, `exists`, `matches` (regex)
- counting: `count_gt`, `count_lt`
- composition: `all`, `any`, `not` (nest child `check` objects)

This covers every config-based check without bespoke Python per rule. A new rule is a
new JSON object; the engine never changes. **Commitment: rules-as-data with a fixed
predicate vocabulary** (arbitrary Python per rule was explicitly rejected).

## Snapshot schema

Normalized dict returned by `analyze_set.data.snapshot` (compact - `key_params`
carries only the handful of params rules reference, to bound tokens):

```jsonc
{
  "transport": { "tempo": 120.0, "is_playing": false, "time_signature": "4/4" },
  "tracks": [
    {
      "index": 0, "name": "Bass", "type": "midi",       // midi | audio | return | master | group
      "mixer": { "volume_db": -6.0, "pan": 0.0, "sends": [0.0, 0.0],
                 "mute": false, "solo": false, "arm": false },
      "is_grouped": false, "group_track": null,
      "devices": [ { "index": 0, "name": "EQ Eight", "class": "Eq8", "on": true,
                     "is_instrument": false, "key_params": {} } ],
      "device_names": ["EQ Eight", "Compressor"],
      "clips": { "count": 4, "named": 4, "warped": 4, "empty_slots": 2 },
      "routing": { "audio_to": "Master", "audio_from": "No Input" },
      "signal": null                                    // reserved for future audio-tap
    }
  ],
  "returns": [ /* same shape, return-track subset */ ],
  "master":  { "device_names": [], "devices": [], "signal": null }
}
```

Respects the device-tool asymmetry: return/master device data comes from
`get_device_info`-style access, not `get_device_parameters` (regular-track-only).
Group tracks have no `.arm` - read via try/except.

## MCP tool contract

`analyze_set(focus="all")` `@mcp.tool()`:

- `focus`: `all` | `mixing` | `mastering` | `sound_design` | `health`.
- Sends one `get_analysis_snapshot`; normalizes; loads the relevant ruleset(s); runs
  `auto` rules; returns the uniform envelope:

```jsonc
{ "ok": true, "data": {
    "snapshot": { /* compact, as above */ },
    "findings": [ { "id": "master.limiter_present", "domain": "mastering",
                    "status": "fail", "severity": "fail",
                    "evidence": "Master chain: EQ Eight", "remediation": "..." } ],
    "manual_rules":   [ { "id": "...", "domain": "sound_design",
                          "title": "...", "rationale": "..." } ],
    "deferred_rules": [ { "id": "...", "domain": "mastering",
                          "title": "Integrated loudness in target range",
                          "reason": "needs metering" } ],
    "summary": { "fail": 2, "warn": 5, "pass": 18, "manual": 6, "deferred": 4 }
} }
```

`analyze_set` is a read - naturally idempotent, no settle delay, no write-lag concern.
The tool does the deterministic work (status + evidence + counts); the skill does the
prose, prioritization, and per-track judgment.

## Skill + report format

`commands/analyze.md` → `/ableton:analyze [focus]` (same command-as-skill pattern as
`best-practices`, `new-track`, `add-to-track`). Instructed flow:

1. Connection triage (reuse `best-practices` etiquette - retry-once on first call).
2. Call `analyze_set(focus)` - one round-trip; do **not** hand-loop the read tools.
3. `Read` the relevant `rulesets/*.json` for rationale/citations + `manual` rule text.
4. Compose the report; for `manual` rules, reason over the returned snapshot to give a
   real assessment, not just echo the checklist.
5. Surface `deferred_rules` honestly; never invent loudness/dB numbers.

Report (printed in chat, sectioned by domain, worst-first):

```
# Track Health Report - <set name> @ 120 BPM
## ❌ Fails (2)
- [mastering] No limiter on master bus - add a Limiter (ceiling ~-1 dB) as last master device. (src)
- [health] Track 4 "MIDI" unnamed/default - rename for a navigable session.
## ⚠️ Warnings (5)
- [mixing] Bass fader at +2.1 dB - gain-stage below 0 dB to preserve headroom. ...
## 👂 Manual checks (judgment) (6)
- [sound_design] Reverb tail on "Lead" (Decay 4.2 s) at 120 BPM may wash the mix - verify it sits in the groove.
## 📏 Needs metering - not yet measurable (4)
- [mastering] Integrated loudness vs target - requires audio metering (future audio-tap device).
## ✅ Passed (18)  - collapsed count, expandable on request.
```

`focus` scopes which domains appear (default `all`). The report is **read-only** - it
recommends, never mutates the set. A `--fix`-style follow-up that chains the existing
write tools is explicitly out of v1 scope (YAGNI).

## Testing

Offline, fits the project's pytest + py_compile gate (no signal/Live needed):

- `tests/test_ruleset_utils.py` - every shipped `rulesets/*.json` loads + passes schema
  validation (required keys; valid `severity`/`mode`/`op` enums; `check` present iff
  `mode == auto`; `source` anchor exists in `sources.md`). The drift guard.
- `tests/test_analysis_utils.py` - predicate evaluator against synthetic snapshots
  (one fixture per op, plus `all`/`any`/`not`), plus end-to-end "snapshot + ruleset →
  expected findings" cases (limiter-missing → fail; clean master → pass; fader > 0 →
  warn).
- `tests/test_snapshot_normalize.py` - raw remote payload → normalized snapshot (group
  track has no `.arm`; return-track subset; empty Simpler clips; `signal: null`
  reserved).
- `uv run python -m py_compile remote_script/AbletonMCP/__init__.py` + server import
  check.
- **Live-verify** (manual, recorded in PROGRESS.md): run `/ableton:analyze`; confirm
  the snapshot matches reality, auto-findings are correct, deferred section is honest.

## Docs

- Regenerate the tool-index (`scripts/build_tool_index.py`) and docs site
  (`scripts/gen_docs_site.py`) - both assert every tool is categorized, so `analyze_set`
  must be filed under a new "Analysis" category.
- Add `/ableton:analyze` to the README / docs command list.

## Rollout / phasing

1. **Engine + data, offline** - `ruleset_utils`, `analysis_utils`, the 4 ruleset JSONs +
   `sources.md`, full unit tests. No Live. (Curating accurate, cited guidelines is the
   real work here - front-loaded into pure data + tests.)
2. **Both halves wired** - remote `get_analysis_snapshot` + server `analyze_set` tool;
   install + dual-restart; live-verify the snapshot.
3. **Skill + docs** - `commands/analyze.md`, report format, tool-index/docs regen,
   README.

Additive (new tool + new command), non-breaking on its own. Releases under v0.5.0 (the
already-pending bump) or a follow-up minor - decided at release time.

## Files to create/modify

- `ableton_mcp_max/rulesets/{mixing,mastering,sound_design,health}.json` - new
- `ableton_mcp_max/rulesets/sources.md` - new (citations/attribution)
- `ableton_mcp_max/ruleset_utils.py` - new (load + schema validate)
- `ableton_mcp_max/analysis_utils.py` - new (normalize + predicate evaluator)
- `ableton_mcp_max/server.py` - add `analyze_set` `@mcp.tool()`
- `remote_script/AbletonMCP/__init__.py` - add `get_analysis_snapshot` read handler
- `commands/analyze.md` - new skill
- `tests/test_ruleset_utils.py`, `tests/test_analysis_utils.py`,
  `tests/test_snapshot_normalize.py` - new
- `commands/tool-index.md`, docs site pages, README - regenerated/updated

## Verification

- `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q`
  green (new tests + existing suite).
- `uv run python -c "import ableton_mcp_max.server"` and
  `uv run python -m py_compile remote_script/AbletonMCP/__init__.py` clean.
- Live-verify `/ableton:analyze` against an open set; record results in PROGRESS.md.
