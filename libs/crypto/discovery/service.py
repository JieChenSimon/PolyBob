"""Concurrent orchestration for the real-data altcoin discovery workbench."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import math
import time
from typing import Any, Protocol

import httpx

from libs.networking import classify_network_error
from .models import (
    AlphaToken,
    DiscoveryCandidate,
    DiscoverySnapshot,
    Evidence,
    FuturesContract,
    FuturesMarketSignals,
    MarketCandle,
    ProviderHealth,
)
from .scoring import clamp, derive_market_features, score_candidate
from .trade_plan import build_trade_plan
from .universe import build_universe


class AlphaProvider(Protocol):
    async def list_alpha_tokens(self, chain_id: str) -> list[AlphaToken]: ...

    async def list_smart_money(self, chain_id: str, *, period: str = "24h") -> Evidence: ...

    async def klines(
        self, token: AlphaToken, *, interval: str = "1d", limit: int = 180
    ) -> list[MarketCandle]: ...


class FuturesProvider(Protocol):
    async def list_perpetuals(self) -> list[FuturesContract]: ...

    async def klines(
        self, symbol: str, *, interval: str = "1d", limit: int = 180
    ) -> list[MarketCandle]: ...

    async def market_signals(self, symbol: str) -> FuturesMarketSignals: ...


class AltcoinDiscoveryService:
    def __init__(
        self,
        *,
        alpha_provider: AlphaProvider,
        futures_provider: FuturesProvider,
        chain_ids: tuple[str, ...] = ("1", "56", "8453", "CT_501"),
        account_equity: float | None = None,
        min_coverage: float = 0.70,
        max_cashout_risk: float = 45.0,
        min_pump_potential: float = 70.0,
        min_liquidity_usd: float = 500_000.0,
        min_volume_24h_usd: float = 1_000_000.0,
        refresh_ttl_seconds: float = 60.0,
        max_concurrency: int = 8,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.alpha_provider = alpha_provider
        self.futures_provider = futures_provider
        self.chain_ids = chain_ids
        self.account_equity = account_equity
        self.min_coverage = min_coverage
        self.max_cashout_risk = max_cashout_risk
        self.min_pump_potential = min_pump_potential
        self.min_liquidity_usd = min_liquidity_usd
        self.min_volume_24h_usd = min_volume_24h_usd
        self.refresh_ttl_seconds = refresh_ttl_seconds
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._lock = asyncio.Lock()
        self._snapshot: DiscoverySnapshot | None = None
        self._last_refresh_monotonic = 0.0
        self._background_task: asyncio.Task[DiscoverySnapshot] | None = None
        self._http_client = http_client

    async def start(self) -> None:
        if self._background_task is None or self._background_task.done():
            self._background_task = asyncio.create_task(self.refresh())

    async def stop(self) -> None:
        if self._background_task and not self._background_task.done():
            self._background_task.cancel()
            try:
                await self._background_task
            except asyncio.CancelledError:
                pass
        if self._http_client is not None:
            await self._http_client.aclose()

    async def get_snapshot(self) -> DiscoverySnapshot:
        if self._snapshot is not None:
            if time.monotonic() - self._last_refresh_monotonic >= self.refresh_ttl_seconds:
                if self._background_task is None or self._background_task.done():
                    self._background_task = asyncio.create_task(self.refresh())
            return self._snapshot
        if self._background_task is not None and not self._background_task.done():
            return await self._background_task
        async with self._lock:
            if self._snapshot is not None:
                return self._snapshot
            return await self.refresh()

    async def refresh(self) -> DiscoverySnapshot:
        chain_results = await asyncio.gather(
            *(self.alpha_provider.list_alpha_tokens(chain_id) for chain_id in self.chain_ids),
            return_exceptions=True,
        )
        alpha_tokens: list[AlphaToken] = []
        chain_health: dict[str, ProviderHealth] = {}
        successful_chains: list[str] = []
        for chain_id, result in zip(self.chain_ids, chain_results):
            if isinstance(result, BaseException):
                chain_health[chain_id] = _failure_health(
                    f"binance_alpha:{chain_id}", result
                )
            else:
                successful_chains.append(chain_id)
                alpha_tokens.extend(result)
                chain_health[chain_id] = ProviderHealth(
                    status="ok",
                    provider=f"binance_alpha:{chain_id}",
                    message=f"{len(result)} Alpha tokens",
                    last_success_at=datetime.now(timezone.utc),
                )

        source_health: dict[str, ProviderHealth] = {
            "binance_alpha": ProviderHealth(
                status="ok" if len(successful_chains) == len(self.chain_ids) else "degraded",
                provider="binance_alpha",
                message=f"{len(alpha_tokens)} tokens across {len(successful_chains)} chains",
                last_success_at=datetime.now(timezone.utc) if successful_chains else None,
            )
        }

        if not alpha_tokens:
            source_health["binance_alpha"] = ProviderHealth(
                status="unavailable",
                provider="binance_alpha",
                message="Binance Alpha returned no tokens across all configured chains",
                last_failure_at=datetime.now(timezone.utc),
                failure_category="empty_payload",
                retryable=True,
            )
            return self._fallback_or_unavailable(source_health, chain_health)

        try:
            futures_contracts = await self.futures_provider.list_perpetuals()
            if not futures_contracts:
                raise ValueError("Binance Futures returned no live USDT perpetual contracts")
            futures_transport = getattr(self.futures_provider, "last_transport", "provider")
            source_health["binance_futures"] = ProviderHealth(
                status=(
                    "degraded"
                    if futures_transport == "websocket_api_inferred_perpetual"
                    else "ok"
                ),
                provider="binance_futures",
                message=(
                    f"{len(futures_contracts)} current USDT symbols via "
                    f"{futures_transport}"
                ),
                last_success_at=datetime.now(timezone.utc),
            )
        except Exception as exc:
            source_health["binance_futures"] = _failure_health("binance_futures", exc)
            return self._fallback_or_unavailable(source_health, chain_health)

        if not successful_chains:
            return self._fallback_or_unavailable(source_health, chain_health)

        universe = build_universe(alpha_tokens, futures_contracts)
        token_by_id = {token.asset_id: token for token in alpha_tokens}
        contract_by_symbol = {contract.symbol: contract for contract in futures_contracts}
        smart_money_percentiles = await self._smart_money_percentiles(successful_chains)
        eligible_asset_ids = {
            item.asset_id
            for item in universe.candidates
            if item.mapping_status == "unique" and not item.vetoes
        }
        cap_percentiles = _percentiles(
            {
                token.asset_id: token.market_cap
                for token in alpha_tokens
                if token.asset_id in eligible_asset_ids and token.market_cap is not None
            }
        )
        enriched = await asyncio.gather(
            *(
                self._enrich_candidate(
                    candidate,
                    token_by_id[candidate.asset_id],
                    contract_by_symbol.get(candidate.futures_symbol or ""),
                    cap_percentiles.get(candidate.asset_id),
                    smart_money_percentiles.get(candidate.asset_id),
                )
                for candidate in universe.candidates
                if candidate.asset_id in eligible_asset_ids
            )
        )
        degraded = any(health.status != "ok" for health in chain_health.values()) or any(
            health.status != "ok" for health in source_health.values()
        )
        snapshot = DiscoverySnapshot(
            status="degraded" if degraded else "ok",
            candidates=sorted(enriched, key=_candidate_sort_key),
            source_health=source_health,
            chain_health=chain_health,
            universe_counts={**universe.counts, **{f"chain_{key}": value for key, value in universe.chain_counts.items()}},
        )
        self._snapshot = snapshot
        self._last_refresh_monotonic = time.monotonic()
        return snapshot

    def get_status(self) -> dict[str, Any]:
        if self._snapshot is None:
            return {"status": "unavailable", "source_health": {}, "chain_health": {}}
        return {
            "status": self._snapshot.status,
            "observed_at": self._snapshot.observed_at,
            "stale": self._snapshot.stale,
            "source_health": self._snapshot.source_health,
            "chain_health": self._snapshot.chain_health,
        }

    async def get_detail(self, asset_id: str) -> DiscoveryCandidate | None:
        snapshot = await self.get_snapshot()
        return next(
            (candidate for candidate in snapshot.candidates if candidate.asset_id == asset_id),
            None,
        )

    async def _smart_money_percentiles(
        self, successful_chains: list[str]
    ) -> dict[str, float]:
        results = await asyncio.gather(
            *(self.alpha_provider.list_smart_money(chain_id) for chain_id in successful_chains),
            return_exceptions=True,
        )
        flows: dict[str, float] = {}
        contract_to_asset: dict[str, str] = {}
        for chain_id, result in zip(successful_chains, results):
            if isinstance(result, BaseException) or result.status != "observed":
                continue
            if not isinstance(result.value, list):
                continue
            for row in result.value:
                if not isinstance(row, dict) or row.get("ca") is None:
                    continue
                asset_id = f"{chain_id}:{str(row['ca'])}"
                try:
                    if row.get("inflow") is None:
                        continue
                    flows[asset_id] = float(row["inflow"])
                    contract_to_asset[str(row["ca"]).casefold()] = asset_id
                except (TypeError, ValueError):
                    continue
        del contract_to_asset
        return _percentiles(flows)

    async def _enrich_candidate(
        self,
        candidate: DiscoveryCandidate,
        token: AlphaToken,
        contract: FuturesContract | None,
        market_cap_percentile: float | None,
        smart_money_percentile: float | None,
    ) -> DiscoveryCandidate:
        if candidate.mapping_status != "unique" or contract is None:
            return candidate

        candidate.chip_concentration_percent = token.holders_top10_percent

        async with self._semaphore:
            market_result, signals_result = await asyncio.gather(
                self.alpha_provider.klines(token, interval="1d", limit=180),
                self.futures_provider.market_signals(contract.symbol),
                return_exceptions=True,
            )
        candles = market_result if isinstance(market_result, list) else []
        signals = signals_result if isinstance(signals_result, FuturesMarketSignals) else None
        evidence = _base_risk_evidence(token, smart_money_percentile, signals)
        evidence.extend(_capability_evidence(signals))

        if candles:
            closes = [candle.close for candle in candles]
            volumes = [candle.volume for candle in candles]
            price_change = closes[-1] / closes[0] - 1.0 if closes[0] > 0 else 0.0
            features = derive_market_features(
                closes=closes,
                volumes=volumes,
                market_cap_percentile=market_cap_percentile,
                top10_holder_percent=token.holders_top10_percent,
                smart_money_inflow_percentile=smart_money_percentile,
                buy_volume=token.volume_24h_buy,
                sell_volume=token.volume_24h_sell,
                negative_funding_score=(
                    clamp(-signals.funding_rate / 0.005)
                    if signals is not None and signals.funding_rate is not None
                    else None
                ),
                open_interest_price_divergence=(
                    clamp(0.5 + (signals.open_interest_change - abs(price_change)) / 0.5)
                    if signals is not None and signals.open_interest_change is not None
                    else None
                ),
                short_crowding_score=(
                    clamp((1.0 - signals.long_short_ratio) / 0.5)
                    if signals is not None and signals.long_short_ratio is not None
                    else None
                ),
            )
            evidence.extend(
                Evidence(
                    name=name,
                    value=value,
                    status="observed",
                    provider="polybob_derived",
                    field="binance_alpha_klines",
                )
                for name, value in features.items()
            )

        scores = score_candidate(evidence)
        candidate.evidence = evidence
        candidate.pump_potential = scores.pump_potential
        candidate.cashout_risk = scores.cashout_risk
        candidate.coverage = scores.coverage
        candidate.confidence = scores.coverage
        if signals is not None:
            candidate.price = signals.price
            candidate.volume_24h = signals.volume_24h_usd or token.volume_24h

        if candles:
            for horizon in ("7d", "30d", "90d"):
                potential = candidate.pump_potential[horizon].value
                risk = candidate.cashout_risk[horizon].value
                if potential is None or risk is None:
                    continue
                candidate.trade_plans[horizon] = build_trade_plan(
                    closes=[candle.close for candle in candles],
                    highs=[candle.high for candle in candles],
                    lows=[candle.low for candle in candles],
                    volumes=[candle.volume for candle in candles],
                    pump_potential=potential,
                    cashout_risk=risk,
                    coverage=scores.coverage,
                    account_equity=self.account_equity,
                    liquidity_usd=token.liquidity,
                    volume_24h_usd=(
                        signals.volume_24h_usd
                        if signals and signals.volume_24h_usd is not None
                        else token.volume_24h
                    ),
                    quantity_step=contract.quantity_step,
                    min_pump_potential=self.min_pump_potential,
                    max_cashout_risk=self.max_cashout_risk,
                    min_coverage=self.min_coverage,
                    min_liquidity_usd=self.min_liquidity_usd,
                    min_volume_24h_usd=self.min_volume_24h_usd,
                )

        if candidate.vetoes:
            candidate.status = "vetoed"
        elif any(plan.eligible for plan in candidate.trade_plans.values()):
            candidate.status = "trade_eligible"
        elif candidate.coverage < self.min_coverage:
            candidate.status = "data_insufficient"
        else:
            candidate.status = "watch"
        return candidate

    def _fallback_or_unavailable(
        self,
        source_health: dict[str, ProviderHealth],
        chain_health: dict[str, ProviderHealth],
    ) -> DiscoverySnapshot:
        if self._snapshot is None:
            snapshot = DiscoverySnapshot(
                status="unavailable",
                candidates=[],
                source_health=source_health,
                chain_health=chain_health,
            )
            self._snapshot = snapshot
            self._last_refresh_monotonic = time.monotonic()
            return snapshot
        fallback = self._snapshot.model_copy(deep=True)
        fallback.status = "degraded"
        fallback.stale = True
        fallback.source_health.update(source_health)
        fallback.chain_health.update(chain_health)
        fallback.observed_at = datetime.now(timezone.utc)
        self._snapshot = fallback
        self._last_refresh_monotonic = time.monotonic()
        return fallback


def _base_risk_evidence(
    token: AlphaToken,
    smart_money_percentile: float | None,
    signals: FuturesMarketSignals | None,
) -> list[Evidence]:
    observed: list[Evidence] = []
    for field, name in (
        ("devHoldingPercent", "dev_concentration"),
        ("insiderHoldingPercent", "insider_concentration"),
    ):
        value = _optional_float(token.raw.get(field))
        if value is not None:
            observed.append(_number_evidence(name, clamp(value / 100.0), "binance_web3", field))

    if token.audit_risk_level is not None or token.audit_risk_codes:
        audit_risk = (
            clamp((token.audit_risk_level - 1) / 2.0)
            if token.audit_risk_level is not None
            else 0.0
        )
        if token.audit_risk_codes:
            audit_risk = max(audit_risk, 0.75)
        observed.append(
            _number_evidence("audit_risk", audit_risk, "binance_web3", "auditInfo")
        )

    if token.liquidity is not None:
        observed.append(
            _number_evidence(
                "liquidity_risk",
                1.0 - clamp(token.liquidity / 5_000_000.0),
                "binance_web3",
                "liquidity",
            )
        )
    if token.market_cap and token.volume_24h is not None:
        observed.append(
            _number_evidence(
                "abnormal_turnover",
                clamp((token.volume_24h / token.market_cap) / 2.0),
                "binance_web3",
                "volume24h/marketCap",
            )
        )
    if smart_money_percentile is not None:
        observed.append(
            _number_evidence(
                "adverse_flow",
                clamp(1.0 - smart_money_percentile),
                "binance_web3",
                "smart_money_inflow",
            )
        )
    if signals is not None and signals.long_short_ratio is not None:
        observed.append(
            _number_evidence(
                "crowded_longs",
                clamp((signals.long_short_ratio - 1.0) / 1.5),
                "binance_futures",
                "longShortRatio",
            )
        )
    return observed


def _capability_evidence(signals: FuturesMarketSignals | None) -> list[Evidence]:
    evidence: list[Evidence] = [
        Evidence(
            name="unlock_risk",
            status="unsupported",
            provider="polybob_capability",
            field="token_unlock_schedule",
            detail="No free unlock schedule provider is configured; this gate is excluded from applicable coverage.",
        )
    ]
    if (
        signals is None
        or signals.funding_rate is None
        or signals.open_interest_change is None
        or signals.long_short_ratio is None
    ):
        evidence.append(
            Evidence(
                name="futures_squeeze",
                status="unsupported",
                provider="binance_futures",
                field="funding/openInterest/longShortRatio",
                detail="Current futures transport provides price but not the full squeeze inputs.",
            )
        )
    if signals is None or signals.long_short_ratio is None:
        evidence.append(
            Evidence(
                name="crowded_longs",
                status="unsupported",
                provider="binance_futures",
                field="longShortRatio",
                detail="Current futures transport does not expose global long/short positioning.",
            )
        )
    return evidence


def _number_evidence(name: str, value: float, provider: str, field: str) -> Evidence:
    return Evidence(
        name=name,
        value=value,
        status="observed",
        provider=provider,
        field=field,
    )


def _optional_float(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _percentiles(values: dict[str, float | None]) -> dict[str, float]:
    valid = sorted(
        (float(value), key)
        for key, value in values.items()
        if value is not None and math.isfinite(float(value))
    )
    if not valid:
        return {}
    if len(valid) == 1:
        return {valid[0][1]: 1.0 if valid[0][0] > 0 else 0.0}
    ranks: dict[float, float] = {}
    for value in {item[0] for item in valid}:
        positions = [index for index, item in enumerate(valid) if item[0] == value]
        ranks[value] = (positions[0] + positions[-1]) / 2 / (len(valid) - 1)
    return {key: ranks[value] for value, key in valid}


def _failure_health(provider: str, error: BaseException) -> ProviderHealth:
    endpoint = None
    if isinstance(error, httpx.HTTPStatusError):
        endpoint = str(error.request.url)
    if isinstance(error, (TimeoutError, asyncio.TimeoutError)):
        category = "connect_timeout"
        retryable = True
        detail = str(error)
    elif isinstance(error, Exception):
        failure = classify_network_error(error)
        category = failure.category
        retryable = failure.retryable
        detail = failure.detail
    else:
        category = type(error).__name__
        retryable = False
        detail = str(error)
    return ProviderHealth(
        status="unavailable",
        provider=provider,
        message=detail,
        endpoint=endpoint,
        last_failure_at=datetime.now(timezone.utc),
        failure_category=category,
        retryable=retryable,
    )


def _candidate_sort_key(candidate: DiscoveryCandidate) -> tuple[int, float, str]:
    status_order = {"trade_eligible": 0, "watch": 1, "data_insufficient": 2, "vetoed": 3}
    score = candidate.pump_potential.get("30d")
    value = score.value if score and score.value is not None else -1.0
    return status_order[candidate.status], -value, candidate.symbol.casefold()
