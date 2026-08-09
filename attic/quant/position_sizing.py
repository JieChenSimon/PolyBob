"""
仓位管理模块 - Position Sizing
实现 Kelly 公式、固定比例、波动率目标等仓位管理策略
"""


def kelly_criterion(win_prob: float, win_loss_ratio: float, fraction: float = 0.25) -> float:
    """
    Kelly 公式计算最优仓位

    Args:
        win_prob: 胜率 (0-1)
        win_loss_ratio: 盈亏比 (平均盈利/平均亏损)
        fraction: Kelly 分数 (0-1), 默认 0.25 (1/4 Kelly)

    Returns:
        最优仓位比例 (0-1)
    """
    if win_prob <= 0 or win_prob >= 1:
        return 0.0

    # Kelly 公式: f* = (p*b - q) / b
    # 其中 p=胜率, q=败率, b=赔率
    loss_prob = 1 - win_prob
    kelly_fraction = (win_prob * win_loss_ratio - loss_prob) / win_loss_ratio

    # 应用 fractional Kelly
    kelly_fraction = max(0.0, kelly_fraction) * fraction

    return min(kelly_fraction, 1.0)


def kelly_continuous(expected_return: float, variance: float, fraction: float = 0.25) -> float:
    """
    连续 Kelly 公式 (对数效用)

    Args:
        expected_return: 期望收益率
        variance: 收益率方差
        fraction: Kelly 分数

    Returns:
        最优仓位比例
    """
    if variance <= 0:
        return 0.0

    kelly_fraction = expected_return / variance
    kelly_fraction = max(0.0, kelly_fraction) * fraction

    return min(kelly_fraction, 1.0)


def fixed_fractional(capital: float, risk_fraction: float = 0.02) -> float:
    """
    固定比例仓位管理

    Args:
        capital: 总资金
        risk_fraction: 风险比例 (默认 2%)

    Returns:
        仓位大小
    """
    return capital * risk_fraction


def volatility_targeting(
    base_size: float,
    target_vol: float,
    realized_vol: float
) -> float:
    """
    波动率目标仓位管理

    Args:
        base_size: 基础仓位
        target_vol: 目标波动率
        realized_vol: 已实现波动率

    Returns:
        调整后仓位
    """
    if realized_vol <= 0:
        return base_size

    adjustment = target_vol / realized_vol
    return base_size * adjustment


def estimate_win_prob_bayesian(
    prior_wins: int,
    prior_total: int,
    observed_wins: int,
    observed_total: int
) -> float:
    """
    贝叶斯胜率估计

    Args:
        prior_wins: 先验胜利次数
        prior_total: 先验总次数
        observed_wins: 观测胜利次数
        observed_total: 观测总次数

    Returns:
        后验胜率估计
    """
    posterior_wins = prior_wins + observed_wins
    posterior_total = prior_total + observed_total

    if posterior_total == 0:
        return 0.5

    return posterior_wins / posterior_total


def kelly_with_estimation_error(
    win_prob: float,
    win_loss_ratio: float,
    prob_variance: float,
    fraction: float = 0.25
) -> float:
    """
    考虑估计误差的 Kelly 公式

    Args:
        win_prob: 胜率估计
        win_loss_ratio: 盈亏比
        prob_variance: 胜率估计的方差
        fraction: Kelly 分数

    Returns:
        调整后的仓位比例
    """
    base_kelly = kelly_criterion(win_prob, win_loss_ratio, fraction)

    # 根据估计误差调整
    adjustment = 1.0 / (1.0 + prob_variance)

    return base_kelly * adjustment
