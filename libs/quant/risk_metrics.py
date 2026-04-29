"""
风险度量模块 - Risk Metrics
实现 VaR, CVaR, 最大回撤等风险指标
"""
import numpy as np
from typing import List, Tuple
from dataclasses import dataclass
from numba import jit


@dataclass
class RiskMetrics:
    """风险指标"""
    var_95: float
    cvar_95: float
    max_drawdown: float
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float


@jit(nopython=True, cache=True)
def _calculate_max_drawdown_jit(equity_curve: np.ndarray) -> Tuple[float, int, int]:
    """JIT优化的最大回撤计算"""
    peak = equity_curve[0]
    peak_idx = 0
    max_dd = 0.0
    max_dd_peak_idx = 0
    max_dd_trough_idx = 0

    for i in range(len(equity_curve)):
        value = equity_curve[i]
        if value > peak:
            peak = value
            peak_idx = i

        dd = (peak - value) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
            max_dd_peak_idx = peak_idx
            max_dd_trough_idx = i

    return max_dd, max_dd_peak_idx, max_dd_trough_idx


def calculate_var(returns: np.ndarray, confidence: float = 0.95) -> float:
    """计算 Value at Risk (历史模拟法)"""
    if len(returns) == 0:
        return 0.0
    return -np.percentile(returns, (1 - confidence) * 100)


def calculate_cvar(returns: np.ndarray, confidence: float = 0.95) -> float:
    """计算 Conditional VaR (Expected Shortfall)"""
    if len(returns) == 0:
        return 0.0
    var = calculate_var(returns, confidence)
    return -returns[returns <= -var].mean()


def calculate_max_drawdown(equity_curve: np.ndarray) -> Tuple[float, int, int]:
    """
    计算最大回撤 - 优化版本
    Returns: (max_drawdown, peak_idx, trough_idx)
    """
    if len(equity_curve) == 0:
        return 0.0, 0, 0
    return _calculate_max_drawdown_jit(equity_curve)


def calculate_sharpe_ratio(returns: np.ndarray, risk_free_rate: float = 0.0) -> float:
    """计算夏普比率"""
    if len(returns) == 0 or returns.std() == 0:
        return 0.0
    excess_returns = returns - risk_free_rate
    return excess_returns.mean() / returns.std() * np.sqrt(252)


def calculate_sortino_ratio(returns: np.ndarray, risk_free_rate: float = 0.0) -> float:
    """计算索提诺比率 (仅惩罚下行波动)"""
    if len(returns) == 0:
        return 0.0
    excess_returns = returns - risk_free_rate
    downside_returns = returns[returns < 0]
    if len(downside_returns) == 0:
        return 0.0
    downside_std = downside_returns.std()
    if downside_std == 0:
        return 0.0
    return excess_returns.mean() / downside_std * np.sqrt(252)


def calculate_calmar_ratio(annual_return: float, max_drawdown: float) -> float:
    """计算卡玛比率"""
    if max_drawdown == 0:
        return 0.0
    return annual_return / max_drawdown


def calculate_all_metrics(returns: np.ndarray, equity_curve: np.ndarray) -> RiskMetrics:
    """计算所有风险指标"""
    var_95 = calculate_var(returns, 0.95)
    cvar_95 = calculate_cvar(returns, 0.95)
    max_dd, _, _ = calculate_max_drawdown(equity_curve)
    sharpe = calculate_sharpe_ratio(returns)
    sortino = calculate_sortino_ratio(returns)

    # 计算年化收益
    total_return = (equity_curve[-1] - equity_curve[0]) / equity_curve[0] if len(equity_curve) > 0 else 0.0
    days = len(equity_curve)
    annual_return = (1 + total_return) ** (252 / days) - 1 if days > 0 else 0.0

    calmar = calculate_calmar_ratio(annual_return, max_dd)

    return RiskMetrics(
        var_95=var_95,
        cvar_95=cvar_95,
        max_drawdown=max_dd,
        sharpe_ratio=sharpe,
        sortino_ratio=sortino,
        calmar_ratio=calmar
    )
