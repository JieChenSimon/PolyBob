"""
协整检验增强模块 - Enhanced Cointegration
添加半衰期计算和协整强度评分
"""
import numpy as np
from typing import Tuple
from dataclasses import dataclass
from .cointegration import CointegrationResult, ols_regression, adf_test


@dataclass
class EnhancedCointegrationResult(CointegrationResult):
    """增强协整检验结果"""
    half_life: float  # 均值回归半衰期
    cointegration_strength: float  # 协整强度评分 (0-1)


def calculate_half_life(residuals: np.ndarray) -> float:
    """
    计算均值回归半衰期

    模型: Δε_t = λ·ε_{t-1} + u_t
    半衰期 = -ln(2) / ln(1+λ)

    Returns:
        半衰期（期数），np.inf表示不回归
    """
    if len(residuals) < 2:
        return np.inf

    lag_residuals = residuals[:-1]
    delta_residuals = np.diff(residuals)

    _, beta, _ = ols_regression(delta_residuals, lag_residuals)

    if beta >= 0:
        return np.inf

    half_life = -np.log(2) / np.log(1 + beta)
    return max(1.0, half_life)


def calculate_cointegration_strength(
    adf_statistic: float,
    p_value: float,
    half_life: float,
    max_half_life: float = 100.0
) -> float:
    """
    计算协整强度评分 (0-1)

    综合考虑:
    - ADF统计量（越负越强）
    - p值（越小越强）
    - 半衰期（越短越强）
    """
    # ADF评分: -3.43以下为1分，-2.57以上为0分
    adf_score = np.clip((-adf_statistic - 2.57) / (3.43 - 2.57), 0, 1)

    # p值评分
    p_score = 1 - np.clip(p_value / 0.1, 0, 1)

    # 半衰期评分
    if np.isinf(half_life):
        hl_score = 0.0
    else:
        hl_score = 1 - np.clip(half_life / max_half_life, 0, 1)

    # 加权平均
    strength = 0.4 * adf_score + 0.3 * p_score + 0.3 * hl_score
    return strength


def engle_granger_test_enhanced(
    y: np.ndarray,
    x: np.ndarray,
    significance_level: float = 0.05
) -> EnhancedCointegrationResult:
    """
    增强版 Engle-Granger 协整检验

    Returns:
        EnhancedCointegrationResult 包含半衰期和强度评分
    """
    # 基础协整检验
    alpha, beta, residuals = ols_regression(y, x)
    adf_stat, p_value = adf_test(residuals)
    is_cointegrated = p_value < significance_level

    # 计算半衰期
    half_life = calculate_half_life(residuals)

    # 计算协整强度
    strength = calculate_cointegration_strength(adf_stat, p_value, half_life)

    return EnhancedCointegrationResult(
        is_cointegrated=is_cointegrated,
        hedge_ratio=beta,
        adf_statistic=adf_stat,
        p_value=p_value,
        residuals=residuals,
        half_life=half_life,
        cointegration_strength=strength
    )


def optimal_lookback_window(half_life: float) -> int:
    """
    基于半衰期计算最优回看窗口

    经验法则: 2-3倍半衰期
    """
    if np.isinf(half_life):
        return 60  # 默认值

    window = int(half_life * 2.5)
    return np.clip(window, 20, 120)
