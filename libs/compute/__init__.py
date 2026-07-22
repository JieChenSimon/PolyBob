"""Compute backend facade for CPU-heavy PolyBob kernels."""

from .backend import (
    ComputeBackendError,
    kalman_hedge_ratio,
    max_drawdown,
    risk_metrics,
    rolling_zscore,
    slippage_batch,
)

__all__ = [
    "ComputeBackendError",
    "kalman_hedge_ratio",
    "max_drawdown",
    "risk_metrics",
    "rolling_zscore",
    "slippage_batch",
]
