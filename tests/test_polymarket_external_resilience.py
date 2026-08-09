import asyncio
from datetime import datetime

import httpx
import pytest

from libs.polymarket.websocket import classify_websocket_error, should_log_reconnect_attempt
from libs.schemas import Market, MarketStatus
from modules.market_discovery.service import classify_market_scan_error
from modules.realtime_ingestor.service import RealtimeIngestorService


def test_market_scan_classifies_proxy_503_without_traceback_path():
    assert classify_market_scan_error(httpx.ProxyError("503 Service Unavailable")) == "proxy_503"


def test_websocket_reconnect_attempts_are_rate_limited():
    assert classify_websocket_error(Exception("proxy rejected connection: HTTP 503")) == "provider_or_proxy_503"
    assert [attempt for attempt in range(1, 12) if should_log_reconnect_attempt(attempt)] == [1, 2, 3, 5, 10]


@pytest.mark.asyncio
async def test_realtime_ingestor_defers_polymarket_websocket_until_asset_discovered(monkeypatch):
    service = RealtimeIngestorService()
    connect_calls = 0

    async def fake_connect():
        nonlocal connect_calls
        connect_calls += 1
        await asyncio.Event().wait()

    async def fake_fetch_snapshot(market_id, asset_id):
        return None

    monkeypatch.setattr(service.ws, "connect", fake_connect)
    monkeypatch.setattr(service, "_fetch_snapshot", fake_fetch_snapshot)

    await service.start()
    assert service._ws_task is None
    assert connect_calls == 0

    market = Market(
        market_id="condition-1",
        gamma_market_id="gamma-1",
        slug="test-market",
        question="Test market",
        status=MarketStatus.ACTIVE,
        clob_token_ids=["asset-1"],
        primary_asset_id="asset-1",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    await service._on_market_discovered(market)
    await asyncio.sleep(0)

    assert connect_calls == 1
    assert "asset-1" in service.subscribed_assets

    await service.stop()
