"""Pure cross-track mix analysis. Inputs are integrated per-track signal dicts
produced by the measure pass (server-side). No Live/Max imports."""

def _norm(v):
    s = sum(v) or 1.0
    return [x / s for x in v]

def masking_score(tracks, threshold=0.6):
    """Pairwise spectral overlap (cosine similarity on normalized band vectors).
    Returns a list of {a, b, score} for pairs at/above threshold, sorted desc.
    Tracks without a usable 'bands' vector are skipped."""
    usable = [t for t in tracks if t.get("bands") and any(t["bands"])]
    out = []
    n = len(usable)
    for i in range(n):
        for j in range(i + 1, n):
            na, nb = _norm(usable[i]["bands"]), _norm(usable[j]["bands"])
            dot = sum(x * y for x, y in zip(na, nb))
            mag = (sum(x * x for x in na) ** 0.5) * (sum(y * y for y in nb) ** 0.5) or 1.0
            score = dot / mag
            if score >= threshold:
                out.append({"a": usable[i].get("name"), "b": usable[j].get("name"),
                            "score": round(score, 3)})
    return sorted(out, key=lambda d: -d["score"])

def loudness_balance(tracks, spread_db=12.0):
    """Flag tracks sitting more than spread_db below the loudest active track.
    Active = integrated_lufs present and above the -70 LUFS silence floor."""
    active = [t for t in tracks if t.get("integrated_lufs") is not None
              and t["integrated_lufs"] > -70.0]
    if not active:
        return []
    loudest = max(t["integrated_lufs"] for t in active)
    return [{"name": t.get("name"), "integrated_lufs": t["integrated_lufs"],
             "below_db": round(loudest - t["integrated_lufs"], 1)}
            for t in active if loudest - t["integrated_lufs"] > spread_db]

def headroom_flags(tracks, peak_ceiling=-1.0, crest_floor=4.0):
    """Flag tracks near clipping (true_peak above ceiling) or over-compressed
    (crest below floor). near_clip takes precedence over over_compressed."""
    out = []
    for t in tracks:
        tp, crest = t.get("true_peak_dbtp"), t.get("crest")
        if tp is not None and tp > peak_ceiling:
            out.append({"name": t.get("name"), "issue": "near_clip", "true_peak_dbtp": tp})
        elif crest is not None and crest < crest_floor:
            out.append({"name": t.get("name"), "issue": "over_compressed", "crest": crest})
    return out

def stereo_flags(tracks, corr_floor=-0.2):
    """Flag tracks with correlation below corr_floor (mono-compat risk)."""
    return [{"name": t.get("name"), "correlation": t["correlation"]}
            for t in tracks
            if t.get("correlation") is not None and t["correlation"] < corr_floor]


# Maps each signal-backed mixing rule id to the cross-track function that
# evaluates it. analyze_set / measure_mix own the data; this keeps the rule->fn
# wiring in one pure, testable place.
MIX_RULE_FNS = {
    "mixing.spectral_masking": masking_score,
    "mixing.loudness_balance": loudness_balance,
    "mixing.headroom_per_track": headroom_flags,
    "mixing.stereo_correlation": stereo_flags,
}


def _mix_evidence(rule_id, items):
    """One-line human evidence for a built mix finding."""
    if not items:
        return "no issues detected"
    if rule_id == "mixing.spectral_masking":
        return "; ".join("%s vs %s overlap %s" % (i.get("a"), i.get("b"), i.get("score"))
                         for i in items)
    if rule_id == "mixing.loudness_balance":
        return "; ".join("%s %s dB below loudest" % (i.get("name"), i.get("below_db"))
                         for i in items)
    if rule_id == "mixing.headroom_per_track":
        return "; ".join("%s %s" % (i.get("name"), i.get("issue")) for i in items)
    if rule_id == "mixing.stereo_correlation":
        return "; ".join("%s correlation %s" % (i.get("name"), i.get("correlation"))
                         for i in items)
    return "%d issue(s)" % len(items)


def build_mix_findings(sigs, rules):
    """Run each signal-backed mixing rule present in `rules` over the per-track
    signals `sigs`, producing finding dicts.

    A finding is {id, domain, status, severity, items, evidence, remediation}.
    status is 'pass' when the rule's cross-track function returns no items, else
    the rule's severity. Each rule's thresholds come from its `params` dict (so
    the ruleset JSON stays the source of truth). Rules whose id is not one of the
    four mix rules are ignored (e.g. focus=mastering loads no mix rules at all).
    """
    out = []
    by_id = {r["id"]: r for r in rules}
    for rid, fn in MIX_RULE_FNS.items():
        rule = by_id.get(rid)
        if rule is None:
            continue
        params = rule.get("params") or {}
        items = fn(sigs, **params)
        severity = rule.get("severity", "warn")
        out.append({
            "id": rid,
            "domain": rule.get("domain", "mixing"),
            "status": "pass" if not items else severity,
            "severity": severity,
            "items": items,
            "evidence": _mix_evidence(rid, items),
            "remediation": rule.get("remediation", ""),
        })
    return out


def enrich_names(sigs, name_by_index):
    """Fill blank/missing per-track names from a {track_index: name} map.

    The tap device reports an empty `name`, so cross-track findings would read
    a:""/b:"". This backfills readable names from the LOM track index (master is
    index -1). An existing non-empty name is preserved; an unknown index is left
    blank. Mutates and returns `sigs`.
    """
    for s in sigs:
        if not s.get("name"):
            nm = name_by_index.get(s.get("index"))
            if nm:
                s["name"] = nm
    return sigs
