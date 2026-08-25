import pytest

from scripts.btc5m_stateful_direction_kernel_replay import stateful_target_pairs, stateful_targets


def test_stateful_targets_hold_direction_before_reversal():
    rows = [{"probability": value} for value in [0.8, 0.2, 0.2, 0.2, 0.2, 0.5]]
    assert stateful_targets(rows, 0.6, hold_windows=3) == [0.1, 0.1, 0.1, 0.1, -0.1, -0.1]


def test_stateful_targets_rejects_invalid_hold_window():
    with pytest.raises(ValueError, match="hold_windows"):
        stateful_targets([], 0.6, hold_windows=0)


def test_stateful_target_pairs_do_not_force_flat_at_window_exit():
    rows = [{"probability": value} for value in [0.8, 0.8]]
    assert stateful_target_pairs(rows, 0.6) == [(0.1, 0.1), (0.1, 0.1)]
