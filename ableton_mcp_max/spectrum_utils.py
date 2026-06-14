"""Pure spectral-band math for the per-track taps. stdlib only; no Live/Max."""
import math

BAND_LABELS = ["sub", "low", "low_mid", "mid", "high_mid", "presence", "brilliance", "air"]
# nominal log-spaced band centers (Hz), documentation only; the device filterbank owns the real splits
BAND_HZ = [40, 100, 250, 600, 1500, 3500, 8000, 15000]


def integrate_bands(blocks):
    """Mean per-band energy across blocks. Returns 8 floats (zeros if empty).
    Tolerates blocks with a missing or short 'bands' vector (treated as 0)."""
    if not blocks:
        return [0.0] * 8
    acc = [0.0] * 8
    n = 0
    for b in blocks:
        bands = b.get("bands") or []
        for i in range(8):
            acc[i] += bands[i] if i < len(bands) else 0.0
        n += 1
    return [a / n for a in acc]


def band_profile_db(energy, floor_db=-60.0):
    """Normalize a band-energy vector to dB relative to its loudest band (<=0 dB).
    Silent/zero bands clamp to floor_db; an all-zero vector returns all floor_db."""
    peak = max(energy) if energy else 0.0
    if peak <= 0.0:
        return [floor_db] * len(energy)
    out = []
    for e in energy:
        if e <= 0.0:
            out.append(floor_db)
        else:
            out.append(max(floor_db, 10.0 * math.log10(e / peak)))
    return out


def stereo_metrics(blocks):
    """Aggregate mid/side energy into width + a correlation proxy.
    width = side/(mid+side); correlation proxy = (mid-side)/(mid+side) in [-1,1]."""
    if not blocks:
        return {"width": 0.0, "correlation": 0.0}
    mid = sum(b.get("mid", 0.0) for b in blocks)
    side = sum(b.get("side", 0.0) for b in blocks)
    total = mid + side
    if total <= 0.0:
        return {"width": 0.0, "correlation": 0.0}
    width = side / total
    corr = max(-1.0, min(1.0, (mid - side) / total))
    return {"width": width, "correlation": corr}
