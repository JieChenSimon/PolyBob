"""跨市场对冲策略 - Polymarket + 加密货币。

对冲比率不再写死为 0.5，而是从配对价格序列用 OLS 回归得到经验对冲比率
（Polymarket 事件敞口对加密价格的 beta），可选滚动窗口。回归/滚动 beta 的
底层实现复用 ``libs.quant.cointegration``，避免重复造轮子。
"""

from __future__ import annotations

from typing import Dict, Optional, Sequence

import numpy as np

from libs.quant.cointegration import ols_regression


def compute_hedge_ratio(
    pm_series: Sequence[float],
    crypto_series: Sequence[float],
    *,
    lookback: int | None = None,
    default: float = 0.5,
) -> float:
    """从配对序列估计对冲比率（crypto 对 pm 敞口的 beta）。

    用 OLS：``pm ≈ alpha + beta * crypto``，返回 |beta|。``lookback`` 给定时只
    用最近 N 个同步观测（滚动 beta）。数据不足或退化时回退到 ``default``。
    """
    pm = np.asarray(pm_series, dtype=float)
    crypto = np.asarray(crypto_series, dtype=float)
    n = min(len(pm), len(crypto))
    if n < 3:
        return default
    pm, crypto = pm[-n:], crypto[-n:]
    if lookback is not None and lookback >= 2:
        pm, crypto = pm[-lookback:], crypto[-lookback:]
    if len(pm) < 3 or np.std(crypto) == 0:
        return default
    _alpha, beta, _resid = ols_regression(pm, crypto)
    if not np.isfinite(beta):
        return default
    return float(abs(beta))


class CrossMarketHedge:
    """跨市场对冲"""

    def __init__(self, polymarket_client, crypto_client, *, default_hedge_ratio: float = 0.5):
        self.pm_client = polymarket_client
        self.crypto_client = crypto_client
        self.default_hedge_ratio = default_hedge_ratio

    def analyze_hedge_opportunity(
        self,
        event: str,
        crypto_symbol: str,
        *,
        pm_series: Optional[Sequence[float]] = None,
        crypto_series: Optional[Sequence[float]] = None,
        lookback: Optional[int] = None,
    ) -> Optional[Dict]:
        """分析对冲机会。

        提供配对价格序列时用 OLS 估计对冲比率；否则回退到默认比率。
        """
        if "regulation" not in event.lower() and "sec" not in event.lower():
            return None

        if pm_series is not None and crypto_series is not None:
            hedge_ratio = compute_hedge_ratio(
                pm_series, crypto_series, lookback=lookback, default=self.default_hedge_ratio
            )
            ratio_source = "ols_beta"
        else:
            hedge_ratio = self.default_hedge_ratio
            ratio_source = "default"

        return {
            "event": event,
            "crypto_symbol": crypto_symbol,
            "hedge_ratio": hedge_ratio,
            "ratio_source": ratio_source,
            "direction": "short",  # 做空加密货币对冲政策风险
        }

    def execute_hedge(self, pm_position: float, crypto_symbol: str, hedge_ratio: float):
        """执行对冲"""
        hedge_size = abs(pm_position) * hedge_ratio
        return {
            "pm_position": pm_position,
            "crypto_hedge": hedge_size,
            "symbol": crypto_symbol,
        }


__all__ = ["CrossMarketHedge", "compute_hedge_ratio"]
