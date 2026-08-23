"""Regression tests for "missing data must never become a number".

Each test below pins one confirmed way the pipeline used to turn an *absence*
of data into a concrete figure a gate would happily wave through:

1. the event bus silently dropping market-data ticks it promised to coalesce
   (and counting failed handler calls as successful deliveries),
2. a one-sided order book publishing the *previous* mid/spread under a fresh
   timestamp — or a brand-new zero spread, which reads as free arbitrage,
3. paper-trading positions marked at their own entry price, pinning unrealized
   pnl to exactly 0 and thereby faking the return/vol of the whole run,
4. on-chain transfers with no USD quote counted as $0, so a real large
   distribution never reaches its alert threshold.

The invariant they all defend: unknown is ``None``, gates refuse ``None``, and
``0.0`` is only ever a measured zero.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from libs.events import EventBus, Topics
from libs.schemas import OnchainEntityType, OnchainWatchAddress, OrderbookTick
from modules.feature_engine.service import FeatureEngineService, MarketFeatures
from modules.onchain_monitor.service import OnchainMonitorService
from modules.realtime_ingestor.service import RealtimeIngestorService
from modules.simulation import metrics as sim_metrics
from modules.simulation.service import SimulationService


# --------------------------------------------------------------- 1. event bus


def _tick(asset_id: str, seq: int) -> OrderbookTick:
    return OrderbookTick(
        market_id=f"market-{asset_id}",
        asset_id=asset_id,
        timestamp=datetime(2026, 7, 1) + timedelta(seconds=seq),
        bid_price=0.40,
        ask_price=0.60,
        bid_size=float(seq),
        ask_size=1.0,
    )


@pytest.mark.asyncio
async def test_lossy_topic_coalesces_pydantic_payloads_not_only_dicts():
    """ORDERBOOK_TICK ships pydantic models, and those must coalesce too."""
    bus = EventBus(default_queue_maxsize=4)
    received: list[OrderbookTick] = []
    release = asyncio.Event()

    async def slow_handler(tick):
        await release.wait()
        received.append(tick)

    await bus.subscribe(Topics.ORDERBOOK_TICK, slow_handler)

    for seq in range(30):
        await bus.publish(Topics.ORDERBOOK_TICK, _tick("asset-1", seq))

    release.set()
    await bus.drain()

    stats = bus.stats()
    assert stats["coalesced_total"] > 0, "model payloads were never keep-latest merged"
    assert stats["dropped_total"] == 0, "coalescing must replace, not drop"
    assert received[-1].bid_size == 29.0, "the newest tick must survive"


@pytest.mark.asyncio
async def test_busy_asset_does_not_evict_a_quiet_asset():
    """A burst on one asset must not push another asset's only tick out."""
    bus = EventBus(default_queue_maxsize=2)
    received: list[OrderbookTick] = []
    release = asyncio.Event()

    async def slow_handler(tick):
        await release.wait()
        received.append(tick)

    await bus.subscribe(Topics.ORDERBOOK_TICK, slow_handler)

    await bus.publish(Topics.ORDERBOOK_TICK, _tick("quiet-asset", 0))
    for seq in range(1, 30):
        await bus.publish(Topics.ORDERBOOK_TICK, _tick("busy-asset", seq))

    release.set()
    await bus.drain()

    assert any(t.asset_id == "quiet-asset" for t in received)


@pytest.mark.asyncio
async def test_delivered_counts_only_successful_handler_calls():
    """A handler that always raises must not inflate the delivered counter."""
    bus = EventBus()

    async def failing_handler(_data):
        raise ValueError("boom")

    await bus.subscribe(Topics.MARKET_DISCOVERED, failing_handler)
    for index in range(3):
        await bus.publish(Topics.MARKET_DISCOVERED, {"market_id": f"m{index}"})
    await bus.drain()

    stats = bus.stats()
    assert stats["delivered"] == 0
    assert stats["handler_errors_total"] == 3
    assert stats["handler_errors"][Topics.MARKET_DISCOVERED] == 3


# ------------------------------------------------------- 2. one-sided book


ONE_SIDED_BOOK = {
    "event_type": "book",
    "asset_id": "asset-1",
    "market": "market-1",
    "timestamp": "1753099200000",
    "bids": [{"price": "0.90", "size": "10"}],
    "asks": [],
}

TWO_SIDED_BOOK = {
    "event_type": "book",
    "asset_id": "asset-1",
    "market": "market-1",
    "timestamp": "1753099200000",
    "bids": [{"price": "0.40", "size": "100"}],
    "asks": [{"price": "0.60", "size": "80"}],
}


class _RecordingBus:
    def __init__(self):
        self.published: list[tuple[str, object]] = []

    async def publish(self, topic, payload):
        self.published.append((topic, payload))

    async def subscribe(self, topic, handler):
        return None


@pytest.mark.asyncio
async def test_one_sided_book_publishes_none_not_zero_for_the_missing_side():
    service = RealtimeIngestorService()
    service.event_bus = _RecordingBus()
    try:
        await service._handle_message(dict(ONE_SIDED_BOOK))
        (tick,) = [p for _, p in service.event_bus.published if isinstance(p, OrderbookTick)]
        assert tick.bid_price == 0.90
        assert tick.ask_price is None, "a missing ask must not be quoted as 0.0"
        assert tick.ask_size is None
    finally:
        await service.rest_client.close()


def test_one_sided_book_clears_mid_and_spread_instead_of_keeping_stale_values():
    features = MarketFeatures("market-1")
    healthy = OrderbookTick(
        market_id="market-1",
        timestamp=datetime(2026, 7, 1, 12, 0, 0),
        bid_price=0.40,
        ask_price=0.42,
        bid_size=100.0,
        ask_size=100.0,
    )
    features.update_from_orderbook(healthy)
    healthy_mid = features.mid_price
    assert healthy_mid == pytest.approx(0.41)

    one_sided = OrderbookTick(
        market_id="market-1",
        timestamp=datetime(2026, 7, 1, 12, 0, 5),
        bid_price=0.90,
        ask_price=None,
        bid_size=10.0,
        ask_size=None,
    )
    features.update_from_orderbook(one_sided)

    assert features.mid_price is None, "stale mid was re-published under a new timestamp"
    assert features.spread_bps is None
    assert features.last_update == one_sided.timestamp


@pytest.mark.asyncio
async def test_one_sided_book_does_not_raise_in_anomaly_checks():
    """Missing spread must be a quiet degraded state, not a handler error."""
    engine = FeatureEngineService()
    features = MarketFeatures("market-1")
    features.update_from_orderbook(
        OrderbookTick(
            market_id="market-1",
            timestamp=datetime(2026, 7, 1, 12, 0, 0),
            bid_price=0.90,
            ask_price=None,
            bid_size=10.0,
            ask_size=None,
        )
    )

    await engine._check_anomalies(features)


def test_feature_gate_blocks_snapshot_without_a_mid_price():
    engine = FeatureEngineService()
    now = datetime.utcnow()
    assert engine._gate_snapshot(
        {"market_id": "m1", "timestamp": now, "mid_price": None, "spread_bps": None}
    ) is None
    # A zero mid is not a price either — an empty book is not a free option.
    assert engine._gate_snapshot(
        {"market_id": "m1", "timestamp": now, "mid_price": 0.0, "spread_bps": 0.0}
    ) is None
    ok = engine._gate_snapshot(
        {"market_id": "m1", "timestamp": now, "mid_price": 0.41, "spread_bps": 48.7}
    )
    assert ok is not None


def test_brand_new_one_sided_book_never_reports_a_zero_spread():
    """Zero spread on a fresh one-sided book used to look like free arbitrage."""
    features = MarketFeatures("market-1")
    features.update_from_orderbook(
        OrderbookTick(
            market_id="market-1",
            timestamp=datetime(2026, 7, 1, 12, 0, 0),
            bid_price=0.90,
            ask_price=None,
            bid_size=10.0,
            ask_size=None,
        )
    )
    snapshot = features.to_dict()
    assert snapshot["spread_bps"] is None
    assert snapshot["mid_price"] is None
    assert FeatureEngineService()._gate_snapshot(snapshot) is None


# ------------------------------------------------------------ 3. sim marks


class _MarkOnlySource:
    """A source that never signals: it only proves marks track snapshots."""

    topics = (Topics.FEATURE_SNAPSHOT,)

    async def on_snapshot(self, topic, snapshot):
        return []


def _make_sim(tmp_path) -> SimulationService:
    return SimulationService(
        tmp_path / "sim.sqlite3",
        equity_poll_seconds=3600,
        source_factories={"probe": lambda config, db_path: _MarkOnlySource()},
    )


async def _seeded_run(service: SimulationService) -> tuple[str, object]:
    run = await service.create_run(
        name="probe",
        strategy_id="probe",
        universe=["m1"],
        initial_capital=10_000.0,
        config={"max_staleness_seconds": 30.0},
    )
    run_id = run["run_id"]
    await service.start_run(run_id)
    # An open long booked at 1.00 — its value must follow the market, not entry.
    service.store.upsert_position(run_id, "m1", 100.0, 1.00)
    return run_id, service._active[run_id]


@pytest.mark.asyncio
async def test_marks_follow_snapshots_even_when_no_signal_is_produced(tmp_path):
    service = _make_sim(tmp_path)
    run_id, active = await _seeded_run(service)

    await service._dispatch(
        Topics.FEATURE_SNAPSHOT,
        {
            "market_id": "m1",
            "timestamp": datetime.now(UTC),
            "mid_price": 1.50,
            "bid_price": 1.49,
            "ask_price": 1.51,
        },
    )

    assert active.marks["m1"] == pytest.approx(1.50)
    equity, _gross, _notionals, degraded = service._equity_snapshot(active)
    assert not degraded
    # 10_000 cash + 100 units marked at 1.50 — unrealized pnl is +50, not 0.
    assert equity == pytest.approx(10_150.0)


@pytest.mark.asyncio
async def test_stale_mark_degrades_the_equity_point_and_voids_curve_metrics(tmp_path):
    service = _make_sim(tmp_path)
    run_id, active = await _seeded_run(service)

    await service._dispatch(
        Topics.FEATURE_SNAPSHOT,
        {
            "market_id": "m1",
            "timestamp": datetime.now(UTC) - timedelta(minutes=10),
            "mid_price": 1.50,
        },
    )
    await service._record_equity(active)

    points = service.store.list_equity_points(run_id)
    assert points[-1].degraded is True

    metrics = sim_metrics.compute_run_metrics(service.store, run_id)
    assert metrics["equity_curve_degraded"] is True
    assert metrics["total_return"] is None
    assert metrics["max_drawdown"] is None
    assert metrics["sharpe"] is None


@pytest.mark.asyncio
async def test_position_without_any_mark_degrades_the_equity_point(tmp_path):
    service = _make_sim(tmp_path)
    run_id, active = await _seeded_run(service)

    await service._record_equity(active)

    points = service.store.list_equity_points(run_id)
    assert points[-1].degraded is True


# ------------------------------------------------------------- 4. on-chain


def _monitor() -> OnchainMonitorService:
    return OnchainMonitorService(
        watches=[
            OnchainWatchAddress(
                watch_id="rave_deployer",
                chain="ethereum",
                token_symbol="RAVE",
                contract_address="0x1111",
                address="0xaaaa",
                label="RAVE deployer",
                entity_type=OnchainEntityType.DEPLOYER,
                cex_transfer_threshold_usd=50_000,
            )
        ],
        cex_addresses={"0xdddd": {"label": "binance_hot_wallet_sample", "exchange": "binance"}},
    )


def _transfer(**overrides) -> dict:
    payload = {
        "chain": "ethereum",
        "tx_hash": "0xtx1",
        "block_time": datetime.utcnow().isoformat(),
        "token_symbol": "RAVE",
        "contract_address": "0x1111",
        "from_address": "0xaaaa",
        "to_address": "0xdddd",
        "amount": 100_000,
        "usd_value": 80_000,
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_transfer_without_usd_quote_is_undetermined_not_zero():
    service = _monitor()
    payload = _transfer()
    payload.pop("usd_value")

    result = await service.ingest_event(payload)

    assert result["event"]["usd_value"] is None, "$0 would hide a real distribution"
    assert result["alert_count"] == 0
    assert result["undetermined_usd_value"] is True
    summary = service.get_summary()
    assert summary["undetermined_usd_events"] == 1
    assert summary["recent_cex_flow_usd"] is None


@pytest.mark.asyncio
async def test_cluster_aggregate_refuses_to_total_an_unknown_leg():
    service = _monitor()
    await service.ingest_event(_transfer(event_id="evt_1", usd_value=45_000))
    payload = _transfer(event_id="evt_2", tx_hash="0xtx2")
    payload.pop("usd_value")

    result = await service.ingest_event(payload)

    alert_types = {alert["alert_type"] for alert in result["alerts"]}
    assert "distribution_cluster" not in alert_types
    assert service.get_summary()["undetermined_cluster_windows"] >= 1


@pytest.mark.asyncio
async def test_transfer_without_block_time_is_rejected():
    service = _monitor()
    payload = _transfer()
    payload.pop("block_time")

    with pytest.raises(ValueError):
        await service.ingest_event(payload)

    assert service.list_events() == []
