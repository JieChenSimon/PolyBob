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
import urllib.request
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

CACHE_DIR = Path("data/market_cache/sec")
_BASE = "https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets"
# The SEC requires a User-Agent naming the requester with contact details, and
# caps requests at 10/second; anything vaguer is rejected with HTTP 403.
_UA = "PolyBob Research idiotprofessorchen@gmail.com"


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
        return datetime.strptime(value.strip(), "%d-%b-%Y").strftime("%Y-%m-%d")
    except (ValueError, AttributeError):
        return ""


def _download_quarter(year: int, quarter: int) -> bytes:
    cache = CACHE_DIR / f"{year}q{quarter}_form345.zip"
    if cache.exists() and cache.stat().st_size > 1000:
        return cache.read_bytes()
    url = f"{_BASE}/{year}q{quarter}_form345.zip"
    request = urllib.request.Request(url, headers={"User-Agent": _UA})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            payload = response.read()
    except Exception as exc:  # noqa: BLE001 - surface provider failure honestly
        raise SecDataUnavailable(f"{year}Q{quarter}: {exc}") from exc
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(payload)
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
