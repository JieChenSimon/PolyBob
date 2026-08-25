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


# ------------------------------------------------ round 2: differentiated edges
# Round 1 (generic TA on closes) produced 0/61 — win rates at coin-flip. These
# hypotheses instead use information generic TA ignores: intraday range, volume,
# overnight gaps and perp funding. Each targets a *specific* documented market
# behaviour rather than a chart pattern.


def gap_fade(bars, gap_z: float = 1.0, lookback: int = 20) -> np.ndarray:
    """Fade the overnight gap (A-share/US retail overreaction at the open).

    Hypothesis: a large open-vs-prior-close gap in a retail-heavy market is
    largely sentiment and partially reverts intraday. Position at bar i is set
    from bar i's *open* gap (known at the open) and earns close-to-close, so it
    is causal.
    """
    opens = np.asarray(bars.opens, float)
    closes = np.asarray(bars.closes, float)
    n = len(closes)
    pos = np.zeros(n)
    for i in range(lookback + 1, n):
        prev_close = closes[i - 1]
        if prev_close <= 0:
            continue
        gap = opens[i] / prev_close - 1.0
        hist = opens[i - lookback : i] / np.maximum(closes[i - lookback - 1 : i - 1], 1e-12) - 1.0
        sd = hist.std(ddof=1) if len(hist) > 2 else 0.0
        if sd <= 0:
            continue
        z = gap / sd
        if z > gap_z:
            pos[i] = -1.0        # gapped up -> fade
        elif z < -gap_z:
            pos[i] = 1.0         # gapped down -> buy the dip
    return pos


def volume_confirmed_trend(bars, lookback: int = 20, vol_window: int = 60) -> np.ndarray:
    """Only follow a trend when volume confirms it.

    Hypothesis: price moves on above-average volume carry information (real
    flow), while low-volume drifts are noise. This is the volume filter generic
    trend-following lacks.
    """
    closes = np.asarray(bars.closes, float)
    volumes = np.asarray(bars.volumes, float)
    n = len(closes)
    pos = np.zeros(n)
    for i in range(max(lookback, vol_window), n):
        if closes[i - lookback] <= 0:
            continue
        trailing = closes[i] / closes[i - lookback] - 1.0
        vol_hist = volumes[i - vol_window : i]
        avg = vol_hist.mean() if len(vol_hist) else 0.0
        if avg <= 0:
            continue
        confirmed = volumes[i] > 1.2 * avg      # today's flow is meaningful
        pos[i] = np.sign(trailing) if confirmed else 0.0
    return pos


def range_expansion(bars, lookback: int = 20) -> np.ndarray:
    """Trade the direction of a volatility/range expansion day.

    Hypothesis: a day whose true range far exceeds its recent norm marks a
    regime break (news/flow), and the immediate direction persists briefly.
    """
    closes = np.asarray(bars.closes, float)
    highs = np.asarray(bars.highs, float)
    lows = np.asarray(bars.lows, float)
    opens = np.asarray(bars.opens, float)
    n = len(closes)
    pos = np.zeros(n)
    for i in range(lookback + 1, n):
        rng = highs[i] - lows[i]
        hist = highs[i - lookback : i] - lows[i - lookback : i]
        avg = hist.mean() if len(hist) else 0.0
        if avg <= 0 or opens[i] <= 0:
            continue
        if rng > 1.8 * avg:                       # expansion day
            pos[i] = np.sign(closes[i] - opens[i])
    return pos


def gap_continuation(bars, gap_z: float = 1.0, lookback: int = 20) -> np.ndarray:
    """Follow the overnight gap instead of fading it.

    Round-2 evidence overturned the fade hypothesis: inverting ``gap_fade``
    moved the median Sharpe from -0.78 to +0.15 across altcoins/US/A-shares, so
    on these instruments a gap is *information* that persists (news/flow), not
    retail overreaction that reverts. Kept as its own hypothesis rather than a
    sign flip so the board records what was actually tested.
    """
    return -gap_fade(bars, gap_z=gap_z, lookback=lookback)


def range_contraction(bars, lookback: int = 20) -> np.ndarray:
    """Fade the direction of a range-expansion day (the inverse of the original).

    Same lesson as :func:`gap_continuation`: the expansion-continuation
    hypothesis tested negative (median Sharpe -0.45), its inverse mildly
    positive (+0.09) — i.e. an outsized-range day tends to give some of the move
    back. Still far below the promotion bar; kept for honest tracking.
    """
    return -range_expansion(bars, lookback=lookback)


OHLCV_EDGES = {
    "gap_fade": gap_fade,
    "gap_continuation": gap_continuation,
    "volume_confirmed_trend": volume_confirmed_trend,
    "range_expansion": range_expansion,
    "range_contraction": range_contraction,
}


def funding_contrarian(
    closes: np.ndarray, funding: np.ndarray, threshold_percentile: float = 75.0
) -> np.ndarray:
    """Fade crowded perp positioning (altcoin-specific edge).

    Hypothesis: persistently positive funding means longs are crowded and paying
    to stay in — a documented precursor to long squeezes; negative funding is
    the mirror. ``funding`` is the per-day mean rate aligned to ``closes``.
    Thresholds come from a *trailing* percentile so the rule is causal.  This
    parameter is a percentile rank (e.g. ``75`` means P75/P25), not a funding
    rate of 75 percent.  Real funding rates are decimal fractions such as
    ``0.0005`` (0.05%).
    """
    if not 50.0 <= threshold_percentile <= 100.0:
        raise ValueError("threshold_percentile must be between 50 and 100")
    n = len(closes)
    pos = np.zeros(n)
    window = 30
    for i in range(window, n):
        hist = funding[i - window : i]
        hist = hist[np.isfinite(hist)]
        if len(hist) < 10 or not np.isfinite(funding[i]):
            continue
        hi = np.percentile(hist, threshold_percentile)
        lo = np.percentile(hist, 100.0 - threshold_percentile)
        if funding[i] > hi and hi > 0:
            pos[i] = -1.0      # crowded longs -> short
        elif funding[i] < lo and lo < 0:
            pos[i] = 1.0       # crowded shorts -> long
    return pos


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
    "OHLCV_EDGES",
    "SINGLE_ASSET_EDGES",
    "breakout",
    "cross_sectional_momentum_positions",
    "funding_contrarian",
    "gap_continuation",
    "gap_fade",
    "range_contraction",
    "range_expansion",
    "short_horizon_reversal",
    "trend_vol_scaled",
    "volume_confirmed_trend",
]
