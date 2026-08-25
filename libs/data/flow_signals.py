"""Information beyond price for US equities and altcoins.

The A-share dragon-tiger work showed where edges actually live: not in the price
series (200+ price-only configurations found nothing) but in *disclosures and
positioning* that price alone does not contain. This module provides the
equivalent real data for the other two in-scope domains.

**US equities — insider transactions (Finnhub).** Corporate insiders trade with
an information advantage; the SEC requires them to disclose it. The economic
mechanism is direct: insiders know their business, and open-market *purchases*
in particular are hard to explain except by a belief the stock is cheap.
Critically the feed carries both ``transactionDate`` and ``filingDate`` — only
the filing date is public information, so that is the one used for event timing.

**Altcoins — retail positioning (OKX).** The long/short *account* ratio counts
retail accounts on each side. Crowded retail positioning is a contrarian signal
in a market where those accounts are typically levered and forced out on adverse
moves; open interest confirms whether crowding is backed by real size.

Both fail loudly rather than returning fabricated values.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import time
import urllib.parse
from dataclasses import dataclass

from libs.data.http_client import HttpFetchError, http_get_json

CACHE_DIR = pathlib.Path("data/market_cache")
_UA = "Mozilla/5.0 (PolyBob research)"


class SignalDataUnavailable(RuntimeError):
    """Raised when real signal data cannot be fetched — never fake it."""


def _finnhub_key() -> str:
    key = os.environ.get("FINNHUB_API_KEY", "")
    if key:
        return key
    env = pathlib.Path(".env")
    if env.exists():
        for line in env.read_text().splitlines():
            match = re.match(r"\s*FINNHUB_API_KEY\s*=\s*(.*)", line)
            if match:
                return match.group(1).strip().strip('"').strip("'")
    raise SignalDataUnavailable("FINNHUB_API_KEY is not configured")


def _get(url: str, timeout: float = 20.0) -> dict | list:
    """Fetch over the shared pooled session — see libs/data/http_client.py."""
    try:
        return http_get_json(url, timeout=timeout, headers={"User-Agent": _UA})
    except HttpFetchError as exc:
        raise SignalDataUnavailable(f"{url.split('?')[0]}: {exc}") from exc


def _cached(key: str, loader, ttl: float = 12 * 3600):
    path = CACHE_DIR / f"{key}.json"
    if path.exists() and (time.time() - path.stat().st_mtime) < ttl:
        try:
            return json.loads(path.read_text())
        except Exception:  # noqa: BLE001
            pass
    payload = loader()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))
    return payload


# ------------------------------------------------------------- US insiders
@dataclass(frozen=True)
class InsiderEvent:
    """One insider filing. ``filing_date`` is when the market could know."""

    symbol: str
    name: str
    filing_date: str          # public disclosure date — use THIS for timing
    transaction_date: str     # when the trade happened (not yet public)
    change: float             # shares; >0 buy, <0 sell
    price: float
    transaction_code: str     # "P" purchase, "S" sale, "A" award...

    @property
    def is_open_market_buy(self) -> bool:
        """Open-market purchases carry signal; awards/grants do not."""
        return self.transaction_code.upper().startswith("P") and self.change > 0

    @property
    def is_open_market_sell(self) -> bool:
        return self.transaction_code.upper().startswith("S") and self.change < 0

    @property
    def value_usd(self) -> float:
        return abs(self.change) * self.price


def fetch_insider_transactions(symbol: str) -> list[InsiderEvent]:
    """Real insider filings for one symbol."""
    key = _finnhub_key()

    def load() -> dict:
        url = (
            "https://finnhub.io/api/v1/stock/insider-transactions"
            f"?symbol={urllib.parse.quote(symbol)}&token={key}"
        )
        return _get(url)  # type: ignore[return-value]

    payload = _cached(f"insider_{symbol}", load)
    rows = payload.get("data", []) if isinstance(payload, dict) else []
    events: list[InsiderEvent] = []
    for row in rows:
        try:
            events.append(InsiderEvent(
                symbol=symbol.upper(),
                name=str(row.get("name", "")),
                filing_date=str(row.get("filingDate", ""))[:10],
                transaction_date=str(row.get("transactionDate", ""))[:10],
                change=float(row.get("change") or 0.0),
                price=float(row.get("transactionPrice") or 0.0),
                transaction_code=str(row.get("transactionCode") or ""),
            ))
        except (TypeError, ValueError):
            continue
    if not events:
        raise SignalDataUnavailable(f"no insider rows for {symbol}")
    return events


# ------------------------------------------------------- altcoin positioning
@dataclass(frozen=True)
class PositioningPoint:
    date: str
    long_short_ratio: float      # retail accounts long / short
    open_interest: float


def fetch_retail_positioning(currency: str, days: int = 180) -> list[PositioningPoint]:
    """Real OKX retail long/short account ratio + open interest, oldest first."""
    ccy = currency.split("-")[0].upper()

    def load() -> dict:
        base = "https://www.okx.com/api/v5/rubik/stat/contracts"
        ratio = _get(f"{base}/long-short-account-ratio?ccy={ccy}&period=1D")
        oi = _get(f"{base}/open-interest-volume?ccy={ccy}&period=1D")
        return {"ratio": ratio.get("data", []), "oi": oi.get("data", [])}  # type: ignore[union-attr]

    payload = _cached(f"positioning_{ccy}_{days}", load)
    oi_by_ts = {row[0]: float(row[1]) for row in payload.get("oi", []) if len(row) >= 2}
    points: list[PositioningPoint] = []
    for row in payload.get("ratio", []):
        if len(row) < 2:
            continue
        try:
            stamp = row[0]
            points.append(PositioningPoint(
                date=time.strftime("%Y-%m-%d", time.gmtime(int(stamp) / 1000)),
                long_short_ratio=float(row[1]),
                open_interest=oi_by_ts.get(stamp, 0.0),
            ))
        except (TypeError, ValueError):
            continue
    if not points:
        raise SignalDataUnavailable(f"no positioning data for {ccy}")
    points.sort(key=lambda p: p.date)
    return points[-days:]


__all__ = [
    "InsiderEvent",
    "PositioningPoint",
    "SignalDataUnavailable",
    "fetch_insider_transactions",
    "fetch_retail_positioning",
]
