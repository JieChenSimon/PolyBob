"""
协整检验模块 - Cointegration Testing
实现 Engle-Granger 协整检验和 Kalman Filter 动态对冲比率
"""
import numpy as np
from typing import Tuple
from dataclasses import dataclass


@dataclass
class CointegrationResult:
    """协整检验结果"""
    is_cointegrated: bool
    hedge_ratio: float  # 对冲比率 β
    adf_statistic: float  # ADF 统计量
    p_value: float  # p 值
    residuals: np.ndarray  # 残差序列


def ols_regression(y: np.ndarray, x: np.ndarray) -> Tuple[float, float, np.ndarray]:
    """
    OLS 回归: y = α + β*x + ε

    Returns:
        (alpha, beta, residuals)
    """
    n = len(y)
    x_mean = x.mean()
    y_mean = y.mean()

    # 计算 β
    numerator = ((x - x_mean) * (y - y_mean)).sum()
    denominator = ((x - x_mean) ** 2).sum()

    if denominator == 0:
        return 0.0, 0.0, np.zeros(n)

    beta = numerator / denominator
    alpha = y_mean - beta * x_mean

    # 计算残差
    residuals = y - (alpha + beta * x)

    return alpha, beta, residuals


def adf_test(series: np.ndarray, max_lag: int = 10) -> Tuple[float, float]:
    """
    Augmented Dickey-Fuller 检验
    简化实现,仅返回统计量和近似 p 值

    Returns:
        (adf_statistic, p_value)
    """
    n = len(series)
    if n < max_lag + 2:
        return 0.0, 1.0

    # 一阶差分
    diff = np.diff(series)
    lagged = series[:-1]

    # 回归: Δy_t = α + β*y_{t-1} + ε_t
    _, beta, residuals = ols_regression(diff, lagged)

    # 计算标准误
    residual_var = (residuals ** 2).sum() / (n - 2)
    lagged_var = ((lagged - lagged.mean()) ** 2).sum()

    if lagged_var == 0 or residual_var == 0:
        return 0.0, 1.0

    se_beta = np.sqrt(residual_var / lagged_var)

    # ADF 统计量
    adf_stat = beta / se_beta if se_beta > 0 else 0.0

    # 近似 p 值 (基于临界值)
    # 临界值: 1%=-3.43, 5%=-2.86, 10%=-2.57
    if adf_stat < -3.43:
        p_value = 0.01
    elif adf_stat < -2.86:
        p_value = 0.05
    elif adf_stat < -2.57:
        p_value = 0.10
    else:
        p_value = 0.20

    return adf_stat, p_value


def engle_granger_test(
    y: np.ndarray,
    x: np.ndarray,
    significance_level: float = 0.05
) -> CointegrationResult:
    """
    Engle-Granger 协整检验

    Args:
        y: 因变量序列
        x: 自变量序列
        significance_level: 显著性水平

    Returns:
        CointegrationResult
    """
    # 步骤 1: OLS 回归
    alpha, beta, residuals = ols_regression(y, x)

    # 步骤 2: ADF 检验残差
    adf_stat, p_value = adf_test(residuals)

    # 步骤 3: 判断协整
    is_cointegrated = p_value < significance_level

    return CointegrationResult(
        is_cointegrated=is_cointegrated,
        hedge_ratio=beta,
        adf_statistic=adf_stat,
        p_value=p_value,
        residuals=residuals
    )


@dataclass
class KalmanState:
    """Kalman Filter 状态"""
    beta: float  # 对冲比率估计
    P: float  # 估计误差协方差


def kalman_filter_hedge_ratio(
    y: np.ndarray,
    x: np.ndarray,
    Q: float = 1e-5,  # 过程噪声
    R: float = 1e-3   # 观测噪声
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Kalman Filter 动态估计对冲比率

    状态空间模型:
    β_t = β_{t-1} + w_t,  w_t ~ N(0, Q)
    y_t = β_t * x_t + v_t,  v_t ~ N(0, R)

    Args:
        y: 因变量序列
        x: 自变量序列
        Q: 过程噪声方差
        R: 观测噪声方差

    Returns:
        (beta_estimates, P_estimates)
    """
    n = len(y)
    beta_estimates = np.zeros(n)
    P_estimates = np.zeros(n)

    # 初始化
    beta = 0.0
    P = 1.0

    for t in range(n):
        # 预测步骤
        beta_pred = beta
        P_pred = P + Q

        # 更新步骤
        if x[t] != 0:
            K = P_pred * x[t] / (x[t] * P_pred * x[t] + R)  # Kalman 增益
            beta = beta_pred + K * (y[t] - beta_pred * x[t])
            P = (1 - K * x[t]) * P_pred
        else:
            beta = beta_pred
            P = P_pred

        beta_estimates[t] = beta
        P_estimates[t] = P

    return beta_estimates, P_estimates


def calculate_spread_zscore(
    y: np.ndarray,
    x: np.ndarray,
    hedge_ratio: float,
    lookback: int = 20
) -> np.ndarray:
    """
    计算价差的 Z-score

    Args:
        y: 因变量序列
        x: 自变量序列
        hedge_ratio: 对冲比率
        lookback: 回看窗口

    Returns:
        Z-score 序列
    """
    spread = np.asarray(y - hedge_ratio * x, dtype=np.float64)
    n = len(spread)
    zscores = np.zeros(n)

    if n <= lookback:
        return zscores

    # O(n) rolling mean/std via cumulative sums. Center the series first so a
    # constant spread yields an exact zero variance and cancellation error in
    # (sumsq - sum^2/L) stays small.
    centered = spread - spread.mean()
    cumsum = np.concatenate(([0.0], np.cumsum(centered)))
    cumsq = np.concatenate(([0.0], np.cumsum(centered * centered)))

    # Window for output index i is spread[i-lookback:i], i.e. it excludes i.
    window_sum = cumsum[lookback:n] - cumsum[:n - lookback]
    window_sumsq = cumsq[lookback:n] - cumsq[:n - lookback]

    mean = window_sum / lookback
    variance = (window_sumsq - window_sum * window_sum / lookback) / lookback
    np.maximum(variance, 0.0, out=variance)  # guard tiny negative round-off
    std = np.sqrt(variance)

    valid = std > 0
    result = np.zeros(n - lookback)
    np.divide(centered[lookback:] - mean, std, out=result, where=valid)
    zscores[lookback:] = result

    return zscores
