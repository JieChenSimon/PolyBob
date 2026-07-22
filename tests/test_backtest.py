"""
Tests for backtest engine
"""
import pytest
from datetime import datetime, timedelta
from libs.backtest import BacktestEngine
from libs.backtest.engine import BacktestConfig
from libs.backtest.metrics import PerformanceMetrics
from libs.schemas import Side


def test_backtest_engine_initialization():
    """测试回测引擎初始化"""
    config = BacktestConfig(initial_capital=5000.0)
    engine = BacktestEngine(config)

    assert engine.capital == 5000.0
    assert len(engine.positions) == 0
    assert len(engine.trades) == 0


def test_execute_buy_signal():
    """测试买入信号执行"""
    engine = BacktestEngine()
    timestamp = datetime.utcnow()

    success = engine.execute_signal(
        timestamp=timestamp,
        market_id="market_1",
        side=Side.BUY_YES,
        price=0.5,
        size=100.0
    )

    assert success
    assert len(engine.trades) == 1
    assert engine.positions["market_1"] == 100.0
    assert engine.capital < 10000.0  # 扣除成本


def test_insufficient_capital():
    """测试资金不足"""
    config = BacktestConfig(initial_capital=100.0)
    engine = BacktestEngine(config)
    timestamp = datetime.utcnow()

    success = engine.execute_signal(
        timestamp=timestamp,
        market_id="market_1",
        side=Side.BUY_YES,
        price=0.5,
        size=1000.0  # 需要 500+ 资金
    )

    assert not success
    assert len(engine.trades) == 0


def test_equity_curve():
    """测试权益曲线"""
    engine = BacktestEngine()
    timestamp = datetime.utcnow()

    # 执行交易
    engine.execute_signal(timestamp, "market_1", Side.BUY_YES, 0.5, 100.0)

    # 更新权益
    engine.update_equity(timestamp, {"market_1": 0.6})

    assert len(engine.equity_curve) == 1
    assert engine.equity_curve[0][1] > 10000.0  # 盈利


def test_performance_metrics():
    """测试性能指标"""
    returns = [0.01, 0.02, -0.01, 0.03, -0.005]
    sharpe = PerformanceMetrics.sharpe_ratio(returns)

    assert sharpe > 0


def test_backtest_results():
    """测试回测结果"""
    engine = BacktestEngine()
    timestamp = datetime.utcnow()

    # 执行交易
    engine.execute_signal(timestamp, "market_1", Side.BUY_YES, 0.5, 100.0)
    engine.update_equity(timestamp, {"market_1": 0.6})

    results = engine.get_results()

    assert "total_return" in results
    assert "max_drawdown" in results
    assert results["num_trades"] == 1


class _RecordingBus:
    def __init__(self):
        self.published = []

    async def publish(self, topic, data):
        self.published.append((topic, data))


def _make_replayer(timestamps):
    from libs.backtest.replay import HistoricalDataReplayer

    start = min(timestamps) if timestamps else datetime.utcnow()
    end = max(timestamps) if timestamps else datetime.utcnow()
    replayer = HistoricalDataReplayer("test", start, end)
    replayer.events = [
        {"timestamp": ts, "topic": "t", "data": {"i": i}}
        for i, ts in enumerate(timestamps)
    ]
    return replayer


@pytest.mark.asyncio
async def test_replay_publishes_events_in_timestamp_order():
    base = datetime(2025, 1, 1)
    timestamps = [base + timedelta(seconds=2), base, base + timedelta(seconds=1)]
    replayer = _make_replayer(timestamps)
    bus = _RecordingBus()

    await replayer.replay(bus, speed_multiplier=1e9)

    published_indices = [data["i"] for _, data in bus.published]
    assert published_indices == [1, 2, 0]  # sorted by timestamp
    assert replayer.current_time == base + timedelta(seconds=2)


@pytest.mark.asyncio
async def test_replay_sorted_input_avoids_copy_and_unsorted_uses_cache():
    base = datetime(2025, 1, 1)
    sorted_ts = [base + timedelta(seconds=i) for i in range(5)]
    replayer = _make_replayer(sorted_ts)

    # Fast path: already-sorted events are iterated in place, no copy.
    assert replayer._get_sorted_events() is replayer.events

    # Unsorted: sorted once, cached for repeated replays.
    unsorted = _make_replayer([sorted_ts[2], sorted_ts[0], sorted_ts[1]])
    first = unsorted._get_sorted_events()
    second = unsorted._get_sorted_events()
    assert first is second
    assert [e["timestamp"] for e in first] == sorted_ts[:3]

    bus = _RecordingBus()
    await unsorted.replay(bus, speed_multiplier=1e9)
    assert [data["i"] for _, data in bus.published] == [1, 2, 0]
