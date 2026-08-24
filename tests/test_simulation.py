"""Simulation service tests: persistence, fills, pnl, recovery, metrics, feedback."""

import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest

from libs.db import fact_store
from libs.db.simulation_store import SimRunRecord, SimulationStore
from libs.events import Topics, get_event_bus
from modules.simulation import metrics as sim_metrics
from modules.simulation.service import (
    InvalidRunTransitionError,
    SimulationService,
    UnknownRunError,
    apply_avg_price_fill,
    downsample_equity_curve,
)
from modules.simulation.sources import SimSignal
from strategies.signal_fusion import SignalFusion


def make_store(tmp_path) -> SimulationStore:
    return SimulationStore(tmp_path / "sim.sqlite3")


def make_service(tmp_path) -> SimulationService:
    return SimulationService(tmp_path / "sim.sqlite3", equity_poll_seconds=3600)


def feature_snapshot(
    market_id="m1",
    bid=0.95,
    ask=0.97,
    bid_size=1_000_000.0,
    ask_size=1_000_000.0,
    timestamp=None,
    spread_bps=None,
):
    mid = (bid + ask) / 2
    return {
        "market_id": market_id,
        "timestamp": timestamp or datetime.utcnow(),
        "mid_price": mid,
        "spread_bps": spread_bps if spread_bps is not None else (ask - bid) / mid * 10000,
        "bid_price": bid,
        "ask_price": ask,
        "bid_size": bid_size,
        "ask_size": ask_size,
        "depth_imbalance": 0.1,
        "trade_intensity_1m": 5.0,
        "volume_1m": 100.0,
        "price_jump_score": 0.0,
    }


RUN_CONFIG = {
    "cooldown_seconds": 0.0,
    "impact_coefficient": 0.0,  # exact fill assertions
    "fee_bps": 20.0,
}


# ---------------------------------------------------------------------- store


def test_store_run_round_trip(tmp_path):
    store = make_store(tmp_path)
    record = SimRunRecord(
        run_id="sim_abc",
        name="test",
        strategy_id="spread_reversion_v1",
        universe=["m1", "m2"],
        initial_capital=10_000.0,
        cash=10_000.0,
        status="paused",
        config={"fee_bps": 20.0},
        created_at=datetime.now(UTC).isoformat(),
    )
    store.save_run(record)

    loaded = store.get_run("sim_abc")
    assert loaded is not None
    assert loaded.universe == ["m1", "m2"]
    assert loaded.initial_capital == 10_000.0
    assert loaded.config["fee_bps"] == 20.0
    assert loaded.status == "paused"

    store.update_run("sim_abc", status="running", cash=9_500.0)
    loaded = store.get_run("sim_abc")
    assert loaded.status == "running"
    assert loaded.cash == 9_500.0
    assert store.list_runs(status="running")[0].run_id == "sim_abc"
    assert store.get_run("missing") is None


def test_store_positions_trades_equity_round_trip(tmp_path):
    store = make_store(tmp_path)
    store.upsert_position("r1", "m1", 100.0, 0.5)
    store.upsert_position("r1", "m1", 150.0, 0.52)
    positions = store.list_positions("r1")
    assert len(positions) == 1
    assert positions[0].size == 150.0
    assert positions[0].avg_price == 0.52

    # Zero size deletes the row.
    store.upsert_position("r1", "m1", 0.0, 0.0)
    assert store.list_positions("r1") == []

    trade_id = store.append_trade(
        "r1",
        instrument_id="m1",
        side="buy",
        size=100.0,
        price=0.5,
        fee=0.1,
        slippage=0.01,
        signal_meta={"signals": ["rsi"]},
        realized_pnl=None,
    )
    store.append_trade(
        "r1",
        instrument_id="m1",
        side="sell",
        size=100.0,
        price=0.6,
        fee=0.12,
        slippage=0.0,
        realized_pnl=9.78,
    )
    trades = store.list_trades("r1")
    assert [t.trade_id for t in trades] == [trade_id, trade_id + 1]
    assert trades[0].realized_pnl is None
    assert trades[0].signal_meta == {"signals": ["rsi"]}
    assert trades[1].realized_pnl == pytest.approx(9.78)
    assert store.list_trades("r1", limit=1)[0].trade_id == trade_id + 1
    assert store.list_trades("r1", after_id=trade_id)[0].trade_id == trade_id + 1

    store.append_equity_point("r1", equity=10_000.0, cash=9_950.0, gross_exposure=50.0, ts="t1")
    store.append_equity_point("r1", equity=10_010.0, cash=9_950.0, gross_exposure=60.0, ts="t2")
    points = store.list_equity_points("r1")
    assert [p.equity for p in points] == [10_000.0, 10_010.0]
    assert points[0].gross_exposure == 50.0


# ------------------------------------------------------------ avg-price math


def test_avg_price_open_and_extend():
    size, avg, realized = apply_avg_price_fill(0.0, 0.0, 10.0, 100.0)
    assert (size, avg, realized) == (10.0, 100.0, None)
    size, avg, realized = apply_avg_price_fill(size, avg, 10.0, 110.0)
    assert (size, avg, realized) == (20.0, 105.0, None)


def test_avg_price_partial_and_full_close():
    size, avg, realized = apply_avg_price_fill(20.0, 105.0, -5.0, 120.0)
    assert size == 15.0
    assert avg == 105.0
    assert realized == pytest.approx(75.0)

    size, avg, realized = apply_avg_price_fill(size, avg, -15.0, 100.0)
    assert size == 0.0
    assert realized == pytest.approx(-75.0)


def test_avg_price_short_close_and_flip():
    # Short 10 @ 100, buy back 4 @ 90 -> profit 40.
    size, avg, realized = apply_avg_price_fill(-10.0, 100.0, 4.0, 90.0)
    assert size == -6.0
    assert avg == 100.0
    assert realized == pytest.approx(40.0)

    # Long 5 @ 100, sell 8 @ 110 -> realize 50 on the closed 5, flip short 3 @ 110.
    size, avg, realized = apply_avg_price_fill(5.0, 100.0, -8.0, 110.0)
    assert size == pytest.approx(-3.0)
    assert avg == 110.0
    assert realized == pytest.approx(50.0)


# ------------------------------------------------------------ service + fills


@pytest.mark.asyncio
async def test_run_lifecycle_transitions(tmp_path):
    service = make_service(tmp_path)
    run = await service.create_run(
        name="lifecycle",
        strategy_id="spread_reversion_v1",
        universe=["m1"],
        initial_capital=10_000.0,
    )
    run_id = run["run_id"]
    assert run["status"] == "paused"

    with pytest.raises(InvalidRunTransitionError):
        await service.pause_run(run_id)  # paused -> paused invalid

    started = await service.start_run(run_id)
    assert started["status"] == "running"
    with pytest.raises(InvalidRunTransitionError):
        await service.start_run(run_id)  # running -> running invalid

    paused = await service.pause_run(run_id)
    assert paused["status"] == "paused"
    stopped = await service.stop_run(run_id)
    assert stopped["status"] == "stopped"
    with pytest.raises(InvalidRunTransitionError):
        await service.start_run(run_id)  # stopped is terminal

    with pytest.raises(UnknownRunError):
        await service.start_run("sim_missing")

    # Lifecycle transitions are audited.
    with fact_store.connect(service.store.db_path) as connection:
        events = [
            row["event_type"]
            for row in connection.execute(
                "SELECT event_type FROM audit_events WHERE subject_id = ?", (run_id,)
            ).fetchall()
        ]
    assert "sim.run.created" in events
    assert "sim.run.running" in events
    assert "sim.run.stopped" in events


@pytest.mark.asyncio
async def test_conservative_fill_buys_at_ask_plus_fee(tmp_path):
    service = make_service(tmp_path)
    run = await service.create_run(
        name="fills",
        strategy_id="spread_reversion_v1",
        universe=["m1"],
        initial_capital=10_000.0,
        config=RUN_CONFIG,
    )
    run_id = run["run_id"]
    await service.start_run(run_id)

    # Wide spread + balanced deep book -> buy signal (depth_imbalance >= 0).
    await service._on_feature_snapshot(feature_snapshot(bid=0.90, ask=0.92))

    trades = service.store.list_trades(run_id)
    assert len(trades) == 1
    trade = trades[0]
    assert trade.side == "buy"
    # Conservative: fills exactly at the ask (impact disabled in config).
    assert trade.price == pytest.approx(0.92)
    # Fee = 20 bps of notional.
    assert trade.fee == pytest.approx(trade.size * 0.92 * 0.002)
    assert trade.realized_pnl is None

    # Position sized at position_fraction (5%) of equity, priced at the ask,
    # with the fee folded into avg_price (avg > raw fill price).
    positions = service.store.list_positions(run_id)
    assert len(positions) == 1
    assert positions[0].size == pytest.approx(0.05 * 10_000.0 / 0.92, rel=1e-6)
    assert positions[0].avg_price == pytest.approx(0.92 * 1.002)

    ledger_account = service.ledger.get_account(f"paper:{run_id}")
    assert ledger_account.positions["M1"].quantity > 0
    assert service.ledger.verify_projection(f"paper:{run_id}").consistent is True

    # Cash decreased by notional + fee; equity point written on the trade.
    record = service.store.get_run(run_id)
    assert record.cash == pytest.approx(10_000.0 - trade.size * 0.92 - trade.fee)
    assert len(service.store.list_equity_points(run_id)) >= 1


@pytest.mark.asyncio
async def test_per_instrument_position_fraction_overrides_scalar(tmp_path):
    service = make_service(tmp_path)
    run = await service.create_run(
        name="instrument-sizing",
        strategy_id="spread_reversion_v1",
        universe=["m1", "m2"],
        initial_capital=10_000.0,
        config={**RUN_CONFIG, "position_fraction": 0.05,
                "position_fraction_by_instrument": {"m1": 0.01}},
    )
    await service.start_run(run["run_id"])
    now = datetime.now(UTC)
    await service._process_signal(
        service._active[run["run_id"]],
        SimSignal("m1", "buy", 0.9, bid=0.99, ask=1.01, mid=1.0, timestamp=now),
    )
    await service._process_signal(
        service._active[run["run_id"]],
        SimSignal("m2", "buy", 0.9, bid=0.99, ask=1.01, mid=1.0, timestamp=now),
    )
    positions = {position.instrument_id: position for position in service.store.list_positions(run["run_id"])}
    assert positions["m1"].size == pytest.approx(0.01 * 10_000.0 / 1.01, rel=1e-6)
    # The second fill uses the slightly reduced equity after the first fee;
    # compare the intended five-to-one sizing ratio rather than a stale cash
    # snapshot.
    assert positions["m2"].size / positions["m1"].size == pytest.approx(5.0, rel=2e-4)


@pytest.mark.asyncio
async def test_long_only_run_flattens_sell_signal_without_opening_short(tmp_path):
    service = make_service(tmp_path)
    run = await service.create_run(
        name="long-only", strategy_id="spread_reversion_v1", universe=["m1"],
        initial_capital=10_000.0,
        config={**RUN_CONFIG, "allow_short": False},
    )
    run_id = run["run_id"]
    await service.start_run(run_id)
    active = service._active[run_id]
    now = datetime.now(UTC)

    buy = SimSignal("m1", "buy", 0.9, bid=0.99, ask=1.01, mid=1.0, timestamp=now)
    await service._process_signal(active, buy)
    assert service.store.list_positions(run_id)[0].size > 0

    sell = SimSignal("m1", "sell", 0.9, bid=0.99, ask=1.01, mid=1.0, timestamp=now)
    await service._process_signal(active, sell)
    assert service.store.list_positions(run_id) == []


@pytest.mark.asyncio
async def test_rebalance_hysteresis_skips_immaterial_resize(tmp_path):
    service = make_service(tmp_path)
    run = await service.create_run(
        name="hysteresis", strategy_id="spread_reversion_v1", universe=["m1"],
        initial_capital=10_000.0,
        config={**RUN_CONFIG, "min_rebalance_bps": 25.0},
    )
    run_id = run["run_id"]
    await service.start_run(run_id)
    active = service._active[run_id]
    now = datetime.now(UTC)
    await service._process_signal(
        active, SimSignal("m1", "buy", 0.9, bid=0.99, ask=1.01, mid=1.0, timestamp=now)
    )
    first_count = len(service.store.list_trades(run_id))
    # A roughly 10 bps mark change would require less than the 25 bps target resize.
    await service._process_signal(
        active, SimSignal("m1", "buy", 0.9, bid=0.99099, ask=1.01101, mid=1.001, timestamp=now)
    )
    assert len(service.store.list_trades(run_id)) == first_count


@pytest.mark.asyncio
async def test_funding_snapshot_is_booked_once_and_replayed(tmp_path):
    service = make_service(tmp_path)
    run = await service.create_run(
        name="funding", strategy_id="spread_reversion_v1", universe=["m1"],
        initial_capital=10_000.0, config=RUN_CONFIG,
    )
    await service.start_run(run["run_id"])
    # Use a fresh event timestamp: the production simulator must reject stale
    # funding snapshots, so a hard-coded midnight becomes stale as the test
    # day advances in UTC.
    timestamp = datetime.now(UTC)
    snapshot = feature_snapshot(bid=0.90, ask=0.92, timestamp=timestamp)
    snapshot["funding_rate"] = 0.001
    await service._on_feature_snapshot(snapshot)
    await service._on_feature_snapshot(snapshot)
    total = service.store.total_funding(run["run_id"])
    assert total < 0
    await service._on_feature_snapshot(snapshot)
    assert service.store.total_funding(run["run_id"]) == pytest.approx(total)


@pytest.mark.asyncio
async def test_funding_enabled_run_fails_closed_without_rate(tmp_path):
    service = make_service(tmp_path)
    run = await service.create_run(
        name="funding-required", strategy_id="spread_reversion_v1", universe=["m1"],
        initial_capital=10_000.0, config={**RUN_CONFIG, "funding_enabled": True},
    )
    await service.start_run(run["run_id"])
    await service._on_feature_snapshot(feature_snapshot(timestamp=datetime.now(UTC)))
    assert service.store.list_trades(run["run_id"]) == []
    assert service.store.total_funding(run["run_id"]) == 0.0

@pytest.mark.asyncio
async def test_no_fill_on_degraded_or_stale_book(tmp_path):
    service = make_service(tmp_path)
    run = await service.create_run(
        name="degraded",
        strategy_id="spread_reversion_v1",
        universe=["m1"],
        initial_capital=10_000.0,
        config=RUN_CONFIG,
    )
    run_id = run["run_id"]
    await service.start_run(run_id)
    active = service._active[run_id]

    # Stale snapshot (older than max_staleness_seconds): dropped.
    stale = feature_snapshot(timestamp=datetime.utcnow() - timedelta(minutes=5))
    await service._on_feature_snapshot(stale)
    assert service.store.list_trades(run_id) == []

    # Degraded book (no bid/ask, no mid): the fill model refuses.
    signal = SimSignal(
        instrument_id="m1",
        side="buy",
        confidence=0.9,
        bid=None,
        ask=None,
        mid=None,
        timestamp=datetime.utcnow(),
    )
    assert service._fill_price(active, signal, 100.0) is None
    await service._process_signal(active, signal)
    assert service.store.list_trades(run_id) == []

    # Missing timestamp: unknown != safe, no fill.
    no_ts = SimSignal(
        instrument_id="m1", side="buy", confidence=0.9, bid=0.9, ask=0.92, mid=0.91
    )
    await service._process_signal(active, no_ts)
    assert service.store.list_trades(run_id) == []

    # Mid-only quote pays the penalty (10 bps against the trade).
    mid_only = SimSignal(
        instrument_id="m1",
        side="buy",
        confidence=0.9,
        mid=0.90,
        timestamp=datetime.utcnow(),
    )
    price, _ = service._fill_price(active, mid_only, 100.0)
    assert price == pytest.approx(0.90 * 1.001)
    sell_mid = SimSignal(
        instrument_id="m1",
        side="sell",
        confidence=0.9,
        mid=0.90,
        timestamp=datetime.utcnow(),
    )
    price, _ = service._fill_price(active, sell_mid, 100.0)
    assert price == pytest.approx(0.90 * 0.999)


@pytest.mark.asyncio
async def test_historical_clock_reuses_paper_fill_path_without_wall_clock_staleness(tmp_path):
    """Historical replay must use the event clock, not reject every old bar."""
    clock = [datetime(2020, 1, 1, tzinfo=UTC)]
    service = SimulationService(
        tmp_path / "historical.sqlite3",
        clock=lambda: clock[0],
        equity_poll_seconds=3600,
    )
    run = await service.create_run(
        name="historical-clock",
        strategy_id="momentum_dualma_v1",
        universe=["m1"],
        initial_capital=10_000.0,
        config={"fast_window": 1, "slow_window": 2, "min_separation_bps": 0.0,
                "cooldown_seconds": 0.0},
    )
    await service.start_run(run["run_id"])
    for index, close in enumerate((100.0, 101.0, 102.0)):
        clock[0] = datetime(2020, 1, 1 + index, tzinfo=UTC)
        await service._on_feature_snapshot({
            "market_id": "m1", "timestamp": clock[0], "mid_price": close,
        })

    assert service.store.list_trades(run["run_id"]), "the historical event should be tradable"


@pytest.mark.asyncio
async def test_event_bus_feeds_running_runs_only(tmp_path):
    service = make_service(tmp_path)
    await service.start()
    try:
        run = await service.create_run(
            name="bus",
            strategy_id="spread_reversion_v1",
            universe=["m1"],
            initial_capital=10_000.0,
            config=RUN_CONFIG,
        )
        run_id = run["run_id"]
        bus = get_event_bus()

        # Paused run ignores snapshots.
        await bus.publish(Topics.FEATURE_SNAPSHOT, feature_snapshot())
        await bus.drain()
        assert service.store.list_trades(run_id) == []

        await service.start_run(run_id)
        await bus.publish(Topics.FEATURE_SNAPSHOT, feature_snapshot())
        await bus.drain()
        assert len(service.store.list_trades(run_id)) == 1

        # Instruments outside the universe are ignored.
        await bus.publish(Topics.FEATURE_SNAPSHOT, feature_snapshot(market_id="other"))
        await bus.drain()
        trades = service.store.list_trades(run_id)
        assert {t.instrument_id for t in trades} == {"m1"}
    finally:
        await service.stop()


@pytest.mark.asyncio
async def test_snapshot_routing_indexes_topic_and_instrument(tmp_path):
    service = make_service(tmp_path)
    run = await service.create_run(
        name="indexed",
        strategy_id="spread_reversion_v1",
        universe=["m1"],
        initial_capital=1000,
        config=RUN_CONFIG,
    )
    run_id = run["run_id"]
    assert run_id in service._active_routes[(Topics.FEATURE_SNAPSHOT, "m1")]
    assert (Topics.FEATURE_SNAPSHOT, "m2") not in service._active_routes
    await service.stop_run(run_id)
    assert (Topics.FEATURE_SNAPSHOT, "m1") not in service._active_routes


@pytest.mark.asyncio
async def test_restart_recovery_resumes_runs_and_positions(tmp_path):
    service = make_service(tmp_path)
    run = await service.create_run(
        name="recovery",
        strategy_id="spread_reversion_v1",
        universe=["m1"],
        initial_capital=10_000.0,
        config=RUN_CONFIG,
    )
    run_id = run["run_id"]
    await service.start_run(run_id)
    await service._on_feature_snapshot(feature_snapshot(bid=0.90, ask=0.92))
    assert len(service.store.list_trades(run_id)) == 1
    cash_before = service.store.get_run(run_id).cash

    # Fresh service on the same DB (simulated restart).
    revived = make_service(tmp_path)
    assert revived._active == {}
    await revived.restore_state()
    assert run_id in revived._active
    restored = revived._active[run_id].record
    assert restored.status == "running"
    assert restored.cash == pytest.approx(cash_before)
    positions = revived.store.list_positions(run_id)
    assert len(positions) == 1
    long_size = positions[0].size

    # The revived run keeps trading: closing sell realizes pnl net of fees.
    snapshot = feature_snapshot(bid=1.10, ask=1.12)
    snapshot["depth_imbalance"] = -0.1  # sell-side signal
    await revived._on_feature_snapshot(snapshot)
    trades = revived.store.list_trades(run_id)
    assert len(trades) == 2
    closing = trades[-1]
    assert closing.side == "sell"
    assert closing.realized_pnl is not None
    # Bought @ effective 0.92 * 1.002; the sell closes the long (realizing pnl
    # on exactly the long size) at effective 1.10 * 0.998, fee-inclusive.
    entry_eff = 0.92 * 1.002
    exit_eff = 1.10 * 0.998
    closed_size = min(closing.size, long_size)
    assert closing.realized_pnl == pytest.approx(
        (exit_eff - entry_eff) * closed_size, rel=1e-6
    )


# --------------------------------------------------------------------- metrics


def seed_run(store, run_id="r1", initial=10_000.0, cash=10_000.0, config=None):
    store.save_run(
        SimRunRecord(
            run_id=run_id,
            name="metrics",
            strategy_id="signal_fusion",
            universe=["m1"],
            initial_capital=initial,
            cash=cash,
            status="running",
            config=config or {},
            created_at=datetime.now(UTC).isoformat(),
        )
    )


def test_metrics_on_hand_built_trades(tmp_path):
    store = make_store(tmp_path)
    seed_run(store)

    def trade(instrument, realized, side="sell"):
        store.append_trade(
            "r1",
            instrument_id=instrument,
            side=side,
            size=10.0,
            price=1.0,
            fee=0.02,
            slippage=0.0,
            realized_pnl=realized,
        )

    trade("m1", None, side="buy")  # open (not closed) trade
    trade("m1", 10.0)
    trade("m1", 20.0)
    trade("m2", -15.0)

    base = datetime(2026, 7, 1, tzinfo=UTC)
    for offset, equity in enumerate([10_000.0, 10_100.0, 9_900.0, 10_150.0]):
        store.append_equity_point(
            "r1",
            equity=equity,
            cash=equity,
            gross_exposure=0.0,
            ts=(base + timedelta(minutes=5 * offset)).isoformat(),
        )

    metrics = sim_metrics.compute_run_metrics(store, "r1")
    assert metrics["trade_count"] == 4
    assert metrics["closed_trade_count"] == 3
    assert metrics["win_rate"] == pytest.approx(2 / 3)
    assert metrics["profit_factor"] == pytest.approx(30.0 / 15.0)
    assert metrics["avg_win"] == pytest.approx(15.0)
    assert metrics["avg_loss"] == pytest.approx(-15.0)
    assert metrics["realized_pnl"] == pytest.approx(15.0)
    assert metrics["total_fees"] == pytest.approx(0.08)
    assert metrics["total_slippage"] == pytest.approx(0.0)
    assert metrics["total_explicit_cost"] == pytest.approx(0.08)
    assert metrics["max_drawdown"] == pytest.approx((10_100.0 - 9_900.0) / 10_100.0)
    assert metrics["total_return"] == pytest.approx(10_150.0 / 10_000.0 - 1.0)
    assert metrics["sharpe"] is not None
    assert metrics["per_instrument"]["m1"]["win_rate"] == pytest.approx(1.0)
    assert metrics["per_instrument"]["m2"]["realized_pnl"] == pytest.approx(-15.0)


def test_metrics_empty_sample_is_none_not_zero(tmp_path):
    store = make_store(tmp_path)
    seed_run(store)
    metrics = sim_metrics.compute_run_metrics(store, "r1")
    assert metrics["win_rate"] is None
    assert metrics["profit_factor"] is None
    assert metrics["sharpe"] is None
    assert metrics["trade_count"] == 0
    with pytest.raises(KeyError):
        sim_metrics.compute_run_metrics(store, "missing")


def test_downsample_equity_curve_caps_points():
    class Point:
        def __init__(self, i):
            self.ts = f"t{i:05d}"
            self.equity = float(i)

    points = [Point(i) for i in range(2000)]
    sampled = downsample_equity_curve(points, max_points=500)
    assert len(sampled) <= 500
    assert sampled[0]["ts"] == "t00000"
    assert sampled[-1]["ts"] == "t01999"
    # Small curves pass through untouched.
    assert downsample_equity_curve(points[:10], max_points=500) == [
        {"ts": p.ts, "equity": p.equity} for p in points[:10]
    ]


# -------------------------------------------------------------------- feedback


def closed_fusion_trades(store, run_id, count, pnl=1.0, signals=("rsi",)):
    store.append_trade(
        run_id,
        instrument_id="m1",
        side="buy",
        size=10.0,
        price=1.0,
        fee=0.0,
        slippage=0.0,
        signal_meta={"signals": list(signals)},
        realized_pnl=None,
    )
    for _ in range(count):
        store.append_trade(
            run_id,
            instrument_id="m1",
            side="sell",
            size=10.0,
            price=1.0,
            fee=0.0,
            slippage=0.0,
            signal_meta={"signals": list(signals)},
            realized_pnl=pnl,
        )


def test_feedback_refuses_below_min_sample(tmp_path):
    store = make_store(tmp_path)
    seed_run(store)
    closed_fusion_trades(store, "r1", count=5)
    fusion = SignalFusion()
    before = dict(fusion.weights)

    result = sim_metrics.apply_feedback(store, "r1", fusion, min_closed_trades=20)
    assert result["applied"] is False
    assert "insufficient closed trades" in result["reason"]
    assert fusion.weights == before  # weights untouched


def test_feedback_caps_weight_change_and_audits(tmp_path):
    store = make_store(tmp_path)
    seed_run(store)
    closed_fusion_trades(store, "r1", count=25, pnl=2.0, signals=("rsi",))
    fusion = SignalFusion()
    before = dict(fusion.weights)

    result = sim_metrics.apply_feedback(
        store, "r1", fusion, min_closed_trades=20, max_weight_delta=0.05
    )
    assert result["applied"] is True
    assert result["closed_trades_used"] == 25

    after = fusion.weights
    assert sum(after.values()) == pytest.approx(1.0)
    for name in before:
        assert abs(after[name] - before[name]) <= 0.05 + 1e-6
    # rsi got all the wins, so its weight moved up (but capped).
    assert after["rsi"] > before["rsi"]

    # Every application is audited with before/after weights.
    with fact_store.connect(store.db_path) as connection:
        rows = connection.execute(
            "SELECT payload_json FROM audit_events WHERE event_type = 'sim.feedback.applied'"
        ).fetchall()
    assert len(rows) == 1
    payload = json.loads(rows[0]["payload_json"])
    assert payload["weights_before"] == pytest.approx(before)
    assert payload["weights_after"]["rsi"] == pytest.approx(after["rsi"])

    # Trades are consumed once: a second application finds no new closed trades.
    second = sim_metrics.apply_feedback(store, "r1", fusion, min_closed_trades=20)
    assert second["applied"] is False
    assert second["closed_trades_available"] == 0


def test_feedback_requires_fusion_mechanism(tmp_path):
    store = make_store(tmp_path)
    seed_run(store)
    result = sim_metrics.apply_feedback(store, "r1", None, min_closed_trades=1)
    assert result["applied"] is False
    assert "does not support" in result["reason"]


@pytest.mark.asyncio
async def test_service_apply_feedback_uses_run_guardrail_config(tmp_path):
    service = make_service(tmp_path)
    run = await service.create_run(
        name="feedback",
        strategy_id="signal_fusion",
        universe=["m1"],
        initial_capital=10_000.0,
        config={"feedback_min_closed_trades": 3},
    )
    run_id = run["run_id"]
    closed_fusion_trades(service.store, run_id, count=2)
    result = await service.apply_feedback(run_id)
    assert result["applied"] is False  # 2 < 3

    closed_fusion_trades(service.store, run_id, count=3)
    result = await service.apply_feedback(run_id)
    assert result["applied"] is True
    assert result["weight_deltas"]

    with pytest.raises(UnknownRunError):
        await service.apply_feedback("sim_missing")
