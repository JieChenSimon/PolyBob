"""Typed contracts for altcoin discovery observations and decisions."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AlphaToken(BaseModel):
    chain_id: str
    contract_address: str
    symbol: str
    alpha_id: str | None = None
    name: str | None = None
    decimals: int | None = None
    creator_address: str | None = None
    is_alpha: bool = False
    blacklisted: bool = False
    price: float | None = None
    market_cap: float | None = None
    liquidity: float | None = None
    volume_24h: float | None = None
    volume_24h_buy: float | None = None
    volume_24h_sell: float | None = None
    holders: int | None = None
    holders_top10_percent: float | None = None
    launch_time_ms: int | None = None
    audit_risk_level: int | None = None
    audit_risk_codes: list[str] = Field(default_factory=list)
    token_tags: dict[str, Any] = Field(default_factory=dict)
    raw: dict[str, Any] = Field(default_factory=dict, exclude=True)
    observed_at: datetime = Field(default_factory=utc_now)

    @property
    def asset_id(self) -> str:
        return f"{self.chain_id}:{self.contract_address}"


class FuturesContract(BaseModel):
    symbol: str
    base_asset: str
    price: float | None = None
    quote_asset: str = "USDT"
    status: str = "TRADING"
    contract_type: str = "PERPETUAL"
    price_precision: int | None = None
    quantity_precision: int | None = None
    quantity_step: float | None = None
    observed_at: datetime = Field(default_factory=utc_now)


class MarketCandle(BaseModel):
    open_time_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_time_ms: int | None = None
    trade_count: int | None = None


class FuturesMarketSignals(BaseModel):
    symbol: str
    price: float
    volume_24h_usd: float | None = None
    funding_rate: float | None = None
    open_interest_change: float | None = None
    long_short_ratio: float | None = None
    observed_at: datetime = Field(default_factory=utc_now)


EvidenceStatus = Literal["observed", "unsupported", "unavailable", "stale"]


class Evidence(BaseModel):
    name: str
    value: Any = None
    status: EvidenceStatus
    provider: str
    field: str | None = None
    weight: float = 1.0
    confidence: float = 1.0
    observed_at: datetime = Field(default_factory=utc_now)
    received_at: datetime = Field(default_factory=utc_now)
    block_number: int | None = None
    detail: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProviderHealth(BaseModel):
    status: Literal["ok", "degraded", "unavailable", "unsupported", "stale"]
    provider: str
    message: str | None = None
    endpoint: str | None = None
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    latency_ms: float | None = None
    failure_category: str | None = None
    retryable: bool | None = None


class HorizonScore(BaseModel):
    value: float | None = None
    coverage: float = 0.0
    contributions: dict[str, float] = Field(default_factory=dict)


class PositionSize(BaseModel):
    risk_fraction: float
    quantity: float | None = None
    notional_usd: float | None = None
    max_loss_usd: float | None = None


class TradePlan(BaseModel):
    eligible: bool = False
    entry_low: float | None = None
    entry_high: float | None = None
    stop: float | None = None
    target_1: float | None = None
    target_2: float | None = None
    reward_risk: float | None = None
    vetoes: list[str] = Field(default_factory=list)
    position_sizes: dict[str, PositionSize] = Field(default_factory=dict)


class DiscoveryCandidate(BaseModel):
    asset_id: str
    chain_id: str
    contract_address: str
    symbol: str
    futures_symbol: str | None = None
    mapping_status: Literal["unique", "ambiguous", "unmatched"] = "unmatched"
    price: float | None = None
    market_cap: float | None = None
    liquidity: float | None = None
    volume_24h: float | None = None
    chip_concentration_percent: float | None = None
    coverage: float = 0.0
    confidence: float = 0.0
    pump_potential: dict[str, HorizonScore] = Field(default_factory=dict)
    cashout_risk: dict[str, HorizonScore] = Field(default_factory=dict)
    evidence: list[Evidence] = Field(default_factory=list)
    vetoes: list[str] = Field(default_factory=list)
    trade_plans: dict[str, TradePlan] = Field(default_factory=dict)
    status: Literal["trade_eligible", "watch", "data_insufficient", "vetoed"] = (
        "data_insufficient"
    )


class DiscoverySnapshot(BaseModel):
    status: Literal["ok", "degraded", "unavailable"]
    observed_at: datetime = Field(default_factory=utc_now)
    candidates: list[DiscoveryCandidate] = Field(default_factory=list)
    source_health: dict[str, ProviderHealth] = Field(default_factory=dict)
    chain_health: dict[str, ProviderHealth] = Field(default_factory=dict)
    universe_counts: dict[str, int] = Field(default_factory=dict)
    stale: bool = False
