"""Pure BS.1770 / EBU R128 loudness math, server-side only.

Inputs are ALREADY-K-weighted per-100ms-block mean-squares produced by the
'MCP Audio Tap' Max for Live device; this module only does the gating,
integration, windowing, and dB conversions - the parts that are easy to get
subtly wrong - so they live under the pytest harness.

Stereo channel weights G_L = G_R = 1.0 (BS.1770). A 400 ms gating block is the
mean of four consecutive 100 ms blocks, stepped every 100 ms (75% overlap).
"""
import math

_ABS_GATE_LUFS = -70.0   # BS.1770 absolute gate
_REL_GATE_LU = 10.0      # BS.1770 relative gate (LU below ungated mean)
_BLOCKS_PER_GATE = 4     # 400 ms / 100 ms
_BLOCKS_MOMENTARY = 4    # 400 ms
_BLOCKS_SHORT_TERM = 30  # 3 s


def lin_to_db(x):
    """Linear amplitude -> dB. Returns None for <= 0 or None."""
    if x is None or x <= 0:
        return None
    return 20.0 * math.log10(x)


def _ms_to_loudness(ms_sum):
    """Channel-summed mean-square (K-weighted) -> LKFS/LUFS, or -inf if <= 0."""
    if ms_sum <= 0:
        return float("-inf")
    return -0.691 + 10.0 * math.log10(ms_sum)


def _windowed_ms_sums(blocks, window):
    """Yield channel-summed mean-square for each `window`-block sliding window."""
    for i in range(len(blocks) - window + 1):
        win = blocks[i:i + window]
        zl = sum(b[0] for b in win) / window
        zr = sum(b[1] for b in win) / window
        yield zl + zr


def integrated_lufs(blocks):
    """Gated integrated loudness from 100 ms (ms_l, ms_r) blocks.

    Returns None if no block survives the absolute gate.
    """
    gate_ms = list(_windowed_ms_sums(blocks, _BLOCKS_PER_GATE))
    abs_kept = [z for z in gate_ms if _ms_to_loudness(z) >= _ABS_GATE_LUFS]
    if not abs_kept:
        return None
    rel_thresh = _ms_to_loudness(sum(abs_kept) / len(abs_kept)) - _REL_GATE_LU
    rel_kept = [z for z in abs_kept if _ms_to_loudness(z) >= rel_thresh]
    if not rel_kept:  # unreachable: the loudest block always clears the relative gate
        return None
    return _ms_to_loudness(sum(rel_kept) / len(rel_kept))


def sliding_loudness(blocks, window):
    """Max sliding-window loudness (momentary=4 blocks, short-term=30 blocks).

    Returns the peak (maximum) loudness across all windows, not the final
    window - i.e. "how loud did it ever get", suitable for offline analysis.
    Returns None if there are fewer than `window` blocks.
    """
    if len(blocks) < window:
        return None
    best = max((_ms_to_loudness(z) for z in _windowed_ms_sums(blocks, window)),
               default=float("-inf"))
    return None if best == float("-inf") else best


def true_peak_dbtp(tps):
    """Max per-block true-peak (linear) -> dBTP, or None if empty/all-None."""
    vals = [t for t in tps if t is not None]
    if not vals:
        return None
    return lin_to_db(max(vals))


def _round1(x):
    return None if x is None else round(x, 1)


def compute_metrics(read_payload):
    """Full metering dict from a device `read` payload.

    read_payload: {sample_rate, since_reset_s, block_count,
                   blocks:[{ms_k_l, ms_k_r, tp}, ...], peak, rms}
    """
    raw = read_payload.get("blocks", []) or []
    blocks = [(b.get("ms_k_l") or 0.0, b.get("ms_k_r") or 0.0) for b in raw]
    tps = [b.get("tp") for b in raw]
    return {
        "integrated_lufs": _round1(integrated_lufs(blocks)),
        "short_term_lufs": _round1(sliding_loudness(blocks, _BLOCKS_SHORT_TERM)),
        "momentary_lufs": _round1(sliding_loudness(blocks, _BLOCKS_MOMENTARY)),
        "true_peak_dbtp": _round1(true_peak_dbtp(tps)),
        "peak_dbfs": _round1(lin_to_db(read_payload.get("peak"))),
        "rms_dbfs": _round1(lin_to_db(read_payload.get("rms"))),
        "block_count": read_payload.get("block_count", len(blocks)),
        "duration_s": read_payload.get("since_reset_s"),
    }
