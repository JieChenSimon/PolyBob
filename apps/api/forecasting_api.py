"""Opt-in, fail-closed forecasting lab routes."""

from __future__ import annotations

import asyncio
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
from libs.quant.promotion_registry import get_registry

router = APIRouter(prefix="/api/forecasting", tags=["forecasting-lab"])
_lab: KronosLab | None = None


def get_lab() -> KronosLab:
    global _lab
    if _lab is None:
        _lab = KronosLab(config_from_settings(get_settings()))
    return _lab


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


@router.get("/status")
async def forecast_status(verify: bool = False):
    state = await asyncio.to_thread(get_lab().readiness, verify_hashes=verify)
    state["supported_domains"] = ["crypto_spot", "us_equity", "a_share"]
    state["experimental_domains"] = ["prediction_market"]
    state["trade_permission"] = False
    return state


@router.get("/forecast")
async def forecast(
    symbol: str = Query(min_length=1, max_length=40),
    domain: str = Query(min_length=1, max_length=40),
    horizon: int = Query(default=5, ge=1, le=20),
):
    try:
        if not get_lab().config.enabled:
            raise ForecastUnavailable(
                "lab forecasting is disabled; set ENABLE_LAB_KRONOS_FORECASTING=true"
            )
        frame = await asyncio.to_thread(_frame, symbol, domain)
        artifact = await asyncio.to_thread(get_lab().forecast, frame, horizon=horizon)
    except ForecastUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (DataUnavailable, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    payload = artifact.to_dict()
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
