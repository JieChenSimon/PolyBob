"""
测试交易策略
"""
import pytest
from datetime import datetime
from strategies import CrossMarketDislocationV1, SpreadReversionV1, AIEnhancedPredictionV1


def test_cross_market_dislocation_init():
    """测试跨市场错位策略初始化"""
    config = {
        "z_score_threshold": 2.0,
        "min_spread_bps": 50.0,
        "lookback_window": 100,
        "signal_ttl_seconds": 300,
    }
    strategy = CrossMarketDislocationV1(config)
    assert strategy.strategy_id == "cross_market_dislocation_v1"
    assert strategy.z_score_threshold == 2.0
    assert strategy.min_spread_bps == 50.0


def test_spread_reversion_init():
    """测试价差回归策略初始化"""
    config = {
        "spread_threshold_bps": 150.0,
        "reversion_confidence": 0.7,
        "min_depth_ratio": 0.3,
        "signal_ttl_seconds": 180,
    }
    strategy = SpreadReversionV1(config)
    assert strategy.strategy_id == "spread_reversion_v1"
    assert strategy.spread_threshold_bps == 150.0
    assert strategy.reversion_confidence == 0.7


def test_ai_enhanced_prediction_init():
    """测试 AI 增强预测策略初始化"""
    config = {
        "min_confidence": 0.6,
        "signal_ttl_seconds": 600,
        "analysis_interval_seconds": 60,
    }
    strategy = AIEnhancedPredictionV1(config)
    assert strategy.strategy_id == "ai_enhanced_prediction_v1"
    assert strategy.min_confidence == 0.6
    assert strategy.signal_ttl == 600


@pytest.mark.asyncio
async def test_cross_market_dislocation_start_stop():
    """测试跨市场错位策略启动停止"""
    config = {"z_score_threshold": 2.0}
    strategy = CrossMarketDislocationV1(config)

    await strategy.start()
    assert strategy._running is True

    await strategy.stop()
    assert strategy._running is False


@pytest.mark.asyncio
async def test_spread_reversion_start_stop():
    """测试价差回归策略启动停止"""
    config = {"spread_threshold_bps": 150.0}
    strategy = SpreadReversionV1(config)

    await strategy.start()
    assert strategy._running is True

    await strategy.stop()
    assert strategy._running is False
