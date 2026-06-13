"""Offline tests for the pure BS.1770 loudness math.

loudness_utils consumes ALREADY-K-weighted per-100ms-block mean-squares (the
.amxd applies the K-filter), so these vectors feed mean-square values directly.

Reference: a stereo block with z_l = z_r = 0.0029377 gives channel-summed
mean-square 0.0058754, and -0.691 + 10*log10(0.0058754) == -23.0 LUFS.
"""
import math

from ableton_mcp_max import loudness_utils as lu

_Z23 = 0.0029377     # per-channel mean-square; stereo -> -23.001 LUFS (rounds to -23.0)
_Z43 = 2.9377e-5     # per-channel mean-square that yields -43.0 LUFS in stereo


def _blocks(z, n):
    return [{"ms_k_l": z, "ms_k_r": z, "tp": 0.0} for _ in range(n)]


def test_integrated_steady_tone_is_minus_23():
    blocks = [(b["ms_k_l"], b["ms_k_r"]) for b in _blocks(_Z23, 50)]
    assert round(lu.integrated_lufs(blocks), 1) == -23.0


def test_integrated_all_silence_is_none():
    blocks = [(0.0, 0.0) for _ in range(50)]
    assert lu.integrated_lufs(blocks) is None


def test_absolute_gate_drops_silence():
    # Silence is below the -70 LUFS absolute gate, so appending 30 silent blocks
    # to 30 loud (-23) blocks must NOT drag the integrated value down: it stays
    # close to the loud-only result (boundary overlap windows aside). Without the
    # gate, the silent blocks would tank the linear mean far below -23.
    loud = [(_Z23, _Z23) for _ in range(30)]
    silent = [(0.0, 0.0) for _ in range(30)]
    loud_only = lu.integrated_lufs(loud)
    assert abs(lu.integrated_lufs(loud + silent) - loud_only) < 1.0


def test_relative_gate_drops_quiet_blocks():
    # 30 loud (-23) + 30 quiet (-43): the quiet blocks survive the absolute gate
    # but fall >10 LU below the pre-gate mean, so the relative gate drops them and
    # the integrated value stays near the loud-only result rather than the much
    # lower ungated mean.
    loud = [(_Z23, _Z23) for _ in range(30)]
    quiet = [(_Z43, _Z43) for _ in range(30)]
    loud_only = lu.integrated_lufs(loud)
    result = lu.integrated_lufs(loud + quiet)
    assert abs(result - loud_only) < 1.0
    assert result > -25.0


def test_sliding_momentary_window():
    blocks = [(_Z23, _Z23) for _ in range(10)]
    assert round(lu.sliding_loudness(blocks, 4), 1) == -23.0


def test_sliding_returns_none_when_too_short():
    blocks = [(_Z23, _Z23) for _ in range(2)]
    assert lu.sliding_loudness(blocks, 4) is None


def test_true_peak_dbtp_is_max_in_db():
    assert round(lu.true_peak_dbtp([0.5, 1.05, 0.9]), 2) == round(20 * math.log10(1.05), 2)


def test_true_peak_empty_is_none():
    assert lu.true_peak_dbtp([]) is None


def test_compute_metrics_shape():
    payload = {
        "sample_rate": 48000,
        "since_reset_s": 5.0,
        "block_count": 50,
        "blocks": _blocks(_Z23, 50),
        "peak": 0.5,
        "rms": 0.1,
    }
    m = lu.compute_metrics(payload)
    assert m["integrated_lufs"] == -23.0
    assert m["block_count"] == 50
    assert m["duration_s"] == 5.0
    assert m["peak_dbfs"] == round(20 * math.log10(0.5), 1)
    assert m["momentary_lufs"] == -23.0
    assert m["rms_dbfs"] == round(20 * math.log10(0.1), 1)
    assert set(m) == {
        "integrated_lufs", "short_term_lufs", "momentary_lufs",
        "true_peak_dbtp", "peak_dbfs", "rms_dbfs", "block_count", "duration_s",
    }
