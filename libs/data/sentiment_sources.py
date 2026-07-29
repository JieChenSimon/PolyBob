"""Market-sentiment sources: global indices and A-share risk appetite.

These feed two things: the dashboard's "global sentiment" panel, and — more
importantly — a *conditioning* variable for the strategies. The confirmed edges
so far are all conditional bets on crowd behaviour (dragon-tiger reversal,
altcoin retail crowding, insider clusters), and crowd behaviour is not constant:
it is stronger when speculative appetite is high. The limit-up count is the
cleanest daily read on that appetite in A-shares, so it can gate when the
reversal signal is applied rather than being decoration on a page.

Sources, all real and free:

- **Sina global indices** — Dow, Nasdaq, Hang Seng, Nikkei quotes. Requires a
  ``finance.sina.com.cn`` Referer and is GBK-encoded.
- **Eastmoney limit-up pool** — how many A-shares closed limit-up, the standard
  speculative-sentiment thermometer.
- **Eastmoney breadth** — advancing vs declining counts across the market.
"""

from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

CACHE_DIR = Path("data/market_cache")
_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"


class SentimentUnavailable(RuntimeError):
    """Raised when a sentiment source fails — never substitute invented numbers."""


def _get(url: str, referer: str | None = None, encoding: str = "utf-8", timeout: float = 20.0) -> str:
    headers = {"User-Agent": _UA}
    if referer:
        headers["Referer"] = referer
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode(encoding, "replace")
    except Exception as exc:  # noqa: BLE001 - surface provider failure honestly
        raise SentimentUnavailable(f"{url.split('?')[0]}: {exc}") from exc


@dataclass(frozen=True)
class IndexQuote:
    key: str
    name: str
    price: float
    change: float
    change_pct: float


GLOBAL_INDICES = {
    "int_dji": "Dow Jones", "int_nasdaq": "Nasdaq",
    "int_hangseng": "Hang Seng", "int_nikkei": "Nikkei 225",
    "int_sp500": "S&P 500",
}


def fetch_global_indices() -> list[IndexQuote]:
    """Real global index quotes from Sina (GBK, needs the Sina referer)."""
    codes = ",".join(GLOBAL_INDICES)
    text = _get(f"https://hq.sinajs.cn/list={codes}",
                referer="https://finance.sina.com.cn", encoding="gbk")
    quotes: list[IndexQuote] = []
    for line in text.strip().splitlines():
        if '="' not in line:
            continue
        left, right = line.split('="', 1)
        key = left.split("hq_str_")[-1].strip()
        parts = right.rstrip('";').split(",")
        if len(parts) < 4:
            continue
        try:
            quotes.append(IndexQuote(
                key=key, name=parts[0] or GLOBAL_INDICES.get(key, key),
                price=float(parts[1]), change=float(parts[2]),
                change_pct=float(parts[3]),
            ))
        except (TypeError, ValueError):
            continue
    if not quotes:
        raise SentimentUnavailable("Sina returned no usable index quotes")
    return quotes


@dataclass(frozen=True)
class RiskAppetite:
    """Daily speculative-appetite reading for A-shares."""

    date: str
    limit_up_count: int

    @property
    def regime(self) -> str:
        """Coarse regime label — thresholds reflect typical A-share ranges."""
        if self.limit_up_count >= 80:
            return "hot"          # speculative froth
        if self.limit_up_count >= 40:
            return "warm"
        return "cold"


def fetch_limit_up_count(date: str | None = None) -> RiskAppetite:
    """Number of A-shares that closed limit-up on ``date`` (YYYY-MM-DD)."""
    day = (date or datetime.now().strftime("%Y-%m-%d")).replace("-", "")
    url = ("https://push2ex.eastmoney.com/getTopicZTPool"
           "?ut=7eea3edcaed734bea9cbfc24409ed989&dpt=wz.ztzt"
           f"&Pageindex=0&pagesize=1&sort=fbt%3Aasc&date={day}")
    payload = json.loads(_get(url))
    data = payload.get("data") or {}
    count = data.get("tc")
    if count is None:
        raise SentimentUnavailable(f"no limit-up pool for {day} (non-trading day?)")
    iso = f"{day[:4]}-{day[4:6]}-{day[6:]}"
    return RiskAppetite(date=iso, limit_up_count=int(count))


def fetch_limit_up_history(days: int = 120) -> dict[str, int]:
    """Limit-up counts for recent sessions, ``{date: count}`` (cached)."""
    cache = CACHE_DIR / f"limit_up_{days}.json"
    if cache.exists() and (time.time() - cache.stat().st_mtime) < 12 * 3600:
        try:
            return json.loads(cache.read_text())
        except Exception:  # noqa: BLE001
            pass
    out: dict[str, int] = {}
    today = datetime.now()
    for offset in range(days):
        day = today.timestamp() - offset * 86400
        date = datetime.fromtimestamp(day).strftime("%Y-%m-%d")
        try:
            out[date] = fetch_limit_up_count(date).limit_up_count
        except SentimentUnavailable:
            continue          # weekend/holiday — simply absent, never faked
        time.sleep(0.12)
    if not out:
        raise SentimentUnavailable("no limit-up history available")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(out))
    return out


__all__ = [
    "GLOBAL_INDICES",
    "IndexQuote",
    "RiskAppetite",
    "SentimentUnavailable",
    "fetch_global_indices",
    "fetch_limit_up_count",
    "fetch_limit_up_history",
]
