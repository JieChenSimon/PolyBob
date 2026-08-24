from datetime import UTC, datetime, timedelta

import pytest

from libs.db.simulation_store import SimulationStore
from modules.simulation.service import SimulationService
from modules.simulation.sources import SimSignal


class _OneShotSource:
    topics = ("features.snapshots",)

    def __init__(self, config):
        self.side = config.get("side", "buy")
        self.sent = False

    async def on_snapshot(self, topic, snapshot):
        if self.sent:
            return []
        self.sent = True
        return [SimSignal(
            instrument_id=snapshot["market_id"], side=self.side, confidence=1.0,
            mid=snapshot["mid_price"], timestamp=snapshot["timestamp"],
        )]


def _snapshot(ts, *, rate=None, price=100.0):
    result = {"market_id": "BTC", "mid_price": price, "timestamp": ts}
    if rate is not None:
        result["funding_rate"] = rate
    return result


@pytest.mark.asyncio
async def test_funding_cashflow_direction_and_idempotence(tmp_path):
    service = SimulationService(
        tmp_path / "sim.sqlite3", equity_poll_seconds=3600,
        source_factories={"funding_test": lambda config, _db: _OneShotSource(config)},
    )
    await service.start()
    run = await service.create_run(
        name="funding", strategy_id="funding_test", universe=["BTC"],
        initial_capital=10_000, config={
            "funding_enabled": True, "position_fraction": 0.1,
            "cooldown_seconds": 0, "max_staleness_seconds": 86_400 * 3,
            "equity_interval_minutes": 1440,
        },
    )
    await service.start_run(run["run_id"])
    start = datetime.now(UTC)
    await service._dispatch("features.snapshots", _snapshot(start, rate=0.01))
    # Same timestamp must not charge twice.
    await service._dispatch("features.snapshots", _snapshot(start, rate=0.01))
    await service._dispatch("features.snapshots", _snapshot(start + timedelta(days=1), rate=0.01))
    await service.stop_run(run["run_id"])
    await service.stop()

    records = SimulationStore(tmp_path / "sim.sqlite3").list_cashflows(run["run_id"])
    assert len(records) == 1
    assert records[0].amount < 0  # positive funding: long pays
    assert records[0].notional > 0


@pytest.mark.asyncio
async def test_short_receives_positive_funding(tmp_path):
    service = SimulationService(
        tmp_path / "sim.sqlite3", equity_poll_seconds=3600,
        source_factories={"funding_test": lambda config, _db: _OneShotSource(config)},
    )
    await service.start()
    run = await service.create_run(
        name="funding-short-2", strategy_id="funding_test", universe=["BTC"],
        initial_capital=10_000, config={
            "funding_enabled": True, "position_fraction": 0.1,
            "cooldown_seconds": 0, "max_staleness_seconds": 86_400 * 3,
            "side": "sell",
        },
    )
    await service.start_run(run["run_id"])
    start = datetime.now(UTC)
    await service._dispatch("features.snapshots", _snapshot(start, rate=0.01))
    await service._dispatch("features.snapshots", _snapshot(start + timedelta(days=1), rate=0.01))
    await service.stop_run(run["run_id"])
    await service.stop()
    records = SimulationStore(tmp_path / "sim.sqlite3").list_cashflows(run["run_id"])
    assert records and records[0].amount > 0


@pytest.mark.asyncio
async def test_funding_enabled_missing_rate_fails_closed(tmp_path):
    service = SimulationService(
        tmp_path / "sim.sqlite3", equity_poll_seconds=3600,
        source_factories={"funding_test": lambda config, _db: _OneShotSource(config)},
    )
    await service.start()
    run = await service.create_run(
        name="funding-missing", strategy_id="funding_test", universe=["BTC"],
        initial_capital=10_000, config={"funding_enabled": True, "max_staleness_seconds": 86400},
    )
    await service.start_run(run["run_id"])
    await service._dispatch("features.snapshots", _snapshot(datetime.now(UTC)))
    await service.stop_run(run["run_id"])
    await service.stop()
    store = SimulationStore(tmp_path / "sim.sqlite3")
    assert store.list_trades(run["run_id"]) == []
    assert store.list_cashflows(run["run_id"]) == []
