import importlib.util
import time

import numpy as np
import pytest

from libs.compute.backend import rolling_zscore, slippage_batch


def test_compute_facade_handles_large_vectorized_slippage_workload():
    points = 50_000
    prices = np.linspace(0.40, 0.65, points, dtype=np.float64)
    sizes = np.linspace(10.0, 250.0, points, dtype=np.float64)
    volatilities = np.linspace(0.01, 0.04, points, dtype=np.float64)

    start = time.perf_counter()
    result = slippage_batch(prices, sizes, 100_000.0, 10.0, volatilities, backend="python")
    elapsed_ms = (time.perf_counter() - start) * 1000.0

    assert result.shape == prices.shape
    assert np.isfinite(result).all()
    assert elapsed_ms < 250.0


@pytest.mark.skipif(
    importlib.util.find_spec("polybob_core") is None,
    reason="polybob_core extension is not installed",
)
def test_installed_rust_core_runs_pair_zscore_workload():
    points = 50_000
    x = 100.0 + np.cumsum(np.sin(np.arange(points, dtype=np.float64) / 31.0))
    y = 1.25 * x + np.cos(np.arange(points, dtype=np.float64) / 19.0)

    start = time.perf_counter()
    result = rolling_zscore(y, x, 1.25, lookback=60, backend="rust")
    elapsed_ms = (time.perf_counter() - start) * 1000.0

    assert result.shape == x.shape
    assert np.isfinite(result).all()
    assert elapsed_ms < 250.0
