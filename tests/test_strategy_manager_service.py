import pytest

from services.strategy_manager import StrategyManagerService


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
