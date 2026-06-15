import pytest

from ableton_mcp_max.spectrum_utils import (
    BAND_LABELS,
    band_profile_db,
    integrate_bands,
    stereo_metrics,
)


def test_eight_bands_labeled():
    assert len(BAND_LABELS) == 8


def test_integrate_bands_averages_per_band_energy():
    blocks = [{"bands": [1, 0, 0, 0, 0, 0, 0, 0]}, {"bands": [3, 0, 0, 0, 0, 0, 0, 0]}]
    out = integrate_bands(blocks)
    assert out[0] == 2.0
    assert out[7] == 0.0


def test_band_profile_db_is_relative_normalized():
    prof = band_profile_db([1, 1, 1, 1, 1, 1, 1, 1])
    assert max(prof) == 0.0
    assert all(p <= 0.0 for p in prof)


def test_band_profile_db_floors_silent_bands():
    prof = band_profile_db([1, 0, 0, 0, 0, 0, 0, 0], floor_db=-60.0)
    assert prof[0] == 0.0
    assert prof[1] == -60.0


def test_integrate_bands_empty_returns_zeros():
    assert integrate_bands([]) == [0.0] * 8


def test_integrate_bands_tolerates_missing_or_short_bands():
    blocks = [{"bands": [2, 2]}, {}]  # short vector + missing key
    out = integrate_bands(blocks)
    assert len(out) == 8
    assert out[0] == 1.0  # (2+0)/2


def test_band_profile_db_power_db_with_unequal_bands():
    prof = band_profile_db([1.0, 0.1])
    assert prof[0] == 0.0
    assert prof[1] == pytest.approx(-10.0)  # 10*log10(0.1) = -10 dB (power dB)


def test_band_profile_db_empty_returns_empty():
    assert band_profile_db([]) == []


def test_mono_signal_is_fully_correlated():
    m = stereo_metrics([{"mid": 1.0, "side": 0.0}] * 3)
    assert m["correlation"] > 0.95
    assert m["width"] < 0.05


def test_wide_signal_has_high_width():
    m = stereo_metrics([{"mid": 0.5, "side": 0.5}] * 3)
    assert m["width"] > 0.4


def test_stereo_empty_blocks_safe():
    m = stereo_metrics([])
    assert m["correlation"] == 0.0 and m["width"] == 0.0


def test_stereo_zero_energy_safe():
    m = stereo_metrics([{"mid": 0.0, "side": 0.0}])
    assert m["correlation"] == 0.0 and m["width"] == 0.0


def test_stereo_tolerates_missing_keys():
    m = stereo_metrics([{"mid": 1.0}])  # side missing -> 0
    assert m["width"] == 0.0
