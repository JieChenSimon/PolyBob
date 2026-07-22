from __future__ import annotations

from copy import deepcopy
import asyncio

import pytest

from libs.crypto.discovery.models import (
    AlphaToken,
    Evidence,
    FuturesContract,
    FuturesMarketSignals,
    MarketCandle,
)
from libs.crypto.discovery.service import AltcoinDiscoveryService
from libs.crypto.discovery.service import _base_risk_evidence
from libs.crypto.discovery.service import _failure_health
import httpx


class FakeAlphaProvider:
    def __init__(self, *, failed_chains: set[str] | None = None):
        self.failed_chains = failed_chains or set()
        self.tokens = {
            "56": [
                AlphaToken(
                    chain_id="56",
                    contract_address="0xvelvet",
                    symbol="VELVET",
                    is_alpha=True,
                    price=1.46,
                    market_cap=120_000_000.0,
                    liquidity=2_000_000.0,
                    volume_24h=5_000_000.0,
                    volume_24h_buy=3_000_000.0,
                    volume_24h_sell=2_000_000.0,
                    holders_top10_percent=82.0,
                    audit_risk_level=1,
                    raw={"devHoldingPercent": "35", "insiderHoldingPercent": "10"},
                )
            ],
            "CT_501": [
                AlphaToken(
                    chain_id="CT_501",
                    contract_address="sol-mew",
                    symbol="MEW",
                    is_alpha=True,
                    price=0.004,
                    market_cap=350_000_000.0,
                    liquidity=3_000_000.0,
                    volume_24h=2_000_000.0,
                    volume_24h_buy=1_100_000.0,
                    volume_24h_sell=900_000.0,
                    holders_top10_percent=55.0,
                    audit_risk_level=1,
                )
            ],
        }

    async def list_alpha_tokens(self, chain_id: str):
        if chain_id in self.failed_chains:
            raise TimeoutError(f"{chain_id} connect timeout")
        return deepcopy(self.tokens.get(chain_id, []))

    async def list_smart_money(self, chain_id: str, *, period: str = "24h"):
        if chain_id == "56":
            return Evidence(
                name="smart_money_inflow",
                value=[{"ca": "0xvelvet", "inflow": 250_000.0}],
                status="observed",
                provider="binance_web3",
            )
        return Evidence(
            name="smart_money_inflow",
            value=None,
            status="unsupported",
            provider="binance_web3",
        )

    async def klines(self, token: AlphaToken, *, interval: str = "1d", limit: int = 180):
        closes = [1.0, 1.1, 1.3, 1.8, 2.6, 3.2, 2.7, 2.2, 1.8, 1.55, 1.45, 1.42, 1.44, 1.46, 1.45, 1.47, 1.46, 1.48, 1.47, 1.46]
        return [
            MarketCandle(
                open_time_ms=index * 86_400_000,
                open=close,
                high=close + 0.08,
                low=close - 0.08,
                close=close,
                volume=1000.0 if index < 10 else 300.0,
            )
            for index, close in enumerate(closes)
        ]


class FakeFuturesProvider:
    def __init__(self, *, fail_core: bool = False):
        self.fail_core = fail_core

    async def list_perpetuals(self):
        if self.fail_core:
            raise TimeoutError("futures unavailable")
        return [
            FuturesContract(symbol="VELVETUSDT", base_asset="VELVET"),
            FuturesContract(symbol="MEWUSDT", base_asset="MEW"),
        ]

    async def klines(self, symbol: str, *, interval: str = "1d", limit: int = 180):
        raise AssertionError("Discovery history must use Binance Alpha klines")

    async def market_signals(self, symbol: str):
        return FuturesMarketSignals(
            symbol=symbol,
            price=1.46,
            volume_24h_usd=5_000_000.0,
            funding_rate=-0.001,
            open_interest_change=0.25,
            long_short_ratio=0.8,
        )


class PriceOnlyFuturesProvider(FakeFuturesProvider):
    async def market_signals(self, symbol: str):
        return FuturesMarketSignals(symbol=symbol, price=1.46)


class BlockingRefreshFuturesProvider(FakeFuturesProvider):
    def __init__(self):
        super().__init__()
        self.calls = 0
        self.release = asyncio.Event()

    async def list_perpetuals(self):
        self.calls += 1
        if self.calls > 1:
            await self.release.wait()
        return await super().list_perpetuals()


@pytest.mark.asyncio
async def test_one_chain_failure_keeps_other_chains_visible():
    service = AltcoinDiscoveryService(
        alpha_provider=FakeAlphaProvider(failed_chains={"8453"}),
        futures_provider=FakeFuturesProvider(),
        chain_ids=("1", "56", "8453", "CT_501"),
    )

    snapshot = await service.refresh()

    assert snapshot.status == "degraded"
    assert snapshot.chain_health["8453"].status == "unavailable"
    assert any(item.chain_id == "56" for item in snapshot.candidates)
    assert any(item.chain_id == "CT_501" for item in snapshot.candidates)


@pytest.mark.asyncio
async def test_refresh_builds_three_horizon_dual_scores_from_observed_fields():
    service = AltcoinDiscoveryService(
        alpha_provider=FakeAlphaProvider(),
        futures_provider=FakeFuturesProvider(),
        chain_ids=("56",),
    )

    snapshot = await service.refresh()
    candidate = snapshot.candidates[0]

    assert set(candidate.pump_potential) == {"7d", "30d", "90d"}
    assert set(candidate.cashout_risk) == {"7d", "30d", "90d"}
    assert candidate.pump_potential["30d"].value is not None
    assert candidate.cashout_risk["30d"].value is not None
    assert candidate.chip_concentration_percent == 82.0
    assert any(item.name == "control" for item in candidate.evidence)
    assert any(item.name == "dev_concentration" for item in candidate.evidence)


@pytest.mark.asyncio
async def test_price_only_futures_capability_does_not_make_every_candidate_data_insufficient():
    alpha = FakeAlphaProvider()
    alpha.tokens["56"][0] = alpha.tokens["56"][0].model_copy(
        update={
            "raw": {},
            "audit_risk_level": 1,
            "liquidity": 2_000_000.0,
            "volume_24h": 5_000_000.0,
            "volume_24h_buy": 3_000_000.0,
            "volume_24h_sell": 2_000_000.0,
        }
    )
    service = AltcoinDiscoveryService(
        alpha_provider=alpha,
        futures_provider=PriceOnlyFuturesProvider(),
        chain_ids=("56",),
    )

    snapshot = await service.refresh()
    candidate = snapshot.candidates[0]

    assert candidate.coverage >= service.min_coverage
    assert candidate.status != "data_insufficient"
    assert "COVERAGE_BELOW_MINIMUM" not in candidate.trade_plans["30d"].vetoes
    assert any(item.name == "futures_squeeze" and item.status == "unsupported" for item in candidate.evidence)
    assert any(item.name == "unlock_risk" and item.status == "unsupported" for item in candidate.evidence)


@pytest.mark.asyncio
async def test_last_successful_snapshot_is_preserved_when_core_refresh_fails():
    futures = FakeFuturesProvider()
    service = AltcoinDiscoveryService(
        alpha_provider=FakeAlphaProvider(),
        futures_provider=futures,
        chain_ids=("56",),
    )
    first = await service.refresh()
    futures.fail_core = True

    second = await service.refresh()

    assert first.candidates
    assert second.candidates
    assert second.status == "degraded"
    assert second.stale is True
    assert second.source_health["binance_futures"].status == "unavailable"


@pytest.mark.asyncio
async def test_initial_core_failure_returns_unavailable_not_successful_empty_list():
    service = AltcoinDiscoveryService(
        alpha_provider=FakeAlphaProvider(),
        futures_provider=FakeFuturesProvider(fail_core=True),
        chain_ids=("56",),
    )

    snapshot = await service.refresh()

    assert snapshot.status == "unavailable"
    assert snapshot.candidates == []
    assert service.get_status()["source_health"]["binance_futures"].status == "unavailable"


@pytest.mark.asyncio
async def test_empty_alpha_universe_is_unavailable_not_successful_empty_list():
    alpha = FakeAlphaProvider()
    alpha.tokens = {}
    service = AltcoinDiscoveryService(
        alpha_provider=alpha,
        futures_provider=FakeFuturesProvider(),
        chain_ids=("1", "56", "8453", "CT_501"),
    )

    snapshot = await service.refresh()

    assert snapshot.status == "unavailable"
    assert snapshot.candidates == []
    assert snapshot.source_health["binance_alpha"].status == "unavailable"
    assert snapshot.source_health["binance_alpha"].failure_category == "empty_payload"


def test_single_positive_smart_money_flow_is_not_ranked_as_maximum_adverse_flow():
    from libs.crypto.discovery.service import _percentiles

    assert _percentiles({"56:0xvelvet": 250_000.0}) == {"56:0xvelvet": 1.0}
    assert _percentiles({"56:0xvelvet": -1.0}) == {"56:0xvelvet": 0.0}


def test_missing_audit_fields_do_not_create_observed_zero_risk():
    token = AlphaToken(
        chain_id="56",
        contract_address="0xmissing",
        symbol="MISSING",
        is_alpha=True,
    )

    evidence = _base_risk_evidence(token, None, None)

    assert all(item.name != "audit_risk" for item in evidence)


@pytest.mark.asyncio
async def test_expired_successful_snapshot_returns_immediately_while_refresh_runs():
    futures = BlockingRefreshFuturesProvider()
    service = AltcoinDiscoveryService(
        alpha_provider=FakeAlphaProvider(),
        futures_provider=futures,
        chain_ids=("56",),
        refresh_ttl_seconds=0,
    )
    first = await service.refresh()

    returned = await asyncio.wait_for(service.get_snapshot(), timeout=0.05)

    assert returned is first
    assert service._background_task is not None
    assert not service._background_task.done()
    futures.release.set()
    await service._background_task


def test_provider_health_preserves_http_status_and_endpoint():
    request = httpx.Request("GET", "https://fapi.binance.com/fapi/v1/exchangeInfo")
    response = httpx.Response(451, request=request)
    error = httpx.HTTPStatusError("restricted", request=request, response=response)

    health = _failure_health("binance_futures", error)

    assert health.failure_category == "http_451"
    assert health.retryable is False
    assert health.endpoint == "https://fapi.binance.com/fapi/v1/exchangeInfo"
