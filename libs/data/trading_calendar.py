"""Small, explicit exchange-session calendars with bounded coverage.

The important property is refusal outside known coverage. A weekday is not
automatically a trading day: exchange holidays are data, and guessing them makes
forecast horizons and holding periods silently wrong.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass


class CalendarCoverageError(ValueError):
    """The requested date is outside the calendar's verified coverage."""


@dataclass(frozen=True)
class TradingCalendar:
    calendar_id: str
    timezone: str
    quality: str
    source: str
    holidays: frozenset[dt.date]
    coverage_start: dt.date | None = None
    coverage_end: dt.date | None = None
    weekend: frozenset[int] = frozenset({5, 6})

    def contract(self) -> dict[str, object]:
        return {
            "calendar_id": self.calendar_id,
            "timezone": self.timezone,
            "quality": self.quality,
            "source": self.source,
            "coverage_start": self.coverage_start.isoformat() if self.coverage_start else None,
            "coverage_end": self.coverage_end.isoformat() if self.coverage_end else None,
        }

    def _require_coverage(self, day: dt.date) -> None:
        if self.coverage_start is not None and day < self.coverage_start:
            raise CalendarCoverageError(
                f"{self.calendar_id} calendar starts at {self.coverage_start}; got {day}"
            )
        if self.coverage_end is not None and day > self.coverage_end:
            raise CalendarCoverageError(
                f"{self.calendar_id} calendar ends at {self.coverage_end}; got {day}"
            )

    def is_session(self, day: dt.date) -> bool:
        self._require_coverage(day)
        return day.weekday() not in self.weekend and day not in self.holidays

    def sessions_after(self, day: dt.date, count: int) -> tuple[dt.date, ...]:
        if count < 1:
            raise ValueError("count must be positive")
        sessions: list[dt.date] = []
        cursor = day
        while len(sessions) < count:
            cursor += dt.timedelta(days=1)
            if self.is_session(cursor):
                sessions.append(cursor)
        return tuple(sessions)


# Exchange-published 2026 schedules. Coverage is deliberately bounded to the
# dates audited here; future years must be added from the official notice rather
# than inferred from a civil-holiday calendar.
XNYS_2026 = TradingCalendar(
    calendar_id="XNYS",
    timezone="America/New_York",
    quality="official_exchange_schedule",
    source="https://www.nyse.com/markets/hours-calendars",
    coverage_start=dt.date(2026, 1, 1),
    coverage_end=dt.date(2026, 12, 31),
    holidays=frozenset(
        dt.date.fromisoformat(value)
        for value in (
            "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03",
            "2026-05-25", "2026-06-19", "2026-07-03", "2026-09-07",
            "2026-11-26", "2026-12-25",
        )
    ),
)

XSHG_2026 = TradingCalendar(
    calendar_id="XSHG",
    timezone="Asia/Shanghai",
    quality="official_exchange_schedule",
    source="https://www.sse.com.cn/disclosure/dealinstruc/closed/c/c_20251222_10802510.shtml",
    coverage_start=dt.date(2026, 1, 1),
    coverage_end=dt.date(2026, 12, 31),
    holidays=frozenset(
        day
        for start, end in (
            (dt.date(2026, 1, 1), dt.date(2026, 1, 3)),
            (dt.date(2026, 2, 15), dt.date(2026, 2, 23)),
            (dt.date(2026, 4, 4), dt.date(2026, 4, 6)),
            (dt.date(2026, 5, 1), dt.date(2026, 5, 5)),
            (dt.date(2026, 6, 19), dt.date(2026, 6, 21)),
            (dt.date(2026, 9, 25), dt.date(2026, 9, 27)),
            (dt.date(2026, 10, 1), dt.date(2026, 10, 7)),
        )
        for offset in range((end - start).days + 1)
        for day in (start + dt.timedelta(days=offset),)
    ),
)

CRYPTO_24X7 = TradingCalendar(
    calendar_id="CRYPTO_24X7",
    timezone="UTC",
    quality="exact_24x7",
    source="market_definition",
    holidays=frozenset(),
    weekend=frozenset(),
)


def calendar_for(asset_class: str) -> TradingCalendar:
    key = str(asset_class).lower()
    if key in {"crypto_spot", "crypto_perp"}:
        return CRYPTO_24X7
    if key == "us_equity":
        return XNYS_2026
    if key == "a_share":
        return XSHG_2026
    raise KeyError(f"no trading calendar for asset class: {asset_class}")


__all__ = [
    "CRYPTO_24X7", "XNYS_2026", "XSHG_2026", "CalendarCoverageError",
    "TradingCalendar", "calendar_for",
]
