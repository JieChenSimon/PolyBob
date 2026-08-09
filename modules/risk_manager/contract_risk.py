"""
合约交易风控系统
实现Kelly仓位管理、动态止损止盈、回撤控制
"""
import numpy as np
from typing import Tuple, Optional
from dataclasses import dataclass


@dataclass
class RiskParams:
    """风控参数"""
    max_drawdown_limit: float = 0.15  # 最大回撤15%熔断
    single_risk_limit: float = 0.02   # 单笔风险2%
    kelly_fraction: float = 0.5       # Kelly系数(保守)
    atr_stop_multiplier: float = 2.0  # ATR止损倍数
    atr_profit_multiplier: float = 3.0  # ATR止盈倍数


class ContractRiskManager:
    """合约风控管理器"""

    def __init__(self, initial_capital: float, params: Optional[RiskParams] = None):
        self.initial_capital = initial_capital
        self.current_capital = initial_capital
        self.params = params or RiskParams()
        self.peak_capital = initial_capital

    def calculate_kelly_position(
        self,
        win_rate: float,
        avg_win: float,
        avg_loss: float,
        price: float
    ) -> float:
        """
        Kelly公式计算仓位
        f = (p*b - q) / b
        p=胜率, q=败率, b=盈亏比
        """
        if avg_loss == 0 or win_rate <= 0 or win_rate >= 1:
            return 0.0

        profit_loss_ratio = abs(avg_win / avg_loss)
        kelly = (win_rate * profit_loss_ratio - (1 - win_rate)) / profit_loss_ratio
        kelly = max(0, kelly) * self.params.kelly_fraction  # 保守系数

        # 转换为合约数量
        position_value = self.current_capital * kelly
        return position_value / price if price > 0 else 0.0

    def calculate_stop_loss(self, entry_price: float, atr: float, is_long: bool) -> float:
        """计算止损价格(基于ATR)"""
        stop_distance = atr * self.params.atr_stop_multiplier
        if is_long:
            return entry_price - stop_distance
        return entry_price + stop_distance

    def calculate_take_profit(self, entry_price: float, atr: float, is_long: bool) -> float:
        """计算止盈价格(基于ATR)"""
        profit_distance = atr * self.params.atr_profit_multiplier
        if is_long:
            return entry_price + profit_distance
        return entry_price - profit_distance

    def calculate_position_size(
        self,
        entry_price: float,
        stop_loss: float,
        is_long: bool
    ) -> float:
        """根据单笔风险限制计算仓位"""
        risk_per_contract = abs(entry_price - stop_loss)
        if risk_per_contract == 0:
            return 0.0

        max_risk_amount = self.current_capital * self.params.single_risk_limit
        return max_risk_amount / risk_per_contract

    def check_drawdown(self) -> Tuple[bool, float]:
        """检查回撤是否触发熔断"""
        drawdown = (self.peak_capital - self.current_capital) / self.peak_capital
        is_breached = drawdown >= self.params.max_drawdown_limit
        return is_breached, drawdown

    def update_capital(self, pnl: float):
        """更新资金并检查峰值"""
        self.current_capital += pnl
        if self.current_capital > self.peak_capital:
            self.peak_capital = self.current_capital

    def validate_order(
        self,
        position_size: float,
        entry_price: float,
        stop_loss: float
    ) -> Tuple[bool, str]:
        """综合风控检查"""
        # 检查回撤熔断
        breached, dd = self.check_drawdown()
        if breached:
            return False, f"回撤{dd:.2%}超过限制{self.params.max_drawdown_limit:.2%}"

        # 检查单笔风险
        risk_amount = position_size * abs(entry_price - stop_loss)
        risk_pct = risk_amount / self.current_capital
        if risk_pct > self.params.single_risk_limit:
            return False, f"单笔风险{risk_pct:.2%}超过限制{self.params.single_risk_limit:.2%}"

        return True, "通过"
