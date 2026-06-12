# Track Analysis Rulesets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `/ableton:analyze` feature that checks an open Live 11 set against curated, cited best-practice rulesets (mixing, mastering, sound design, health) and produces a sectioned, remediation-oriented report.

**Architecture:** Declarative rules-as-data (JSON) drive a generic predicate evaluator in pure Python (`analysis_utils`) loaded/validated by `ruleset_utils`. A new remote read `get_analysis_snapshot` walks the whole set in one round-trip; the `analyze_set` MCP tool normalizes it, runs the `auto` rules, and returns `{snapshot, findings, manual_rules, deferred_rules, summary}` in the uniform `{ok, data}` envelope. The `commands/analyze.md` skill calls the tool, reads ruleset rationale/citations, layers judgment on `manual` rules, and writes the report. No audio signal is available from the LOM, so signal-based rules are `deferred` and surfaced honestly.

**Tech Stack:** Python 3.13 (server side), FastMCP, pytest, uv. Remote Script runs Live's embedded Python (no util imports there).

**Spec:** `docs/superpowers/specs/2026-06-11-track-analysis-rulesets-design.md`

**Test command (use everywhere below):**
```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q
```

**Conventions confirmed from the codebase:**
- Pure helper modules live in `ableton_mcp_max/<name>_utils.py`, imported by `server.py` ONLY, with a docstring header explaining they are server-side-only.
- Tests live in `tests/test_<module>.py`, plain `pytest`, mirroring `tests/test_scene_utils.py`.
- Tools: `@mcp.tool()` `def name(ctx: Context, ...) -> str:` with `try/except`, returning `_ok(result)` / `_err(msg)` (defined in `server.py:97-104`).
- Reads are sent via `ableton.send_command("<type>")`; a read command type is NOT added to `MUTATING_COMMANDS` (so it stays idempotent - recv retry allowed, no settle delay).
- Remote reads: a `if command_type == "<type>":` branch in `_process_command` (`remote_script/AbletonMCP/__init__.py:586+`) calling a private `self._<name>()` method.
- Commands: `commands/<name>.md` with frontmatter `description:` + `allowed-tools:`.

---

## Phase 1 - Engine + data (offline, no Live)

### Task 1: `analysis_utils` - path resolver

**Files:**
- Create: `ableton_mcp_max/analysis_utils.py`
- Test: `tests/test_analysis_utils.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_analysis_utils.py
import pytest
from ableton_mcp_max.analysis_utils import resolve_path


SNAP = {
    "transport": {"tempo": 120.0},
    "master": {"device_names": ["EQ Eight", "Limiter"]},
    "tracks": [
        {"name": "Bass", "mixer": {"volume_db": -6.0}, "devices": [{"class": "Eq8"}]},
        {"name": "Lead", "mixer": {"volume_db": 2.0}, "devices": [{"class": "Compressor2"}]},
    ],
}


def test_resolve_scalar():
    assert resolve_path(SNAP, "transport.tempo") == 120.0


def test_resolve_missing_is_none():
    assert resolve_path(SNAP, "transport.nope") is None
    assert resolve_path(SNAP, "nope.deep.path") is None


def test_resolve_list_projection():
    assert resolve_path(SNAP, "tracks[*].name") == ["Bass", "Lead"]


def test_resolve_nested_list_projection_flattens():
    assert resolve_path(SNAP, "tracks[*].devices[*].class") == ["Eq8", "Compressor2"]


def test_resolve_plain_list():
    assert resolve_path(SNAP, "master.device_names") == ["EQ Eight", "Limiter"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q tests/test_analysis_utils.py`
Expected: FAIL - `ModuleNotFoundError` / `ImportError: cannot import name 'resolve_path'`.

- [ ] **Step 3: Write minimal implementation**

```python
# ableton_mcp_max/analysis_utils.py
"""Pure analysis helpers for the track-analysis feature. No Live dependencies.

Server-side only (the Remote Script in Live's embedded Python cannot import
this). Provides a dotted-path resolver, a declarative predicate evaluator, and
the rule -> findings engine. Rules are DATA (see ableton_mcp_max/rulesets/*.json);
this module is the fixed engine that runs them.
"""

import re


def resolve_path(obj, path):
    """Resolve a dotted path against a nested dict/list snapshot.

    Segments ending in ``[*]`` project over a list and map the remaining path
    over each element, flattening one level. A missing key yields ``None`` for a
    scalar walk, or is skipped within a projection. Returns a scalar, or a list
    when any ``[*]`` wildcard is traversed.
    """
    return _walk(obj, path.split("."))


def _walk(obj, parts):
    if not parts:
        return obj
    part, rest = parts[0], parts[1:]
    wildcard = part.endswith("[*]")
    key = part[:-3] if wildcard else part
    nxt = obj.get(key) if isinstance(obj, dict) else None
    if wildcard:
        if not isinstance(nxt, list):
            return []
        out = []
        for item in nxt:
            val = _walk(item, rest)
            out.extend(val) if isinstance(val, list) else out.append(val)
        return out
    return _walk(nxt, rest)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q tests/test_analysis_utils.py`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/analysis_utils.py tests/test_analysis_utils.py
git commit -m "feat(analysis): dotted-path resolver with list projection"
```

---

### Task 2: `analysis_utils` - predicate operators + `evaluate_check`

**Files:**
- Modify: `ableton_mcp_max/analysis_utils.py`
- Test: `tests/test_analysis_utils.py`

- [ ] **Step 1: Write the failing test (append to the test file)**

```python
from ableton_mcp_max.analysis_utils import evaluate_check


def test_op_includes():
    assert evaluate_check({"field": "master.device_names", "op": "includes", "value": "Limiter"}, SNAP) is True
    assert evaluate_check({"field": "master.device_names", "op": "includes", "value": "Saturator"}, SNAP) is False


def test_op_numeric():
    assert evaluate_check({"field": "transport.tempo", "op": "gt", "value": 100}, SNAP) is True
    assert evaluate_check({"field": "transport.tempo", "op": "lte", "value": 120}, SNAP) is True
    assert evaluate_check({"field": "transport.tempo", "op": "equals", "value": 120.0}, SNAP) is True


def test_op_exists_and_missing():
    assert evaluate_check({"field": "master", "op": "exists"}, SNAP) is True
    assert evaluate_check({"field": "nope", "op": "exists"}, SNAP) is False
    # numeric op on a missing field is False, never raises
    assert evaluate_check({"field": "nope", "op": "gt", "value": 0}, SNAP) is False


def test_op_matches_list_any():
    assert evaluate_check({"field": "tracks[*].devices[*].class", "op": "matches", "value": "^Eq"}, SNAP) is True
    assert evaluate_check({"field": "tracks[*].name", "op": "matches", "value": "^Drum"}, SNAP) is False


def test_op_count():
    assert evaluate_check({"field": "tracks[*].name", "op": "count_gt", "value": 1}, SNAP) is True
    assert evaluate_check({"field": "tracks[*].name", "op": "count_lt", "value": 5}, SNAP) is True


def test_composition_all_any_not():
    chk = {"all": [
        {"field": "transport.tempo", "op": "gt", "value": 100},
        {"any": [
            {"field": "master.device_names", "op": "includes", "value": "Limiter"},
            {"field": "master.device_names", "op": "includes", "value": "Saturator"},
        ]},
        {"not": {"field": "tracks[*].name", "op": "includes", "value": "Vocals"}},
    ]}
    assert evaluate_check(chk, SNAP) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q tests/test_analysis_utils.py`
Expected: FAIL - `ImportError: cannot import name 'evaluate_check'`.

- [ ] **Step 3: Write minimal implementation (append to `analysis_utils.py`)**

```python
VALID_OPS = frozenset({
    "equals", "gt", "lt", "gte", "lte",
    "includes", "exists", "matches", "count_gt", "count_lt",
})


def evaluate_check(check, snapshot):
    """Evaluate a declarative check (PASS condition) against a snapshot root.

    Supports composition via ``all`` / ``any`` / ``not`` (each wrapping child
    checks), or a leaf ``{field, op, value}``. Returns a bool. Missing data
    yields False rather than raising.
    """
    if "all" in check:
        return all(evaluate_check(c, snapshot) for c in check["all"])
    if "any" in check:
        return any(evaluate_check(c, snapshot) for c in check["any"])
    if "not" in check:
        return not evaluate_check(check["not"], snapshot)
    actual = resolve_path(snapshot, check["field"])
    return _apply_op(check["op"], actual, check.get("value"))


def _as_list(actual):
    return actual if isinstance(actual, list) else ([] if actual is None else [actual])


def _numeric(actual, value, fn):
    if isinstance(actual, list) or actual is None or not isinstance(actual, (int, float)):
        return False
    return fn(actual, value)


def _apply_op(op, actual, value):
    if op == "exists":
        return actual is not None and actual != []
    if op == "equals":
        return actual == value
    if op == "gt":
        return _numeric(actual, value, lambda a, b: a > b)
    if op == "lt":
        return _numeric(actual, value, lambda a, b: a < b)
    if op == "gte":
        return _numeric(actual, value, lambda a, b: a >= b)
    if op == "lte":
        return _numeric(actual, value, lambda a, b: a <= b)
    if op == "includes":
        return value in _as_list(actual)
    if op == "matches":
        rx = re.compile(value)
        return any(rx.search(str(x)) for x in _as_list(actual))
    if op == "count_gt":
        return len(_as_list(actual)) > value
    if op == "count_lt":
        return len(_as_list(actual)) < value
    raise ValueError("Unknown op '%s'" % op)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q tests/test_analysis_utils.py`
Expected: PASS (all passed).

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/analysis_utils.py tests/test_analysis_utils.py
git commit -m "feat(analysis): declarative predicate evaluator"
```

---

### Task 3: `analysis_utils` - rule → findings engine (`evaluate_rules`)

**Files:**
- Modify: `ableton_mcp_max/analysis_utils.py`
- Test: `tests/test_analysis_utils.py`

- [ ] **Step 1: Write the failing test (append)**

```python
from ableton_mcp_max.analysis_utils import evaluate_rules


RULES = [
    {"id": "master.limiter_present", "domain": "mastering", "severity": "fail",
     "mode": "auto", "scope": "master",
     "check": {"field": "device_names", "op": "includes", "value": "Limiter"},
     "evidence_template": "Master chain: {device_names}",
     "remediation": "Add a Limiter as the last master device."},
    {"id": "track.fader_headroom", "domain": "mixing", "severity": "warn",
     "mode": "auto", "scope": "track",
     "check": {"field": "mixer.volume_db", "op": "lte", "value": 0.0},
     "evidence_template": "{name} fader at {mixer.volume_db} dB",
     "remediation": "Gain-stage below 0 dB."},
    {"id": "sound.reverb_tail_taste", "domain": "sound_design", "severity": "info",
     "mode": "manual", "title": "Reverb tails sit in the groove",
     "rationale": "Long tails at fast tempos can wash the mix."},
    {"id": "master.loudness_target", "domain": "mastering", "severity": "warn",
     "mode": "deferred", "signal_required": True,
     "title": "Integrated loudness in target range"},
]


def test_evaluate_rules_master_pass():
    snap = {"master": {"device_names": ["EQ Eight", "Limiter"]}, "tracks": [], "returns": []}
    out = evaluate_rules(RULES, snap)
    f = [x for x in out["findings"] if x["id"] == "master.limiter_present"][0]
    assert f["status"] == "pass"
    assert f["evidence"] == "Master chain: ['EQ Eight', 'Limiter']"


def test_evaluate_rules_master_fail_and_evidence():
    snap = {"master": {"device_names": ["EQ Eight"]}, "tracks": [], "returns": []}
    out = evaluate_rules(RULES, snap)
    f = [x for x in out["findings"] if x["id"] == "master.limiter_present"][0]
    assert f["status"] == "fail"
    assert f["remediation"] == "Add a Limiter as the last master device."


def test_evaluate_rules_track_scope_emits_per_offender():
    snap = {"master": {"device_names": ["Limiter"]}, "returns": [], "tracks": [
        {"name": "Bass", "mixer": {"volume_db": -6.0}},
        {"name": "Lead", "mixer": {"volume_db": 2.1}},
    ]}
    out = evaluate_rules(RULES, snap)
    fader = [x for x in out["findings"] if x["id"] == "track.fader_headroom"]
    assert len(fader) == 1
    assert fader[0]["status"] == "warn"
    assert fader[0]["entity"] == "Lead"


def test_evaluate_rules_track_scope_all_pass_single_finding():
    snap = {"master": {"device_names": ["Limiter"]}, "returns": [], "tracks": [
        {"name": "Bass", "mixer": {"volume_db": -6.0}},
    ]}
    out = evaluate_rules(RULES, snap)
    fader = [x for x in out["findings"] if x["id"] == "track.fader_headroom"]
    assert len(fader) == 1 and fader[0]["status"] == "pass"


def test_evaluate_rules_routes_manual_and_deferred():
    snap = {"master": {"device_names": ["Limiter"]}, "tracks": [], "returns": []}
    out = evaluate_rules(RULES, snap)
    assert [m["id"] for m in out["manual_rules"]] == ["sound.reverb_tail_taste"]
    assert [d["id"] for d in out["deferred_rules"]] == ["master.loudness_target"]
    assert out["deferred_rules"][0]["reason"] == "needs metering"


def test_summary_counts():
    snap = {"master": {"device_names": ["EQ Eight"]}, "returns": [], "tracks": [
        {"name": "Lead", "mixer": {"volume_db": 2.1}},
    ]}
    out = evaluate_rules(RULES, snap)
    s = out["summary"]
    assert s["fail"] == 1 and s["warn"] == 1
    assert s["manual"] == 1 and s["deferred"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q tests/test_analysis_utils.py`
Expected: FAIL - `ImportError: cannot import name 'evaluate_rules'`.

- [ ] **Step 3: Write minimal implementation (append to `analysis_utils.py`)**

```python
_SCOPE_COLLECTION = {"track": "tracks", "return": "returns"}


def evaluate_rules(rules, snapshot):
    """Run a list of rule dicts against a normalized snapshot.

    Returns ``{findings, manual_rules, deferred_rules, summary}``. ``auto`` rules
    produce findings (status pass/fail/warn/info); ``manual`` rules are surfaced
    for human/Claude judgment; ``deferred`` (or ``signal_required``) rules are
    parked as needing metering.
    """
    findings, manual, deferred = [], [], []
    for rule in rules:
        mode = rule.get("mode", "auto")
        if rule.get("signal_required") or mode == "deferred":
            deferred.append({"id": rule["id"], "domain": rule["domain"],
                             "title": rule.get("title", rule["id"]),
                             "reason": "needs metering"})
            continue
        if mode == "manual":
            manual.append({"id": rule["id"], "domain": rule["domain"],
                           "title": rule.get("title", rule["id"]),
                           "rationale": rule.get("rationale", "")})
            continue
        findings.extend(_eval_auto(rule, snapshot))
    return {"findings": findings, "manual_rules": manual,
            "deferred_rules": deferred, "summary": _summarize(findings, manual, deferred)}


def _eval_auto(rule, snapshot):
    scope = rule.get("scope", "set")
    if scope == "set":
        ok = evaluate_check(rule["check"], snapshot)
        return [_finding(rule, ok, _evidence(rule, snapshot))]
    if scope == "master":
        root = snapshot.get("master") or {}
        ok = evaluate_check(rule["check"], root)
        return [_finding(rule, ok, _evidence(rule, root))]
    entities = snapshot.get(_SCOPE_COLLECTION[scope]) or []
    failed = [_finding(rule, False, _evidence(rule, e), entity=e.get("name"))
              for e in entities if not evaluate_check(rule["check"], e)]
    if failed:
        return failed
    return [_finding(rule, True, "all %ss pass" % scope)]


def _finding(rule, ok, evidence, entity=None):
    f = {"id": rule["id"], "domain": rule["domain"],
         "status": "pass" if ok else rule["severity"],
         "severity": rule["severity"], "evidence": evidence,
         "remediation": rule.get("remediation", "")}
    if entity:
        f["entity"] = entity
    return f


def _evidence(rule, root):
    tmpl = rule.get("evidence_template")
    if not tmpl:
        return ""
    return re.sub(r"\{([^}]+)\}", lambda m: str(resolve_path(root, m.group(1))), tmpl)


def _summarize(findings, manual, deferred):
    counts = {"pass": 0, "fail": 0, "warn": 0, "info": 0}
    for f in findings:
        counts[f["status"]] = counts.get(f["status"], 0) + 1
    counts["manual"] = len(manual)
    counts["deferred"] = len(deferred)
    return counts
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q tests/test_analysis_utils.py`
Expected: PASS (all passed).

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/analysis_utils.py tests/test_analysis_utils.py
git commit -m "feat(analysis): rule-to-findings engine with scope + summary"
```

---

### Task 4: Ruleset data files + `sources.md`

**Files:**
- Create: `ableton_mcp_max/rulesets/health.json`
- Create: `ableton_mcp_max/rulesets/mixing.json`
- Create: `ableton_mcp_max/rulesets/mastering.json`
- Create: `ableton_mcp_max/rulesets/sound_design.json`
- Create: `ableton_mcp_max/rulesets/sources.md`

> These are the seed rulesets. Each rule below is real and field-checkable (or honestly `manual`/`deferred`). Expand later, but every shipped rule must keep a valid `source` anchor present in `sources.md` (Task 5 enforces this). `auto` rules reference only snapshot fields defined in Task 7's normalizer.

- [ ] **Step 1: Write `sources.md`**

```markdown
# Ruleset Sources

Curated, distilled best-practice guidance. Citations are to authoritative,
publicly available material. Rule `source` fields anchor to the headings below.

## health-naming
Default track names ("1-MIDI", "2-Audio") make sessions hard to navigate.
Renaming every track is standard session-hygiene advice in the Ableton manual's
"Managing Files and Sets" and "Arrangement View" workflow guidance.

## health-cpu-devices
Long device chains on a single track raise CPU load and complicate the signal
path; Ableton's "Computer Audio Resources" guidance recommends freezing/printing
or trimming heavy chains.

## health-leftover-states
Mutes and solos left engaged after editing are a common cause of "missing"
parts on export. Standard mixdown checklist item.

## mixing-gain-staging
Keeping channel faders at or below unity preserves headroom into the master and
matches Ableton's mixer/gain-staging guidance.

## mixing-return-effects
Time-based effects (reverb/delay) are best shared on return tracks rather than
inserted per channel, per Ableton's "Return Tracks and Sends" documentation.

## mastering-headroom
Leave headroom and catch peaks before export. Ableton's "Exporting Audio" and
mastering guidance recommends a limiter on the master and avoiding 0 dBFS overs.

## mastering-export-readiness
Mastering processing belongs on the master bus; a flat master with no dynamics
control is rarely export-ready.

## sound-design-modulation
Static patches benefit from movement (LFO/automation/macros); Ableton's
instrument and "Push/Live sound design" material emphasizes modulation.

## sound-design-reverb-taste
Reverb/delay tails must fit the tempo and arrangement - a judgment call, not a
measurable threshold.

## signal-loudness
Integrated loudness / true-peak targets require audio metering not exposed by the
Live Object Model. Deferred to a future audio-analysis device.
```

- [ ] **Step 2: Write `health.json`**

```json
[
  {
    "id": "health.track_named",
    "domain": "health",
    "title": "Tracks are renamed from defaults",
    "severity": "warn",
    "mode": "auto",
    "scope": "track",
    "check": { "not": { "field": "name", "op": "matches", "value": "^(\\d+-)?(MIDI|Audio)( \\d+)?$" } },
    "evidence_template": "Track named \"{name}\"",
    "rationale": "Default names make a session hard to navigate.",
    "remediation": "Rename the track to its musical role (e.g. 'Bass', 'Lead').",
    "source": "sources.md#health-naming"
  },
  {
    "id": "health.device_count",
    "domain": "health",
    "title": "No track is overloaded with devices",
    "severity": "warn",
    "mode": "auto",
    "scope": "track",
    "check": { "field": "device_names", "op": "count_lt", "value": 12 },
    "evidence_template": "{name} has {device_names} devices",
    "rationale": "Very long chains raise CPU load and complicate the signal path.",
    "remediation": "Freeze/flatten or trim the chain; move shared effects to returns.",
    "source": "sources.md#health-cpu-devices"
  },
  {
    "id": "health.no_leftover_solo",
    "domain": "health",
    "title": "No track left soloed",
    "severity": "fail",
    "mode": "auto",
    "scope": "track",
    "check": { "field": "mixer.solo", "op": "equals", "value": false },
    "evidence_template": "{name} is soloed",
    "rationale": "A stray solo silences the rest of the mix on playback/export.",
    "remediation": "Clear the solo before mixing down.",
    "source": "sources.md#health-leftover-states"
  }
]
```

- [ ] **Step 3: Write `mixing.json`**

```json
[
  {
    "id": "mixing.fader_headroom",
    "domain": "mixing",
    "title": "Channel faders at or below unity",
    "severity": "warn",
    "mode": "auto",
    "scope": "track",
    "check": { "field": "mixer.volume_db", "op": "lte", "value": 0.0 },
    "evidence_template": "{name} fader at {mixer.volume_db} dB",
    "rationale": "Faders pushed above unity erode master headroom.",
    "remediation": "Gain-stage below 0 dB; raise the source gain instead if needed.",
    "source": "sources.md#mixing-gain-staging"
  },
  {
    "id": "mixing.returns_present",
    "domain": "mixing",
    "title": "Return tracks exist for shared effects",
    "severity": "info",
    "mode": "auto",
    "scope": "set",
    "check": { "field": "returns[*].name", "op": "count_gt", "value": 0 },
    "evidence_template": "Return tracks: {returns[*].name}",
    "rationale": "Shared reverb/delay on returns is cleaner and lighter than per-channel inserts.",
    "remediation": "Add a return track and send channels to it for time-based effects.",
    "source": "sources.md#mixing-return-effects"
  },
  {
    "id": "mixing.reverb_balance",
    "domain": "mixing",
    "title": "Reverb/delay balance serves the mix",
    "severity": "info",
    "mode": "manual",
    "rationale": "Wet/dry balance and depth are judgment calls best heard, not measured.",
    "source": "sources.md#mixing-return-effects"
  }
]
```

- [ ] **Step 4: Write `mastering.json`**

```json
[
  {
    "id": "mastering.limiter_present",
    "domain": "mastering",
    "title": "Master bus has a limiter",
    "severity": "fail",
    "mode": "auto",
    "scope": "master",
    "check": { "field": "device_names", "op": "includes", "value": "Limiter" },
    "evidence_template": "Master chain: {device_names}",
    "rationale": "A limiter catches peaks before export and sets the ceiling.",
    "remediation": "Add a Limiter as the last master device; ceiling ~-1 dB.",
    "source": "sources.md#mastering-headroom"
  },
  {
    "id": "mastering.master_processing",
    "domain": "mastering",
    "title": "Master bus has some processing",
    "severity": "warn",
    "mode": "auto",
    "scope": "master",
    "check": { "field": "device_names", "op": "count_gt", "value": 0 },
    "evidence_template": "Master devices: {device_names}",
    "rationale": "A completely flat master is rarely export-ready.",
    "remediation": "Consider gentle bus EQ/compression and a limiter on the master.",
    "source": "sources.md#mastering-export-readiness"
  },
  {
    "id": "mastering.loudness_target",
    "domain": "mastering",
    "title": "Integrated loudness in target range",
    "severity": "warn",
    "mode": "deferred",
    "signal_required": true,
    "rationale": "LUFS / true-peak require audio metering the LOM does not expose.",
    "source": "sources.md#signal-loudness"
  }
]
```

- [ ] **Step 5: Write `sound_design.json`**

```json
[
  {
    "id": "sound_design.has_instrument",
    "domain": "sound_design",
    "title": "MIDI tracks have an instrument",
    "severity": "warn",
    "mode": "auto",
    "scope": "track",
    "check": { "any": [
      { "field": "type", "op": "equals", "value": "audio" },
      { "field": "type", "op": "equals", "value": "group" },
      { "field": "has_instrument", "op": "equals", "value": true }
    ] },
    "evidence_template": "{name} ({type}) has_instrument={has_instrument}",
    "rationale": "A MIDI track with no instrument produces no sound.",
    "remediation": "Load an instrument onto the MIDI track.",
    "source": "sources.md#sound-design-modulation"
  },
  {
    "id": "sound_design.modulation_present",
    "domain": "sound_design",
    "title": "Patches use movement/modulation",
    "severity": "info",
    "mode": "manual",
    "rationale": "Static patches feel lifeless; LFOs/automation/macros add motion.",
    "source": "sources.md#sound-design-modulation"
  },
  {
    "id": "sound_design.reverb_tail_taste",
    "domain": "sound_design",
    "title": "Reverb/delay tails fit the tempo",
    "severity": "info",
    "mode": "manual",
    "rationale": "Long tails at fast tempos can wash the mix - verify by ear.",
    "source": "sources.md#sound-design-reverb-taste"
  }
]
```

- [ ] **Step 6: Commit**

```bash
git add ableton_mcp_max/rulesets/
git commit -m "feat(analysis): seed rulesets (health, mixing, mastering, sound_design) + sources"
```

---

### Task 5: `ruleset_utils` - load + schema validation (the drift guard)

**Files:**
- Create: `ableton_mcp_max/ruleset_utils.py`
- Test: `tests/test_ruleset_utils.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ruleset_utils.py
import pytest
from ableton_mcp_max.ruleset_utils import (
    DOMAINS, load_ruleset, load_rulesets, validate_rule, validate_all,
)


def test_all_shipped_rulesets_validate():
    # The drift guard: every shipped rule must pass schema validation, and every
    # `source` anchor must exist in sources.md.
    validate_all()


def test_load_ruleset_returns_list_of_dicts():
    rules = load_ruleset("health")
    assert isinstance(rules, list) and rules
    assert all("id" in r and "domain" in r for r in rules)
    assert all(r["domain"] == "health" for r in rules)


def test_load_rulesets_all_combines_every_domain():
    combined = load_rulesets("all")
    domains = {r["domain"] for r in combined}
    assert domains == set(DOMAINS)


def test_load_rulesets_focus_single_domain():
    combined = load_rulesets("mastering")
    assert {r["domain"] for r in combined} == {"mastering"}


def test_load_rulesets_rejects_unknown_focus():
    with pytest.raises(ValueError):
        load_rulesets("loudness")


def test_validate_rule_rejects_bad_severity():
    with pytest.raises(ValueError):
        validate_rule({"id": "x", "domain": "health", "severity": "boom",
                       "mode": "auto", "scope": "set",
                       "check": {"field": "a", "op": "exists"},
                       "source": "sources.md#health-naming"}, anchors={"health-naming"})


def test_validate_rule_requires_check_for_auto():
    with pytest.raises(ValueError):
        validate_rule({"id": "x", "domain": "health", "severity": "warn",
                       "mode": "auto", "source": "sources.md#health-naming"},
                      anchors={"health-naming"})


def test_validate_rule_rejects_unknown_op():
    with pytest.raises(ValueError):
        validate_rule({"id": "x", "domain": "health", "severity": "warn",
                       "mode": "auto", "scope": "set",
                       "check": {"field": "a", "op": "is_blue", "value": 1},
                       "source": "sources.md#health-naming"}, anchors={"health-naming"})


def test_validate_rule_rejects_missing_source_anchor():
    with pytest.raises(ValueError):
        validate_rule({"id": "x", "domain": "health", "severity": "warn",
                       "mode": "manual", "source": "sources.md#nope"},
                      anchors={"health-naming"})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q tests/test_ruleset_utils.py`
Expected: FAIL - `ModuleNotFoundError: ableton_mcp_max.ruleset_utils`.

- [ ] **Step 3: Write minimal implementation**

```python
# ableton_mcp_max/ruleset_utils.py
"""Load + schema-validate the curated rulesets. Server-side only.

Rulesets are JSON arrays of rule objects under ableton_mcp_max/rulesets/. This
module is the single loader/validator so a malformed rule fails fast (offline)
rather than at analysis time. `validate_all()` is exercised by the test suite as
the drift guard.
"""

import json
import os
import re

from ableton_mcp_max.analysis_utils import VALID_OPS

DOMAINS = ("mixing", "mastering", "sound_design", "health")
_VALID_SEVERITY = frozenset({"fail", "warn", "info"})
_VALID_MODE = frozenset({"auto", "manual", "deferred"})
_VALID_SCOPE = frozenset({"set", "track", "return", "master"})

_DIR = os.path.join(os.path.dirname(__file__), "rulesets")


def _slug(heading):
    return re.sub(r"[^a-z0-9]+", "-", heading.strip().lower()).strip("-")


def _source_anchors():
    """Anchors defined by '## ' headings in sources.md."""
    path = os.path.join(_DIR, "sources.md")
    anchors = set()
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("## "):
                anchors.add(_slug(line[3:]))
    return anchors


def load_ruleset(domain):
    """Load one domain's rule list (no validation)."""
    if domain not in DOMAINS:
        raise ValueError("Unknown domain '%s'. Valid: %s" % (domain, ", ".join(DOMAINS)))
    with open(os.path.join(_DIR, "%s.json" % domain), "r", encoding="utf-8") as fh:
        return json.load(fh)


def load_rulesets(focus="all"):
    """Load rules for a focus: 'all' or a single domain. Returns a flat list."""
    if focus == "all":
        out = []
        for d in DOMAINS:
            out.extend(load_ruleset(d))
        return out
    if focus not in DOMAINS:
        raise ValueError("Unknown focus '%s'. Valid: all, %s" % (focus, ", ".join(DOMAINS)))
    return load_ruleset(focus)


def _check_ops(check):
    if "all" in check:
        for c in check["all"]:
            _check_ops(c)
        return
    if "any" in check:
        for c in check["any"]:
            _check_ops(c)
        return
    if "not" in check:
        _check_ops(check["not"])
        return
    if check.get("op") not in VALID_OPS:
        raise ValueError("Unknown op '%s'" % check.get("op"))
    if "field" not in check:
        raise ValueError("Leaf check missing 'field'")


def validate_rule(rule, anchors):
    """Raise ValueError if a rule violates the schema."""
    for key in ("id", "domain", "severity", "mode", "source"):
        if key not in rule:
            raise ValueError("Rule missing '%s': %r" % (key, rule.get("id", rule)))
    if rule["severity"] not in _VALID_SEVERITY:
        raise ValueError("Rule %s bad severity '%s'" % (rule["id"], rule["severity"]))
    if rule["mode"] not in _VALID_MODE:
        raise ValueError("Rule %s bad mode '%s'" % (rule["id"], rule["mode"]))
    if rule["mode"] == "auto":
        if "check" not in rule:
            raise ValueError("Auto rule %s missing 'check'" % rule["id"])
        if rule.get("scope", "set") not in _VALID_SCOPE:
            raise ValueError("Rule %s bad scope '%s'" % (rule["id"], rule.get("scope")))
        _check_ops(rule["check"])
    anchor = rule["source"].split("#", 1)[-1]
    if anchor not in anchors:
        raise ValueError("Rule %s source anchor '%s' not in sources.md" % (rule["id"], anchor))


def validate_all():
    """Validate every shipped ruleset. Raises on the first violation."""
    anchors = _source_anchors()
    seen = set()
    for domain in DOMAINS:
        for rule in load_ruleset(domain):
            if rule.get("domain") != domain:
                raise ValueError("Rule %s in %s.json has domain '%s'"
                                 % (rule.get("id"), domain, rule.get("domain")))
            if rule["id"] in seen:
                raise ValueError("Duplicate rule id '%s'" % rule["id"])
            seen.add(rule["id"])
            validate_rule(rule, anchors)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q tests/test_ruleset_utils.py`
Expected: PASS. (If `test_all_shipped_rulesets_validate` fails, a seed rule in Task 4 has a bad anchor/op - fix the JSON, not the test.)

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/ruleset_utils.py tests/test_ruleset_utils.py
git commit -m "feat(analysis): ruleset loader + schema validation drift guard"
```

---

### Task 6: `analysis_utils.normalize_snapshot` - raw remote payload → normalized snapshot

**Files:**
- Modify: `ableton_mcp_max/analysis_utils.py`
- Test: `tests/test_snapshot_normalize.py`

> The remote handler (Task 7) returns a raw payload close to the final shape, but the normalizer is where we (a) convert Live's linear volume `0.0..1.0` to dB, (b) reserve `signal: null`, (c) guard optional fields (group tracks have no `arm`), and (d) guarantee the exact field names the rules reference. Keeping it pure makes it testable without Live.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_snapshot_normalize.py
import pytest
from ableton_mcp_max.analysis_utils import normalize_snapshot, live_volume_to_db


def test_live_volume_to_db_unity():
    # Live's linear mixer value 0.85 == 0 dB (unity).
    assert round(live_volume_to_db(0.85)) == 0


def test_live_volume_to_db_silence_is_floor():
    assert live_volume_to_db(0.0) <= -70


RAW = {
    "transport": {"tempo": 120.0, "is_playing": False,
                  "signature_numerator": 4, "signature_denominator": 4},
    "tracks": [
        {"name": "1-MIDI", "type": "midi", "volume": 0.85, "panning": 0.0,
         "sends": [0.0], "mute": False, "solo": False, "arm": True,
         "is_grouped": False, "has_instrument": False,
         "devices": [{"index": 0, "name": "EQ Eight", "class_name": "Eq8", "on": True, "is_instrument": False}],
         "clips": {"count": 2, "named": 1, "warped": 2, "empty_slots": 6},
         "routing": {"audio_to": "Master", "audio_from": "No Input"}},
        {"name": "Group", "type": "group", "volume": 0.85, "panning": 0.0,
         "sends": [0.0], "mute": False, "solo": False,
         "is_grouped": False, "has_instrument": False,
         "devices": [], "clips": {"count": 0, "named": 0, "warped": 0, "empty_slots": 8},
         "routing": {"audio_to": "Master", "audio_from": "No Input"}},
    ],
    "returns": [
        {"name": "A-Reverb", "type": "return", "volume": 0.85, "panning": 0.0,
         "mute": False, "solo": False,
         "devices": [{"index": 0, "name": "Reverb", "class_name": "Reverb", "on": True, "is_instrument": False}]},
    ],
    "master": {"name": "Master", "volume": 0.85, "panning": 0.0,
               "devices": [{"index": 0, "name": "Limiter", "class_name": "Limiter", "on": True, "is_instrument": False}]},
}


def test_normalize_adds_db_and_device_names():
    snap = normalize_snapshot(RAW)
    t0 = snap["tracks"][0]
    assert round(t0["mixer"]["volume_db"]) == 0
    assert t0["device_names"] == ["EQ Eight"]
    assert t0["devices"][0]["class"] == "Eq8"


def test_normalize_reserves_signal_null():
    snap = normalize_snapshot(RAW)
    assert snap["tracks"][0]["signal"] is None
    assert snap["master"]["signal"] is None


def test_normalize_group_track_arm_defaults_false():
    snap = normalize_snapshot(RAW)
    # group track had no 'arm' key -> normalized to False, never KeyError
    assert snap["tracks"][1]["mixer"]["arm"] is False


def test_normalize_master_device_names():
    snap = normalize_snapshot(RAW)
    assert snap["master"]["device_names"] == ["Limiter"]


def test_normalize_returns_subset():
    snap = normalize_snapshot(RAW)
    assert snap["returns"][0]["type"] == "return"
    assert snap["returns"][0]["device_names"] == ["Reverb"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q tests/test_snapshot_normalize.py`
Expected: FAIL - `ImportError: cannot import name 'normalize_snapshot'`.

- [ ] **Step 3: Write minimal implementation (append to `analysis_utils.py`)**

```python
import math

# Live's mixer volume is a 0.0..1.0 linear control where ~0.85 == 0 dB (unity).
# This mirrors Live's fader taper closely enough for gain-staging heuristics.
_UNITY = 0.85
_DB_FLOOR = -70.0


def live_volume_to_db(value):
    """Approximate Live's linear mixer volume (0..1, unity ~0.85) as dB."""
    if value is None or value <= 0.0:
        return _DB_FLOOR
    db = 40.0 * math.log10(value / _UNITY)
    return max(_DB_FLOOR, round(db, 1))


def _norm_devices(raw_devices):
    devices = [{"index": d.get("index"), "name": d.get("name"),
                "class": d.get("class_name"), "on": d.get("on", True),
                "is_instrument": d.get("is_instrument", False),
                "key_params": d.get("key_params", {})}
               for d in (raw_devices or [])]
    return devices, [d["name"] for d in devices]


def _norm_track(raw):
    devices, names = _norm_devices(raw.get("devices"))
    track = {
        "index": raw.get("index"),
        "name": raw.get("name"),
        "type": raw.get("type"),
        "mixer": {
            "volume_db": live_volume_to_db(raw.get("volume")),
            "pan": raw.get("panning", 0.0),
            "sends": raw.get("sends", []),
            "mute": raw.get("mute", False),
            "solo": raw.get("solo", False),
            "arm": raw.get("arm", False),
        },
        "is_grouped": raw.get("is_grouped", False),
        "group_track": raw.get("group_track"),
        "has_instrument": raw.get("has_instrument", False),
        "devices": devices,
        "device_names": names,
        "clips": raw.get("clips", {"count": 0, "named": 0, "warped": 0, "empty_slots": 0}),
        "routing": raw.get("routing", {}),
        "signal": None,
    }
    return track


def normalize_snapshot(raw):
    """Convert the raw remote payload into the normalized snapshot the rules read."""
    master_raw = raw.get("master") or {}
    m_devices, m_names = _norm_devices(master_raw.get("devices"))
    return {
        "transport": {
            "tempo": raw.get("transport", {}).get("tempo"),
            "is_playing": raw.get("transport", {}).get("is_playing", False),
            "time_signature": "%s/%s" % (
                raw.get("transport", {}).get("signature_numerator", 4),
                raw.get("transport", {}).get("signature_denominator", 4)),
        },
        "tracks": [_norm_track(t) for t in raw.get("tracks", [])],
        "returns": [_norm_track(r) for r in raw.get("returns", [])],
        "master": {
            "name": "Master",
            "volume_db": live_volume_to_db(master_raw.get("volume")),
            "devices": m_devices,
            "device_names": m_names,
            "signal": None,
        },
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q tests/test_snapshot_normalize.py`
Expected: PASS.

- [ ] **Step 5: Run the FULL suite (Phase 1 regression gate)**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q`
Expected: PASS - existing 364 + new analysis/ruleset/snapshot tests, all green.

- [ ] **Step 6: Commit**

```bash
git add ableton_mcp_max/analysis_utils.py tests/test_snapshot_normalize.py
git commit -m "feat(analysis): snapshot normalizer (dB, signal slot, arm guard)"
```

**Phase 1 checkpoint:** the entire engine + data is offline-testable and green. No Live yet.

---

## Phase 2 - Wire both halves (needs Live + dual restart)

### Task 7: Remote `get_analysis_snapshot` read handler

**Files:**
- Modify: `remote_script/AbletonMCP/__init__.py` - add a `if`-branch in `_process_command` (near line 586) and a `_get_analysis_snapshot` method (near the other `_get_*` readers, ~line 813).

> This is a READ. Do NOT add it to the mutation dispatch list and do NOT add it to the server's `MUTATING_COMMANDS`. Use Live 3.7-era Python: `%`-formatting, no f-strings, probe optional attributes with try/except (never `hasattr`).

- [ ] **Step 1: Add the dispatch branch**

In `_process_command`, immediately after the `get_track_info` branch (around line 588), add:

```python
            elif command_type == "get_analysis_snapshot":
                response["result"] = self._get_analysis_snapshot()
```

- [ ] **Step 2: Add the reader method**

Near the other `_get_*` methods (after `_get_track_info`, ~line 900), add:

```python
    def _device_summary(self, device):
        info = {
            "index": list(device.canonical_parent.devices).index(device)
                     if hasattr(device, "canonical_parent") else None,
            "name": device.name,
            "class_name": device.class_name,
            "on": True,
            "is_instrument": self._get_device_type(device) == "instrument",
        }
        try:
            info["on"] = bool(device.parameters[0].value) if device.parameters else True
        except Exception:
            pass
        return info

    def _clip_summary(self, track):
        count = named = warped = empty = 0
        try:
            for slot in track.clip_slots:
                if slot.has_clip:
                    count += 1
                    clip = slot.clip
                    if clip.name:
                        named += 1
                    try:
                        if clip.warping:
                            warped += 1
                    except Exception:
                        pass
                else:
                    empty += 1
        except Exception:
            pass
        return {"count": count, "named": named, "warped": warped, "empty_slots": empty}

    def _track_summary(self, track, track_type):
        devices = []
        try:
            for d in track.devices:
                devices.append(self._device_summary(d))
        except Exception:
            pass
        has_instrument = any(d.get("is_instrument") for d in devices)
        info = {
            "name": track.name,
            "type": track_type,
            "volume": track.mixer_device.volume.value,
            "panning": track.mixer_device.panning.value,
            "mute": track.mute,
            "solo": track.solo,
            "has_instrument": has_instrument,
            "devices": devices,
            "clips": self._clip_summary(track),
        }
        try:
            info["sends"] = [s.value for s in track.mixer_device.sends]
        except Exception:
            info["sends"] = []
        # arm is regular-track-only; group/return/master raise.
        try:
            info["arm"] = track.arm
        except Exception:
            info["arm"] = False
        for attr in ("is_grouped",):
            try:
                info[attr] = getattr(track, attr)
            except Exception:
                pass
        try:
            info["routing"] = {
                "audio_to": track.output_routing_type.display_name,
                "audio_from": track.input_routing_type.display_name,
            }
        except Exception:
            info["routing"] = {}
        return info

    def _track_type(self, track):
        if track.has_midi_input:
            return "midi"
        try:
            if track.is_foldable:
                return "group"
        except Exception:
            pass
        return "audio"

    def _get_analysis_snapshot(self):
        """One-shot read of the whole set for analysis. Reads only - no mutation."""
        try:
            song = self._song
            tracks = [self._track_summary(t, self._track_type(t)) for t in song.tracks]
            returns = [self._track_summary(t, "return") for t in song.return_tracks]
            master = song.master_track
            master_devices = []
            try:
                for d in master.devices:
                    master_devices.append(self._device_summary(d))
            except Exception:
                pass
            return {
                "transport": {
                    "tempo": song.tempo,
                    "is_playing": song.is_playing,
                    "signature_numerator": song.signature_numerator,
                    "signature_denominator": song.signature_denominator,
                },
                "tracks": tracks,
                "returns": returns,
                "master": {
                    "name": "Master",
                    "volume": master.mixer_device.volume.value,
                    "panning": master.mixer_device.panning.value,
                    "devices": master_devices,
                },
            }
        except Exception as e:
            self.log_message("Error building analysis snapshot: " + str(e))
            raise
```

- [ ] **Step 3: Syntax-check the remote script**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python -m py_compile remote_script/AbletonMCP/__init__.py`
Expected: no output (success).

- [ ] **Step 4: Install + bounce Live (Claude can self-serve this half)**

```bash
bash scripts/install_remote_script.sh
```
Then quit + relaunch Live (per CLAUDE.md restart protocol): confirm no save sheet, `kill -TERM <MacOS/Live pid>`, `open -a "Ableton Live 11 Suite"`, wait ~10-15s. The AbletonMCP Control Surface must already be selected once so it rebinds 9877.

- [ ] **Step 5: Commit**

```bash
git add remote_script/AbletonMCP/__init__.py
git commit -m "feat(remote): get_analysis_snapshot one-shot set read"
```

---

### Task 8: Server `analyze_set` MCP tool

**Files:**
- Modify: `ableton_mcp_max/server.py` - add imports near the other util imports (top), and the tool near the other read tools (after `get_session_info`, ~line 500).

- [ ] **Step 1: Add imports** (with the other `from ableton_mcp_max...` imports near the top)

```python
from ableton_mcp_max.analysis_utils import normalize_snapshot, evaluate_rules
from ableton_mcp_max.ruleset_utils import load_rulesets
```

- [ ] **Step 2: Add the tool** (after the `get_session_info` tool)

```python
@mcp.tool()
def analyze_set(ctx: Context, focus: str = "all") -> str:
    """Analyze the open Live set against curated best-practice rulesets.

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
    """
    try:
        rules = load_rulesets(focus)
    except ValueError as e:
        return _err(str(e))
    try:
        ableton = get_ableton_connection()
        raw = ableton.send_command("get_analysis_snapshot")
        snapshot = normalize_snapshot(raw)
        result = evaluate_rules(rules, snapshot)
        result["snapshot"] = snapshot
        return _ok(result)
    except Exception as e:
        logger.error(f"Error analyzing set: {str(e)}")
        return _err(f"Error analyzing set: {str(e)}")
```

- [ ] **Step 3: Syntax-check + import-check the server**

Run:
```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python -c "import ableton_mcp_max.server"
```
Expected: no output (success). If it errors on the new imports, fix the import lines.

- [ ] **Step 4: Add a tool-level offline test** (mock connection, no Live)

**Files:** Create `tests/test_analyze_tool.py`

```python
import json
import ableton_mcp_max.server as server


class _FakeConn:
    def __init__(self, raw):
        self._raw = raw

    def send_command(self, command_type, params=None, **kwargs):
        assert command_type == "get_analysis_snapshot"
        return self._raw


_RAW = {
    "transport": {"tempo": 120.0, "is_playing": False,
                  "signature_numerator": 4, "signature_denominator": 4},
    "tracks": [
        {"name": "Lead", "type": "midi", "volume": 0.95, "panning": 0.0,
         "sends": [0.0], "mute": False, "solo": False, "arm": False,
         "has_instrument": True, "is_grouped": False,
         "devices": [{"index": 0, "name": "Wavetable", "class_name": "InstrumentVector",
                      "on": True, "is_instrument": True}],
         "clips": {"count": 1, "named": 1, "warped": 1, "empty_slots": 7},
         "routing": {"audio_to": "Master", "audio_from": "No Input"}},
    ],
    "returns": [],
    "master": {"name": "Master", "volume": 0.85, "panning": 0.0, "devices": []},
}


def test_analyze_set_returns_envelope(monkeypatch):
    monkeypatch.setattr(server, "get_ableton_connection", lambda: _FakeConn(_RAW))
    out = json.loads(server.analyze_set(ctx=None, focus="all"))
    assert out["ok"] is True
    data = out["data"]
    assert "snapshot" in data and "findings" in data and "summary" in data
    # master has no limiter -> a mastering fail finding
    ids = {f["id"]: f for f in data["findings"]}
    assert ids["mastering.limiter_present"]["status"] == "fail"
    # Lead fader 0.95 (> unity 0.85) -> mixing warn
    assert ids["mixing.fader_headroom"]["status"] == "warn"


def test_analyze_set_rejects_bad_focus():
    out = json.loads(server.analyze_set(ctx=None, focus="loudness"))
    assert out["ok"] is False
```

- [ ] **Step 5: Run the tool test + full suite**

Run: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q`
Expected: PASS (all, including the new tool test).

- [ ] **Step 6: Commit**

```bash
git add ableton_mcp_max/server.py tests/test_analyze_tool.py
git commit -m "feat(server): analyze_set tool wiring rulesets to the snapshot"
```

- [ ] **Step 7: Live-verify (manual - requires a Claude Code restart to load the new tool)**

After restarting Claude Code, load the deferred tool: `ToolSearch select:mcp__AbletonDev__analyze_set` (working-tree server) and call `analyze_set(focus="all")` against the open set. Confirm: (a) the snapshot track/return/master names + device chains match the actual set; (b) `mastering.limiter_present` reflects whether the master really has a Limiter; (c) `summary` counts add up; (d) `deferred_rules` lists the loudness rule. Record results in PROGRESS.md.

---

## Phase 3 - Skill + docs

### Task 9: `commands/analyze.md` skill

**Files:**
- Create: `commands/analyze.md`

- [ ] **Step 1: Write the command**

```markdown
---
description: Analyze the open Ableton Live set against curated best-practice rulesets (mixing, mastering, sound design, health) and produce a sectioned, remediation-oriented report.
allowed-tools: ["Bash", "Read"]
---

# /ableton:analyze

Check the open Live set against the curated rulesets and report findings by domain.

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
5. **Write the report** (below). Order: Fails → Warnings → Manual → Needs metering →
   Passed (count only). Scope sections to `focus`. The report is **read-only** - it
   recommends; it never mutates the set.

## Report format

```
# Track Health Report - <set summary> @ <tempo> BPM
## ❌ Fails (<n>)
- [<domain>] <evidence> - <remediation> (<source>)
## ⚠️ Warnings (<n>)
- [<domain>] <evidence> - <remediation>
## 👂 Manual checks (judgment) (<n>)
- [<domain>] <title>: <your assessment from the snapshot> - <rationale>
## 📏 Needs metering - not yet measurable (<n>)
- [<domain>] <title> - requires audio metering (future audio-tap device).
## ✅ Passed (<n>)   (expand on request)
```
```

- [ ] **Step 2: Verify the command file parses (frontmatter sanity)**

Run:
```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" python3 -c "import pathlib,yaml; t=pathlib.Path('commands/analyze.md').read_text(); fm=t.split('---')[1]; d=yaml.safe_load(fm); assert d['description'] and d['allowed-tools']; print('ok')"
```
Expected: `ok`. (If `yaml` is unavailable, visually confirm the frontmatter matches `commands/best-practices.md`.)

- [ ] **Step 3: Commit**

```bash
git add commands/analyze.md
git commit -m "feat(skill): /ableton:analyze report command"
```

---

### Task 10: Regenerate tool-index + docs site; README

**Files:**
- Modify: `scripts/build_tool_index.py` - add `analyze_set` to the category map (a new "Analysis" group).
- Modify: `scripts/gen_docs_site.py` - add `analyze_set` to its category map (new "Analysis" category).
- Regenerate: `commands/tool-index.md`, `docs/` tool pages.
- Modify: `README.md` - add `/ableton:analyze` to the command list.

- [ ] **Step 1: Find the category maps**

Run:
```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" grep -n "get_session_info\|CATEGOR\|category\|GROUPS\|groups" scripts/build_tool_index.py scripts/gen_docs_site.py | head -40
```
Expected: locates the dict/list that maps tool names → category in each script.

- [ ] **Step 2: Add `analyze_set` to both category maps**

In each script's category map, add an "Analysis" category containing `analyze_set`
(follow the exact literal structure already used - a key with a list of tool names,
matching the style of the neighbouring entries you saw in Step 1).

- [ ] **Step 3: Regenerate**

Run:
```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python scripts/build_tool_index.py
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python scripts/gen_docs_site.py
```
Expected: both succeed. These scripts ASSERT every tool is categorized - if `analyze_set` is uncategorized, the script raises and names it. Fix the map (Step 2) until both pass.

- [ ] **Step 4: Add the command to README**

Add a line to the command list in `README.md` mirroring the existing entries:
```
- `/ableton:analyze` - check the open set against best-practice rulesets and report findings by domain.
```

- [ ] **Step 5: Full suite + import sanity (final regression gate)**

Run:
```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest -q
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python -c "import ableton_mcp_max.server"
```
Expected: all tests pass; import clean.

- [ ] **Step 6: Commit**

```bash
git add scripts/build_tool_index.py scripts/gen_docs_site.py commands/tool-index.md docs README.md
git commit -m "docs(analysis): index analyze_set + /ableton:analyze, regen site"
```

---

### Task 11: Update PROGRESS.md

**Files:**
- Modify: `PROGRESS.md`

- [ ] **Step 1:** Add a top entry summarizing the track-analysis feature: the new `analyze_set` tool + `/ableton:analyze` skill, the rules-as-data design (`rulesets/*.json` + `ruleset_utils`/`analysis_utils`), the config-only/signal-deferred boundary, offline test counts, and the live-verify result from Task 8 Step 7. Note the tool count bumped by 1 and the new "Analysis" docs category. State the next action (release decision: fold into v0.5.0 or ship as a follow-up minor).

- [ ] **Step 2: Commit**

```bash
git add PROGRESS.md
git commit -m "docs: PROGRESS.md - track-analysis feature shipped"
```

---

## Self-review notes (coverage check)

- Spec "curated static ruleset + citations" → Tasks 4 (JSON + sources.md), 5 (anchor validation).
- Spec "rules-as-data + fixed predicate vocabulary" → Tasks 1-3 (resolver, ops, engine); arbitrary Python explicitly excluded.
- Spec "whole-set snapshot, one round-trip" → Task 7 remote reader; Task 8 tool.
- Spec "config now, signal deferred with reserved slot" → `signal:null` (Task 6), `deferred`/`signal_required` routing (Task 3), deferred seed rules (Task 4), honest report section (Task 9).
- Spec "all four domains, selectable focus" → `load_rulesets(focus)` (Task 5), tool `focus` arg (Task 8), skill arg (Task 9).
- Spec "skill layers judgment + report" → Task 9.
- Spec testing (ruleset validation, evaluator, normalizer) → Tasks 2/3/5/6 + tool test Task 8.
- Spec docs (tool-index, site assert-categorized, README) → Task 10.
- Spec rollout 3 phases → Phase 1 (offline), Phase 2 (Live), Phase 3 (skill/docs).
```
