"""Small, provider-neutral contracts for price forecasting.

The contracts deliberately preserve missingness and data provenance.  A model
adapter may choose an explicit reduced feature mode, but it may not silently
turn an unknown market observation into zero.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Iterable, Sequence


class AssetClass(str, Enum):
    CRYPTO_SPOT = "crypto_spot"
    CRYPTO_PERP = "crypto_perp"
    US_EQUITY = "us_equity"
    A_SHARE = "a_share"
    PREDICTION_MARKET = "prediction_market"


class BarInterval(str, Enum):
    FIVE_MINUTES = "5m"
    ONE_HOUR = "1h"
    ONE_DAY = "1d"


class ForecastStatus(str, Enum):
    READY = "ready"
    BLOCKED = "blocked"
    ERROR = "error"


@dataclass(frozen=True)
class CanonicalBar:
    timestamp: dt.datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None
    amount: float | None = None

    def validate(self) -> None:
        prices = (self.open, self.high, self.low, self.close)
        if not all(math.isfinite(value) and value > 0 for value in prices):
            raise ValueError("OHLC values must be finite and positive")
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close):
            raise ValueError("bar violates low <= open/close <= high")
        for name, value in (("volume", self.volume), ("amount", self.amount)):
            if value is not None and (not math.isfinite(value) or value < 0):
                raise ValueError(f"{name} must be finite and non-negative when present")
        if self.timestamp.tzinfo is None:
            raise ValueError("bar timestamps must be timezone-aware")


@dataclass(frozen=True)
class CanonicalBarFrame:
    instrument_id: str
    asset_class: AssetClass
    venue: str
    interval: BarInterval
    source: str
    fetched_at: dt.datetime
    bars: tuple[CanonicalBar, ...]
    adjustment: str = "none"
    session: str = "unknown"

    def validate(self, *, minimum_rows: int = 32) -> None:
        if len(self.bars) < minimum_rows:
            raise ValueError(f"need at least {minimum_rows} bars, got {len(self.bars)}")
        if self.fetched_at.tzinfo is None:
            raise ValueError("fetched_at must be timezone-aware")
        previous: dt.datetime | None = None
        for bar in self.bars:
            bar.validate()
            if previous is not None and bar.timestamp <= previous:
                raise ValueError("bars must be strictly increasing with no duplicate timestamps")
            previous = bar.timestamp

    @property
    def feature_mode(self) -> str:
        has_volume = all(bar.volume is not None for bar in self.bars)
        has_amount = all(bar.amount is not None for bar in self.bars)
        if has_volume and has_amount:
            return "ohlcva"
        if has_volume:
            return "ohlcv_amount_derived"
        return "ohlc_only"

    @classmethod
    def from_daily_bars(
        cls,
        daily_bars,
        *,
        asset_class: AssetClass,
        venue: str,
        fetched_at: dt.datetime | None = None,
        adjustment: str = "unknown",
        session: str = "daily_close",
    ) -> "CanonicalBarFrame":
        """Convert ``libs.data.real_sources.DailyBars`` without inventing data."""

        if not daily_bars.opens or not daily_bars.highs or not daily_bars.lows:
            raise ValueError("complete OHLC is required; close-only history is not forecastable")
        rows: list[CanonicalBar] = []
        for index, day in enumerate(daily_bars.dates):
            values = (
                daily_bars.opens[index],
                daily_bars.highs[index],
                daily_bars.lows[index],
                daily_bars.closes[index],
            )
            if any(value is None for value in values):
                raise ValueError(f"missing OHLC at {day}; missing remains UNKNOWN")
            volume = None if daily_bars.volumes is None else daily_bars.volumes[index]
            stamp = dt.datetime.combine(dt.date.fromisoformat(str(day)[:10]), dt.time(), dt.UTC)
            rows.append(
                CanonicalBar(
                    timestamp=stamp,
                    open=float(values[0]),
                    high=float(values[1]),
                    low=float(values[2]),
                    close=float(values[3]),
                    volume=None if volume is None else float(volume),
                )
            )
        frame = cls(
            instrument_id=daily_bars.symbol,
            asset_class=asset_class,
            venue=venue,
            interval=BarInterval.ONE_DAY,
            source=daily_bars.source,
            fetched_at=fetched_at or dt.datetime.now(dt.UTC),
            bars=tuple(rows),
            adjustment=adjustment,
            session=session,
        )
        frame.validate()
        return frame


@dataclass(frozen=True)
class ForecastPoint:
    timestamp: dt.datetime
    open_p50: float
    high_p50: float
    low_p50: float
    close_p10: float
    close_p50: float
    close_p90: float


@dataclass(frozen=True)
class ForecastArtifact:
    run_id: str
    status: ForecastStatus
    instrument_id: str
    asset_class: AssetClass
    interval: BarInterval
    as_of: dt.datetime
    source: str
    model_id: str
    model_revision: str
    tokenizer_id: str
    tokenizer_revision: str
    context_rows: int
    horizon: int
    feature_mode: str
    calendar_quality: str
    paths: int
    last_close: float
    expected_return: float
    up_probability: float
    points: tuple[ForecastPoint, ...]
    calibration_status: str = "uncalibrated"
    promotion_status: str = "lab_only"
    blocked_reason: str | None = None
    generated_at: dt.datetime | None = None

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["status"] = self.status.value
        payload["asset_class"] = self.asset_class.value
        payload["interval"] = self.interval.value
        payload["as_of"] = self.as_of.isoformat()
        payload["generated_at"] = self.generated_at.isoformat() if self.generated_at else None
        for point in payload["points"]:
            point["timestamp"] = point["timestamp"].isoformat()
        return payload


def percentile(values: Sequence[float], quantile: float) -> float:
    if not values:
        raise ValueError("cannot calculate a percentile from no paths")
    ordered = sorted(float(value) for value in values)
    position = (len(ordered) - 1) * quantile
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def ensure_same_length(rows: Iterable[Sequence[object]]) -> int:
    lengths = {len(row) for row in rows}
    if len(lengths) != 1:
        raise ValueError(f"forecast paths have inconsistent lengths: {sorted(lengths)}")
    return next(iter(lengths), 0)
