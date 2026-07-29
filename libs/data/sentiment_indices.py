"""Real sentiment indices — the crowd-behaviour gauges, not index quotes.

Every confirmed edge in this project is a bet on crowd behaviour (dragon-tiger
attention reversal, altcoin retail crowding, insider clusters), so the gauges
that measure crowd emotion are the natural companions — both as dashboard
context and as candidate conditioning variables.

Sources (real, free, no key):

- **Crypto Fear & Greed** (alternative.me) — a composite of volatility, momentum,
  volume, social and dominance. Full daily history back to 2018, which is what
  makes it testable rather than merely displayable.
- **VIX** (Yahoo ``^VIX``) — implied volatility on the S&P 500, the standard
  equity fear gauge, with daily history.

CNN's Fear & Greed endpoint is deliberately not used: it rejects programmatic
access (HTTP 418), and scraping around that is not worth the fragility.
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

CACHE_DIR = Path("data/market_cache")
_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"


class SentimentIndexUnavailable(RuntimeError):
    """Raised when an index cannot be fetched — never invent a reading."""


def _get(url: str, timeout: float = 25.0) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": _UA})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except Exception as exc:  # noqa: BLE001 - surface provider failure honestly
        raise SentimentIndexUnavailable(f"{url.split('?')[0]}: {exc}") from exc


def _cached(key: str, loader, ttl: float = 6 * 3600):
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


@dataclass(frozen=True)
class SentimentReading:
    index: str
    date: str
    value: float
    label: str

    def to_dict(self) -> dict:
        return {"index": self.index, "date": self.date,
                "value": self.value, "label": self.label}


def _crypto_label(value: float) -> str:
    if value <= 24:
        return "extreme_fear"
    if value <= 44:
        return "fear"
    if value <= 54:
        return "neutral"
    if value <= 74:
        return "greed"
    return "extreme_greed"


def fetch_crypto_fear_greed_history(limit: int = 0) -> dict[str, int]:
    """Daily Crypto Fear & Greed, ``{date: value}``. ``limit=0`` = full history."""
    def load() -> dict:
        payload = json.loads(_get(f"https://api.alternative.me/fng/?limit={limit}"))
        return payload.get("data", [])

    rows = _cached(f"crypto_fng_{limit}", load)
    out: dict[str, int] = {}
    for row in rows:
        try:
            date = time.strftime("%Y-%m-%d", time.gmtime(int(row["timestamp"])))
            out[date] = int(row["value"])
        except (KeyError, TypeError, ValueError):
            continue
    if not out:
        raise SentimentIndexUnavailable("crypto fear & greed returned no rows")
    return out


def fetch_crypto_fear_greed() -> SentimentReading:
    """Latest Crypto Fear & Greed reading."""
    history = fetch_crypto_fear_greed_history(limit=2)
    date = max(history)
    value = float(history[date])
    return SentimentReading("crypto_fear_greed", date, value, _crypto_label(value))


def _vix_label(value: float) -> str:
    if value < 15:
        return "complacent"
    if value < 20:
        return "calm"
    if value < 30:
        return "elevated"
    return "panic"


def fetch_vix_history(years: int = 2) -> dict[str, float]:
    """Daily VIX closes, ``{date: close}`` (skips unfinished sessions)."""
    def load() -> dict:
        url = ("https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX"
               f"?range={years}y&interval=1d")
        return json.loads(_get(url))

    payload = _cached(f"vix_{years}", load)
    try:
        result = payload["chart"]["result"][0]
        stamps = result["timestamp"]
        closes = result["indicators"]["quote"][0]["close"]
    except (KeyError, IndexError, TypeError) as exc:
        raise SentimentIndexUnavailable(f"VIX payload unusable: {exc}") from exc
    out: dict[str, float] = {}
    for stamp, close in zip(stamps, closes):
        if close is None:
            continue
        out[time.strftime("%Y-%m-%d", time.gmtime(stamp))] = float(close)
    if not out:
        raise SentimentIndexUnavailable("VIX returned no usable closes")
    return out


def fetch_vix() -> SentimentReading:
    """Latest VIX close."""
    history = fetch_vix_history(years=1)
    date = max(history)
    value = history[date]
    return SentimentReading("vix", date, round(value, 2), _vix_label(value))


def _yahoo_closes(symbol: str, years: int = 1) -> dict[str, float]:
    def load() -> dict:
        url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}"
               f"?range={years}y&interval=1d")
        return json.loads(_get(url))

    payload = _cached(f"yq_{symbol.replace('=', '_')}_{years}", load)
    try:
        result = payload["chart"]["result"][0]
        stamps = result["timestamp"]
        closes = result["indicators"]["quote"][0]["close"]
    except (KeyError, IndexError, TypeError) as exc:
        raise SentimentIndexUnavailable(f"{symbol} payload unusable: {exc}") from exc
    return {
        time.strftime("%Y-%m-%d", time.gmtime(stamp)): float(close)
        for stamp, close in zip(stamps, closes) if close is not None
    }


def _gold_oil_label(value: float) -> str:
    """High ratios mean oil is cheap relative to gold — a classic stress read."""
    if value >= 45:
        return "stress"
    if value >= 30:
        return "elevated"
    if value >= 20:
        return "normal"
    return "risk_on"


def fetch_gold_oil_ratio() -> SentimentReading:
    """Gold / WTI crude — a macro stress gauge (both legs from Yahoo futures)."""
    gold = _yahoo_closes("GC=F")
    oil = _yahoo_closes("CL=F")
    shared = sorted(set(gold) & set(oil))
    if not shared:
        raise SentimentIndexUnavailable("no overlapping gold/oil sessions")
    date = shared[-1]
    if oil[date] <= 0:
        raise SentimentIndexUnavailable("oil close is non-positive")
    ratio = gold[date] / oil[date]
    return SentimentReading("gold_oil_ratio", date, round(ratio, 2), _gold_oil_label(ratio))


__all__ = [
    "SentimentIndexUnavailable",
    "SentimentReading",
    "fetch_crypto_fear_greed",
    "fetch_crypto_fear_greed_history",
    "fetch_gold_oil_ratio",
    "fetch_vix",
    "fetch_vix_history",
]
