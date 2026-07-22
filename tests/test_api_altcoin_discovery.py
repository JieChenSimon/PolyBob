from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

import apps.api.main as api
from libs.crypto.discovery.models import (
    DiscoveryCandidate,
    DiscoverySnapshot,
    Evidence,
    HorizonScore,
    ProviderHealth,
    TradePlan,
)


class SnapshotService:
    def __init__(self, snapshot: DiscoverySnapshot):
        self.snapshot = snapshot

    async def get_snapshot(self):
        return self.snapshot

    def get_status(self):
        return {
            "status": self.snapshot.status,
            "source_health": self.snapshot.source_health,
        }

    async def get_detail(self, asset_id: str):
        return next(
            (candidate for candidate in self.snapshot.candidates if candidate.asset_id == asset_id),
            None,
        )


@pytest.mark.asyncio
async def test_list_route_returns_503_for_unavailable_core_sources(monkeypatch):
    snapshot = DiscoverySnapshot(
        status="unavailable",
        observed_at=datetime.now(timezone.utc),
        candidates=[],
        source_health={
            "binance_futures": ProviderHealth(
                status="unavailable",
                provider="binance_futures",
                failure_category="connect_timeout",
            )
        },
    )
    monkeypatch.setattr(api, "altcoin_discovery", SnapshotService(snapshot))

    response = await api.get_altcoin_discovery()

    assert response.status_code == 503
    payload = json.loads(response.body)
    assert payload["status"] == "unavailable"
    assert payload["candidates"] == []
    assert payload["source_health"]["binance_futures"]["failure_category"] == "connect_timeout"


@pytest.mark.asyncio
async def test_status_route_exposes_provider_health(monkeypatch):
    snapshot = DiscoverySnapshot(
        status="degraded",
        source_health={
            "binance_alpha": ProviderHealth(status="ok", provider="binance_alpha")
        },
    )
    monkeypatch.setattr(api, "altcoin_discovery", SnapshotService(snapshot))

    payload = await api.get_altcoin_discovery_status()

    assert payload["status"] == "degraded"
    assert payload["source_health"]["binance_alpha"].status == "ok"


@pytest.mark.asyncio
async def test_list_route_returns_lightweight_summaries_and_keeps_detail_on_demand(monkeypatch):
    candidate = DiscoveryCandidate(
        asset_id="56:0xabc",
        chain_id="56",
        contract_address="0xabc",
        symbol="TEST",
        futures_symbol="TESTUSDT",
        mapping_status="unique",
        pump_potential={
            "30d": HorizonScore(
                value=80,
                coverage=0.8,
                contributions={"floor": 20, "accumulation": 30, "control": 10, "washout": 5},
            )
        },
        cashout_risk={
            "30d": HorizonScore(value=20, coverage=0.8, contributions={"audit": 5})
        },
        evidence=[
            Evidence(name="floor", value=0.8, status="observed", provider="binance_alpha")
        ],
        trade_plans={"30d": TradePlan(eligible=False, entry_low=1, entry_high=1.1)},
    )
    snapshot = DiscoverySnapshot(status="ok", candidates=[candidate])
    monkeypatch.setattr(api, "altcoin_discovery", SnapshotService(snapshot))

    payload = await api.get_altcoin_discovery()
    detail = await api.get_altcoin_discovery_detail("56:0xabc")

    summary = payload["candidates"][0]
    assert summary["evidence"] == []
    assert summary["trade_plans"] == {}
    assert summary["pump_potential"]["30d"]["contributions"] == {
        "accumulation": 30,
        "floor": 20,
        "control": 10,
    }
    assert summary["cashout_risk"]["30d"]["contributions"] == {"audit": 5}
    assert detail.evidence[0].name == "floor"
    assert detail.trade_plans["30d"].entry_low == 1
