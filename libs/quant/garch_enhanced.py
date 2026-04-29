"""
GARCH模型增强 - MLE估计和EGARCH
"""
import numpy as np
from typing import Tuple
from dataclasses import dataclass
from scipy.optimize import minimize


@dataclass
class GARCHParams:
    """GARCH(1,1) 参数"""
    omega: float
    alpha: float
    beta: float


def estimate_garch_mle(returns: np.ndarray, max_iter: int = 1000) -> GARCHParams:
    """
    极大似然估计 GARCH(1,1) 参数

    最小化负对数似然: -Σ[ln(σ²_t) + ε²_t/σ²_t]
    """
    def neg_log_likelihood(params):
        omega, alpha, beta = params

        # 约束检查
        if omega <= 0 or alpha < 0 or beta < 0 or alpha + beta >= 1:
            return 1e10

        n = len(returns)
        sigma2 = np.zeros(n)
        sigma2[0] = returns.var()

        for t in range(1, n):
            sigma2[t] = omega + alpha * returns[t-1]**2 + beta * sigma2[t-1]
            if sigma2[t] <= 0:
                return 1e10

        log_likelihood = -0.5 * np.sum(np.log(sigma2) + returns**2 / sigma2)
        return -log_likelihood

    # 初始值
    var = returns.var()
    x0 = [var * 0.05, 0.1, 0.85]

    # 优化
    bounds = [(1e-6, var), (0, 0.3), (0, 0.95)]
    result = minimize(neg_log_likelihood, x0, method='L-BFGS-B',
                     bounds=bounds, options={'maxiter': max_iter})

    if result.success:
        return GARCHParams(*result.x)
    else:
        return GARCHParams(x0[0], x0[1], x0[2])


def forecast_volatility_rolling(
    returns: np.ndarray,
    params: GARCHParams,
    window: int = 252,
    horizon: int = 1
) -> np.ndarray:
    """
    滚动窗口波动率预测

    Returns:
        每个时间点的h步预测波动率
    """
    n = len(returns)
    forecasts = np.zeros(n)

    for t in range(window, n):
        window_returns = returns[t-window:t]

        # 计算当前条件方差
        sigma2 = np.zeros(window)
        sigma2[0] = window_returns.var()

        for i in range(1, window):
            sigma2[i] = (params.omega +
                        params.alpha * window_returns[i-1]**2 +
                        params.beta * sigma2[i-1])

        # h步预测
        if horizon == 1:
            forecast = (params.omega +
                       params.alpha * window_returns[-1]**2 +
                       params.beta * sigma2[-1])
        else:
            forecast = (params.omega * (1 - (params.alpha + params.beta)**(horizon-1)) /
                       (1 - params.alpha - params.beta) +
                       (params.alpha + params.beta)**(horizon-1) * sigma2[-1])

        forecasts[t] = np.sqrt(forecast)

    return forecasts
