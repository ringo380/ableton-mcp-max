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
analyze_set(focus: str = 'all')
```

Analyze the open Live set against curated best-practice rulesets.

focus: one of "all" (default), "mixing", "mastering", "sound_design",
"health" - selects which rule domains run.

Reads the whole set in one round-trip, runs the deterministic ("auto") rules,
and returns JSON {ok, data} where data = {snapshot, findings, manual_rules,
deferred_rules, summary}:
- snapshot: normalized per-track/return/master state (mixer, devices, clips,
  routing); each carries signal:null (reserved for a future audio-tap).
- findings: auto-rule results {id, domain, status (pass|fail|warn|info),
  severity, evidence, remediation, [entity]}.
- manual_rules: rules needing human/Claude judgment (id, domain, title, rationale).
- deferred_rules: rules needing audio metering the LOM can't provide.
- summary: counts by status + manual/deferred.

This is read-only; it never mutates the set. The /ableton:analyze skill layers
the report and per-track judgment on top of this output.

