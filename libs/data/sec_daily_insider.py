"""Near-real-time insider cluster buys from EDGAR's daily filing index.

``libs/data/sec_insider.py`` reads the SEC's quarterly Form 345 *bulk* datasets.
They are complete and convenient, and they are published weeks after a quarter
closes — which made the one tradable US edge structurally impossible to act on:
the twenty-day window the study measured always fell inside a quarter that was
not out yet, so the detector could only ever answer "unknown". A validated edge
you can never see fire is not a tradable edge.

This module reads the other EDGAR endpoint: the **daily index**, published the
same evening, which lists every filing by form type.

Two things make it cheap enough to run:

**A pre-filter that costs nothing.** The daily index lists Form 4 filings under
the *issuer's* CIK, one row per filing. A cluster is by definition several
insiders filing on the same issuer the same day, so an issuer with only one
Form 4 that day cannot be one. Keeping only CIKs that appear at least twice cut
a representative day from 712 filings to 217 — the rest cannot contain the
event, so they are never fetched.

**A cache that is correct by construction.** A past day's filings never change,
so each completed day is parsed once and stored. Today is never cached: its
index is still being written.

Coverage is tracked and returned, not assumed. If some day in the window could
not be read, callers are told — because "no cluster in the days I managed to
read" is a different statement from "no cluster", and collapsing the two is the
same mistake this project keeps finding in its own code.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from libs.data.http_client import HttpFetchError, http_get_bytes

CACHE_DIR = Path("data/market_cache/sec_daily")
_BASE = "https://www.sec.gov/Archives"
# The SEC requires a User-Agent naming the requester with contact details and
# caps requests at 10/second.
_UA = "PolyBob Research idiotprofessorchen@gmail.com"
_REQUEST_PAUSE = 0.12          # ~8 req/s, comfortably inside the cap

# The validated thresholds, identical to the study and to the strategy.
MIN_INSIDERS = 2
MIN_VALUE_USD = 50_000.0


class DailyInsiderUnavailable(RuntimeError):
    """Raised when EDGAR cannot be read — never fabricate a filing."""


@dataclass(frozen=True)
class ClusterEvent:
    """Several insiders filing open-market purchases on one issuer, one day."""

    symbol: str
    filing_date: str
    insiders: int
    value_usd: float
    issuer: str = ""

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "filing_date": self.filing_date,
            "insiders": self.insiders,
            "value_usd": round(self.value_usd, 2),
            "issuer": self.issuer,
        }

    @classmethod
    def from_dict(cls, row: dict) -> ClusterEvent:
        return cls(
            symbol=str(row["symbol"]),
            filing_date=str(row["filing_date"]),
            insiders=int(row["insiders"]),
            value_usd=float(row["value_usd"]),
            issuer=str(row.get("issuer", "")),
        )


@dataclass
class ClusterScan:
    """Cluster events found, plus exactly which days were actually read."""

    events: list[ClusterEvent] = field(default_factory=list)
    days_covered: list[str] = field(default_factory=list)
    days_missing: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return not self.days_missing

    def for_symbol(self, symbol: str) -> list[ClusterEvent]:
        wanted = symbol.strip().upper()
        return [e for e in self.events if e.symbol == wanted]


# --------------------------------------------------------------- daily index
def _index_url(day: date) -> str:
    quarter = (day.month - 1) // 3 + 1
    return f"{_BASE}/edgar/daily-index/{day.year}/QTR{quarter}/form.{day:%Y%m%d}.idx"


def _fetch_index(day: date) -> list[tuple[str, str, str]]:
    """``(cik, company, path)`` for every Form 4 filed on ``day``.

    Raises :class:`DailyInsiderUnavailable` on a weekend, holiday, or outage —
    the caller decides what an unreadable day means, rather than silently
    treating it as a day with no filings.
    """
    try:
        raw = http_get_bytes(_index_url(day), timeout=60,
                             headers={"User-Agent": _UA}).decode("latin-1")
    except HttpFetchError as exc:
        raise DailyInsiderUnavailable(f"{day.isoformat()}: {exc}") from exc

    rows: list[tuple[str, str, str]] = []
    for line in raw.splitlines():
        if not line.startswith("4 ") or "edgar/data/" not in line:
            continue
        parts = line.split()
        path = parts[-1]
        cik = parts[-3]
        company = line[16:line.index(cik)].strip() if cik in line else ""
        rows.append((cik, company, path))
    if not rows:
        raise DailyInsiderUnavailable(f"{day.isoformat()}: no Form 4 rows in the index")
    return rows


# ------------------------------------------------------------ filing parsing
_TXN_BLOCK = re.compile(r"<nonDerivativeTransaction>.*?</nonDerivativeTransaction>", re.S)


def _tag(text: str, name: str) -> str | None:
    match = re.search(rf"<{name}>(.*?)</{name}>", text, re.S)
    if not match:
        return None
    inner = match.group(1)
    # Numeric fields are wrapped one level deeper: <value>123</value>.
    value = re.search(r"<value>(.*?)</value>", inner, re.S)
    return (value.group(1) if value else inner).strip()


@dataclass(frozen=True)
class _Purchase:
    symbol: str
    owner: str
    value_usd: float


def parse_form4(text: str) -> _Purchase | None:
    """Total open-market purchase value in one Form 4, or ``None``.

    Only transaction code ``P`` counts. Awards, option exercises and gifts carry
    no information about what the insider thinks the stock is worth, which is
    the whole mechanism behind the edge.
    """
    document = re.search(r"<ownershipDocument>.*?</ownershipDocument>", text, re.S)
    if not document:
        return None
    body = document.group(0)

    symbol = (_tag(body, "issuerTradingSymbol") or "").upper()
    owner = _tag(body, "rptOwnerName") or ""
    if not symbol or symbol in {"NONE", "N/A"}:
        return None

    total = 0.0
    for block in _TXN_BLOCK.findall(body):
        if (_tag(block, "transactionCode") or "").upper() != "P":
            continue
        try:
            shares = float(_tag(block, "transactionShares") or 0.0)
            price = float(_tag(block, "transactionPricePerShare") or 0.0)
        except ValueError:
            continue
        total += shares * price
    if total <= 0:
        return None
    return _Purchase(symbol=symbol, owner=owner, value_usd=total)


# ------------------------------------------------------------------ per day
def _cache_path(day: date) -> Path:
    return CACHE_DIR / f"{day:%Y%m%d}.json"


def scan_day(day: date, *, allow_fetch: bool = True) -> list[ClusterEvent]:
    """Cluster buys filed on ``day``. Cached; a past day never changes.

    With ``allow_fetch=False`` only the cache is consulted, which is what the
    interactive API path uses: warming a cold twenty-day window costs thousands
    of requests and must never happen inside a page load.
    """
    cache = _cache_path(day)
    if cache.exists():
        try:
            return [ClusterEvent.from_dict(r) for r in json.loads(cache.read_text())]
        except Exception:  # noqa: BLE001 - a corrupt cache is refetched
            pass
    if not allow_fetch:
        raise DailyInsiderUnavailable(f"{day.isoformat()}: not in cache")

    rows = _fetch_index(day)

    # The pre-filter: an issuer with a single Form 4 that day cannot have a
    # cluster, so its filing is never fetched.
    by_cik: dict[str, set[str]] = {}
    names: dict[str, str] = {}
    for cik, company, path in rows:
        by_cik.setdefault(cik, set()).add(path)
        names.setdefault(cik, company)
    candidates = {cik: paths for cik, paths in by_cik.items() if len(paths) >= MIN_INSIDERS}

    events: list[ClusterEvent] = []
    for cik, paths in candidates.items():
        purchases: list[_Purchase] = []
        for path in sorted(paths):
            try:
                text = http_get_bytes(f"{_BASE}/{path}", timeout=60,
                                      headers={"User-Agent": _UA}).decode("utf-8", "replace")
            except HttpFetchError:
                continue          # one unreadable filing must not lose the day
            time.sleep(_REQUEST_PAUSE)
            purchase = parse_form4(text)
            if purchase and purchase.value_usd >= MIN_VALUE_USD:
                purchases.append(purchase)

        # Distinct insiders, matching cluster_buys() in the bulk path.
        owners = {p.owner for p in purchases}
        if len(owners) < MIN_INSIDERS:
            continue
        symbol = purchases[0].symbol
        events.append(ClusterEvent(
            symbol=symbol, filing_date=day.isoformat(), insiders=len(owners),
            value_usd=sum(p.value_usd for p in purchases), issuer=names.get(cik, ""),
        ))

    # Only completed days are cached: today's index is still being written.
    if day < datetime.now(UTC).date():
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps([e.to_dict() for e in events], ensure_ascii=False))
    return events


def scan_window(
    as_of: date | None = None,
    window_days: int = 20,
    *,
    allow_fetch: bool = True,
    max_fetch_days: int | None = None,
) -> ClusterScan:
    """Cluster buys over the trailing window, with honest coverage reporting.

    ``max_fetch_days`` bounds how many uncached days one call will go and get,
    so a cold cache warms over several runs instead of blocking one of them for
    minutes. Days that were not read land in ``days_missing``.
    """
    as_of = as_of or datetime.now(UTC).date()
    scan = ClusterScan()
    fetched = 0

    for offset in range(window_days + 1):
        day = as_of - timedelta(days=offset)
        if day.weekday() >= 5:            # EDGAR publishes no weekend index
            continue
        cached = _cache_path(day).exists()
        if not cached:
            if not allow_fetch or (max_fetch_days is not None and fetched >= max_fetch_days):
                scan.days_missing.append(day.isoformat())
                continue
            fetched += 1
        try:
            scan.events.extend(scan_day(day, allow_fetch=allow_fetch))
            scan.days_covered.append(day.isoformat())
        except DailyInsiderUnavailable:
            # A holiday and an outage look the same from here, so neither is
            # allowed to masquerade as "a day with no clusters".
            scan.days_missing.append(day.isoformat())

    scan.days_covered.sort()
    scan.days_missing.sort()
    return scan


__all__ = [
    "MIN_INSIDERS",
    "MIN_VALUE_USD",
    "ClusterEvent",
    "ClusterScan",
    "DailyInsiderUnavailable",
    "parse_form4",
    "scan_day",
    "scan_window",
]
