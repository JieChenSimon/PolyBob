"""Real market data sources for PolyBob's three instrument domains.

Hard project constraint: every strategy / backtest / win-rate / return figure
must come from REAL data. Simulated or placeholder data is only ever allowed
inside unit tests to exercise code paths — never to judge a strategy.

Domains and their live sources (all verified reachable):

- **Altcoins**: OKX public candles (Binance is geo-blocked 451 from here).
- **US equities**: Yahoo Finance chart API.
- **A-shares**: Tencent gtimg (same source the dashboard already uses).

Every fetcher returns plain ``DailyBars`` (dates + closes), is cached on disk so
repeated backtests do not hammer the providers, and raises ``DataUnavailable``
rather than silently returning fake data.
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

CACHE_DIR = Path("data/market_cache")
CACHE_TTL_SECONDS = 6 * 3600
_UA = "Mozilla/5.0 (PolyBob real-data research)"


class DataUnavailable(RuntimeError):
    """Raised when real data cannot be fetched — never substitute fake data."""


@dataclass(frozen=True)
class DailyBars:
    symbol: str
    domain: str          # "altcoin" | "us_equity" | "a_share"
    dates: list[str]
    closes: list[float]
    source: str
    opens: list[float] | None = None
    highs: list[float] | None = None
    lows: list[float] | None = None
    volumes: list[float] | None = None

    def __len__(self) -> int:
        return len(self.closes)

    @property
    def is_usable(self) -> bool:
        return len(self.closes) >= 200

    @property
    def has_ohlc(self) -> bool:
        return self.opens is not None and len(self.opens) == len(self.closes)


def _http_get(url: str, timeout: float = 20.0) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": _UA})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except Exception as exc:  # noqa: BLE001 - surface provider failure honestly
        raise DataUnavailable(f"{url} -> {type(exc).__name__}: {exc}") from exc


def _cache_path(key: str) -> Path:
    safe = key.replace("/", "_").replace(":", "_")
    return CACHE_DIR / f"{safe}.json"


def _cached_json(key: str, loader) -> dict:
    path = _cache_path(key)
    if path.exists() and (time.time() - path.stat().st_mtime) < CACHE_TTL_SECONDS:
        try:
            return json.loads(path.read_text())
        except Exception:  # noqa: BLE001 - corrupt cache falls through to refetch
            pass
    payload = loader()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))
    return payload


# --------------------------------------------------------------------- altcoin
def okx_usdt_universe(limit: int = 400) -> list[str]:
    """Real list of OKX USDT spot instruments (the altcoin universe)."""
    def load() -> dict:
        raw = _http_get("https://www.okx.com/api/v5/public/instruments?instType=SPOT")
        return json.loads(raw)

    payload = _cached_json("okx_universe", load)
    ids = [
        item["instId"]
        for item in payload.get("data", [])
        if item.get("instId", "").endswith("-USDT") and item.get("state") == "live"
    ]
    return sorted(ids)[:limit]


def fetch_altcoin_daily(inst_id: str, days: int = 720) -> DailyBars:
    """Daily closes for an OKX spot pair, oldest → newest.

    OKX ``history-candles`` returns newest-first in pages of 100; we page back
    with the ``after`` cursor until we have ``days`` bars.
    """
    def load() -> dict:
        rows: list[list[str]] = []
        after = ""
        while len(rows) < days:
            url = (
                "https://www.okx.com/api/v5/market/history-candles"
                f"?instId={urllib.parse.quote(inst_id)}&bar=1D&limit=100"
            )
            if after:
                url += f"&after={after}"
            payload = json.loads(_http_get(url))
            page = payload.get("data") or []
            if not page:
                break
            rows.extend(page)
            after = page[-1][0]
            if len(page) < 100:
                break
        return {"rows": rows}

    rows = _cached_json(f"okx_{inst_id}_{days}", load).get("rows", [])
    if not rows:
        raise DataUnavailable(f"OKX returned no candles for {inst_id}")
    rows = sorted(rows, key=lambda r: int(r[0]))[-days:]   # oldest first
    dates = [time.strftime("%Y-%m-%d", time.gmtime(int(r[0]) / 1000)) for r in rows]
    return DailyBars(
        inst_id, "altcoin", dates, [float(r[4]) for r in rows], "okx",
        opens=[float(r[1]) for r in rows], highs=[float(r[2]) for r in rows],
        lows=[float(r[3]) for r in rows], volumes=[float(r[5]) for r in rows],
    )


def fetch_funding_rate_daily(inst_id: str, days: int = 400) -> dict[str, float]:
    """Daily mean funding rate for an OKX perp swap (e.g. ``SOL-USDT-SWAP``).

    Funding settles every 8h; we average per UTC day. Positive = longs pay
    shorts (crowded longs). Returns ``{date: mean_rate}``.
    """
    swap_id = inst_id if inst_id.endswith("-SWAP") else f"{inst_id}-SWAP"

    def load() -> dict:
        rows: list[dict] = []
        after = ""
        while len(rows) < days * 3:
            url = (
                "https://www.okx.com/api/v5/public/funding-rate-history"
                f"?instId={urllib.parse.quote(swap_id)}&limit=100"
            )
            if after:
                url += f"&after={after}"
            payload = json.loads(_http_get(url))
            page = payload.get("data") or []
            if not page:
                break
            rows.extend(page)
            after = page[-1]["fundingTime"]
            if len(page) < 100:
                break
        return {"rows": rows}

    rows = _cached_json(f"okx_funding_{swap_id}_{days}", load).get("rows", [])
    if not rows:
        raise DataUnavailable(f"OKX returned no funding history for {swap_id}")
    by_day: dict[str, list[float]] = {}
    for row in rows:
        day = time.strftime("%Y-%m-%d", time.gmtime(int(row["fundingTime"]) / 1000))
        try:
            by_day.setdefault(day, []).append(float(row["fundingRate"]))
        except (KeyError, TypeError, ValueError):
            continue
    return {day: sum(v) / len(v) for day, v in sorted(by_day.items())}


# ------------------------------------------------------------------ us equity
def fetch_us_equity_daily(symbol: str, years: int = 5) -> DailyBars:
    """Daily closes from Yahoo Finance (drops the unfinished current bar)."""
    def load() -> dict:
        url = (
            f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}"
            f"?range={years}y&interval=1d"
        )
        return json.loads(_http_get(url))

    payload = _cached_json(f"yahoo_{symbol}_{years}", load)
    try:
        result = payload["chart"]["result"][0]
        stamps = result["timestamp"]
        quote_closes = result["indicators"]["quote"][0]["close"]
    except (KeyError, IndexError, TypeError) as exc:
        raise DataUnavailable(f"Yahoo payload unusable for {symbol}: {exc}") from exc

    quote = result["indicators"]["quote"][0]
    dates: list[str] = []
    closes: list[float] = []
    opens: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    volumes: list[float] = []
    for i, (stamp, close) in enumerate(zip(stamps, quote_closes)):
        o = quote.get("open", [None])[i] if i < len(quote.get("open", [])) else None
        if close is None or o is None:   # unfinished/halted session — never fabricate
            continue
        dates.append(time.strftime("%Y-%m-%d", time.gmtime(stamp)))
        closes.append(float(close))
        opens.append(float(o))
        highs.append(float(quote["high"][i]) if quote.get("high") and quote["high"][i] is not None else float(close))
        lows.append(float(quote["low"][i]) if quote.get("low") and quote["low"][i] is not None else float(close))
        volumes.append(float(quote["volume"][i]) if quote.get("volume") and quote["volume"][i] is not None else 0.0)
    if not closes:
        raise DataUnavailable(f"Yahoo returned no usable closes for {symbol}")
    return DailyBars(symbol.upper(), "us_equity", dates, closes, "yahoo",
                     opens=opens, highs=highs, lows=lows, volumes=volumes)


# --------------------------------------------------------------------- a-share
def _tencent_code(symbol: str) -> str:
    """`600519` / `600519.SH` -> `sh600519` (infers exchange from the code)."""
    code = symbol.split(".")[0].strip()
    if not code.isdigit() or len(code) != 6:
        raise DataUnavailable(f"invalid A-share code: {symbol}")
    if code.startswith("920"):
        prefix = "bj"
    elif code[0] in "659":
        prefix = "sh"
    elif code[0] in "01232":
        prefix = "sz"
    elif code[0] in "48":
        prefix = "bj"
    else:
        raise DataUnavailable(f"cannot infer exchange for {symbol}")
    return f"{prefix}{code}"


def fetch_a_share_daily(symbol: str, days: int = 1200) -> DailyBars:
    """Daily closes for an A-share from Tencent gtimg (forward-adjusted)."""
    tencent = _tencent_code(symbol)

    def load() -> dict:
        url = (
            "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
            f"?param={tencent},day,,,{days},qfq"
        )
        return json.loads(_http_get(url))

    payload = _cached_json(f"tencent_{tencent}_{days}", load)
    node = (payload.get("data") or {}).get(tencent) or {}
    rows = node.get("qfqday") or node.get("day") or []
    if not rows:
        raise DataUnavailable(f"Tencent returned no bars for {symbol}")
    # row = [date, open, close, high, low, volume]
    return DailyBars(
        tencent.upper(), "a_share", [r[0] for r in rows], [float(r[2]) for r in rows], "tencent",
        opens=[float(r[1]) for r in rows], highs=[float(r[3]) for r in rows],
        lows=[float(r[4]) for r in rows], volumes=[float(r[5]) for r in rows],
    )


__all__ = [
    "DailyBars",
    "DataUnavailable",
    "fetch_a_share_daily",
    "fetch_altcoin_daily",
    "fetch_funding_rate_daily",
    "fetch_us_equity_daily",
    "okx_usdt_universe",
]
