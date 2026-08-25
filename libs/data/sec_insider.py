"""SEC Form 4 insider transactions — the free, complete US source.

The Finnhub feed could not test the insider-buying anomaly: one year of history
across mega-caps yielded only 23 open-market purchases, because large-cap
insiders sell (option/RSU liquidation) rather than buy. The SEC's own quarterly
"Form 345" structured datasets remove that limitation — each quarter carries
~100k non-derivative transactions across the whole market, including the small
and mid caps where insider *buying* actually happens.

Why the buy signal has a mechanism (unlike a chart pattern): insiders know their
own business, an open-market purchase costs them real money and is legally
constrained, so it is expensive to fake. The classic result is that purchases
predict returns while sales are mostly diversification noise.

Timing discipline: ``FILING_DATE`` is when the trade becomes public and is the
only date used for event studies; ``TRANS_DATE`` (when the insider traded) is
not yet public and using it would be look-ahead.
"""

from __future__ import annotations

import csv
import io
import time
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from libs.data.http_client import HttpFetchError
from libs.data.resilient import FetchPolicy, fetch_cached_bytes

CACHE_DIR = Path("data/market_cache/sec")
_BASE = "https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets"
_CURRENT_BASE = "https://www.sec.gov/files/datastandardsinnovation/data/insider-transactions-data-sets"
# The SEC requires a User-Agent naming the requester with contact details, and
# caps requests at 10/second; anything vaguer is rejected with HTTP 403.
_UA = "PolyBob Research idiotprofessorchen@gmail.com"
_MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}


class SecDataUnavailable(RuntimeError):
    """Raised when the SEC dataset cannot be fetched — never fabricate filings."""


@dataclass(frozen=True)
class InsiderTrade:
    symbol: str
    issuer: str
    filing_date: str        # public disclosure date — use this for event timing
    trans_date: str         # when the insider traded (not public until filing)
    trans_code: str         # P purchase, S sale, A award, G gift, M option exercise
    shares: float
    price: float

    @property
    def is_open_market_buy(self) -> bool:
        return self.trans_code.upper() == "P" and self.shares > 0

    @property
    def is_open_market_sell(self) -> bool:
        return self.trans_code.upper() == "S" and self.shares > 0

    @property
    def value_usd(self) -> float:
        return self.shares * self.price


def _parse_date(value: str) -> str:
    """SEC uses ``31-MAR-2026``; normalise to ISO so it sorts and joins."""
    try:
        day, month, year = value.strip().upper().split("-", 2)
        month_number = _MONTHS.get(month)
        if month_number is None:
            raise ValueError("unknown month")
        return f"{int(year):04d}-{month_number:02d}-{int(day):02d}"
    except (ValueError, AttributeError, TypeError):
        return ""


def _download_quarter(year: int, quarter: int) -> bytes:
    cache = CACHE_DIR / f"{year}q{quarter}_form345.zip"
    if cache.exists() and cache.stat().st_size > 1000:
        return cache.read_bytes()
    # SEC moved the current-quarter download directory in 2026. Keep the
    # historical path for vintages that are already stable, and use the
    # official current link for the newly published quarter.
    base = _CURRENT_BASE if (year, quarter) >= (2026, 2) else _BASE
    url = f"{base}/{year}q{quarter}_form345.zip"
    try:
        # Multi-megabyte zip: streamed and retried; the durable cache means a
        # later run never re-downloads quarters that already completed.
        payload = fetch_cached_bytes(
            url, cache_dir=CACHE_DIR / "responses",
            policy=FetchPolicy(attempts=5, timeout_seconds=120.0,
                               initial_backoff_seconds=2.0, max_backoff_seconds=30.0),
            headers={"User-Agent": _UA}, stream=True,
            dataset="sec_form345_raw", source="sec.gov",
        )
    except HttpFetchError as exc:
        raise SecDataUnavailable(f"{year}Q{quarter}: {exc}") from exc
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = cache.with_suffix(".tmp")
    tmp.write_bytes(payload)
    tmp.replace(cache)
    time.sleep(0.2)          # stay well inside the SEC's rate limit
    return payload


def fetch_insider_trades(year: int, quarter: int) -> list[InsiderTrade]:
    """All non-derivative insider transactions filed in one quarter."""
    archive = zipfile.ZipFile(io.BytesIO(_download_quarter(year, quarter)))

    # Submissions carry the ticker and the filing (public) date.
    submissions: dict[str, tuple[str, str, str]] = {}
    with archive.open("SUBMISSION.tsv") as handle:
        for row in csv.DictReader(io.TextIOWrapper(handle, "utf-8", errors="replace"), delimiter="\t"):
            symbol = (row.get("ISSUERTRADINGSYMBOL") or "").strip().upper()
            if not symbol or symbol in {"NONE", "N/A"}:
                continue
            submissions[row["ACCESSION_NUMBER"]] = (
                symbol, (row.get("ISSUERNAME") or "").strip(),
                _parse_date(row.get("FILING_DATE", "")),
            )

    trades: list[InsiderTrade] = []
    with archive.open("NONDERIV_TRANS.tsv") as handle:
        for row in csv.DictReader(io.TextIOWrapper(handle, "utf-8", errors="replace"), delimiter="\t"):
            meta = submissions.get(row.get("ACCESSION_NUMBER", ""))
            if not meta:
                continue
            symbol, issuer, filing_date = meta
            if not filing_date:
                continue
            try:
                shares = float(row.get("TRANS_SHARES") or 0.0)
                price = float(row.get("TRANS_PRICEPERSHARE") or 0.0)
            except (TypeError, ValueError):
                continue
            trades.append(InsiderTrade(
                symbol=symbol, issuer=issuer, filing_date=filing_date,
                trans_date=_parse_date(row.get("TRANS_DATE", "")),
                trans_code=(row.get("TRANS_CODE") or "").strip(),
                shares=shares, price=price,
            ))
    if not trades:
        raise SecDataUnavailable(f"{year}Q{quarter} contained no usable transactions")
    from libs.data.data_lake import write_records
    write_records(
        "sec_filings",
        [
            {
                "symbol": trade.symbol,
                "event_at": f"{trade.filing_date}T00:00:00+00:00",
                "transaction_at": trade.trans_date,
                "issuer": trade.issuer,
                "transaction_code": trade.trans_code,
                "shares": trade.shares,
                "price": trade.price,
                "value_usd": trade.value_usd,
                "is_open_market_buy": trade.is_open_market_buy,
                "is_open_market_sell": trade.is_open_market_sell,
                "source": "sec_form345",
            }
            for trade in trades
        ],
        source="sec_form345",
        partition_by=("symbol",),
    )
    # Mirror the normalized events into the bitemporal query store as well.  The
    # immutable lake is the archival source, while the store is the canonical
    # point-in-time query layer used by edges, coverage checks, and the dashboard.
    # Without this mirror a successful SEC download still appeared as
    # ``insider_filings: 0 rows`` to research consumers.
    from libs.data import store

    by_symbol: dict[str, list[dict[str, object]]] = defaultdict(list)
    for trade in trades:
        by_symbol[trade.symbol].append({
            "symbol": trade.symbol,
            "symbol_reported": trade.symbol,
            store.EVENT_DATE: trade.filing_date,
            "insider": trade.issuer,
            "transaction_date": trade.trans_date,
            "value_usd": trade.value_usd,
            "is_open_market_buy": trade.is_open_market_buy,
            "source": "sec_form345",
        })
    for symbol, rows in by_symbol.items():
        store.write(store.INSIDER_FILINGS, symbol, rows, deduplicate_payload=True)
    return trades


def cluster_buys(
    trades: list[InsiderTrade], min_insiders: int = 2, min_value_usd: float = 50_000.0
) -> dict[tuple[str, str], float]:
    """Group open-market buys by (symbol, filing_date) into cluster events.

    Cluster buying — several insiders purchasing around the same time — is the
    subset with the strongest documented signal, since it is far harder to
    explain by one person's liquidity needs. Returns ``{(symbol, date): value}``.
    """
    grouped: dict[tuple[str, str], list[InsiderTrade]] = defaultdict(list)
    for trade in trades:
        if trade.is_open_market_buy and trade.value_usd >= min_value_usd:
            grouped[(trade.symbol, trade.filing_date)].append(trade)
    return {
        key: sum(t.value_usd for t in group)
        for key, group in grouped.items()
        if len(group) >= min_insiders
    }


__all__ = [
    "InsiderTrade",
    "SecDataUnavailable",
    "cluster_buys",
    "fetch_insider_trades",
]
