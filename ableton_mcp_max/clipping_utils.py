"""Pure clipping / peak-overflow detection. No Live or socket dependency.

Server-side only. Inputs are linear peak amplitudes where 1.0 == 0 dBFS full
scale - read either from Live's per-track output meters (the no-tap path) or
from the audio-tap signal's `peak` (the tap path). The dB conversion and
threshold logic live here under the pytest harness.
"""

from ableton_mcp_max.loudness_utils import lin_to_db

_DBFS_FLOOR = -120.0


def peak_to_dbfs(peak):
    """Linear peak amplitude -> dBFS (1.0 -> 0.0). <=0 / None -> floor (-120)."""
    db = lin_to_db(peak)
    if db is None:
        return _DBFS_FLOOR
    return round(db, 1)


def annotate_meters(meters, ceiling_db=0.0):
    """Annotate every entity with peak_dbfs / is_clipping / overshoot_db.

    meters: list of {name, index, [track_type], peak} where peak is linear.
    Returns one dict per input entity (no filtering): {name, index, track_type,
    peak_dbfs, is_clipping, overshoot_db}. An entity is clipping when its peak
    meets/exceeds ceiling_db (default 0 dBFS); overshoot_db is the amount above
    the ceiling (0.0 when not clipping).
    """
    out = []
    for m in meters:
        peak_dbfs = peak_to_dbfs(m.get("peak"))
        clipping = peak_dbfs >= ceiling_db
        out.append({
            "name": m.get("name"),
            "index": m.get("index"),
            "track_type": m.get("track_type", "regular"),
            "peak_dbfs": peak_dbfs,
            "is_clipping": clipping,
            "overshoot_db": round(peak_dbfs - ceiling_db, 1) if clipping else 0.0,
        })
    return out


def clipping_flags(meters, ceiling_db=0.0):
    """The CLIPPING entities only, sorted by peak descending (worst first)."""
    return sorted(
        [m for m in annotate_meters(meters, ceiling_db) if m["is_clipping"]],
        key=lambda d: -d["peak_dbfs"],
    )
