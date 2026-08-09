"""
回测统计验证增强
添加Deflated Sharpe Ratio和显著性检验
"""
import numpy as np
from typing import Tuple
from scipy.stats import t as t_dist


def deflated_sharpe_ratio(returns: np.ndarray, n_trials: int) -> float:
    """
    Deflated Sharpe Ratio - 考虑多重检验偏差

    DSR = SR · √(1 - γ·SR/√N)
    γ = √(2·ln(N_trials))
    """
    n = len(returns)
    if n == 0 or returns.std() == 0:
        return 0.0

    sr = returns.mean() / returns.std() * np.sqrt(252)
    gamma = np.sqrt(2 * np.log(n_trials))
    dsr = sr * np.sqrt(max(0, 1 - gamma * sr / np.sqrt(n)))
    return dsr


def sharpe_ttest(returns: np.ndarray, risk_free_rate: float = 0.0) -> Tuple[float, float]:
    """
    夏普比率显著性t检验

    H₀: SR = 0
    t = SR · √N

    Returns:
        (t_statistic, p_value)
    """
    n = len(returns)
    if n == 0 or returns.std() == 0:
        return 0.0, 1.0

    excess_returns = returns - risk_free_rate
    sr = excess_returns.mean() / returns.std() * np.sqrt(252)
    t_stat = sr * np.sqrt(n)
    p_value = 2 * (1 - t_dist.cdf(abs(t_stat), n - 1))

    return t_stat, p_value


def profit_factor(returns: np.ndarray) -> float:
    """
    盈利因子 = 总盈利 / |总亏损|
    """
    profits = returns[returns > 0].sum()
    losses = abs(returns[returns < 0].sum())
    return profits / losses if losses > 0 else np.inf


def calculate_degradation(sr_in: float, sr_out: float) -> float:
    """
    样本内外性能退化

    Degradation = (SR_in - SR_out) / SR_in
    """
    if sr_in <= 0:
        return 1.0
    return (sr_in - sr_out) / sr_in
