import pytest

from modules.strategy_manager import StrategyManagerService


def test_strategy_manager_loads_templates():
    manager = StrategyManagerService()
    manager._load_templates()

    templates = manager.list_templates()
    strategy_ids = {template["strategy_id"] for template in templates}

    assert "cross_market_dislocation_v1" in strategy_ids
    assert "spread_reversion_v1" in strategy_ids
    assert "ai_enhanced_prediction_v1" in strategy_ids
    assert "spread_arbitrage_v1" in strategy_ids


@pytest.mark.asyncio
async def test_strategy_manager_seeds_and_runs_default_instance():
    manager = StrategyManagerService()
    await manager.start()

    instances = manager.list_instances()
    default_ids = {instance["instance_id"] for instance in instances}
    assert "cross_market_dislocation_v1:default" in default_ids

    started = await manager.start_instance("cross_market_dislocation_v1:default")
    assert started["status"] == "running"

    stopped = await manager.stop_instance("cross_market_dislocation_v1:default")
    assert stopped["status"] == "stopped"

    await manager.stop()


@pytest.mark.asyncio
async def test_strategy_manager_create_and_delete_instance():
    manager = StrategyManagerService()
    await manager.start()

    created = await manager.create_instance(
        strategy_id="spread_reversion_v1",
        name="Spread Paper",
        config={"spread_threshold_bps": 220.0},
    )

    assert created["name"] == "Spread Paper"
    assert created["config"]["spread_threshold_bps"] == 220.0

    await manager.delete_instance(created["instance_id"])
    assert manager.get_instance(created["instance_id"]) is None

    await manager.stop()


@pytest.mark.asyncio
async def test_strategy_instance_survives_manager_restart(tmp_path):
    db_path = tmp_path / "strategy.sqlite3"
    first = StrategyManagerService(db_path=db_path)
    await first.start()
    created = await first.create_instance(
        strategy_id="spread_reversion_v1",
        name="Durable Paper",
        config={"spread_threshold_bps": 220.0},
    )
    await first.stop()

    second = StrategyManagerService(db_path=db_path)
    await second.start()
    restored = second.get_instance(created["instance_id"])
    assert restored is not None
    assert restored.status == "stopped"
    assert restored.config["spread_threshold_bps"] == 220.0
    await second.stop()


@pytest.mark.asyncio
async def test_scanning_strategy_start_returns_without_blocking(tmp_path):
    manager = StrategyManagerService(db_path=tmp_path / "strategy.sqlite3")
    await manager.start()
    created = await manager.create_instance(strategy_id="altcoin_retail_crowding")

    started = await manager.start_instance(created["instance_id"])
    assert started["status"] == "running"
    assert created["instance_id"] in manager._tasks

    stopped = await manager.stop_instance(created["instance_id"])
    assert stopped["status"] == "stopped"
    assert created["instance_id"] not in manager._tasks
    await manager.stop()


@pytest.mark.asyncio
async def test_scanning_strategy_failure_is_reflected_in_instance(tmp_path):
    manager = StrategyManagerService(db_path=tmp_path / "strategy.sqlite3")
    await manager.start()

    class FailingStrategy:
        async def start(self):
            await asyncio.sleep(0)
            raise RuntimeError("provider unavailable")

        async def stop(self):
            return None

    import asyncio
    manager._factories["altcoin_retail_crowding"] = lambda config, deps: FailingStrategy()
    created = await manager.create_instance(strategy_id="altcoin_retail_crowding")
    await manager.start_instance(created["instance_id"])
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    failed = manager.get_instance(created["instance_id"])
    assert failed is not None
    assert failed.status == "error"
    assert failed.error == "provider unavailable"
    await manager.stop()
