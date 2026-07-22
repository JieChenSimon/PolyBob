"""Compute backend facade for CPU-heavy PolyBob kernels."""

from .backend import (
    ComputeBackendError,
    benchmark_rolling_zscore,
    kalman_hedge_ratio,
    max_drawdown,
    native_core_available,
    native_core_status,
    risk_metrics,
    rolling_zscore,
    slippage_batch,
)

__all__ = [
    "ComputeBackendError",
    "benchmark_rolling_zscore",
    "kalman_hedge_ratio",
    "max_drawdown",
    "native_core_available",
    "native_core_status",
    "risk_metrics",
    "rolling_zscore",
    "slippage_batch",
]
