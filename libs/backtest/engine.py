"""
Backtest Engine - 回测引擎核心
"""
from datetime import datetime
from typing import List, Dict, Any, Optional
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
                      volatility: float = 0.01) -> bool:
        """执行交易信号 - 优化版本"""
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

    def update_equity(self, timestamp: datetime, market_prices: Dict[str, float]):
        """更新权益曲线"""
        missing = [mid for mid in self.positions if mid not in market_prices]
        if missing:
            raise ValueError(f"missing mark price for {', '.join(sorted(missing))}")
        position_value = sum(
            qty * market_prices[mid]
            for mid, qty in self.positions.items()
        )
        total_equity = self.capital + position_value
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
