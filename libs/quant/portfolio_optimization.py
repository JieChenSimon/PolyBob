"""
组合优化增强 - 风险平价和最大夏普比率
"""
import numpy as np
from typing import Optional
from scipy.optimize import minimize


def risk_parity_weights(cov_matrix: np.ndarray, max_iter: int = 1000) -> np.ndarray:
    """
    风险平价权重优化

    目标: 使每个资产的风险贡献相等
    RC_i = w_i * (Σ·w)_i / (w^T·Σ·w)
    """
    n = len(cov_matrix)

    def risk_budget_objective(weights):
        portfolio_var = weights @ cov_matrix @ weights
        marginal_contrib = cov_matrix @ weights
        risk_contrib = weights * marginal_contrib / portfolio_var
        target = 1.0 / n
        return np.sum((risk_contrib - target) ** 2)

    constraints = {'type': 'eq', 'fun': lambda w: np.sum(w) - 1}
    bounds = tuple((0, 1) for _ in range(n))
    x0 = np.ones(n) / n

    result = minimize(risk_budget_objective, x0, method='SLSQP',
                     bounds=bounds, constraints=constraints,
                     options={'maxiter': max_iter})

    return result.x if result.success else x0


def max_sharpe_weights(
    mean_returns: np.ndarray,
    cov_matrix: np.ndarray,
    risk_free_rate: float = 0.0
) -> np.ndarray:
    """
    最大夏普比率权重

    解析解: w* = Σ^{-1}·(μ - r_f·1) / (1^T·Σ^{-1}·(μ - r_f·1))
    """
    n = len(mean_returns)
    excess_returns = mean_returns - risk_free_rate

    try:
        inv_cov = np.linalg.inv(cov_matrix)
        weights = inv_cov @ excess_returns
        weights = weights / np.sum(weights)
        weights = np.clip(weights, 0, 1)
        return weights / np.sum(weights)
    except np.linalg.LinAlgError:
        return np.ones(n) / n


def dynamic_position_adjustment(
    base_weight: float,
    realized_vol: float,
    target_vol: float,
    current_dd: float,
    max_dd: float
) -> float:
    """
    动态仓位调整

    综合考虑波动率目标和回撤控制
    """
    # 波动率调整
    vol_adjustment = target_vol / realized_vol if realized_vol > 0 else 1.0
    vol_adjustment = np.clip(vol_adjustment, 0.5, 2.0)

    # 回撤控制
    dd_adjustment = max(0, 1 - current_dd / max_dd) if max_dd > 0 else 1.0

    # 综合调整
    adjusted_weight = base_weight * vol_adjustment * dd_adjustment
    return np.clip(adjusted_weight, 0, 1)
