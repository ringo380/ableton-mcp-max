---
layout: default
title: Analysis
parent: Tools
nav_order: 14
---

# Analysis
{: .no_toc }

Inspect the open set against best-practice rulesets and surface findings by domain.

<details open markdown="block">
  <summary>Tools on this page</summary>
  {: .text-delta }
1. TOC
{:toc}
</details>

---

## analyze_set

```python
analyze_set(focus: str = 'all', measure: bool = False, measure_window_s: float = 15.0)
```

Analyze the open Live set against curated best-practice rulesets.

focus: one of "all" (default), "mixing", "mastering", "sound_design",
"health" - selects which rule domains run.

measure: when True AND per-track MCP Tap devices are connected, run a brief
measure pass (plays the set for measure_window_s seconds, then stops/restores)
to capture audio and add a signal-backed "mix_signal" section (see below).
Default False keeps analyze_set read-only - the signal-backed mixing rules
stay deferred. measure_window_s: capture length when measure=True (default 15).

Reads the whole set in one round-trip, runs the deterministic ("auto") rules,
and returns JSON {ok, data} where data = {snapshot, findings, manual_rules,
deferred_rules, summary, [mix_signal]}:
- snapshot: normalized per-track/return/master state (mixer, devices, clips,
  routing); master.signal carries audio-tap metering (LUFS/dBTP) when the
  MCP Audio Tap device is loaded, else null.
- findings: auto-rule results {id, domain, status (pass|fail|warn|info),
  severity, evidence, remediation, [entity]}.
- manual_rules: rules needing human/Claude judgment (id, domain, title, rationale).
- deferred_rules: signal-required rules still needing metering (no audio tap
  connected / measure not run); the four mixing.* signal rules promote out of
  here into mix_signal when a measure pass runs.
- summary: counts by status + manual/deferred.
- mix_signal (only when measure=True with taps): {window_s, tracks:[{name,
  index,kind,signal}], findings:[{id,domain,status,severity,items,evidence,
  remediation}]} - cross-track spectral masking / loudness balance / per-track
  headroom / stereo correlation computed from the simultaneous per-track taps.

With measure=False this is read-only; it never mutates the set. The
/ableton:analyze skill layers the report and per-track judgment on top.

