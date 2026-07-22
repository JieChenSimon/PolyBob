"""Backend selection for CPU-heavy numerical kernels.

The default remains the existing Python/NumPy implementation so a missing local
Rust extension cannot break startup. Set POLYBOB_COMPUTE_BACKEND=rust to use
the Rust extension when it is installed, or verify to compare both paths.
"""

from __future__ import annotations

import importlib
import os
from functools import lru_cache
from typing import Any, Literal

import numpy as np

from libs.quant.cointegration import calculate_spread_zscore
from libs.quant.cointegration import kalman_filter_hedge_ratio as _python_kalman
from libs.quant.risk_metrics import RiskMetrics
from libs.quant.risk_metrics import calculate_all_metrics as _python_risk_metrics
from libs.quant.risk_metrics import calculate_max_drawdown as _python_max_drawdown

BackendName = Literal["python", "rust", "verify"]


class ComputeBackendError(RuntimeError):
    """Raised when a requested compute backend is unavailable or mismatched."""


@lru_cache(maxsize=1)
def _rust_core() -> Any | None:
    try:
        return importlib.import_module("polybob_core")
    except ImportError:
        return None


def _selected_backend(backend: str | None = None) -> BackendName:
    selected = (backend or os.getenv("POLYBOB_COMPUTE_BACKEND", "python")).strip().lower()
    if selected not in {"python", "rust", "verify"}:
        raise ComputeBackendError(
            "POLYBOB_COMPUTE_BACKEND must be one of: python, rust, verify"
        )
    return selected  # type: ignore[return-value]


def _fallback_enabled() -> bool:
    return os.getenv("POLYBOB_RUST_FALLBACK_ENABLED", "true").strip().lower() not in {
        "0",
        "false",
        "no",
    }


def _require_rust() -> Any | None:
    module = _rust_core()
    if module is None and not _fallback_enabled():
        raise ComputeBackendError(
            "POLYBOB_COMPUTE_BACKEND=rust but polybob_core is not installed"
        )
    return module


def _as_float64_array(values: np.ndarray | list[float] | tuple[float, ...]) -> np.ndarray:
    return np.ascontiguousarray(values, dtype=np.float64)


def rolling_zscore(
    y: np.ndarray,
    x: np.ndarray,
    hedge_ratio: float,
    lookback: int = 20,
    *,
    backend: str | None = None,
) -> np.ndarray:
    selected = _selected_backend(backend)
    y_array = _as_float64_array(y)
    x_array = _as_float64_array(x)

    if selected == "python":
        return calculate_spread_zscore(y_array, x_array, hedge_ratio, lookback)

    rust = _require_rust()
    if rust is None:
        return calculate_spread_zscore(y_array, x_array, hedge_ratio, lookback)

    rust_result = np.asarray(rust.rolling_zscore(y_array, x_array, hedge_ratio, lookback))
    if selected == "verify":
        python_result = calculate_spread_zscore(y_array, x_array, hedge_ratio, lookback)
        if not np.allclose(rust_result, python_result, rtol=1e-10, atol=1e-12):
            raise ComputeBackendError("rolling_zscore mismatch between Rust and Python")
        return python_result
    return rust_result


def kalman_hedge_ratio(
    y: np.ndarray,
    x: np.ndarray,
    q: float = 1e-5,
    r: float = 1e-3,
    *,
    backend: str | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    selected = _selected_backend(backend)
    y_array = _as_float64_array(y)
    x_array = _as_float64_array(x)

    if selected == "python":
        return _python_kalman(y_array, x_array, Q=q, R=r)

    rust = _require_rust()
    if rust is None:
        return _python_kalman(y_array, x_array, Q=q, R=r)

    rust_betas, rust_covariances = rust.kalman_hedge_ratio(y_array, x_array, q, r)
    rust_result = (np.asarray(rust_betas), np.asarray(rust_covariances))
    if selected == "verify":
        python_result = _python_kalman(y_array, x_array, Q=q, R=r)
        if not np.allclose(rust_result[0], python_result[0], rtol=1e-10, atol=1e-12):
            raise ComputeBackendError("kalman hedge beta mismatch between Rust and Python")
        if not np.allclose(rust_result[1], python_result[1], rtol=1e-10, atol=1e-12):
            raise ComputeBackendError("kalman hedge covariance mismatch between Rust and Python")
        return python_result
    return rust_result


def max_drawdown(
    equity_curve: np.ndarray,
    *,
    backend: str | None = None,
) -> tuple[float, int, int]:
    selected = _selected_backend(backend)
    equity_array = _as_float64_array(equity_curve)

    if selected == "python":
        return _python_max_drawdown(equity_array)

    rust = _require_rust()
    if rust is None:
        return _python_max_drawdown(equity_array)

    rust_result = rust.max_drawdown(equity_array)
    if selected == "verify":
        python_result = _python_max_drawdown(equity_array)
        if not np.allclose(rust_result[0], python_result[0], rtol=1e-10, atol=1e-12):
            raise ComputeBackendError("max_drawdown mismatch between Rust and Python")
        return python_result
    return float(rust_result[0]), int(rust_result[1]), int(rust_result[2])


def risk_metrics(
    returns: np.ndarray,
    equity_curve: np.ndarray,
    *,
    confidence: float = 0.95,
    backend: str | None = None,
) -> RiskMetrics:
    selected = _selected_backend(backend)
    returns_array = _as_float64_array(returns)
    equity_array = _as_float64_array(equity_curve)

    if selected == "python":
        return _python_risk_metrics(returns_array, equity_array)

    rust = _require_rust()
    if rust is None:
        return _python_risk_metrics(returns_array, equity_array)

    rust_result = rust.risk_metrics(returns_array, equity_array, confidence, 252.0)
    metrics = RiskMetrics(
        var_95=float(rust_result["var_95"]),
        cvar_95=float(rust_result["cvar_95"]),
        max_drawdown=float(rust_result["max_drawdown"]),
        sharpe_ratio=float(rust_result["sharpe_ratio"]),
        sortino_ratio=float(rust_result["sortino_ratio"]),
        calmar_ratio=float(rust_result["calmar_ratio"]),
    )
    if selected == "verify":
        python_result = _python_risk_metrics(returns_array, equity_array)
        if not np.allclose(tuple(metrics.__dict__.values()), tuple(python_result.__dict__.values())):
            raise ComputeBackendError("risk_metrics mismatch between Rust and Python")
        return python_result
    return metrics


def slippage_batch(
    prices: np.ndarray,
    sizes: np.ndarray,
    market_depth: float,
    base_slippage_bps: float,
    volatilities: np.ndarray,
    *,
    backend: str | None = None,
) -> np.ndarray:
    selected = _selected_backend(backend)
    prices_array = _as_float64_array(prices)
    sizes_array = _as_float64_array(sizes)
    volatilities_array = _as_float64_array(volatilities)

    python_result = prices_array * (
        (base_slippage_bps + (sizes_array / market_depth) * volatilities_array * 10_000.0)
        / 10_000.0
    )
    if selected == "python":
        return python_result

    rust = _require_rust()
    if rust is None:
        return python_result

    rust_result = np.asarray(
        rust.slippage_batch(
            prices_array,
            sizes_array,
            market_depth,
            base_slippage_bps,
            volatilities_array,
        )
    )
    if selected == "verify":
        if not np.allclose(rust_result, python_result, rtol=1e-10, atol=1e-12):
            raise ComputeBackendError("slippage_batch mismatch between Rust and Python")
        return python_result
    return rust_result
