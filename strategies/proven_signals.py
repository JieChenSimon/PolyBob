"""Empirically-supported directional signals, as pure causal functions.

These are the best-replicated systematic edges from the academic literature,
implemented as dependency-light functions that a trader could actually compute
in real time (every value at bar ``i`` uses only data up to ``i``). They are
designed to feed the ensemble combiner in :mod:`strategies.ensemble`.

- **Time-series momentum (trend following)** — the sign of each asset's own
  vol-scaled trailing return. One of the most robust, most-replicated factors
  and confirmed in crypto (Moskowitz/Ooi/Pedersen; crypto TSMOM studies).
- **Cross-sectional momentum** — rank a universe and go long recent winners /
  short recent losers (Jegadeesh & Titman; "momentum everywhere").
- **Short-term reversal** — fade the most recent move; documented but
  structure-sensitive, so it is scaled conservatively.

Every signal is normalised to ``[-1, 1]`` (sign = direction, magnitude =
conviction) so heterogeneous strategies combine on the same scale.
"""

from __future__ import annotations

import numpy as np


def _clip_unit(value: float, cap: float) -> float:
    if cap <= 0:
        return 0.0
    return float(np.clip(value / cap, -1.0, 1.0))


def time_series_momentum(
    prices,
    *,
    lookback: int = 20,
    vol_lookback: int = 20,
    cap: float = 3.0,
) -> list[float]:
    """Per-bar vol-scaled trend signal in [-1, 1] (causal).

    Signal at bar ``i`` = trailing ``lookback``-return divided by its realised
    volatility, squashed to [-1, 1]. Uses only prices up to and including ``i``,
    so it is safe against look-ahead (guard it with
    ``libs.quant.pit.assert_no_lookahead``).
    """
    p = np.asarray(prices, dtype=float)
    n = len(p)
    out = [0.0] * n
    for i in range(n):
        if i < lookback or p[i - lookback] <= 0:
            continue
        trailing_ret = p[i] / p[i - lookback] - 1.0
        start = max(0, i - vol_lookback)
        window = p[start : i + 1]
        if len(window) > 2:
            rets = np.diff(window) / window[:-1]
            vol = float(rets.std(ddof=1))
        else:
            vol = 0.0
        if vol <= 0:
            out[i] = float(np.sign(trailing_ret))
        else:
            z = trailing_ret / (vol * np.sqrt(lookback))
            out[i] = _clip_unit(z, cap)
    return out


def short_term_reversal(
    prices,
    *,
    lookback: int = 5,
    vol_lookback: int = 20,
    cap: float = 3.0,
) -> list[float]:
    """Per-bar mean-reversion signal in [-1, 1] (causal): fade the recent move."""
    p = np.asarray(prices, dtype=float)
    n = len(p)
    out = [0.0] * n
    for i in range(n):
        if i < lookback or p[i - lookback] <= 0:
            continue
        recent_ret = p[i] / p[i - lookback] - 1.0
        start = max(0, i - vol_lookback)
        window = p[start : i + 1]
        if len(window) > 2:
            rets = np.diff(window) / window[:-1]
            vol = float(rets.std(ddof=1))
        else:
            vol = 0.0
        if vol <= 0:
            out[i] = -float(np.sign(recent_ret))
        else:
            z = recent_ret / (vol * np.sqrt(lookback))
            out[i] = -_clip_unit(z, cap)  # negative: revert toward the mean
    return out


def cross_sectional_momentum(
    trailing_returns: dict[str, float],
    *,
    quantile: float = 0.3,
) -> dict[str, int]:
    """Rank a universe by trailing return; long the top, short the bottom.

    ``trailing_returns`` maps instrument -> its trailing return (the caller must
    compute these causally). Returns instrument -> {+1 long, -1 short, 0 flat}.
    The top/bottom ``quantile`` fraction are traded.
    """
    if not trailing_returns:
        return {}
    items = sorted(trailing_returns.items(), key=lambda kv: kv[1], reverse=True)
    n = len(items)
    k = max(1, int(round(n * quantile)))
    if 2 * k > n:
        k = max(1, n // 2)
    signals = {name: 0 for name, _ in items}
    for name, _ in items[:k]:
        signals[name] = 1
    for name, _ in items[-k:]:
        # Don't let a tiny universe assign both long and short to one name.
        if signals[name] == 0:
            signals[name] = -1
    return signals


__all__ = [
    "cross_sectional_momentum",
    "short_term_reversal",
    "time_series_momentum",
]
