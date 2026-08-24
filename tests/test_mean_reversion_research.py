import numpy as np
import pytest

from scripts.mean_reversion_research import _has_unresolved_price_jump, mean_reversion_positions


def test_mean_reversion_is_causal_and_long_only():
    prices = np.array([100.0] * 10 + [90.0, 89.0, 88.0, 100.0])
    positions = mean_reversion_positions(prices, lookback=10, entry_bps=500)

    assert np.all((positions == 0) | (positions == 1))
    assert positions[10] == 1


def test_mean_reversion_rejects_invalid_parameters():
    with pytest.raises(ValueError):
        mean_reversion_positions([1.0, 2.0], lookback=1, entry_bps=100)


def test_unresolved_price_jump_is_unknown_not_a_windfall():
    assert _has_unresolved_price_jump([1.0, 10.0], 5.0) is True
    assert _has_unresolved_price_jump([1.0, 1.2, 1.1], 1.5) is False
