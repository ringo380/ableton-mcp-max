import pytest
from ableton_mcp_max import groove_utils as g


def test_resolve_swing_direct_fraction():
    assert g.resolve_swing(0.0) == 0.0
    assert g.resolve_swing(0.3) == pytest.approx(0.3)
    assert g.resolve_swing(1.0) == 1.0


def test_resolve_swing_mpc_percent_number():
    assert g.resolve_swing(50) == 0.0
    assert g.resolve_swing(60) == pytest.approx(0.2)
    assert g.resolve_swing(66) == pytest.approx(0.32)
    assert g.resolve_swing(75) == pytest.approx(0.5)


def test_resolve_swing_percent_string():
    assert g.resolve_swing("66%") == pytest.approx(0.32)
    assert g.resolve_swing("50%") == 0.0


def test_resolve_swing_clamps():
    assert g.resolve_swing(100) == 1.0      # (100-50)/50 = 1.0
    assert g.resolve_swing(200) == 1.0      # over-range clamps to 1
    assert g.resolve_swing(40) == 0.0       # (40-50)/50 = -0.2 -> 0
    assert g.resolve_swing("40%") == 0.0


def test_resolve_swing_rejects_garbage():
    with pytest.raises(ValueError):
        g.resolve_swing("loads")


def test_grid_to_step():
    assert g.grid_to_step("1/8") == 0.5
    assert g.grid_to_step("1/16") == 0.25
    with pytest.raises(ValueError):
        g.grid_to_step("1/4")


def test_swing_notes_delays_offbeats_only():
    # 1/16 grid (step 0.25): k=0,1,2,3 at t=0,0.25,0.5,0.75; odd k (1,3) swung.
    notes = [
        {"pitch": 60, "start_time": 0.0, "duration": 0.25, "velocity": 100},
        {"pitch": 60, "start_time": 0.25, "duration": 0.25, "velocity": 100},
        {"pitch": 60, "start_time": 0.5, "duration": 0.25, "velocity": 100},
        {"pitch": 60, "start_time": 0.75, "duration": 0.25, "velocity": 100},
    ]
    out = g.swing_notes(notes, step=0.25, fraction=0.5)
    starts = [n["start_time"] for n in out]
    # on-beats unchanged, off-beats delayed by 0.5 * (0.25/2) = 0.0625
    assert starts == [0.0, 0.3125, 0.5, 0.8125]


def test_swing_notes_preserves_other_fields_and_offgrid():
    notes = [
        {"pitch": 62, "start_time": 0.25, "duration": 0.5, "velocity": 80},
        {"pitch": 64, "start_time": 0.30, "duration": 0.5, "velocity": 80},  # off-grid
    ]
    out = g.swing_notes(notes, step=0.25, fraction=1.0, tolerance=0.02)
    # first is on a step (k=1, odd) -> delayed by 0.125; second is off-grid -> unchanged
    assert out[0]["start_time"] == 0.375
    assert out[0]["pitch"] == 62 and out[0]["duration"] == 0.5 and out[0]["velocity"] == 80
    assert out[1]["start_time"] == 0.30


def test_swing_notes_zero_fraction_is_identity():
    notes = [{"pitch": 60, "start_time": 0.25, "duration": 0.25, "velocity": 100}]
    out = g.swing_notes(notes, step=0.25, fraction=0.0)
    assert out[0]["start_time"] == 0.25
