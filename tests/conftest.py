"""
测试配置与Fixtures
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, Mock
from datetime import datetime
from typing import Dict, List


@pytest.fixture
def event_loop():
    """创建事件循环"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_event_bus():
    """Mock事件总线"""
    bus = AsyncMock()
    bus.publish = AsyncMock()
    bus.subscribe = AsyncMock()
    bus.unsubscribe = AsyncMock()
    return bus


@pytest.fixture
def mock_polymarket_api():
    """Mock Polymarket API"""
    api = AsyncMock()
    api.get_markets = AsyncMock(return_value=[
        {
            "id": "market_1",
            "question": "Will BTC reach $100k?",
            "end_date": "2026-12-31",
        }
    ])
    api.get_orderbook = AsyncMock(return_value={
        "bids": [[0.55, 1000], [0.54, 2000]],
        "asks": [[0.56, 1500], [0.57, 2500]],
    })
    api.place_order = AsyncMock(return_value={"order_id": "order_123"})
    return api


@pytest.fixture
def mock_database():
    """Mock数据库连接"""
    db = AsyncMock()
    db.execute = AsyncMock()
    db.fetch_all = AsyncMock(return_value=[])
    db.fetch_one = AsyncMock(return_value=None)
    return db


@pytest.fixture
def mock_redis():
    """Mock Redis缓存"""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock()
    redis.delete = AsyncMock()
    redis.exists = AsyncMock(return_value=False)
    return redis


@pytest.fixture
def sample_market_data():
    """样本市场数据"""
    return {
        "market_id": "market_1",
        "timestamp": datetime.utcnow(),
        "best_bid": 0.55,
        "best_ask": 0.56,
        "mid_price": 0.555,
        "spread_bps": 180,
        "bid_depth": 3000,
        "ask_depth": 4000,
    }


@pytest.fixture
def sample_feature_snapshot():
    """样本特征快照"""
    return {
        "market_1": {
            "mid_price": 0.555,
            "spread_bps": 180,
            "volatility": 0.02,
            "momentum_5m": 0.01,
            "depth_imbalance": 0.15,
        }
    }


@pytest.fixture
def promoted_strategy(monkeypatch):
    """Let a test build intents without the promotion gate standing in the way.

    The gate now lives in ``IntentExecutionService.create_intent`` — the only
    place an intent can be born — so every test about dedupe, persistence or
    risk checking would otherwise have to care about the board. Those tests are
    about other things; this fixture states plainly that they are exercising a
    strategy the desk has cleared, without pinning them to whatever real edge
    happens to be on the board today.

    The gate's own behaviour is tested directly in
    ``tests/test_promotion_gate.py`` and ``tests/test_promoted_strategies.py``.
    """
    from libs.quant import promotion_registry

    class _AllPromoted:
        def is_promoted(self, strategy, instrument=None):
            return True

        def reason_blocked(self, strategy, instrument=None):
            return "promoted"

    monkeypatch.setattr(promotion_registry, "get_registry", lambda: _AllPromoted())
    return _AllPromoted()


@pytest.fixture
def btc5m_promoted(monkeypatch, tmp_path):
    """Give the BTC-5m workbench a board that promoted it.

    The live board does *not* promote ``btc5m_mispricing`` (n=95, t=3.45 against
    a 3.77 hurdle), so every snapshot now degrades to ``research_only`` and
    withholds the limit price and Kelly size. That is the intended production
    behaviour; tests that exercise the entry optimiser itself need the gate open
    to reach the code they are about. The gate's own behaviour is covered in
    ``tests/unit/test_btc_five_minute_gate.py``.
    """
    import json

    from libs.polymarket import btc_five_minute as btc
    from libs.quant.promotion_registry import PromotionRegistry

    path = tmp_path / "board.json"
    path.write_text(json.dumps({"board": [{
        "strategy": "btc5m_mispricing", "instrument": "BTC_5M",
        "approved": True, "role": "trade", "failed": [],
    }]}))
    registry = PromotionRegistry(path)
    monkeypatch.setattr(btc, "get_registry", lambda: registry)
    return registry
