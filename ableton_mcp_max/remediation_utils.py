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
                "reason": "%s fader -> %.1f dB" % (entity, _HEADROOM_TARGET_DB),
            }

        elif fid == "health.no_clipping":
            # Clipping finding carries its own index/type/peak/current volume
            # (analyze_set embeds them from the peak-hold pass). Lower the fader
            # so the peak lands at _HEADROOM_TARGET_DB below 0 dBFS.
            peak_dbfs = f.get("peak_dbfs")
            cur_db = f.get("current_volume_db")
            idx = f.get("track_index")
            if peak_dbfs is None or cur_db is None or idx is None:
                continue
            ttype = f.get("track_type", "regular")
            new_db = cur_db - (peak_dbfs - _HEADROOM_TARGET_DB)
            new_vol = db_to_live_volume(new_db)
            f["action"] = {
                "tool": "set_mixer_property",
                "params": {"track_index": idx, "property": "volume",
                           "value": new_vol, "track_type": ttype},
                "reason": "%s peak %.1f dBFS -> trim to %.1f dB" % (
                    entity, peak_dbfs, _HEADROOM_TARGET_DB),
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
                "reason": "master peak %.1f dBTP -> lower by %.1f dB" % (tp, excess),
            }

    return findings


def build_correction_plan(findings: list, severity_filter: list,
                           focus: list = None) -> dict:
    """Filter and sequence fixable findings into an execution plan.

    Returns {plan, planned_count, skipped_count, skipped_reasons}.
    Each plan entry is {finding_id, severity, action, status: "planned"}.
    Deduplicates by (track_index, track_type, property) -- last action wins.
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
