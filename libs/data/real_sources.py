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
from dataclasses import dataclass
from pathlib import Path

from libs.data.http_client import HttpFetchError, http_get_bytes

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
    # Optional per-bar values are ``float | None``: a gap in the vendor's data is
    # a gap, not a zero and not a copy of the close. Consumers must decide what
    # an unknown bar means for them rather than being handed a plausible number.
    highs: list[float | None] | None = None
    lows: list[float | None] | None = None
    volumes: list[float | None] | None = None

    def __len__(self) -> int:
        return len(self.closes)

    @property
    def is_usable(self) -> bool:
        return len(self.closes) >= 200

    @property
    def has_ohlc(self) -> bool:
        return self.opens is not None and len(self.opens) == len(self.closes)


def _http_get(url: str, timeout: float = 20.0) -> bytes:
    """Fetch over the shared pooled session — see libs/data/http_client.py."""
    try:
        return http_get_bytes(url, timeout=timeout, headers={"User-Agent": _UA})
    except HttpFetchError as exc:
        raise DataUnavailable(str(exc)) from exc


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


# --------------------------------------------------------------- store mirror
def _mirror(bars: "DailyBars") -> "DailyBars":
    """Record what we just observed in the bitemporal store, then hand it back.

    Every fetch passes through here so that ``libs/data/store`` accumulates a real
    ``fetched_at`` for each bar. That is what lets an experiment pin an ``as_of``
    and get the same sample size twice — the property this project lacked when the
    insider study returned n=753 one day and n=667 the next off "the same" cache.

    Mirroring is best-effort by design. A store write failing must not take down a
    page that already has its data in hand; the cost of a missed write is a gap in
    the observation history, which is visible, rather than a broken read path.
    """
    try:
        from libs.data import store

        rows = []
        for i, date in enumerate(bars.dates):
            def at(seq, idx=i):
                return None if seq is None or idx >= len(seq) else seq[idx]

            rows.append({
                "symbol": bars.symbol,
                store.EVENT_DATE: date,
                "open": at(bars.opens),
                "high": at(bars.highs),
                "low": at(bars.lows),
                "close": bars.closes[i],
                "volume": at(bars.volumes),
                "source": bars.source,
            })
        store.write(store.DAILY_BARS, bars.symbol, rows)
    except Exception as exc:  # noqa: BLE001
        logger.debug("store mirror skipped for %s: %s", bars.symbol, exc)
    return bars


def bars_as_of(
    symbol: str, domain: str, when, *, start=None, end=None
) -> "DailyBars":
    """Bars as they were **known** at ``when`` — the point-in-time read.

    This is the function research must use. ``fetch_*`` returns today's view of
    history, which is the right answer for a live scan and the wrong one for a
    backtest: today's view has been restated, backfilled and survivorship-cleaned,
    none of which was available on the day the decision would have been made.

    Raises :class:`DataUnavailable` when the store holds nothing at that cut,
    rather than falling back to a live fetch. A silent fallback would defeat the
    entire purpose: the run would quietly read the future.
    """
    from libs.data import store

    frame = store.read(store.DAILY_BARS, symbol, as_of=when, start=start, end=end)
    if len(frame) == 0:
        raise DataUnavailable(
            f"store 里没有 {symbol} 在 {when} 之前的观测。"
            f"先运行 scripts/warm_cache.py,或把 as_of 放宽到有数据的时点。"
        )

    def col(name):
        if name not in frame.columns:
            return None
        values = [None if v != v else v for v in frame[name].tolist()]  # NaN -> None
        return None if all(v is None for v in values) else values

    closes = [float(v) for v in frame["close"].tolist()]
    sources = [str(v) for v in frame["source"].tolist() if v]
    # Deliberately not mirrored: this is a read. Writing back would stamp
    # historical rows with today's fetched_at and destroy the very ordering the
    # as-of query depends on.
    return DailyBars(
        symbol=symbol,
        domain=domain,
        dates=[str(d) for d in frame[store.EVENT_DATE].tolist()],
        closes=closes,
        source=f"store@{sources[-1] if sources else 'unknown'}",
        opens=col("open"),
        highs=col("high"),
        lows=col("low"),
        volumes=col("volume"),
    )


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
    return _mirror(DailyBars(
        inst_id, "altcoin", dates, [float(r[4]) for r in rows], "okx",
        opens=[float(r[1]) for r in rows], highs=[float(r[2]) for r in rows],
        lows=[float(r[3]) for r in rows], volumes=[float(r[5]) for r in rows],
    ))


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
    highs: list[float | None] = []
    lows: list[float | None] = []
    volumes: list[float | None] = []

    def _optional(field: str, index: int) -> float | None:
        """A missing field is ``None``. It is never a number.

        This used to substitute ``close`` for a missing high/low and ``0.0`` for
        a missing volume. Both are fabrications, and the volume one was
        load-bearing: six missing bars out of three hundred moved the 20-day
        volume ratio from 1.00 to 0.70 and flipped the verdict's volume gate
        from ``confirming`` to ``drying_up`` — the page told you nobody was
        trading a stock because the vendor dropped 2% of its fields.
        """
        series = quote.get(field)
        if not series or index >= len(series) or series[index] is None:
            return None
        try:
            return float(series[index])
        except (TypeError, ValueError):
            return None

    for i, (stamp, close) in enumerate(zip(stamps, quote_closes)):
        o = quote.get("open", [None])[i] if i < len(quote.get("open", [])) else None
        if close is None or o is None:   # unfinished/halted session — never fabricate
            continue
        dates.append(time.strftime("%Y-%m-%d", time.gmtime(stamp)))
        closes.append(float(close))
        opens.append(float(o))
        highs.append(_optional("high", i))
        lows.append(_optional("low", i))
        volumes.append(_optional("volume", i))
    if not closes:
        raise DataUnavailable(f"Yahoo returned no usable closes for {symbol}")
    return _mirror(DailyBars(symbol.upper(), "us_equity", dates, closes, "yahoo",
                             opens=opens, highs=highs, lows=lows, volumes=volumes))


# --------------------------------------------------------------------- a-share
def _tencent_code(symbol: str) -> str:
    """`600519` / `600519.SH` / `SH600519` -> `sh600519`.

    Accepts an already-prefixed symbol because callers round-trip our own output
    (e.g. the verdict endpoint re-fetches bars using the normalised ``SH600519``
    it just returned); rejecting that would make the symbol non-idempotent.

    An explicit prefix is **honoured, not re-inferred**. Inference reads the
    leading digits, which is right for ordinary stocks but wrong for indices:
    the CSI 300 is ``sh000300``, yet ``000300`` infers to Shenzhen. Discarding
    the caller's prefix there does not fail — it silently returns a *different
    instrument*, which is the worst way for market data to be wrong.
    """
    raw = symbol.split(".")[0].strip().upper()
    if raw[:2] in {"SH", "SZ", "BJ"} and raw[2:].isdigit() and len(raw[2:]) == 6:
        return raw.lower()
    code = raw
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
    return _mirror(DailyBars(
        tencent.upper(), "a_share", [r[0] for r in rows], [float(r[2]) for r in rows], "tencent",
        opens=[float(r[1]) for r in rows], highs=[float(r[3]) for r in rows],
        lows=[float(r[4]) for r in rows], volumes=[float(r[5]) for r in rows],
    ))


__all__ = [
    "DailyBars",
    "DataUnavailable",
    "bars_as_of",
    "fetch_a_share_daily",
    "fetch_altcoin_daily",
    "fetch_funding_rate_daily",
    "fetch_us_equity_daily",
    "okx_usdt_universe",
]
