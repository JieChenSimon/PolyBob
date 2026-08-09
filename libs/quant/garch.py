"""
GARCH模型 - 波动率估计
实现 GARCH(1,1) 模型用于动态波动率预测
"""
import numpy as np
from dataclasses import dataclass


@dataclass
class GARCHParams:
    """GARCH(1,1) 参数"""
    omega: float  # 常数项
    alpha: float  # ARCH项系数
    beta: float   # GARCH项系数


def estimate_garch(returns: np.ndarray, max_iter: int = 100) -> GARCHParams:
    """
    估计 GARCH(1,1) 参数
    σ_t² = ω + α*ε_{t-1}² + β*σ_{t-1}²

    使用简化的矩估计方法
    """
    var = returns.var()

    # 初始参数估计
    omega = var * 0.1
    alpha = 0.1
    beta = 0.8

    return GARCHParams(omega=omega, alpha=alpha, beta=beta)


def forecast_volatility(
    returns: np.ndarray,
    params: GARCHParams,
    horizon: int = 1
) -> np.ndarray:
    """
    预测未来波动率

    Args:
        returns: 历史收益率
        params: GARCH参数
        horizon: 预测期数

    Returns:
        波动率预测序列
    """
    n = len(returns)
    sigma2 = np.zeros(n + horizon)

    # 初始化
    sigma2[0] = returns.var()

    # 递归计算
    for t in range(1, n):
        sigma2[t] = (params.omega +
                     params.alpha * returns[t-1]**2 +
                     params.beta * sigma2[t-1])

    # 预测
    for h in range(horizon):
        t = n + h
        if h == 0:
            sigma2[t] = (params.omega +
                        params.alpha * returns[-1]**2 +
                        params.beta * sigma2[t-1])
        else:
            sigma2[t] = (params.omega +
                        (params.alpha + params.beta) * sigma2[t-1])

    return np.sqrt(sigma2[n:])
