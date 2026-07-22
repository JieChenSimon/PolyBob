"""Cross-check the O(n) rolling z-score against a naive reference implementation."""
import numpy as np
import pytest

from libs.quant.cointegration import calculate_spread_zscore


def naive_spread_zscore(y, x, hedge_ratio, lookback):
    """Reference implementation matching the original O(n*lookback) code."""
    spread = y - hedge_ratio * x
    n = len(spread)
    zscores = np.zeros(n)
    for i in range(lookback, n):
        window = spread[i - lookback:i]
        mean = window.mean()
        std = window.std()
        if std > 0:
            zscores[i] = (spread[i] - mean) / std
    return zscores


@pytest.mark.parametrize("lookback", [2, 5, 20, 199, 200, 500])
def test_matches_naive_on_random_data(lookback):
    rng = np.random.default_rng(42)
    n = 200
    x = np.cumsum(rng.normal(size=n)) + 100.0
    y = 1.3 * x + rng.normal(scale=0.5, size=n)

    fast = calculate_spread_zscore(y, x, 1.25, lookback=lookback)
    ref = naive_spread_zscore(y, x, 1.25, lookback=lookback)

    assert fast.shape == ref.shape
    np.testing.assert_allclose(fast, ref, rtol=1e-9, atol=1e-12)


def test_warmup_indices_are_zero():
    rng = np.random.default_rng(0)
    y = rng.normal(size=50)
    x = rng.normal(size=50)
    lookback = 20
    result = calculate_spread_zscore(y, x, 1.0, lookback=lookback)
    np.testing.assert_array_equal(result[:lookback], np.zeros(lookback))


def test_constant_spread_yields_zero():
    n = 100
    x = np.linspace(1.0, 2.0, n)
    # Exactly-representable constant so window mean/std are exact in both
    # implementations (a value like 3.7 accumulates rounding in the naive
    # np.mean and yields spurious +/-1 z-scores in the OLD code too).
    y = np.full(n, 3.5)  # hedge_ratio 0 -> spread exactly 3.5 everywhere
    result = calculate_spread_zscore(y, x, 0.0, lookback=10)
    np.testing.assert_array_equal(result, np.zeros(n))
    np.testing.assert_array_equal(result, naive_spread_zscore(y, x, 0.0, 10))


def test_short_series_and_lookback_geq_n():
    y = np.array([1.0, 2.0, 3.0])
    x = np.array([1.0, 1.0, 1.0])
    for lookback in (3, 5, 100):
        result = calculate_spread_zscore(y, x, 1.0, lookback=lookback)
        np.testing.assert_array_equal(result, np.zeros(3))
        ref = naive_spread_zscore(y, x, 1.0, lookback)
        np.testing.assert_array_equal(result, ref)


def test_large_offset_numerical_stability():
    rng = np.random.default_rng(7)
    n = 5000
    x = np.cumsum(rng.normal(size=n)) + 1e6
    y = 0.9 * x + rng.normal(scale=2.0, size=n)
    fast = calculate_spread_zscore(y, x, 0.87, lookback=250)
    ref = naive_spread_zscore(y, x, 0.87, lookback=250)
    np.testing.assert_allclose(fast, ref, rtol=1e-9, atol=1e-9)
