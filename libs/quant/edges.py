"""L1 — Edge hypotheses, one per instrument domain.

The blunt lesson from the first promotion board (0/25 on generic TA): a backtest
cannot rescue a strategy that has no edge. So instead of reusing textbook
indicators everywhere, each domain gets hypotheses grounded in *why* that
specific market might be inefficient:

- **Altcoins** — cross-sectional momentum (winners keep winning across a broad
  universe) and volatility-scaled trend; the best-replicated crypto anomalies.
- **US equities** — medium-term momentum and trend-following on liquid names.
- **A-shares** — retail-driven markets show stronger short-horizon reversal and
  limit-up/streak sentiment effects than developed markets.

Every hypothesis is a *causal* position generator: ``positions[i]`` may only use
information available at bar ``i``, and is applied to the return from ``i`` to
``i+1``. They are deliberately simple and near-parameter-free so the promotion
gate measures the edge, not a curve-fit.
"""

from __future__ import annotations

import numpy as np


# ------------------------------------------------------------------ primitives
def _rolling_vol(prices: np.ndarray, window: int) -> np.ndarray:
    rets = np.diff(prices, prepend=prices[0]) / np.maximum(prices, 1e-12)
    out = np.zeros(len(prices))
    for i in range(len(prices)):
        lo = max(0, i - window + 1)
        seg = rets[lo : i + 1]
        out[i] = float(seg.std(ddof=1)) if len(seg) > 2 else 0.0
    return out


def _zscore(prices: np.ndarray, window: int) -> np.ndarray:
    out = np.zeros(len(prices))
    for i in range(len(prices)):
        lo = max(0, i - window + 1)
        seg = prices[lo : i + 1]
        if len(seg) < max(5, window // 2):
            continue
        sd = seg.std(ddof=1)
        out[i] = 0.0 if sd == 0 else (prices[i] - seg.mean()) / sd
    return out


# ------------------------------------------------------- single-asset hypotheses
def trend_vol_scaled(prices: np.ndarray, lookback: int = 60, vol_window: int = 30) -> np.ndarray:
    """Time-series momentum: hold the sign of the vol-scaled trailing return."""
    n = len(prices)
    pos = np.zeros(n)
    vol = _rolling_vol(prices, vol_window)
    for i in range(n):
        if i < lookback or prices[i - lookback] <= 0:
            continue
        trailing = prices[i] / prices[i - lookback] - 1.0
        if vol[i] <= 0:
            pos[i] = np.sign(trailing)
        else:
            pos[i] = np.clip(trailing / (vol[i] * np.sqrt(lookback)), -1.0, 1.0)
    return pos


def short_horizon_reversal(prices: np.ndarray, lookback: int = 5, z_window: int = 20) -> np.ndarray:
    """Fade short-term extremes — the A-share retail-flow hypothesis."""
    z = _zscore(prices, z_window)
    n = len(prices)
    pos = np.zeros(n)
    for i in range(n):
        if i < max(lookback, z_window):
            continue
        if z[i] > 1.5:
            pos[i] = -1.0          # stretched up -> fade
        elif z[i] < -1.5:
            pos[i] = 1.0           # stretched down -> buy
        elif abs(z[i]) < 0.5:
            pos[i] = 0.0
        else:
            pos[i] = pos[i - 1]
    return pos


def breakout(prices: np.ndarray, window: int = 55) -> np.ndarray:
    """Donchian-style breakout: long new highs, flat/short new lows."""
    n = len(prices)
    pos = np.zeros(n)
    current = 0.0
    for i in range(n):
        if i < window:
            continue
        hi = prices[i - window : i].max()
        lo = prices[i - window : i].min()
        if prices[i] >= hi:
            current = 1.0
        elif prices[i] <= lo:
            current = -1.0
        pos[i] = current
    return pos


SINGLE_ASSET_EDGES = {
    "trend_vol_scaled": trend_vol_scaled,
    "short_horizon_reversal": short_horizon_reversal,
    "breakout": breakout,
}


# ------------------------------------------------- cross-sectional (altcoins)
def cross_sectional_momentum_positions(
    price_matrix: np.ndarray, lookback: int = 30, top_frac: float = 0.2
) -> np.ndarray:
    """Long the top decile / short the bottom, rebalanced daily.

    ``price_matrix`` is ``(n_assets, n_days)``. Returns a same-shaped position
    matrix where each row is that asset's position, dollar-neutral per day.
    Only past prices are used to rank, so the signal is causal.
    """
    n_assets, n_days = price_matrix.shape
    pos = np.zeros_like(price_matrix)
    k = max(1, int(round(n_assets * top_frac)))
    for day in range(lookback, n_days):
        past = price_matrix[:, day - lookback]
        now = price_matrix[:, day]
        valid = (past > 0) & (now > 0)
        if valid.sum() < 4:
            continue
        rets = np.full(n_assets, np.nan)
        rets[valid] = now[valid] / past[valid] - 1.0
        order = np.argsort(np.where(np.isnan(rets), -np.inf, rets))
        winners = order[-k:]
        losers = order[:k]
        pos[winners, day] = 1.0 / k
        pos[losers, day] = -1.0 / k
    return pos


__all__ = [
    "SINGLE_ASSET_EDGES",
    "breakout",
    "cross_sectional_momentum_positions",
    "short_horizon_reversal",
    "trend_vol_scaled",
]
