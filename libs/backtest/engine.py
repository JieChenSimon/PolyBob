"""
Backtest Engine - 回测引擎核心
"""
from datetime import datetime
from typing import List, Dict, Any, Optional, Sequence
from dataclasses import dataclass, field
import structlog
import numpy as np
from numba import jit

from libs.schemas import OrderbookTick, TradeTick, Side

logger = structlog.get_logger()


@dataclass
class Trade:
    """成交记录"""
    timestamp: datetime
    market_id: str
    side: Side
    price: float
    size: float
    fee: float = 0.0


@jit(nopython=True, cache=True)
def _calculate_slippage_vectorized(prices: np.ndarray, sizes: np.ndarray,
                                   market_depth: float, base_slippage_bps: float,
                                   volatilities: np.ndarray) -> np.ndarray:
    """向量化滑点计算 (JIT编译)"""
    impacts = sizes / market_depth
    slippage_bps = base_slippage_bps + impacts * volatilities * 10000
    return prices * (slippage_bps / 10000)


@jit(nopython=True, cache=True)
def _calculate_max_drawdown_fast(equity_curve: np.ndarray) -> float:
    """快速最大回撤计算 (JIT编译)"""
    peak = equity_curve[0]
    max_dd = 0.0

    for value in equity_curve:
        if value > peak:
            peak = value
        dd = (peak - value) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd

    return max_dd


@dataclass
class BacktestConfig:
    """回测配置"""
    initial_capital: float = 10000.0
    fee_rate: float = 0.002  # 0.2% 手续费
    slippage_bps: float = 10.0  # 10bps 滑点
    use_dynamic_slippage: bool = True  # 默认启用动态滑点
    market_depth: float = 100000.0  # 市场深度
    enable_vectorization: bool = True  # 启用向量化计算
    allow_short: bool = False  # explicit margin/borrow contract required
    short_margin_ratio: float = 1.0


class BacktestEngine:
    """回测引擎 - 优化版本"""

    def __init__(self, config: BacktestConfig = None):
        self.config = config or BacktestConfig()
        self.capital = self.config.initial_capital
        self.positions: Dict[str, float] = {}
        self.trades: List[Trade] = []
        self.equity_curve: List[tuple[datetime, float]] = []

        # 性能优化：预分配数组
        self._trade_buffer: List[Trade] = []
        self._equity_buffer: List[tuple[datetime, float]] = []

    def calculate_slippage(self, price: float, size: float, volatility: float = 0.01) -> float:
        """计算动态滑点 - 改进的市场冲击模型"""
        if not self.config.use_dynamic_slippage:
            return price * (self.config.slippage_bps / 10000)

        # 平方根市场冲击模型 (更真实)
        impact = np.sqrt(size / self.config.market_depth)
        slippage_bps = self.config.slippage_bps * (1 + impact * volatility * 100)
        return price * (slippage_bps / 10000)

    def execute_signal(self, timestamp: datetime, market_id: str,
                      side: Side, price: float, size: float,
                      volatility: float = 0.01,
                      effective_at: datetime | None = None) -> bool:
        """执行交易信号 - 优化版本"""
        if effective_at is not None and timestamp < effective_at:
            raise ValueError("cannot fill before signal effective_at")
        if not np.isfinite(price) or price <= 0 or not np.isfinite(size) or size <= 0:
            raise ValueError("price and size must be finite and positive")
        slippage = self.calculate_slippage(price, size, volatility)
        exec_price = price + slippage if "buy" in side.value else price - slippage

        notional = exec_price * size
        fee = notional * self.config.fee_rate
        total_cost = notional + fee

        if "buy" in side.value and total_cost > self.capital:
            return False

        current_pos = self.positions.get(market_id, 0.0)
        if "buy" in side.value:
            self.positions[market_id] = current_pos + size
            self.capital -= total_cost
        else:
            if not self.config.allow_short and current_pos < size:
                return False
            opening_short = current_pos - size < 0 and current_pos < 0 or current_pos < size
            if self.config.allow_short and opening_short and current_pos < size:
                # A short is not free cash: require explicit initial margin for
                # the newly opened short notional.  Closing an existing long
                # remains unrestricted by this check.
                short_open = max(0.0, size - max(current_pos, 0.0))
                required = exec_price * short_open * self.config.short_margin_ratio + fee
                if self.capital < required:
                    return False
            self.positions[market_id] = current_pos - size
            self.capital += notional - fee

        self.trades.append(Trade(
            timestamp=timestamp,
            market_id=market_id,
            side=side,
            price=exec_price,
            size=size,
            fee=fee
        ))
        return True

    def mark_to_market(self, market_prices: Dict[str, float]) -> tuple[str, float | None]:
        """Return an explicit valuation status instead of treating missing data as zero."""
        missing = [mid for mid in self.positions if mid not in market_prices]
        if missing:
            return "unknown_missing_price", None
        if any(not np.isfinite(price) or price <= 0 for price in market_prices.values()):
            return "unknown_invalid_price", None
        position_value = sum(
            qty * market_prices[mid]
            for mid, qty in self.positions.items()
        )
        return "ok", self.capital + position_value

    def update_equity(self, timestamp: datetime, market_prices: Dict[str, float]):
        """更新权益曲线; incomplete marks fail closed and are never valued at zero."""
        status, total_equity = self.mark_to_market(market_prices)
        if status != "ok":
            raise ValueError(f"cannot mark portfolio: {status}")
        self.equity_curve.append((timestamp, total_equity))

    def get_results(self) -> Dict[str, Any]:
        """获取回测结果 - 优化版本"""
        if not self.equity_curve:
            return {}

        initial = self.config.initial_capital
        final = self.equity_curve[-1][1]
        total_return = (final - initial) / initial

        # 使用JIT优化的最大回撤计算
        equity_values = np.array([eq for _, eq in self.equity_curve])
        max_dd = _calculate_max_drawdown_fast(equity_values)

        return {
            "initial_capital": initial,
            "final_equity": final,
            "total_return": total_return,
            "total_return_pct": total_return * 100,
            "max_drawdown": max_dd,
            "max_drawdown_pct": max_dd * 100,
            "num_trades": len(self.trades),
            "total_fees": sum(t.fee for t in self.trades),
        }


def simulate_position_series(
    prices: Sequence[float], positions: Sequence[float], *,
    cost_bps: float = 0.0, allow_short: bool = False,
) -> tuple[np.ndarray, Dict[str, Any]]:
    """Canonical causal position replay used by research and backtest callers.

    A target position observed at bar *t* is filled at that bar's price and
    can only earn the return from *t* to *t+1*.  This prevents the common
    vectorized look-ahead where today's close is both signal and exit price.
    """
    values = np.asarray(prices, dtype=float)
    targets = np.asarray(positions, dtype=float)
    if len(values) != len(targets) or len(values) < 2:
        raise ValueError("prices and positions must have equal length >= 2")
    if np.any(~np.isfinite(values)) or np.any(values <= 0):
        raise ValueError("prices must be finite and positive")
    if np.any(~np.isfinite(targets)):
        raise ValueError("positions must be finite")
    # Research positions are exposure fractions (1.0 = 100% of equity), not
    # asset units.  Convert exposure deltas to units at the fill price so the
    # same accounting engine can serve both portfolio and research callers.
    initial = 1.0 + cost_bps / 10_000.0 * max(1.0, float(np.max(np.abs(np.diff(np.concatenate(([0.0], targets)))))))
    engine = BacktestEngine(BacktestConfig(
        initial_capital=initial, fee_rate=cost_bps / 10_000.0,
        slippage_bps=0.0, use_dynamic_slippage=False, allow_short=allow_short,
    ))
    equity = [initial]
    ts = datetime(1970, 1, 1)
    current_target = 0.0
    for price, target in zip(values, targets):
        # ``target`` is an exposure fraction, while BacktestEngine stores
        # signed asset units. A stable target must not rebalance every bar as
        # price moves; only a target change creates an order. Convert the new
        # target using current marked equity, then compare with actual units.
        current_units = float(engine.positions.get("series", 0.0))
        if float(target) == current_target:
            delta = 0.0
        else:
            status, marked_equity = engine.mark_to_market({"series": float(price)})
            if status != "ok" or marked_equity is None:
                raise ValueError(f"cannot size portfolio target: {status}")
            fee_rate = cost_bps / 10_000.0
            # Leave room for the taker fee when sizing a positive target;
            # otherwise a nominal 100% target would be rejected because its
            # notional plus fee exceeds the available cash.
            fee_adjustment = 1.0 + fee_rate + 1e-12 if target > 0 else 1.0
            desired_units = float(target) * marked_equity / float(price) / fee_adjustment
            delta = desired_units - current_units
        if delta > 0:
            if not engine.execute_signal(ts, "series", Side.BUY_YES, float(price), delta):
                raise ValueError("position target violates cash or margin constraints")
        elif delta < 0:
            if not engine.execute_signal(ts, "series", Side.SELL_YES, float(price), -delta):
                raise ValueError("position target violates short/position constraints")
        current_target = float(target)
        engine.update_equity(ts, {"series": float(price)})
        equity.append(engine.equity_curve[-1][1])
    curve = np.asarray(equity[1:], dtype=float)
    returns = curve[1:] / curve[:-1] - 1.0
    return returns, engine.get_results()
