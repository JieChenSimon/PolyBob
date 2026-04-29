"""GARCH模型单元测试"""
import numpy as np
import pytest
from libs.quant.garch import estimate_garch, forecast_volatility, GARCHParams


def test_estimate_garch():
    """测试GARCH参数估计"""
    np.random.seed(42)
    returns = np.random.randn(100) * 0.02

    params = estimate_garch(returns)

    assert params.omega > 0
    assert params.alpha >= 0
    assert params.beta >= 0
    assert params.alpha + params.beta < 1


def test_forecast_volatility():
    """测试波动率预测"""
    np.random.seed(42)
    returns = np.random.randn(100) * 0.02
    params = GARCHParams(omega=0.0001, alpha=0.1, beta=0.8)

    vol_forecast = forecast_volatility(returns, params, horizon=5)

    assert len(vol_forecast) == 5
    assert np.all(vol_forecast > 0)
