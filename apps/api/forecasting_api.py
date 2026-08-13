"""Opt-in, fail-closed forecasting lab routes."""

from __future__ import annotations

import asyncio
import math
import statistics
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from libs.config import get_settings
from libs.data.real_sources import (
    DataUnavailable,
    fetch_a_share_daily,
    fetch_altcoin_daily,
    fetch_us_equity_daily,
)
from libs.forecasting.contracts import AssetClass, CanonicalBarFrame
from libs.forecasting.kronos import ForecastUnavailable, KronosLab, config_from_settings
from libs.forecasting.state_store import ForecastInstrumentStore
from libs.quant.promotion_registry import get_registry

router = APIRouter(prefix="/api/forecasting", tags=["forecasting-lab"])
_lab: KronosLab | None = None
_instrument_store: ForecastInstrumentStore | None = None


def get_lab() -> KronosLab:
    global _lab
    if _lab is None:
        _lab = KronosLab(config_from_settings(get_settings()))
    return _lab


def get_instrument_store() -> ForecastInstrumentStore:
    global _instrument_store
    if _instrument_store is None:
        _instrument_store = ForecastInstrumentStore(get_settings().polybob_db_path)
    return _instrument_store


def _normalise_domain(domain: str) -> str:
    aliases = {
        "altcoin": "crypto_spot",
        "crypto": "crypto_spot",
        "us": "us_equity",
        "cn": "a_share",
        "polymarket": "prediction_market",
    }
    return aliases.get(domain.strip().lower(), domain.strip().lower())


def _frame(symbol: str, domain: str) -> CanonicalBarFrame:
    domain = _normalise_domain(domain)
    if domain == "crypto_spot":
        instrument = symbol.upper()
        if not instrument.endswith(("-USDT", "-USD")):
            instrument = f"{instrument}-USDT"
        bars = fetch_altcoin_daily(instrument, days=720)
        return CanonicalBarFrame.from_daily_bars(
            bars, asset_class=AssetClass.CRYPTO_SPOT, venue="OKX", adjustment="none", session="24x7"
        )
    if domain == "us_equity":
        bars = fetch_us_equity_daily(symbol.upper(), years=5)
        return CanonicalBarFrame.from_daily_bars(
            bars,
            asset_class=AssetClass.US_EQUITY,
            venue="US_CONSOLIDATED",
            adjustment="provider_adjusted_unknown",
            session="regular_daily",
        )
    if domain == "a_share":
        bars = fetch_a_share_daily(symbol, days=1200)
        return CanonicalBarFrame.from_daily_bars(
            bars,
            asset_class=AssetClass.A_SHARE,
            venue="SSE_OR_SZSE",
            adjustment="provider_adjusted_unknown",
            session="cash_daily_with_lunch_break",
        )
    if domain == "prediction_market":
        raise ForecastUnavailable(
            "Polymarket stays experimental: bounded probabilities, liquidity and time-to-resolution need a dedicated adapter"
        )
    raise ValueError(f"unsupported forecast domain: {domain}")


def _return_over(closes: list[float], periods: int) -> float | None:
    if len(closes) <= periods or closes[-periods - 1] <= 0:
        return None
    return closes[-1] / closes[-periods - 1] - 1


def _input_state(frame: CanonicalBarFrame) -> dict:
    """Describe model inputs without pretending to expose model causality."""

    context = frame.bars[-512:]
    closes = [bar.close for bar in context]
    returns = [math.log(current / previous) for previous, current in zip(closes, closes[1:])]
    recent_returns = returns[-20:]
    volatility = (
        statistics.stdev(recent_returns) * math.sqrt(252)
        if len(recent_returns) >= 2
        else None
    )
    high_60d = max(closes[-60:]) if closes else None
    volumes = [bar.volume for bar in context]
    volume_ratio = None
    if len(volumes) >= 20 and all(value is not None for value in volumes[-20:]):
        recent_5d = statistics.fmean(float(value) for value in volumes[-5:])
        prior_20d = statistics.fmean(float(value) for value in volumes[-20:])
        if prior_20d > 0:
            volume_ratio = recent_5d / prior_20d
    return {
        "interpretation": "descriptive_not_causal",
        "return_5d": _return_over(closes, 5),
        "return_20d": _return_over(closes, 20),
        "realized_volatility_20d": volatility,
        "drawdown_from_60d_high": closes[-1] / high_60d - 1 if high_60d else None,
        "volume_ratio_5d_vs_20d": volume_ratio,
        "history": [
            {"timestamp": bar.timestamp.isoformat(), "close": bar.close}
            for bar in context[-40:]
        ],
    }


@router.get("/status")
async def forecast_status(verify: bool = False):
    state = await asyncio.to_thread(get_lab().readiness, verify_hashes=verify)
    state["supported_domains"] = ["crypto_spot", "us_equity", "a_share"]
    state["experimental_domains"] = ["prediction_market"]
    state["trade_permission"] = False
    return state


class InstrumentSettingUpdate(BaseModel):
    enabled: bool
    horizon: int = Field(default=5, ge=1, le=20)


@router.get("/instruments")
async def enabled_instruments(domain: str | None = None):
    try:
        clean_domain = _normalise_domain(domain) if domain else None
        rows = await asyncio.to_thread(get_instrument_store().list_enabled, clean_domain)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"rows": [row.to_dict() for row in rows]}


@router.get("/instruments/{domain}/{symbol}")
async def instrument_setting(domain: str, symbol: str):
    try:
        setting = await asyncio.to_thread(
            get_instrument_store().get, _normalise_domain(domain), symbol
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    payload = setting.to_dict()
    readiness = await asyncio.to_thread(get_lab().readiness)
    payload.update({
        "engine_enabled": readiness["enabled"],
        "engine_ready": readiness["ready"],
        "engine_reason": readiness["reason"],
        "promotion_status": "lab_only",
        "trade_permission": False,
    })
    return payload


@router.put("/instruments/{domain}/{symbol}")
async def configure_instrument(
    domain: str, symbol: str, request: InstrumentSettingUpdate
):
    if request.enabled:
        readiness = await asyncio.to_thread(get_lab().readiness)
        if not readiness["enabled"] or not readiness["ready"]:
            raise HTTPException(
                status_code=409,
                detail=readiness["reason"] or "forecasting engine is not ready",
            )
    try:
        setting = await asyncio.to_thread(
            get_instrument_store().set,
            _normalise_domain(domain),
            symbol,
            enabled=request.enabled,
            horizon=request.horizon,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        **setting.to_dict(),
        "promotion_status": "lab_only",
        "trade_permission": False,
    }


class ForecastRunRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=40)
    domain: str = Field(min_length=1, max_length=40)
    horizon: int | None = Field(default=None, ge=1, le=20)


async def _run_forecast(symbol: str, domain: str, horizon: int | None):
    try:
        if not get_lab().config.enabled:
            raise ForecastUnavailable(
                "lab forecasting is disabled; set ENABLE_LAB_KRONOS_FORECASTING=true"
            )
        clean_domain = _normalise_domain(domain)
        setting = await asyncio.to_thread(
            get_instrument_store().get, clean_domain, symbol
        )
        if not setting.enabled:
            raise ForecastUnavailable(
                f"Kronos is disabled for {setting.domain}:{setting.symbol}; enable this instrument first"
            )
        selected_horizon = horizon if horizon is not None else setting.horizon
        frame = await asyncio.to_thread(_frame, symbol, clean_domain)
        artifact = await asyncio.to_thread(
            get_lab().forecast, frame, horizon=selected_horizon
        )
    except ForecastUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (DataUnavailable, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    payload = artifact.to_dict()
    payload["explanation"] = {
        "method": "forecast_distribution_with_descriptive_inputs",
        "causal_attribution_available": False,
        "input_state": _input_state(frame),
        "baseline": {
            "name": "unchanged_last_close",
            "terminal_price": artifact.last_close,
            "expected_return": 0.0,
        },
        "historical_validation": {
            "status": "unknown",
            "reason": "walk-forward validation is not available for this instrument and model revision",
        },
        "invalidation_rule": "an observed daily close outside that date's P10-P90 band is an interval breach, not proof of model causality",
    }
    strategy = "kronos_daily_forecast"
    registry = get_registry()
    promoted = registry.is_promoted(strategy, frame.instrument_id)
    calibrated = artifact.calibration_status == "calibrated"
    payload["trade_permission"] = promoted and calibrated
    payload["gate_reason"] = (
        registry.reason_blocked(strategy, frame.instrument_id)
        if not promoted
        else "forecast artifact is uncalibrated; promotion alone cannot validate this run"
    )
    return payload


@router.post("/runs")
async def create_forecast_run(request: ForecastRunRequest):
    return await _run_forecast(request.symbol, request.domain, request.horizon)


@router.get("/forecast")
async def forecast(
    symbol: str = Query(min_length=1, max_length=40),
    domain: str = Query(min_length=1, max_length=40),
    horizon: int = Query(default=5, ge=1, le=20),
):
    """Compatibility endpoint; new clients use POST /runs for expensive work."""
    return await _run_forecast(symbol, domain, horizon)


class ScanRequest(BaseModel):
    domain: Literal["crypto_spot", "us_equity", "a_share"]
    symbols: list[str] = Field(min_length=1, max_length=8)
    horizon: int = Field(default=5, ge=1, le=20)


@router.post("/scan")
async def scan(request: ScanRequest):
    if not get_lab().config.enabled:
        raise HTTPException(
            status_code=409,
            detail="lab forecasting is disabled; set ENABLE_LAB_KRONOS_FORECASTING=true",
        )
    rows = []
    for symbol in request.symbols:
        try:
            setting = await asyncio.to_thread(
                get_instrument_store().get, request.domain, symbol
            )
            if not setting.enabled:
                raise ForecastUnavailable("instrument is not enabled for Kronos")
            frame = await asyncio.to_thread(_frame, symbol, request.domain)
            artifact = await asyncio.to_thread(get_lab().forecast, frame, horizon=request.horizon)
            rows.append({
                "symbol": symbol,
                "status": artifact.status.value,
                "expected_return": artifact.expected_return,
                "up_probability": artifact.up_probability,
                "as_of": artifact.as_of.isoformat(),
                "source": artifact.source,
                "paths": artifact.paths,
                "trade_permission": False,
            })
        except Exception as exc:  # one bad symbol must not falsify the other rows
            rows.append({"symbol": symbol, "status": "unknown", "reason": str(exc), "trade_permission": False})
    return {"domain": request.domain, "horizon": request.horizon, "rows": rows, "promotion_status": "lab_only"}
