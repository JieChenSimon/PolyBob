"""A-share 龙虎榜 (dragon-tiger list) — real seat-level flow disclosure.

This is the "information beyond price" the price-only sweeps lacked, and it is
structurally unique to A-shares: after the close, the exchanges publish the
brokerage seats that dominated trading in stocks that hit disclosure triggers
(large moves, extreme turnover, limit-ups). Eastmoney serves the full history —
265k+ records back to 2004 — including who bought, who sold, and forward returns.

Why an edge could survive here (the mechanism a chart pattern lacks):

- The disclosure is an **attention shock** in a retail-dominated market. Retail
  investors chase names that appear on the list, which can push prices past fair
  value and revert (behavioural overreaction).
- Conversely a ``机构专用`` (institution-only) seat buying heavily is *informed*
  flow being revealed, which can predict continuation.
- Both effects can persist because arbitrage is genuinely limited: T+1
  settlement, ±10%/20% daily price limits, and costly/limited shorting.

These are competing, falsifiable hypotheses — exactly what pre-registration is
for. This module only fetches the real data; it takes no view.

Timing discipline: the list is published **after the close** of ``TRADE_DATE``,
so the first tradeable moment is the next session. The provided ``D1``…``D30``
fields are cumulative close-to-close returns *from* ``TRADE_DATE``'s close, so a
capturable holding period must start at D1 (see :func:`capturable_return`).
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from libs.data.http_client import HttpFetchError, http_get_json

CACHE_DIR = Path("data/market_cache")
_BASE = "https://datacenter-web.eastmoney.com/api/data/v1/get"
_REPORT = "RPT_DAILYBILLBOARD_DETAILSNEW"
_UA = "Mozilla/5.0 (PolyBob research)"


class FlowDataUnavailable(RuntimeError):
    """Raised when real flow data cannot be fetched — never substitute fakes."""


@dataclass(frozen=True)
class BillboardEvent:
    """One stock-day appearance on the dragon-tiger list."""

    trade_date: str          # event date; list is published after this close
    code: str
    name: str
    change_rate: float       # that day's % move
    net_amount: float        # 龙虎榜净买入额 (buy - sell), CNY
    deal_amount: float       # 龙虎榜总成交额, CNY
    turnover_amount: float   # 全日成交额, CNY
    free_market_cap: float
    explanation: str         # why it was listed (trigger rule)
    explain: str             # exchange note, e.g. "1家机构买入，成功率22.11%"
    buy_seats: str
    sell_seats: str
    d1: float | None         # cumulative close-to-close return from event close
    d2: float | None
    d5: float | None
    d10: float | None

    @property
    def net_ratio(self) -> float:
        """Net buying as a share of the day's total turnover — flow intensity."""
        return self.net_amount / self.turnover_amount if self.turnover_amount else 0.0

    @property
    def institutional_buy_count(self) -> int:
        """How many institution-only seats bought, per the exchange's own note.

        Seat fields are numeric codes, but ``EXPLAIN`` carries the exchange text
        (e.g. ``"1家机构买入，成功率22.11%"``), which is the reliable source.
        """
        import re

        match = re.search(r"(\d+)\s*家机构买入", self.explain or "")
        return int(match.group(1)) if match else 0

    @property
    def institutional_buy(self) -> bool:
        return self.institutional_buy_count > 0


def capturable_return(event: BillboardEvent, exit_day: int = 5) -> float | None:
    """Return actually capturable given the list publishes after the close.

    Entry is at the D1 close (the first session after publication), exit at the
    ``exit_day`` close. Computed as ``(1+D_exit)/(1+D1) - 1`` so the un-tradeable
    overnight gap between the event close and D1 is excluded — using D1 itself as
    the return would be look-ahead.
    """
    d1 = event.d1
    d_exit = {2: event.d2, 5: event.d5, 10: event.d10}.get(exit_day)
    if d1 is None or d_exit is None:
        return None
    return (1.0 + d_exit / 100.0) / (1.0 + d1 / 100.0) - 1.0


def _fetch_page(page: int, page_size: int) -> list[dict]:
    params = {
        "reportName": _REPORT, "columns": "ALL", "pageSize": str(page_size),
        "pageNumber": str(page), "sortColumns": "TRADE_DATE", "sortTypes": "-1",
    }
    url = f"{_BASE}?{urllib.parse.urlencode(params)}"
    try:
        payload = http_get_json(url, timeout=30, headers={"User-Agent": _UA})
    except HttpFetchError as exc:
        raise FlowDataUnavailable(f"dragon-tiger page {page}: {exc}") from exc
    result = payload.get("result") or {}
    return result.get("data") or []


def _to_event(row: dict) -> BillboardEvent | None:
    try:
        return BillboardEvent(
            trade_date=str(row.get("TRADE_DATE", ""))[:10],
            code=str(row.get("SECURITY_CODE", "")),
            name=str(row.get("SECURITY_NAME_ABBR", "")),
            change_rate=float(row.get("CHANGE_RATE") or 0.0),
            net_amount=float(row.get("BILLBOARD_NET_AMT") or 0.0),
            deal_amount=float(row.get("BILLBOARD_DEAL_AMT") or 0.0),
            turnover_amount=float(row.get("ACCUM_AMOUNT") or 0.0),
            free_market_cap=float(row.get("FREE_MARKET_CAP") or 0.0),
            explanation=str(row.get("EXPLANATION") or ""),
            explain=str(row.get("EXPLAIN") or ""),
            buy_seats=str(row.get("BUY_SEAT") or row.get("BUY_SEAT_NEW") or ""),
            sell_seats=str(row.get("SELL_SEAT") or row.get("SELL_SEAT_NEW") or ""),
            d1=_opt_float(row.get("D1_CLOSE_ADJCHRATE")),
            d2=_opt_float(row.get("D2_CLOSE_ADJCHRATE")),
            d5=_opt_float(row.get("D5_CLOSE_ADJCHRATE")),
            d10=_opt_float(row.get("D10_CLOSE_ADJCHRATE")),
        )
    except (TypeError, ValueError):
        return None


def _opt_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fetch_billboard_events(
    max_events: int = 20_000, page_size: int = 500, use_cache: bool = True
) -> list[BillboardEvent]:
    """Fetch real dragon-tiger events, newest first, with disk caching."""
    cache = CACHE_DIR / f"billboard_{max_events}.json"
    if use_cache and cache.exists() and (time.time() - cache.stat().st_mtime) < 24 * 3600:
        try:
            rows = json.loads(cache.read_text())
            events = [_to_event(r) for r in rows]
            return [e for e in events if e is not None]
        except Exception:  # noqa: BLE001 - corrupt cache refetches
            pass

    rows: list[dict] = []
    page = 1
    while len(rows) < max_events:
        page_rows = _fetch_page(page, page_size)
        if not page_rows:
            break
        rows.extend(page_rows)
        page += 1
        if len(page_rows) < page_size:
            break
        time.sleep(0.25)          # be polite to the provider

    if not rows:
        raise FlowDataUnavailable("dragon-tiger returned no rows")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(rows[:max_events]))
    events = [_to_event(r) for r in rows[:max_events]]
    return [e for e in events if e is not None]


__all__ = [
    "BillboardEvent",
    "FlowDataUnavailable",
    "capturable_return",
    "fetch_billboard_events",
]
