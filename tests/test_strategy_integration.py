"""
测试策略与策略引擎集成
"""
import pytest

from services.strategy_engine import StrategyEngineService
from strategies import AIEnhancedPredictionV1, CrossMarketDislocationV1, SpreadReversionV1


def test_cross_market_strategy_init():
    """测试跨市场策略初始化"""
    strategy = CrossMarketDislocationV1({"z_score_threshold": 2.0})
    assert strategy.strategy_id == "cross_market_dislocation_v1"
    assert strategy.z_score_threshold == 2.0


def test_ai_enhanced_strategy_init():
    """测试 AI 增强策略初始化"""
    strategy = AIEnhancedPredictionV1({"min_confidence": 0.6})
    assert strategy.strategy_id == "ai_enhanced_prediction_v1"
    assert strategy.min_confidence == 0.6


@pytest.mark.asyncio
async def test_strategy_engine_registration():
    """测试策略引擎注册"""
    engine = StrategyEngineService()

    strategy1 = CrossMarketDislocationV1({"z_score_threshold": 2.0})
    strategy2 = SpreadReversionV1({"spread_threshold_bps": 150.0})

    engine.register_strategy(strategy1)
    engine.register_strategy(strategy2)

    assert len(engine.strategies) == 2


@pytest.mark.asyncio
async def test_cross_market_signal_generation():
    """测试跨市场策略信号生成"""
    strategy = CrossMarketDislocationV1({"z_score_threshold": 2.0})

    features = {
        "market_id": "test_market_1",
        "mid_price": 0.55,
        "spread_bps": 100.0,
    }

    await strategy._on_feature_snapshot(features)
    assert strategy.features["test_market_1"]["mid_price"] == 0.55
