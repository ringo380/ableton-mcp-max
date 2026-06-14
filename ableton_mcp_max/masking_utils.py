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
