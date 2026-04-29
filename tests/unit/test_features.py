"""
特征计算单元测试
"""
import pytest
import math
from typing import List


class FeatureCalculator:
    """特征计算器"""

    @staticmethod
    def mid_price(best_bid: float, best_ask: float) -> float:
        """计算中间价"""
        return (best_bid + best_ask) / 2

    @staticmethod
    def spread_bps(best_bid: float, best_ask: float) -> float:
        """计算价差(基点)"""
        mid = FeatureCalculator.mid_price(best_bid, best_ask)
        return ((best_ask - best_bid) / mid) * 10000

    @staticmethod
    def depth_imbalance(bid_depth: float, ask_depth: float) -> float:
        """计算深度不平衡"""
        total = bid_depth + ask_depth
        return (bid_depth - ask_depth) / total if total > 0 else 0.0

    @staticmethod
    def volatility(prices: List[float]) -> float:
        """计算波动率(标准差)"""
        if len(prices) < 2:
            return 0.0
        mean = sum(prices) / len(prices)
        variance = sum((p - mean) ** 2 for p in prices) / len(prices)
        return math.sqrt(variance)

    @staticmethod
    def momentum(prices: List[float], window: int = 5) -> float:
        """计算动量(价格变化率)"""
        if len(prices) <= window:
            return 0.0
        base_price = prices[-(window + 1)]
        return (prices[-1] - base_price) / base_price if base_price else 0.0

    @staticmethod
    def z_score(value: float, values: List[float]) -> float:
        """计算Z-score"""
        if len(values) < 2:
            return 0.0
        mean = sum(values) / len(values)
        std = math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))
        return (value - mean) / std if std > 0 else 0.0


def test_mid_price_calculation():
    """测试中间价计算"""
    assert FeatureCalculator.mid_price(0.50, 0.52) == 0.51
    assert FeatureCalculator.mid_price(0.45, 0.55) == 0.50
    assert abs(FeatureCalculator.mid_price(0.333, 0.667) - 0.5) < 0.001


def test_spread_bps_calculation():
    """测试价差计算"""
    spread = FeatureCalculator.spread_bps(0.50, 0.51)
    assert abs(spread - 198.02) < 1.0  # 约200bps

    spread = FeatureCalculator.spread_bps(0.49, 0.51)
    assert abs(spread - 400.0) < 10.0  # 约400bps


def test_depth_imbalance():
    """测试深度不平衡计算"""
    # 买方深度更大
    imbalance = FeatureCalculator.depth_imbalance(6000, 4000)
    assert abs(imbalance - 0.2) < 0.01

    # 卖方深度更大
    imbalance = FeatureCalculator.depth_imbalance(3000, 7000)
    assert abs(imbalance - (-0.4)) < 0.01

    # 平衡
    imbalance = FeatureCalculator.depth_imbalance(5000, 5000)
    assert abs(imbalance) < 0.01


def test_volatility_calculation():
    """测试波动率计算"""
    # 无波动
    prices = [0.5, 0.5, 0.5, 0.5]
    assert FeatureCalculator.volatility(prices) == 0.0

    # 有波动
    prices = [0.5, 0.52, 0.48, 0.51, 0.49]
    vol = FeatureCalculator.volatility(prices)
    assert vol > 0.0
    assert vol < 0.1


def test_momentum_calculation():
    """测试动量计算"""
    # 上涨趋势
    prices = [0.50, 0.51, 0.52, 0.53, 0.54, 0.55]
    momentum = FeatureCalculator.momentum(prices, window=5)
    assert momentum > 0.0
    assert abs(momentum - 0.1) < 0.01  # 10%涨幅

    # 下跌趋势
    prices = [0.55, 0.54, 0.53, 0.52, 0.51, 0.50]
    momentum = FeatureCalculator.momentum(prices, window=5)
    assert momentum < 0.0


def test_z_score_calculation():
    """测试Z-score计算"""
    values = [0.50, 0.51, 0.49, 0.52, 0.48]

    # 接近均值
    z = FeatureCalculator.z_score(0.50, values)
    assert abs(z) < 0.5

    # 远离均值
    z = FeatureCalculator.z_score(0.60, values)
    assert z > 2.0


def test_edge_cases():
    """测试边界条件"""
    # 空列表
    assert FeatureCalculator.volatility([]) == 0.0
    assert FeatureCalculator.momentum([]) == 0.0
    assert FeatureCalculator.z_score(0.5, []) == 0.0

    # 单个元素
    assert FeatureCalculator.volatility([0.5]) == 0.0
    assert FeatureCalculator.momentum([0.5]) == 0.0

    # 零深度
    assert FeatureCalculator.depth_imbalance(0, 0) == 0.0
