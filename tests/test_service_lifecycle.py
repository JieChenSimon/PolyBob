import asyncio

import pytest

from libs.events import EventBus
from modules.feature_engine import service as feature_module
from modules.market_discovery import service as discovery_module


@pytest.mark.asyncio
async def test_feature_engine_stop_cancels_snapshot_task_and_subscriptions(monkeypatch):
    bus = EventBus()
    monkeypatch.setattr(feature_module, "get_event_bus", lambda: bus)
    service = feature_module.FeatureEngineService()
    await service.start()
    assert service._snapshot_task is not None
    await service.stop()
    assert service._snapshot_task is None
    assert all(all(depth == 0 for depth in depths) for depths in bus.stats()["queue_depths"].values())


@pytest.mark.asyncio
async def test_market_discovery_stop_cancels_scan_task(monkeypatch):
    service = discovery_module.MarketDiscoveryService()
    monkeypatch.setattr(service, "_scan_markets", _never_scan)
    await service.start()
    assert service._scan_task is not None
    await service.stop()
    assert service._scan_task is None


async def _never_scan():
    await asyncio.sleep(60)
