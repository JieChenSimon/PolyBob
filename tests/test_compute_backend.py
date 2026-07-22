import importlib.util

import numpy as np
import pytest

from libs.compute.backend import (
    ComputeBackendError,
    kalman_hedge_ratio,
    max_drawdown,
    risk_metrics,
    rolling_zscore,
    slippage_batch,
)
from libs.quant.cointegration import calculate_spread_zscore, kalman_filter_hedge_ratio
from libs.quant.risk_metrics import calculate_all_metrics, calculate_max_drawdown


def test_python_backend_matches_existing_quant_functions():
    x = np.array([100.0, 101.0, 102.0, 101.5, 103.0, 104.0], dtype=np.float64)
    y = 1.2 * x + np.array([0.0, 0.2, -0.1, 0.1, -0.2, 0.0], dtype=np.float64)

    np.testing.assert_allclose(
        rolling_zscore(y, x, 1.2, lookback=3, backend="python"),
        calculate_spread_zscore(y, x, 1.2, lookback=3),
    )

    betas, covariances = kalman_hedge_ratio(y, x, backend="python")
    expected_betas, expected_covariances = kalman_filter_hedge_ratio(y, x)
    np.testing.assert_allclose(betas, expected_betas)
    np.testing.assert_allclose(covariances, expected_covariances)


def test_python_backend_matches_existing_risk_functions():
    returns = np.array([-0.10, -0.03, 0.01, 0.04, 0.08], dtype=np.float64)
    equity = np.array([100.0, 120.0, 90.0, 130.0, 80.0], dtype=np.float64)

    actual_metrics = risk_metrics(returns, equity, backend="python")
    expected_metrics = calculate_all_metrics(returns, equity)
    assert actual_metrics == expected_metrics
    assert max_drawdown(equity, backend="python") == calculate_max_drawdown(equity)


def test_slippage_batch_matches_backtest_vector_formula():
    prices = np.array([100.0, 50.0, 25.0], dtype=np.float64)
    sizes = np.array([1000.0, 500.0, 250.0], dtype=np.float64)
    volatilities = np.array([0.02, 0.04, 0.08], dtype=np.float64)

    result = slippage_batch(prices, sizes, 100_000.0, 10.0, volatilities, backend="python")
    expected = prices * ((10.0 + (sizes / 100_000.0) * volatilities * 10_000.0) / 10_000.0)
    np.testing.assert_allclose(result, expected)


def test_rust_backend_falls_back_when_extension_is_absent(monkeypatch):
    monkeypatch.setenv("POLYBOB_COMPUTE_BACKEND", "rust")
    monkeypatch.setenv("POLYBOB_RUST_FALLBACK_ENABLED", "true")

    x = np.array([1.0, 2.0, 3.0], dtype=np.float64)
    y = np.array([1.1, 2.1, 2.9], dtype=np.float64)
    result = rolling_zscore(y, x, 1.0, lookback=2)
    np.testing.assert_allclose(result, calculate_spread_zscore(y, x, 1.0, lookback=2))


def test_rust_backend_can_fail_fast_when_extension_is_absent(monkeypatch):
    if importlib.util.find_spec("polybob_core") is not None:
        pytest.skip("polybob_core is installed in this environment")

    monkeypatch.setenv("POLYBOB_COMPUTE_BACKEND", "rust")
    monkeypatch.setenv("POLYBOB_RUST_FALLBACK_ENABLED", "false")

    with pytest.raises(ComputeBackendError):
        rolling_zscore(np.array([1.0, 2.0]), np.array([1.0, 2.0]), 1.0, lookback=1)


@pytest.mark.skipif(
    importlib.util.find_spec("polybob_core") is None,
    reason="polybob_core extension is not installed",
)
def test_rust_backend_matches_python_backend_when_installed():
    x = np.linspace(100.0, 130.0, 128, dtype=np.float64)
    y = 1.15 * x + np.sin(np.arange(128, dtype=np.float64) / 7.0)
    returns = np.diff(y) / y[:-1]
    equity = 1000.0 * np.cumprod(1.0 + returns)

    np.testing.assert_allclose(
        rolling_zscore(y, x, 1.15, lookback=20, backend="rust"),
        rolling_zscore(y, x, 1.15, lookback=20, backend="python"),
    )
    np.testing.assert_allclose(
        kalman_hedge_ratio(y, x, backend="rust")[0],
        kalman_hedge_ratio(y, x, backend="python")[0],
    )

    rust_metrics = risk_metrics(returns, equity, backend="rust")
    python_metrics = risk_metrics(returns, equity, backend="python")
    np.testing.assert_allclose(
        tuple(rust_metrics.__dict__.values()),
        tuple(python_metrics.__dict__.values()),
    )
