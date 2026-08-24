import numpy as np

from scripts.cross_sectional_local_screen import has_unresolved_price_jump, select_long_only


def test_cross_sectional_selection_uses_only_past_prices():
    prices = np.array([
        [100, 101, 102, 103, 104, 105],
        [100, 99, 98, 97, 96, 95],
        [100, 100, 100, 100, 100, 100],
        [100, 100, 100, 100, 100, 100],
    ], dtype=float)
    positions = select_long_only(prices, lookback=2, top_frac=0.25)
    assert np.all(positions[:, :2] == 0)
    assert positions[0, 2] == 1.0
    assert positions[1, 2] == 0.0


def test_cross_sectional_selection_is_long_only_and_bounded():
    rng = np.random.default_rng(7)
    prices = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, size=(8, 20)), axis=1))
    positions = select_long_only(prices, lookback=5, top_frac=0.25)
    assert np.all(positions >= 0)
    assert np.all(positions <= 1)


def test_cross_sectional_rejects_unresolved_price_jump():
    values = np.ones(300)
    values[150] = 100.0
    assert has_unresolved_price_jump(values, 1.5)
