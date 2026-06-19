# Closed-loop Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 4 new MCP tools and a `remediation_utils.py` module that translate `analyze_set` findings into applied mix corrections, completing the analyze->act->verify loop.

**Architecture:** A new pure module `remediation_utils.py` holds all volume-math, action-generation, and plan-building logic. `server.py` gains 4 `@mcp.tool()` functions (`adjust_track_gain`, `gain_stage_track`, `balance_mix`, `apply_findings`) that orchestrate existing primitives via it. `analyze_set` is enhanced to call `generate_actions` before returning so findings carry machine-parseable `action` dicts for deterministic fixes.

**Tech Stack:** Python 3.12+, FastMCP, existing `analysis_utils.live_volume_to_db`, existing `_measure_pass` / `_run_measure_playback` / `_tap_registry` / `_uuid_for_index` / `_integrate_buffer` server-side seams, existing `set_mixer_property` / `get_mixer` wire commands.

## Global Constraints

- All new logic in `remediation_utils.py` is pure (no Live/socket dependency) — importable without Live running.
- Remote Script: zero changes. No Live restart required.
- Volume math uses `_UNITY = 0.85`, taper `db = 40 * log10(v / _UNITY)` (40× not 20× — Live's squared-power fader); inverse `v = _UNITY * 10^(db / 40)`.
- `_DB_FLOOR = -70.0`, `_DB_CEIL = 6.0` — clamp all computed dB before converting back.
- Version bump 0.11.0 → 0.12.0 in THREE places: `pyproject.toml`, `.claude-plugin/plugin.json`, then `uv lock`.
- Run tests with: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/ -q`
- Syntax-check server imports with: `PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python -c "import ableton_mcp_max.server"`
- Never reformat existing code; `ruff` / `black` are not used in this repo.
- All new `@mcp.tool()` functions go in `server.py` grouped together after the existing metering tools (after the `remove_taps` function).
- New category name (for `gen_docs_site.py`): `"remediation"` with title `"Remediation"`.

---

### Task 1: `remediation_utils.py` — volume math + action generation + plan building

**Files:**
- Create: `ableton_mcp_max/remediation_utils.py`
- Create: `tests/test_remediation_utils.py`

**Interfaces:**
- Produces:
  - `db_to_live_volume(db: float) -> float` — inverse of `live_volume_to_db`; clamps to [0, 1]
  - `generate_actions(findings: list, snapshot: dict) -> list` — enriches findings in-place with `action` dicts; returns same list
  - `build_correction_plan(findings: list, severity_filter: list, focus: list) -> dict` — filters+sequences fixable findings into a plan dict
  - `compute_balance_deltas(signals: list, reference_idx: int, target_offsets: list) -> list` — per-track dB deltas for `balance_mix`

- [ ] **Step 1: Write the failing tests for volume math**

```python
# tests/test_remediation_utils.py
import math
from ableton_mcp_max.remediation_utils import db_to_live_volume
from ableton_mcp_max.analysis_utils import live_volume_to_db

_UNITY = 0.85

def test_db_to_live_volume_unity():
    assert abs(db_to_live_volume(0.0) - _UNITY) < 0.001

def test_db_to_live_volume_floor_clamp():
    assert db_to_live_volume(-999.0) == 0.0

def test_db_to_live_volume_ceil_clamp():
    assert db_to_live_volume(999.0) == 1.0

def test_db_to_live_volume_roundtrip():
    for v in [0.2, 0.5, 0.85, 0.95, 1.0]:
        db = live_volume_to_db(v)
        assert abs(db_to_live_volume(db) - v) < 0.001, f"roundtrip failed for v={v}"

def test_db_to_live_volume_negative_3():
    v = db_to_live_volume(-3.0)
    assert 0.0 < v < _UNITY
    # must round-trip within 0.1 dB
    assert abs(live_volume_to_db(v) - (-3.0)) < 0.1
```

- [ ] **Step 2: Run to verify failure**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_remediation_utils.py -q 2>&1 | head -15
```
Expected: ModuleNotFoundError or ImportError (module doesn't exist yet).

- [ ] **Step 3: Create `ableton_mcp_max/remediation_utils.py` with volume math only**

```python
"""Pure remediation helpers. No Live or socket dependency."""

import math

_UNITY = 0.85
_DB_FLOOR = -70.0
_DB_CEIL = 6.0


def db_to_live_volume(db: float) -> float:
    """Inverse of analysis_utils.live_volume_to_db.

    Maps a dB value to a Live mixer volume knob position [0..1].
    Taper: db = 40 * log10(v / 0.85) => v = 0.85 * 10^(db / 40).
    Clamps to [0, 1] (floor -70 dB, ceil +6 dB).
    """
    if db <= _DB_FLOOR:
        return 0.0
    v = _UNITY * (10.0 ** (db / 40.0))
    return min(1.0, max(0.0, v))
```

- [ ] **Step 4: Run volume tests**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_remediation_utils.py -q
```
Expected: 5 passed.

- [ ] **Step 5: Write failing tests for `generate_actions`**

Append to `tests/test_remediation_utils.py`:

```python
from ableton_mcp_max.remediation_utils import generate_actions

# Minimal snapshot with one regular track (index 0) and master
_SNAPSHOT = {
    "tracks": [
        {"index": 0, "name": "Bass", "type": "regular",
         "mixer": {"volume_db": 1.5, "solo": False}},
        {"index": 1, "name": "Lead", "type": "regular",
         "mixer": {"volume_db": 0.5, "solo": True}},
    ],
    "returns": [],
    "master": {
        "volume_db": 0.0,
        "signal": {"true_peak_dbtp": 0.2, "integrated_lufs": -11.0},
    },
}

def test_generate_actions_solo_finding():
    findings = [
        {"id": "health.no_leftover_solo", "status": "fail", "severity": "fail",
         "entity": "Lead", "remediation": "Clear the solo."},
    ]
    result = generate_actions(findings, _SNAPSHOT)
    assert len(result) == 1
    action = result[0].get("action")
    assert action is not None
    assert action["tool"] == "set_mixer_property"
    assert action["params"]["track_index"] == 1
    assert action["params"]["property"] == "solo"
    assert action["params"]["value"] == 0.0

def test_generate_actions_fader_headroom():
    findings = [
        {"id": "mixing.fader_headroom", "status": "warn", "severity": "warn",
         "entity": "Bass", "remediation": "Gain-stage below 0 dB."},
    ]
    result = generate_actions(findings, _SNAPSHOT)
    action = result[0].get("action")
    assert action is not None
    assert action["tool"] == "set_mixer_property"
    assert action["params"]["track_index"] == 0
    assert action["params"]["property"] == "volume"
    assert action["params"]["value"] < _UNITY   # below unity = lower than current

def test_generate_actions_true_peak():
    findings = [
        {"id": "mastering.true_peak", "status": "fail", "severity": "fail",
         "entity": None, "remediation": "Lower the ceiling."},
    ]
    result = generate_actions(findings, _SNAPSHOT)
    action = result[0].get("action")
    assert action is not None
    assert action["tool"] == "set_mixer_property"
    assert action["params"]["track_type"] == "master"
    assert action["params"]["value"] < _UNITY   # lowered from 0.85

def test_generate_actions_true_peak_no_signal():
    snapshot_no_sig = dict(_SNAPSHOT)
    snapshot_no_sig["master"] = {"volume_db": 0.0, "signal": None}
    findings = [
        {"id": "mastering.true_peak", "status": "fail", "severity": "fail",
         "entity": None, "remediation": "Lower the ceiling."},
    ]
    result = generate_actions(findings, snapshot_no_sig)
    assert result[0].get("action") is None

def test_generate_actions_no_fix_passes_through():
    findings = [
        {"id": "mixing.spectral_masking", "status": "warn", "severity": "warn",
         "items": [], "remediation": "EQ-carve."},
    ]
    result = generate_actions(findings, _SNAPSHOT)
    assert result[0].get("action") is None

def test_generate_actions_pass_status_unchanged():
    findings = [
        {"id": "health.no_leftover_solo", "status": "pass", "severity": "fail",
         "entity": "Bass"},
    ]
    result = generate_actions(findings, _SNAPSHOT)
    # pass-status findings don't get an action even if the id is fixable
    assert result[0].get("action") is None

def test_generate_actions_unknown_entity_skipped():
    findings = [
        {"id": "health.no_leftover_solo", "status": "fail", "severity": "fail",
         "entity": "GhostTrack"},  # not in snapshot
    ]
    result = generate_actions(findings, _SNAPSHOT)
    assert result[0].get("action") is None
```

- [ ] **Step 6: Run to verify failure**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_remediation_utils.py::test_generate_actions_solo_finding -q
```
Expected: ImportError (`generate_actions` not defined yet).

- [ ] **Step 7: Implement `generate_actions` in `remediation_utils.py`**

Append to `ableton_mcp_max/remediation_utils.py`:

```python
# Target headroom dB when fixing a clipping fader
_HEADROOM_TARGET_DB = -3.0


def _name_to_index(snapshot: dict) -> dict:
    """Build {name: (index, track_type)} from snapshot tracks + returns."""
    out = {}
    for t in snapshot.get("tracks", []):
        n = t.get("name")
        if n:
            out[n] = (t.get("index"), "regular")
    for r in snapshot.get("returns", []):
        n = r.get("name")
        if n:
            out[n] = (r.get("index"), "return")
    return out


def generate_actions(findings: list, snapshot: dict) -> list:
    """Enrich findings in-place with machine-parseable ``action`` dicts.

    Only adds an ``action`` when the fix is deterministic and the required
    context (track index, signal data) is available. Findings where the fix
    requires human judgment have no ``action`` key. Pass-status findings are
    never actioned.

    Mutates and returns the findings list.
    """
    name_idx = _name_to_index(snapshot)
    master = snapshot.get("master") or {}
    master_vol_db = master.get("volume_db", 0.0)
    master_signal = master.get("signal") or {}

    for f in findings:
        if f.get("status") == "pass":
            continue
        fid = f.get("id", "")
        entity = f.get("entity")

        if fid == "health.no_leftover_solo":
            info = name_idx.get(entity)
            if info is None:
                continue
            idx, ttype = info
            f["action"] = {
                "tool": "set_mixer_property",
                "params": {"track_index": idx, "property": "solo",
                           "value": 0.0, "track_type": ttype},
                "reason": "%s solo cleared" % entity,
            }

        elif fid == "mixing.fader_headroom":
            info = name_idx.get(entity)
            if info is None:
                continue
            idx, ttype = info
            target_vol = db_to_live_volume(_HEADROOM_TARGET_DB)
            f["action"] = {
                "tool": "set_mixer_property",
                "params": {"track_index": idx, "property": "volume",
                           "value": target_vol, "track_type": ttype},
                "reason": "%s fader → %.1f dB" % (entity, _HEADROOM_TARGET_DB),
            }

        elif fid == "mastering.true_peak":
            tp = master_signal.get("true_peak_dbtp")
            if tp is None:
                continue
            excess = tp - (-1.0)   # how many dB above -1 dBTP ceiling
            if excess <= 0:
                continue
            new_db = master_vol_db - excess
            new_vol = db_to_live_volume(new_db)
            f["action"] = {
                "tool": "set_mixer_property",
                "params": {"track_index": 0, "property": "volume",
                           "value": new_vol, "track_type": "master"},
                "reason": "master peak %.1f dBTP → lower by %.1f dB" % (tp, excess),
            }

    return findings
```

- [ ] **Step 8: Run generate_actions tests**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_remediation_utils.py -q
```
Expected: 13 passed (5 volume + 8 action tests).

- [ ] **Step 9: Write failing tests for `build_correction_plan`**

Append to `tests/test_remediation_utils.py`:

```python
from ableton_mcp_max.remediation_utils import build_correction_plan

_ACTION_SOLO = {
    "tool": "set_mixer_property",
    "params": {"track_index": 1, "property": "solo", "value": 0.0, "track_type": "regular"},
}
_ACTION_VOL = {
    "tool": "set_mixer_property",
    "params": {"track_index": 0, "property": "volume", "value": 0.7, "track_type": "regular"},
}
_ACTION_MASTER = {
    "tool": "set_mixer_property",
    "params": {"track_index": 0, "property": "volume", "value": 0.8, "track_type": "master"},
}

_ENRICHED = [
    {"id": "health.no_leftover_solo", "status": "fail", "severity": "fail",
     "entity": "Lead", "action": _ACTION_SOLO},
    {"id": "mixing.fader_headroom", "status": "warn", "severity": "warn",
     "entity": "Bass", "action": _ACTION_VOL},
    {"id": "mastering.true_peak", "status": "fail", "severity": "fail",
     "action": _ACTION_MASTER},
    {"id": "mixing.spectral_masking", "status": "warn", "severity": "warn",
     "items": []},   # no action
    {"id": "health.track_named", "status": "info", "severity": "info",
     "entity": "1-MIDI"},  # filtered by severity
]

def test_build_plan_basic():
    plan = build_correction_plan(_ENRICHED, severity_filter=["fail", "warn"], focus=None)
    ids = [p["finding_id"] for p in plan["plan"]]
    assert "health.no_leftover_solo" in ids
    assert "mixing.fader_headroom" in ids
    assert "mastering.true_peak" in ids

def test_build_plan_skips_no_action():
    plan = build_correction_plan(_ENRICHED, severity_filter=["fail", "warn"], focus=None)
    ids = [p["finding_id"] for p in plan["plan"]]
    assert "mixing.spectral_masking" not in ids
    assert plan["skipped_count"] >= 1
    assert "mixing.spectral_masking" in plan["skipped_reasons"]

def test_build_plan_severity_filter():
    plan = build_correction_plan(_ENRICHED, severity_filter=["fail"], focus=None)
    ids = [p["finding_id"] for p in plan["plan"]]
    assert "mixing.fader_headroom" not in ids   # warn, not fail

def test_build_plan_focus_filter():
    plan = build_correction_plan(_ENRICHED, severity_filter=["fail", "warn"],
                                  focus=["health.no_leftover_solo"])
    ids = [p["finding_id"] for p in plan["plan"]]
    assert ids == ["health.no_leftover_solo"]

def test_build_plan_sequence_health_first():
    plan = build_correction_plan(_ENRICHED, severity_filter=["fail", "warn"], focus=None)
    ids = [p["finding_id"] for p in plan["plan"]]
    # health findings must come before mixing/mastering
    health_pos = next(i for i, x in enumerate(ids) if x.startswith("health."))
    other_pos = [i for i, x in enumerate(ids) if not x.startswith("health.")]
    assert all(health_pos < op for op in other_pos)

def test_build_plan_dedup_same_target():
    # Two findings targeting same track_index + property → keep last
    dup = [
        {"id": "mixing.fader_headroom", "status": "warn", "severity": "warn",
         "entity": "A", "action": {
             "tool": "set_mixer_property",
             "params": {"track_index": 0, "property": "volume", "value": 0.6, "track_type": "regular"}}},
        {"id": "mixing.fader_headroom", "status": "warn", "severity": "warn",
         "entity": "A", "action": {
             "tool": "set_mixer_property",
             "params": {"track_index": 0, "property": "volume", "value": 0.7, "track_type": "regular"}}},
    ]
    plan = build_correction_plan(dup, severity_filter=["warn"], focus=None)
    assert plan["planned_count"] == 1
    assert plan["plan"][0]["action"]["params"]["value"] == 0.7  # last wins

def test_build_plan_counts():
    plan = build_correction_plan(_ENRICHED, severity_filter=["fail", "warn"], focus=None)
    assert plan["planned_count"] == len(plan["plan"])
    assert plan["planned_count"] + plan["skipped_count"] == len(_ENRICHED)
```

- [ ] **Step 10: Run to verify failure**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_remediation_utils.py::test_build_plan_basic -q
```
Expected: ImportError.

- [ ] **Step 11: Implement `build_correction_plan` in `remediation_utils.py`**

Append to `ableton_mcp_max/remediation_utils.py`:

```python
def build_correction_plan(findings: list, severity_filter: list,
                           focus: list = None) -> dict:
    """Filter and sequence fixable findings into an execution plan.

    Returns {plan, planned_count, skipped_count, skipped_reasons}.
    Each plan entry is {finding_id, severity, action, status: "planned"}.
    Deduplicates by (track_index, track_type, property) — last action wins.
    Sequences health.* findings before mixing.*/mastering.*.
    """
    sev_set = set(severity_filter or ["fail", "warn"])
    focus_set = set(focus) if focus else None
    skipped_reasons = {}

    eligible = []
    for f in findings:
        fid = f.get("id", "")
        if focus_set and fid not in focus_set:
            skipped_reasons[fid] = "not in focus filter"
            continue
        if f.get("status") == "pass":
            skipped_reasons[fid] = "already passing"
            continue
        if f.get("severity") not in sev_set:
            skipped_reasons[fid] = "severity filtered"
            continue
        if "action" not in f:
            skipped_reasons[fid] = "no deterministic action"
            continue
        eligible.append(f)

    # Deduplicate: key = (tool, track_index, track_type, property)
    seen = {}
    for f in eligible:
        p = f["action"].get("params", {})
        key = (
            f["action"].get("tool"),
            p.get("track_index"),
            p.get("track_type", "regular"),
            p.get("property"),
        )
        seen[key] = f  # last wins

    deduped = list(seen.values())

    # Sequence: health.* first, then others
    health = [f for f in deduped if f.get("id", "").startswith("health.")]
    others = [f for f in deduped if not f.get("id", "").startswith("health.")]
    ordered = health + others

    plan = [
        {"finding_id": f["id"], "severity": f.get("severity", ""),
         "action": f["action"], "status": "planned"}
        for f in ordered
    ]

    # skipped count: all findings not in the plan
    planned_ids = {p["finding_id"] for p in plan}
    for f in findings:
        fid = f.get("id", "")
        if fid not in planned_ids and fid not in skipped_reasons:
            skipped_reasons[fid] = "deduplicated"

    return {
        "plan": plan,
        "planned_count": len(plan),
        "skipped_count": len(findings) - len(plan),
        "skipped_reasons": skipped_reasons,
    }
```

- [ ] **Step 12: Write and run tests for `compute_balance_deltas`**

Append to `tests/test_remediation_utils.py`:

```python
from ableton_mcp_max.remediation_utils import compute_balance_deltas

def test_compute_balance_deltas_basic():
    signals = [
        {"index": 0, "name": "Kick", "integrated_lufs": -14.0},
        {"index": 1, "name": "Bass", "integrated_lufs": -22.0},
        {"index": 2, "name": "Lead", "integrated_lufs": -14.5},
    ]
    deltas = compute_balance_deltas(signals, reference_idx=0, target_offsets=None)
    # reference (idx 0) should be skipped or have delta 0
    ref = next(d for d in deltas if d["track_index"] == 0)
    assert ref["skipped"] is True
    # Bass is 8 dB below ref, default spread 12 dB -> within spread -> skipped? No...
    # Actually it should NOT be skipped — default behavior is match to ref with offset 0
    bass = next(d for d in deltas if d["track_index"] == 1)
    assert abs(bass["delta_db"] - 8.0) < 0.1   # -22 + 8 = -14 = reference

def test_compute_balance_deltas_within_tolerance():
    signals = [
        {"index": 0, "name": "A", "integrated_lufs": -14.0},
        {"index": 1, "name": "B", "integrated_lufs": -14.4},  # within 1 dB
    ]
    deltas = compute_balance_deltas(signals, reference_idx=0, target_offsets=None)
    b = next(d for d in deltas if d["track_index"] == 1)
    assert b["skipped"] is True  # within tolerance

def test_compute_balance_deltas_custom_offset():
    signals = [
        {"index": 0, "name": "Kick", "integrated_lufs": -14.0},
        {"index": 1, "name": "Bass", "integrated_lufs": -14.0},
    ]
    # Bass should sit 3 dB below Kick
    offsets = [{"track_index": 1, "offset_db": -3.0}]
    deltas = compute_balance_deltas(signals, reference_idx=0, target_offsets=offsets)
    bass = next(d for d in deltas if d["track_index"] == 1)
    assert abs(bass["delta_db"] - (-3.0)) < 0.1   # needs to go down 3 dB

def test_compute_balance_deltas_missing_lufs_skipped():
    signals = [
        {"index": 0, "name": "A", "integrated_lufs": -14.0},
        {"index": 1, "name": "B", "integrated_lufs": None},
    ]
    deltas = compute_balance_deltas(signals, reference_idx=0, target_offsets=None)
    b = next(d for d in deltas if d["track_index"] == 1)
    assert b["skipped"] is True
```

- [ ] **Step 13: Implement `compute_balance_deltas`**

Append to `ableton_mcp_max/remediation_utils.py`:

```python
_BALANCE_TOLERANCE_DB = 1.0


def compute_balance_deltas(signals: list, reference_idx: int,
                            target_offsets: list = None) -> list:
    """Compute per-track dB corrections to balance signals relative to a reference.

    signals: list of {index, name, integrated_lufs} from a measure_mix pass.
    reference_idx: track index whose LUFS is the baseline.
    target_offsets: optional list of {track_index, offset_db}; default 0 (match ref).

    Returns list of {track_index, name, delta_db, current_lufs, target_lufs, skipped}.
    Tracks within _BALANCE_TOLERANCE_DB of their target are skipped.
    Tracks with None LUFS are skipped.
    The reference track itself is always skipped.
    """
    offset_map = {}
    for o in (target_offsets or []):
        offset_map[o["track_index"]] = o.get("offset_db", 0.0)

    # Find reference LUFS
    ref_lufs = None
    for s in signals:
        if s.get("index") == reference_idx:
            ref_lufs = s.get("integrated_lufs")
            break

    out = []
    for s in signals:
        idx = s.get("index")
        lufs = s.get("integrated_lufs")
        name = s.get("name", "")

        if idx == reference_idx:
            out.append({"track_index": idx, "name": name, "delta_db": 0.0,
                        "current_lufs": lufs, "target_lufs": lufs, "skipped": True})
            continue

        if lufs is None or ref_lufs is None:
            out.append({"track_index": idx, "name": name, "delta_db": 0.0,
                        "current_lufs": lufs, "target_lufs": None, "skipped": True})
            continue

        offset = offset_map.get(idx, 0.0)
        target_lufs = ref_lufs + offset
        delta = target_lufs - lufs

        skipped = abs(delta) < _BALANCE_TOLERANCE_DB
        out.append({"track_index": idx, "name": name,
                    "delta_db": round(delta, 1),
                    "current_lufs": lufs, "target_lufs": round(target_lufs, 1),
                    "skipped": skipped})
    return out
```

- [ ] **Step 14: Run all tests so far**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_remediation_utils.py -q
```
Expected: ~26 passed, 0 failed.

- [ ] **Step 15: Commit**

```bash
git add ableton_mcp_max/remediation_utils.py tests/test_remediation_utils.py
git commit -m "feat(remediation): add remediation_utils with volume math, action generation, plan building"
```

---

### Task 2: `adjust_track_gain` tool

**Files:**
- Modify: `ableton_mcp_max/server.py` (add import + 1 new `@mcp.tool()`)
- Create: `tests/test_adjust_track_gain.py`

**Interfaces:**
- Consumes: `db_to_live_volume` from `remediation_utils`, `live_volume_to_db` from `analysis_utils`, `get_ableton_connection`, `_ok`, `_err`
- Produces: `adjust_track_gain(ctx, track_index, delta_db, track_type="regular") -> str` (JSON `{ok, data}`)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_adjust_track_gain.py
import json
import ableton_mcp_max.server as server
from ableton_mcp_max.analysis_utils import live_volume_to_db
from ableton_mcp_max.remediation_utils import db_to_live_volume


class _FakeConn:
    def __init__(self, mixer_vol=0.85):
        self._mixer_vol = mixer_vol
        self.last_set = None

    def send_command(self, cmd, params=None):
        if cmd == "get_mixer":
            return {"volume": self._mixer_vol}
        if cmd == "set_mixer_property":
            self.last_set = params
            return {"ok": True}
        return {}


def test_adjust_track_gain_down():
    conn = _FakeConn(mixer_vol=0.85)  # 0.85 = 0 dB
    monkeypatch_conn = lambda: conn
    import ableton_mcp_max.server as s
    orig = s.get_ableton_connection
    s.get_ableton_connection = monkeypatch_conn
    try:
        out = json.loads(s.adjust_track_gain(ctx=None, track_index=0, delta_db=-3.0))
        assert out["ok"] is True
        d = out["data"]
        assert abs(d["db_before"] - 0.0) < 0.1
        assert abs(d["db_after"] - (-3.0)) < 0.2
        assert d["volume_after"] < d["volume_before"]
        # verify set_mixer_property was called with the new volume
        assert conn.last_set is not None
        assert abs(conn.last_set["value"] - db_to_live_volume(-3.0)) < 0.001
    finally:
        s.get_ableton_connection = orig


def test_adjust_track_gain_up():
    conn = _FakeConn(mixer_vol=0.70)  # below unity
    import ableton_mcp_max.server as s
    orig = s.get_ableton_connection
    s.get_ableton_connection = lambda: conn
    try:
        out = json.loads(s.adjust_track_gain(ctx=None, track_index=1, delta_db=3.0))
        d = out["data"]
        assert d["volume_after"] > d["volume_before"]
    finally:
        s.get_ableton_connection = orig


def test_adjust_track_gain_clamps_at_floor():
    conn = _FakeConn(mixer_vol=0.1)
    import ableton_mcp_max.server as s
    orig = s.get_ableton_connection
    s.get_ableton_connection = lambda: conn
    try:
        out = json.loads(s.adjust_track_gain(ctx=None, track_index=0, delta_db=-200.0))
        d = out["data"]
        assert d["volume_after"] == 0.0
        assert d["db_after"] == -70.0
    finally:
        s.get_ableton_connection = orig


def test_adjust_track_gain_no_volume_returns_error():
    class NoVolConn:
        def send_command(self, cmd, params=None):
            return {}  # no "volume" key
    import ableton_mcp_max.server as s
    orig = s.get_ableton_connection
    s.get_ableton_connection = lambda: NoVolConn()
    try:
        out = json.loads(s.adjust_track_gain(ctx=None, track_index=0, delta_db=-3.0))
        assert out["ok"] is False
    finally:
        s.get_ableton_connection = orig
```

- [ ] **Step 2: Run to verify failure**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_adjust_track_gain.py -q
```
Expected: AttributeError (`adjust_track_gain` not on module).

- [ ] **Step 3: Add import to server.py and implement `adjust_track_gain`**

Add to the imports block in `ableton_mcp_max/server.py` (after the existing `from ableton_mcp_max.arrangement_structure_utils import` block):

```python
from ableton_mcp_max.remediation_utils import (
    db_to_live_volume,
    generate_actions,
    build_correction_plan,
    compute_balance_deltas,
)
from ableton_mcp_max.analysis_utils import live_volume_to_db
```

Note: `live_volume_to_db` is NOT yet imported in server.py. Add it to the existing `from ableton_mcp_max.analysis_utils import` line:

Find this line (around line 102):
```python
from ableton_mcp_max.analysis_utils import normalize_snapshot, evaluate_rules
```
Change to:
```python
from ableton_mcp_max.analysis_utils import normalize_snapshot, evaluate_rules, live_volume_to_db
```

Then add the new tool after the `remove_taps` function (find `def remove_taps` and add after its closing):

```python
@mcp.tool()
def adjust_track_gain(
    ctx: Context,
    track_index: int,
    delta_db: float,
    track_type: str = "regular",
) -> str:
    """Shift a track's fader by a signed dB amount without playback.

    Reads the current volume knob value, converts using Live's 40x log taper
    (unity = 0.85), applies delta_db, clamps to [-70, +6] dB, and writes the
    new value back via set_mixer_property. No tap or playback required.

    Parameters:
    - track_index: index of the track (ignored for master; pass 0)
    - delta_db: signed dB shift; positive = louder, negative = quieter
    - track_type: "regular" (default), "return", or "master"

    Returns JSON {ok, data:{track_index, delta_db, volume_before, volume_after,
    db_before, db_after}}.
    """
    try:
        ableton = get_ableton_connection()
        mixer = ableton.send_command(
            "get_mixer", {"track_index": track_index, "track_type": track_type}
        )
        current_vol = mixer.get("volume")
        if current_vol is None:
            return _err("Volume not available for track %s (%s)" % (track_index, track_type))
        current_db = live_volume_to_db(current_vol)
        new_db = max(-70.0, min(6.0, current_db + delta_db))
        new_vol = db_to_live_volume(new_db)
        ableton.send_command(
            "set_mixer_property",
            {"track_index": track_index, "track_type": track_type,
             "property": "volume", "value": new_vol, "send_index": -1},
        )
        return _ok({
            "track_index": track_index,
            "track_type": track_type,
            "delta_db": delta_db,
            "volume_before": current_vol,
            "volume_after": new_vol,
            "db_before": current_db,
            "db_after": round(new_db, 1),
        })
    except Exception as e:
        logger.error("Error adjusting track gain: %s", e)
        return _err("Error adjusting track gain: %s" % e)
```

- [ ] **Step 4: Run tests and verify server import**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_adjust_track_gain.py -q
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python -c "import ableton_mcp_max.server; print('ok')"
```
Expected: 4 passed, "ok".

- [ ] **Step 5: Run full suite**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/ -q
```
Expected: 618 + 4 new = 622 passed.

- [ ] **Step 6: Commit**

```bash
git add ableton_mcp_max/server.py tests/test_adjust_track_gain.py
git commit -m "feat(remediation): add adjust_track_gain tool"
```

---

### Task 3: `gain_stage_track` tool

**Files:**
- Modify: `ableton_mcp_max/server.py` (add `gain_stage_track` after `adjust_track_gain`)
- Create: `tests/test_gain_stage_track.py`

**Interfaces:**
- Consumes: `_uuid_for_index`, `_tap_registry`, `_run_measure_playback`, `_integrate_buffer`, `adjust_track_gain` (called via server internals), `live_volume_to_db`, `db_to_live_volume`
- Produces: `gain_stage_track(ctx, track_index, target_db, window_s, max_iterations, track_type) -> str`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_gain_stage_track.py
import json
import ableton_mcp_max.server as server


class _FakeTapState:
    def __init__(self, tracks, lufs_sequence):
        self._tracks = tracks
        self._seq = iter(lufs_sequence)
        self._buf = []

    def tracks(self):
        return self._tracks

    def reset(self, uuid=None):
        pass

    def buffer(self, uuid):
        return self._buf


class _FakeConn:
    def __init__(self, vol=0.85):
        self._vol = vol
        self.set_calls = []

    def send_command(self, cmd, params=None):
        if cmd == "get_mixer":
            return {"volume": self._vol}
        if cmd == "set_mixer_property":
            self.set_calls.append(params)
            # simulate the volume update
            self._vol = params.get("value", self._vol)
            return {}
        return {}


def _make_buf_for_lufs(lufs):
    """Fake buffer that produces the given integrated LUFS from _integrate_buffer.
    We monkeypatch _integrate_buffer directly so the buf content doesn't matter.
    """
    return [{"ms_k_l": 1e-5, "ms_k_r": 1e-5, "peak": 0.1, "rms": 0.05}] * 50


def test_gain_stage_track_no_tap_error():
    import ableton_mcp_max.server as s

    class _EmptyReg:
        class state:
            @staticmethod
            def tracks(): return []
            @staticmethod
            def reset(uuid=None): pass

    orig_reg = s._tap_registry
    s._tap_registry = _EmptyReg()
    try:
        out = json.loads(s.gain_stage_track(ctx=None, track_index=0))
        assert out["ok"] is False
        assert "No tap" in out["error"]
    finally:
        s._tap_registry = orig_reg


def test_gain_stage_track_converges_in_one_iteration(monkeypatch):
    """Track measures -21 dBLUFS, target -18: delta +3, should converge after 1 iter."""
    TRACK_IDX = 2
    UUID = "abc"

    class _FakeReg:
        class state:
            @staticmethod
            def tracks():
                return [{"uuid": UUID, "index": TRACK_IDX, "kind": "regular",
                         "sample_rate": 48000}]
            @staticmethod
            def reset(uuid=None): pass
            @staticmethod
            def buffer(uuid): return []

    conn = _FakeConn(vol=0.75)  # some starting volume
    monkeypatch.setattr(server, "_tap_registry", _FakeReg())
    monkeypatch.setattr(server, "get_ableton_connection", lambda: conn)

    # First measure: -21 dBLUFS; after correction re-measure: -18.1 (converged)
    call_count = [0]
    def fake_integrate(buf, sr):
        call_count[0] += 1
        if call_count[0] == 1:
            return {"integrated_lufs": -21.0, "momentary_lufs": None,
                    "short_term_lufs": None, "true_peak_dbtp": None,
                    "peak": 0.1, "rms": 0.05, "crest": None,
                    "bands": None, "width": None, "correlation": None,
                    "block_count": 50, "sample_rate": 48000}
        return {"integrated_lufs": -18.1, "momentary_lufs": None,
                "short_term_lufs": None, "true_peak_dbtp": None,
                "peak": 0.1, "rms": 0.05, "crest": None,
                "bands": None, "width": None, "correlation": None,
                "block_count": 50, "sample_rate": 48000}

    monkeypatch.setattr(server, "_integrate_buffer", fake_integrate)
    monkeypatch.setattr(server, "_run_measure_playback", lambda s, r=None: True)

    out = json.loads(server.gain_stage_track(
        ctx=None, track_index=TRACK_IDX, target_db=-18.0, window_s=4.0, max_iterations=3
    ))
    assert out["ok"] is True
    d = out["data"]
    assert d["before_db"] == -21.0
    assert d["converged"] is True
    assert d["iterations"] == 2
    assert len(conn.set_calls) >= 1  # fader was adjusted


def test_gain_stage_track_does_not_converge(monkeypatch):
    """Simulate a track that never converges (oscillates)."""
    TRACK_IDX = 3
    UUID = "xyz"

    class _FakeReg:
        class state:
            @staticmethod
            def tracks():
                return [{"uuid": UUID, "index": TRACK_IDX, "kind": "regular",
                         "sample_rate": 48000}]
            @staticmethod
            def reset(uuid=None): pass
            @staticmethod
            def buffer(uuid): return []

    monkeypatch.setattr(server, "_tap_registry", _FakeReg())
    monkeypatch.setattr(server, "get_ableton_connection", lambda: _FakeConn(0.85))
    monkeypatch.setattr(server, "_run_measure_playback", lambda s, r=None: True)

    call_count = [0]
    def fake_integrate(buf, sr):
        call_count[0] += 1
        return {"integrated_lufs": -21.0, "momentary_lufs": None,
                "short_term_lufs": None, "true_peak_dbtp": None,
                "peak": 0.1, "rms": 0.05, "crest": None,
                "bands": None, "width": None, "correlation": None,
                "block_count": 50, "sample_rate": 48000}

    monkeypatch.setattr(server, "_integrate_buffer", fake_integrate)
    out = json.loads(server.gain_stage_track(
        ctx=None, track_index=TRACK_IDX, target_db=-18.0, window_s=4.0, max_iterations=2
    ))
    assert out["ok"] is True
    d = out["data"]
    assert d["converged"] is False
    assert d["iterations"] == 2
```

- [ ] **Step 2: Run to verify failure**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_gain_stage_track.py -q
```
Expected: AttributeError (`gain_stage_track` not defined).

- [ ] **Step 3: Implement `gain_stage_track` in server.py** (after `adjust_track_gain`)

```python
@mcp.tool()
def gain_stage_track(
    ctx: Context,
    track_index: int,
    target_db: float = -18.0,
    window_s: float = 4.0,
    max_iterations: int = 3,
    track_type: str = "regular",
) -> str:
    """Play the set, measure the track's LUFS via its MCP Tap, and iteratively
    converge the fader to target_db.

    Requires an MCP Tap device deployed on the target track (via deploy_taps).
    Plays the arrangement for window_s seconds each iteration, integrates the
    buffered tap blocks into LUFS, computes the correction, and applies it via
    the fader. Repeats up to max_iterations times or until within 1 dB of target.

    Parameters:
    - track_index: index of the regular/return/master track to stage
    - target_db: target integrated LUFS (default -18.0, a standard gain-staging level)
    - window_s: playback capture window per iteration in seconds (default 4.0)
    - max_iterations: maximum correction cycles (default 3)
    - track_type: "regular" (default), "return", or "master"

    Returns JSON {ok, data:{track_index, target_db, before_db, after_db,
    correction_db, converged, iterations, volume_before, volume_after}}.
    {ok:false,error} if no tap is connected for this track.
    """
    try:
        uuid = _uuid_for_index(track_index)
        if uuid is None:
            return _err("No tap connected for track %s" % track_index)

        ableton = get_ableton_connection()
        mixer_initial = ableton.send_command(
            "get_mixer", {"track_index": track_index, "track_type": track_type}
        )
        volume_before = mixer_initial.get("volume")
        if volume_before is None:
            return _err("Volume not available for track %s" % track_index)

        sample_rate = 48000
        for t in _tap_registry.state.tracks():
            if t.get("uuid") == uuid:
                sample_rate = t.get("sample_rate", 48000)
                break

        before_db = None
        measured_db = None
        last_vol = volume_before
        total_correction = 0.0
        converged = False
        iterations = 0

        for _ in range(max(1, max_iterations)):
            iterations += 1
            _tap_registry.state.reset(uuid)
            _run_measure_playback(window_s)
            buf = _tap_registry.state.buffer(uuid)
            metrics = _integrate_buffer(buf, sample_rate)
            measured_db = metrics.get("integrated_lufs")
            if measured_db is None:
                return _err("No audio data received for track %s; is the set playing?" % track_index)
            if before_db is None:
                before_db = measured_db
            delta = target_db - measured_db
            if abs(delta) < 1.0:
                converged = True
                break
            current_db = live_volume_to_db(last_vol)
            new_db = max(-70.0, min(6.0, current_db + delta))
            new_vol = db_to_live_volume(new_db)
            ableton.send_command(
                "set_mixer_property",
                {"track_index": track_index, "track_type": track_type,
                 "property": "volume", "value": new_vol, "send_index": -1},
            )
            last_vol = new_vol
            total_correction += delta

        mixer_final = ableton.send_command(
            "get_mixer", {"track_index": track_index, "track_type": track_type}
        )
        volume_after = mixer_final.get("volume", last_vol)

        return _ok({
            "track_index": track_index,
            "track_type": track_type,
            "target_db": target_db,
            "before_db": before_db,
            "after_db": measured_db,
            "correction_db": round(total_correction, 1),
            "converged": converged,
            "iterations": iterations,
            "volume_before": volume_before,
            "volume_after": volume_after,
        })
    except Exception as e:
        logger.error("Error in gain_stage_track: %s", e)
        return _err("Error in gain_stage_track: %s" % e)
```

- [ ] **Step 4: Run tests + full suite**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_gain_stage_track.py -q
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/ -q
```
Expected: 3 passed (new), ~625 total.

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/server.py tests/test_gain_stage_track.py
git commit -m "feat(remediation): add gain_stage_track tool"
```

---

### Task 4: `balance_mix` tool

**Files:**
- Modify: `ableton_mcp_max/server.py` (add `balance_mix` after `gain_stage_track`)
- Create: `tests/test_balance_mix.py`

**Interfaces:**
- Consumes: `_measure_pass`, `compute_balance_deltas`, `get_ableton_connection`, `_ok`, `_err`
- Produces: `balance_mix(ctx, reference_track_index, window_s, target_offsets, tracks) -> str`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_balance_mix.py
import json
import ableton_mcp_max.server as server


def test_balance_mix_applies_corrections(monkeypatch):
    """Two tracks: ref at -14, other at -22 (delta +8). Should call set_mixer_property."""
    set_calls = []

    class _FakeConn:
        def send_command(self, cmd, params=None):
            if cmd == "set_mixer_property":
                set_calls.append(params)
            if cmd == "get_mixer":
                return {"volume": 0.75}
            return {}

    TRACKS_OUT = [
        {"name": "Kick", "index": 0, "kind": "regular",
         "signal": {"integrated_lufs": -14.0}},
        {"name": "Bass", "index": 1, "kind": "regular",
         "signal": {"integrated_lufs": -22.0}},
    ]
    SIGS = [
        {"index": 0, "name": "Kick", "integrated_lufs": -14.0},
        {"index": 1, "name": "Bass", "integrated_lufs": -22.0},
    ]

    monkeypatch.setattr(server, "_measure_pass",
                        lambda w, region=None, name_by_index=None: (TRACKS_OUT, SIGS))
    monkeypatch.setattr(server, "get_ableton_connection", lambda: _FakeConn())

    out = json.loads(server.balance_mix(ctx=None, reference_track_index=0))
    assert out["ok"] is True
    d = out["data"]
    assert d["reference_track_index"] == 0
    assert d["reference_db"] == -14.0
    adj = {a["track_index"]: a for a in d["adjustments"]}
    assert adj[0]["skipped"] is True       # reference is always skipped
    assert adj[1]["skipped"] is False
    assert abs(adj[1]["delta_db"] - 8.0) < 0.1
    # set_mixer_property was called for Bass
    assert any(c["track_index"] == 1 for c in set_calls)


def test_balance_mix_within_tolerance_skips(monkeypatch):
    """Tracks already within 1 dB of reference should be skipped."""
    class _FakeConn:
        def send_command(self, cmd, params=None): return {}

    TRACKS_OUT = [
        {"name": "A", "index": 0, "kind": "regular", "signal": {"integrated_lufs": -14.0}},
        {"name": "B", "index": 1, "kind": "regular", "signal": {"integrated_lufs": -14.5}},
    ]
    SIGS = [
        {"index": 0, "name": "A", "integrated_lufs": -14.0},
        {"index": 1, "name": "B", "integrated_lufs": -14.5},
    ]
    monkeypatch.setattr(server, "_measure_pass",
                        lambda w, region=None, name_by_index=None: (TRACKS_OUT, SIGS))
    monkeypatch.setattr(server, "get_ableton_connection", lambda: _FakeConn())

    out = json.loads(server.balance_mix(ctx=None, reference_track_index=0))
    d = out["data"]
    adj = {a["track_index"]: a for a in d["adjustments"]}
    assert adj[1]["skipped"] is True


def test_balance_mix_custom_offsets(monkeypatch):
    """Bass should sit 3 dB below Kick via target_offsets."""
    set_calls = []

    class _FakeConn:
        def send_command(self, cmd, params=None):
            if cmd == "set_mixer_property":
                set_calls.append(params)
            if cmd == "get_mixer":
                return {"volume": 0.85}
            return {}

    SIGS = [
        {"index": 0, "name": "Kick", "integrated_lufs": -14.0},
        {"index": 1, "name": "Bass", "integrated_lufs": -14.0},  # same as ref
    ]
    TRACKS_OUT = [{"name": s["name"], "index": s["index"], "kind": "regular",
                   "signal": {"integrated_lufs": s["integrated_lufs"]}} for s in SIGS]

    monkeypatch.setattr(server, "_measure_pass",
                        lambda w, region=None, name_by_index=None: (TRACKS_OUT, SIGS))
    monkeypatch.setattr(server, "get_ableton_connection", lambda: _FakeConn())

    out = json.loads(server.balance_mix(
        ctx=None, reference_track_index=0,
        target_offsets=[{"track_index": 1, "offset_db": -3.0}]
    ))
    d = out["data"]
    adj = {a["track_index"]: a for a in d["adjustments"]}
    assert adj[1]["skipped"] is False
    assert abs(adj[1]["delta_db"] - (-3.0)) < 0.1
```

- [ ] **Step 2: Run to verify failure**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_balance_mix.py -q
```
Expected: AttributeError.

- [ ] **Step 3: Implement `balance_mix` in server.py** (after `gain_stage_track`)

```python
@mcp.tool()
def balance_mix(
    ctx: Context,
    reference_track_index: int,
    window_s: float = 8.0,
    target_offsets: list = None,
    tracks: list = None,
) -> str:
    """Single coherent measure pass + batch-apply level corrections.

    Runs one measure_mix-style playback window across all connected taps,
    then adjusts each track's fader so its integrated LUFS matches the
    reference track (plus any per-track offset_db you specify). Tracks within
    1 dB of their target are skipped. All corrections are applied individually
    (not batched) so each adjust_track_gain call validates its own target.

    Parameters:
    - reference_track_index: track whose LUFS is the balance baseline
    - window_s: capture length in seconds (default 8.0)
    - target_offsets: optional list of {track_index, offset_db} specifying
      how many dB above/below the reference each track should sit
    - tracks: optional list of track indices to correct (subset of tapped tracks)

    Returns JSON {ok, data:{reference_track_index, reference_db, window_s,
    adjustments:[{track_index, name, before_db, delta_db, skipped}]}}.
    """
    try:
        tracks_out, sigs = _measure_pass(window_s)
        ref_lufs = None
        for s in sigs:
            if s.get("index") == reference_track_index:
                ref_lufs = s.get("integrated_lufs")
                break
        if ref_lufs is None:
            return _err(
                "Reference track %s not found in tap signals. "
                "Is a tap deployed on that track?" % reference_track_index
            )

        deltas = compute_balance_deltas(sigs, reference_track_index, target_offsets)

        # Filter to the requested subset
        if tracks is not None:
            track_set = set(tracks)
            deltas = [d for d in deltas if d["track_index"] in track_set]

        ableton = get_ableton_connection()
        adjustments = []
        for d in deltas:
            if d["skipped"]:
                adjustments.append({
                    "track_index": d["track_index"],
                    "name": d["name"],
                    "before_db": d["current_lufs"],
                    "delta_db": d["delta_db"],
                    "skipped": True,
                })
                continue
            idx = d["track_index"]
            mixer = ableton.send_command(
                "get_mixer", {"track_index": idx, "track_type": "regular"}
            )
            vol = mixer.get("volume")
            if vol is not None:
                current_db = live_volume_to_db(vol)
                new_db = max(-70.0, min(6.0, current_db + d["delta_db"]))
                new_vol = db_to_live_volume(new_db)
                ableton.send_command(
                    "set_mixer_property",
                    {"track_index": idx, "track_type": "regular",
                     "property": "volume", "value": new_vol, "send_index": -1},
                )
            adjustments.append({
                "track_index": idx,
                "name": d["name"],
                "before_db": d["current_lufs"],
                "delta_db": d["delta_db"],
                "skipped": False,
            })

        return _ok({
            "reference_track_index": reference_track_index,
            "reference_db": ref_lufs,
            "window_s": window_s,
            "adjustments": adjustments,
        })
    except Exception as e:
        logger.error("Error in balance_mix: %s", e)
        return _err("Error in balance_mix: %s" % e)
```

- [ ] **Step 4: Run tests + full suite**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_balance_mix.py -q
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/ -q
```
Expected: 3 passed (new), ~628 total.

- [ ] **Step 5: Commit**

```bash
git add ableton_mcp_max/server.py tests/test_balance_mix.py
git commit -m "feat(remediation): add balance_mix tool"
```

---

### Task 5: `apply_findings` tool + finding enrichment in `analyze_set`

**Files:**
- Modify: `ableton_mcp_max/server.py` (add `apply_findings`, enhance `analyze_set`)
- Create: `tests/test_apply_findings.py`

**Interfaces:**
- Consumes: `generate_actions`, `build_correction_plan`, `get_ableton_connection`, `_ok`, `_err`
- Produces:
  - `apply_findings(ctx, findings, dry_run, severity_filter, focus) -> str`
  - `analyze_set` now calls `generate_actions` before returning, adding `action` fields to enrichable findings

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_apply_findings.py
import json
import ableton_mcp_max.server as server


# A realistic enriched findings list (as returned by the enhanced analyze_set)
_ACTION_SOLO = {"tool": "set_mixer_property",
                "params": {"track_index": 1, "property": "solo", "value": 0.0,
                           "track_type": "regular"},
                "reason": "Lead solo cleared"}
_ACTION_VOL  = {"tool": "set_mixer_property",
                "params": {"track_index": 0, "property": "volume", "value": 0.76,
                           "track_type": "regular"},
                "reason": "Bass fader → -3.0 dB"}

_FINDINGS = [
    {"id": "health.no_leftover_solo", "status": "fail", "severity": "fail",
     "entity": "Lead", "action": _ACTION_SOLO},
    {"id": "mixing.fader_headroom", "status": "warn", "severity": "warn",
     "entity": "Bass", "action": _ACTION_VOL},
    {"id": "mixing.spectral_masking", "status": "warn", "severity": "warn",
     "items": []},  # no action
]


def test_apply_findings_dry_run_returns_plan_only():
    """dry_run=True should never call set_mixer_property."""
    set_calls = []

    class _FakeConn:
        def send_command(self, cmd, params=None):
            if cmd == "set_mixer_property":
                set_calls.append(params)
            return {}

    orig = server.get_ableton_connection
    server.get_ableton_connection = lambda: _FakeConn()
    try:
        out = json.loads(server.apply_findings(
            ctx=None, findings=_FINDINGS, dry_run=True, severity_filter=["fail", "warn"]
        ))
        assert out["ok"] is True
        d = out["data"]
        assert d["dry_run"] is True
        assert d["planned_count"] >= 2
        assert all(p["status"] == "planned" for p in d["plan"])
        assert set_calls == []  # no mutations
    finally:
        server.get_ableton_connection = orig


def test_apply_findings_applies_when_not_dry_run():
    set_calls = []

    class _FakeConn:
        def send_command(self, cmd, params=None):
            if cmd == "set_mixer_property":
                set_calls.append(params)
            return {}

    orig = server.get_ableton_connection
    server.get_ableton_connection = lambda: _FakeConn()
    try:
        out = json.loads(server.apply_findings(
            ctx=None, findings=_FINDINGS, dry_run=False, severity_filter=["fail", "warn"]
        ))
        assert out["ok"] is True
        d = out["data"]
        assert d["dry_run"] is False
        applied = [p for p in d["plan"] if p["status"] == "applied"]
        assert len(applied) >= 2
        assert len(set_calls) >= 2
    finally:
        server.get_ableton_connection = orig


def test_apply_findings_skips_no_action():
    orig = server.get_ableton_connection
    server.get_ableton_connection = lambda: type("C", (), {"send_command": lambda s, c, p=None: {}})()
    try:
        out = json.loads(server.apply_findings(
            ctx=None, findings=_FINDINGS, dry_run=True, severity_filter=["fail", "warn"]
        ))
        d = out["data"]
        skipped = d["skipped_reasons"]
        assert "mixing.spectral_masking" in skipped
    finally:
        server.get_ableton_connection = orig


def test_apply_findings_severity_filter():
    orig = server.get_ableton_connection
    server.get_ableton_connection = lambda: type("C", (), {"send_command": lambda s, c, p=None: {}})()
    try:
        out = json.loads(server.apply_findings(
            ctx=None, findings=_FINDINGS, dry_run=True, severity_filter=["fail"]
        ))
        d = out["data"]
        ids = [p["finding_id"] for p in d["plan"]]
        assert "mixing.fader_headroom" not in ids   # warn only
        assert "health.no_leftover_solo" in ids      # fail
    finally:
        server.get_ableton_connection = orig


def test_analyze_set_enriches_findings(monkeypatch):
    """analyze_set should add action fields to fixable findings."""
    _RAW = {
        "transport": {"tempo": 120.0, "is_playing": False,
                      "signature_numerator": 4, "signature_denominator": 4},
        "tracks": [
            {"name": "Lead", "index": 0, "type": "midi", "volume": 0.95, "panning": 0.0,
             "sends": [0.0], "mute": False, "solo": True, "arm": False,
             "has_instrument": True, "is_grouped": False,
             "devices": [{"index": 0, "name": "Wavetable", "class_name": "InstrumentVector",
                          "on": True, "is_instrument": True}],
             "clips": {"count": 0, "named": 0, "warped": 0, "empty_slots": 8},
             "routing": {"audio_to": "Master", "audio_from": "No Input"}},
        ],
        "returns": [],
        "master": {"name": "Master", "volume": 0.85, "panning": 0.0, "devices": []},
    }

    class _FakeConn:
        def send_command(self, cmd, params=None):
            return _RAW

    monkeypatch.setattr(server, "get_ableton_connection", lambda: _FakeConn())
    out = json.loads(server.analyze_set(ctx=None, focus="health"))
    assert out["ok"] is True
    findings = out["data"]["findings"]
    solo_f = next((f for f in findings if f["id"] == "health.no_leftover_solo"
                   and f["status"] == "fail"), None)
    assert solo_f is not None
    assert "action" in solo_f
    assert solo_f["action"]["tool"] == "set_mixer_property"
    assert solo_f["action"]["params"]["property"] == "solo"
```

- [ ] **Step 2: Run to verify failure**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_apply_findings.py -q
```
Expected: AttributeError (`apply_findings` not defined).

- [ ] **Step 3: Implement `apply_findings` in server.py** (after `balance_mix`)

```python
@mcp.tool()
def apply_findings(
    ctx: Context,
    findings: list,
    dry_run: bool = True,
    severity_filter: list = None,
    focus: list = None,
) -> str:
    """Translate analyze_set findings into a correction plan and optionally apply it.

    Takes the ``findings`` list from analyze_set output (or a merged list) and
    executes the mechanically-fixable ones. Findings with an ``action`` dict
    (added by analyze_set's generate_actions enrichment) that match the
    severity_filter are applied; others are reported as skipped with a reason.

    IMPORTANT: dry_run defaults to True — the plan is returned without mutating
    Live. Always inspect the plan before passing dry_run=False.

    Parameters:
    - findings: list of finding dicts from analyze_set data.findings (must
      have been produced with action enrichment — i.e. from this server v0.12+)
    - dry_run: when True (default), return the plan without applying changes
    - severity_filter: list of severities to include (default ["fail", "warn"])
    - focus: optional list of finding ids to restrict to

    Returns JSON {ok, data:{dry_run, plan:[{finding_id, severity, action, status,
    [error]}], planned_count, skipped_count, skipped_reasons}}.
    """
    try:
        sev = severity_filter if severity_filter is not None else ["fail", "warn"]
        plan_data = build_correction_plan(findings, severity_filter=sev, focus=focus)

        if dry_run:
            return _ok({
                "dry_run": True,
                "plan": plan_data["plan"],
                "planned_count": plan_data["planned_count"],
                "skipped_count": plan_data["skipped_count"],
                "skipped_reasons": plan_data["skipped_reasons"],
            })

        ableton = get_ableton_connection()
        results = []
        for entry in plan_data["plan"]:
            action = entry["action"]
            tool_name = action.get("tool")
            params = action.get("params", {})
            try:
                if tool_name == "set_mixer_property":
                    ableton.send_command("set_mixer_property", {
                        "track_index": params.get("track_index", 0),
                        "track_type": params.get("track_type", "regular"),
                        "property": params.get("property"),
                        "value": params.get("value"),
                        "send_index": params.get("send_index", -1),
                    })
                    results.append({**entry, "status": "applied"})
                else:
                    results.append({**entry, "status": "error",
                                    "error": "unknown tool %s" % tool_name})
            except Exception as exc:
                results.append({**entry, "status": "error", "error": str(exc)})

        applied = sum(1 for r in results if r["status"] == "applied")
        return _ok({
            "dry_run": False,
            "plan": results,
            "planned_count": len(results),
            "applied_count": applied,
            "skipped_count": plan_data["skipped_count"],
            "skipped_reasons": plan_data["skipped_reasons"],
        })
    except Exception as e:
        logger.error("Error in apply_findings: %s", e)
        return _err("Error in apply_findings: %s" % e)
```

- [ ] **Step 4: Enhance `analyze_set` to call `generate_actions`**

In `server.py`, find the `analyze_set` function's return statement (around line 765):

```python
        return _ok(result)
    except Exception as e:
        logger.error(f"Error analyzing set: {str(e)}")
        return _err(f"Error analyzing set: {str(e)}")
```

Change the `return _ok(result)` line to call `generate_actions` first:

Find this block in `analyze_set`:
```python
        return _ok(result)
    except Exception as e:
        logger.error(f"Error analyzing set: {str(e)}")
        return _err(f"Error analyzing set: {str(e)}")
```

Replace with:
```python
        result["findings"] = generate_actions(result["findings"], snapshot)
        return _ok(result)
    except Exception as e:
        logger.error(f"Error analyzing set: {str(e)}")
        return _err(f"Error analyzing set: {str(e)}")
```

- [ ] **Step 5: Run all tests**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/test_apply_findings.py -q
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/ -q
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python -c "import ableton_mcp_max.server; print('ok')"
```
Expected: 5 passed (new), ~633 total, "ok".

- [ ] **Step 6: Commit**

```bash
git add ableton_mcp_max/server.py tests/test_apply_findings.py
git commit -m "feat(remediation): add apply_findings tool and enrich analyze_set with action dicts"
```

---

### Task 6: Docs regen + version bump

**Files:**
- Modify: `scripts/gen_docs_site.py` (add Remediation category)
- Modify: `docs/index.md` (update hero counts: 128→132, 18→19)
- Modify: `pyproject.toml` (version 0.11.0→0.12.0)
- Modify: `.claude-plugin/plugin.json` (version 0.11.0→0.12.0)
- Run: `uv lock` to sync `uv.lock`
- Run: `python3 scripts/gen_docs_site.py` to regenerate tool pages

**Interfaces:**
- No new code — configuration and doc regen only.

- [ ] **Step 1: Add "Remediation" category to `gen_docs_site.py`**

In `scripts/gen_docs_site.py`, find the `CATEGORIES` list and add AFTER the `("composition", ...)` entry:

```python
    ("remediation", "Remediation", "Translate analysis findings into applied mix corrections: shift faders by dB, auto-stage a track to a target LUFS via its MCP Tap, balance all tapped tracks in one coherent pass, and execute a structured correction plan from analyze_set findings.", [
        "adjust_track_gain",
        "gain_stage_track",
        "balance_mix",
        "apply_findings",
    ]),
```

- [ ] **Step 2: Verify the script asserts with no unknown tools**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run python scripts/gen_docs_site.py
```
Expected: exits cleanly, regenerates `docs/tools/`.

- [ ] **Step 3: Update `docs/index.md` hero counts**

In `docs/index.md`, make these exact replacements (5 spots):

Find (line ~5):
```
description: "Control Ableton Live 11 and 12 from Claude with 128 MCP tools."
```
Replace with:
```
description: "Control Ableton Live 11 and 12 from Claude with 132 MCP tools."
```

Find (line ~12):
```
  <p class="hero__tagline">Drive Ableton Live 11 and 12 straight from Claude. 128 tools spanning tracks,
```
Replace with:
```
  <p class="hero__tagline">Drive Ableton Live 11 and 12 straight from Claude. 132 tools spanning tracks,
```

Find (line ~17):
```
    <div><div class="stats__num">128</div><div class="stats__label">Tools</div></div>
```
Replace with:
```
    <div><div class="stats__num">132</div><div class="stats__label">Tools</div></div>
```

Find (line ~18):
```
    <div><div class="stats__num">18</div><div class="stats__label">Categories</div></div>
```
Replace with:
```
    <div><div class="stats__num">19</div><div class="stats__label">Categories</div></div>
```

Find (line ~24):
```
[Browse all 128 tools](./tools/){: .btn .btn-primary .mr-2 }
```
Replace with:
```
[Browse all 132 tools](./tools/){: .btn .btn-primary .mr-2 }
```

Find (line ~93):
```
- A **FastMCP server** (Python, launched by Claude Code) exposes the 128 `@mcp.tool()` functions.
```
Replace with:
```
- A **FastMCP server** (Python, launched by Claude Code) exposes the 132 `@mcp.tool()` functions.
```

- [ ] **Step 4: Bump version in `pyproject.toml`**

Find:
```
version = "0.11.0"
```
Replace with:
```
version = "0.12.0"
```

- [ ] **Step 5: Bump version in `.claude-plugin/plugin.json`**

Find:
```
"version": "0.11.0"
```
Replace with:
```
"version": "0.12.0"
```

- [ ] **Step 6: Update `uv.lock`**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv lock
```

- [ ] **Step 7: Run final full test suite**

```bash
PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" uv run --with pytest pytest tests/ -q
```
Expected: ~633 passed, 0 failed.

- [ ] **Step 8: Commit everything**

```bash
git add scripts/gen_docs_site.py docs/ pyproject.toml .claude-plugin/plugin.json uv.lock
git commit -m "chore: docs regen + version bump 0.11.0 -> 0.12.0 - remediation tools (132 tools)"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Task covering it |
|---|---|
| `adjust_track_gain` tool | Task 2 |
| `gain_stage_track` tool | Task 3 |
| `balance_mix` tool | Task 4 |
| `apply_findings` tool | Task 5 |
| `remediation_utils.py` module | Task 1 |
| `db_to_live_volume` (inverse of `live_volume_to_db`) | Task 1 |
| `generate_actions` enriching findings | Task 1 + Task 5 |
| `build_correction_plan` filtering/sequencing | Task 1 |
| `compute_balance_deltas` | Task 1 |
| `action` field on `health.no_leftover_solo` | Task 1 |
| `action` field on `mixing.fader_headroom` | Task 1 |
| `action` field on `mastering.true_peak` | Task 1 |
| No action for mastering.true_peak without signal | Task 1 |
| No RS changes | all tasks |
| 128→132 tool count | Task 6 |
| New "Remediation" category | Task 6 |
| Version bump 0.11.0→0.12.0 | Task 6 |
| ~32 new tests | Tasks 1-5 (estimate ~34) |

**Placeholder scan:** No TBD, no "implement later", no references to unexplained types.

**Type consistency check:**
- `generate_actions` defined in Task 1, imported in Task 2 import block, called in Task 5 `analyze_set` change — all consistent.
- `build_correction_plan` defined in Task 1, imported in Task 2, called in Task 5 `apply_findings` — consistent.
- `compute_balance_deltas` defined in Task 1, imported in Task 2, called in Task 4 `balance_mix` — consistent.
- `db_to_live_volume` defined in Task 1, imported in Task 2 import block, used in Tasks 3 and 4 — consistent.
- `live_volume_to_db` added to existing import in Task 2, used in Tasks 3 and 4 — consistent.
- `_measure_pass` used in Task 4 — already exists in server.py, no import needed (same module).
