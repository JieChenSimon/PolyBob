"""Smoke tests against the live providers. Deselected by default.

The unit suite runs in nine seconds because every provider is mocked, which is
right for a suite you run on every edit — but it means the one constraint this
project actually lives by, *real data only*, has no test at all. When Yahoo
changes a field name or Eastmoney rejects the User-Agent, nothing goes red; the
operator finds out by opening a page and seeing an empty panel.

So these run for real, and are marked ``real_data`` so they stay out of the
default run:

    conda run -n polybob python -m pytest -m real_data -q

They assert *shape and freshness*, never specific prices: a test that pins a
price is broken by tomorrow and teaches you nothing today. What they check is
that the provider still answers, that the payload still parses into the schema
the rest of the code expects, and that a failure raises the domain's own error
instead of quietly returning something empty.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

pytestmark = pytest.mark.real_data


@pytest.fixture(autouse=True)
def bypass_disk_cache(monkeypatch):
    """Force a genuine request on every fetch in this module.

    The data layer caches provider responses for six hours, which is right for
    normal use and wrong here: a cached read would keep passing for six hours
    after a provider started returning 403, which is exactly the failure these
    tests exist to catch. Disabling the cache is what makes them a smoke test
    rather than a test of the cache.
    """
    from libs.data import flow_signals, real_sources

    monkeypatch.setattr(real_sources, "CACHE_TTL_SECONDS", 0)

    def uncached(key, loader, ttl=0):
        return loader()

    monkeypatch.setattr(flow_signals, "_cached", uncached)


def _recent(dates: list[str], max_age_days: int) -> bool:
    """The series must reach近期 — a stale-but-parseable feed is still broken."""
    latest = datetime.fromisoformat(dates[-1][:10]).replace(tzinfo=UTC)
    return datetime.now(UTC) - latest <= timedelta(days=max_age_days)


# ------------------------------------------------------------------- altcoin
def test_okx_daily_bars_are_live_and_well_formed():
    from libs.data.real_sources import fetch_altcoin_daily

    bars = fetch_altcoin_daily("SOL-USDT")
    assert len(bars) >= 200
    assert len(bars.dates) == len(bars.closes)
    assert all(c > 0 for c in bars.closes)
    assert bars.dates == sorted(bars.dates)
    assert _recent(bars.dates, 3), f"OKX series ends at {bars.dates[-1]}"


def test_okx_funding_history_is_live():
    """Funding is part of the altcoin edge's P&L, so it has to be fetchable."""
    from libs.data.real_sources import fetch_funding_rate_daily

    funding = fetch_funding_rate_daily("SOL-USDT")
    assert len(funding) >= 30
    assert all(isinstance(v, float) for v in funding.values())


def test_okx_retail_positioning_is_live():
    from libs.data.flow_signals import fetch_retail_positioning

    points = fetch_retail_positioning("SOL")
    assert len(points) >= 31, "the crowding rule needs a 30-day trailing window"
    assert all(p.long_short_ratio > 0 for p in points)
    assert _recent([p.date for p in points], 3)


# ---------------------------------------------------------------- us equity
def test_yahoo_daily_bars_are_live_and_well_formed():
    from libs.data.real_sources import fetch_us_equity_daily

    bars = fetch_us_equity_daily("AAPL")
    assert len(bars) >= 200
    assert bars.has_ohlc, "the volume and trend checks need OHLC, not just closes"
    assert len(bars.volumes or []) == len(bars.closes)
    assert _recent(bars.dates, 7), f"Yahoo series ends at {bars.dates[-1]}"


def test_sec_form345_is_reachable():
    """The one tradable US edge is built entirely on this dataset.

    The SEC publishes a quarter some weeks after it ends, so "the latest
    quarter" is not a fixed offset from today. The test therefore walks back
    until it finds a published one — what must hold is that *recent* filings are
    reachable, not that any particular quarter is.
    """
    from libs.data.sec_insider import (
        SecDataUnavailable,
        cluster_buys,
        fetch_insider_trades,
    )

    now = datetime.now(UTC)
    year, quarter = now.year, (now.month - 1) // 3 + 1
    trades: list = []
    tried: list[str] = []
    for _ in range(4):
        year, quarter = (year - 1, 4) if quarter == 1 else (year, quarter - 1)
        tried.append(f"{year}Q{quarter}")
        try:
            trades = fetch_insider_trades(year, quarter)
            break
        except SecDataUnavailable:
            continue

    assert trades, f"no published SEC quarter among {', '.join(tried)}"
    assert len(trades) > 1000
    assert any(t.is_open_market_buy for t in trades)
    assert all(t.filing_date for t in trades)
    # The clustering the strategy depends on must produce events.
    assert cluster_buys(trades, min_insiders=2, min_value_usd=50_000.0)


# ------------------------------------------------------------------ a share
def test_tencent_a_share_bars_are_live():
    from libs.data.real_sources import fetch_a_share_daily

    bars = fetch_a_share_daily("600519")
    assert len(bars) >= 200
    assert all(c > 0 for c in bars.closes)
    assert _recent(bars.dates, 7)


def test_eastmoney_billboard_is_live():
    """The measured A-share trap is unusable if this feed cannot be read."""
    from libs.data.a_share_flow import fetch_billboard_events

    events = fetch_billboard_events(max_events=200, use_cache=False)
    assert len(events) >= 100
    assert all(e.code and e.trade_date for e in events)
    assert _recent(sorted(e.trade_date for e in events), 10)


# ------------------------------------------------------------------ failures
def test_an_unknown_symbol_raises_rather_than_returning_empty_data():
    """Absence must be loud. A silent empty series is how fake data creeps in."""
    from libs.data.real_sources import DataUnavailable, fetch_us_equity_daily

    with pytest.raises(DataUnavailable):
        fetch_us_equity_daily("NOT-A-REAL-TICKER-XYZ")


def test_the_pooled_session_survives_a_burst():
    """Several providers in a row must not accumulate sockets."""
    import os
    import subprocess

    from libs.data.http_client import close_session
    from libs.data.real_sources import fetch_altcoin_daily, fetch_us_equity_daily

    def sockets() -> int:
        out = subprocess.run(["lsof", "-nP", "-a", "-p", str(os.getpid()), "-i"],
                             capture_output=True, text=True, check=False).stdout
        return len([line for line in out.splitlines()[1:] if line.strip()])

    close_session()
    fetch_altcoin_daily("SOL-USDT")
    baseline = sockets()
    for symbol in ("ADA-USDT", "LINK-USDT", "AVAX-USDT"):
        fetch_altcoin_daily(symbol)
    fetch_us_equity_daily("MSFT")

    assert sockets() - baseline <= 3
