"""Tests for per-instrument edge detection.

These pin the behaviour that was actually wrong on the dashboard: the verdict
claimed a validated edge on any US ticker because *some* US ticker had insider
buying, and reported the A-share dragon-tiger trap as clear on every stock while
never fetching the list at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pytest

from libs.quant.edge_instance import (
    EdgeStatus,
    detect,
    detect_billboard_listing,
    detect_insider_cluster,
    detect_retail_crowding,
)


@dataclass(frozen=True)
class _Trade:
    """Minimal stand-in for libs.data.sec_insider.InsiderTrade."""

    symbol: str
    filing_date: str
    shares: float = 1000.0
    price: float = 100.0
    trans_code: str = "P"

    @property
    def is_open_market_buy(self) -> bool:
        return self.trans_code == "P" and self.shares > 0

    @property
    def value_usd(self) -> float:
        return self.shares * self.price


def _source(trades):
    return lambda year, quarter: list(trades)


# ------------------------------------------------------------- insider cluster
def test_cluster_on_this_symbol_is_active():
    trades = [_Trade("ACME", "2026-07-28"), _Trade("ACME", "2026-07-28")]
    result = detect_insider_cluster(
        "ACME", as_of=date(2026, 7, 30), trade_source=_source(trades)
    )
    assert result.status is EdgeStatus.ACTIVE
    assert "2026-07-28" in result.evidence_zh


def test_cluster_on_a_different_symbol_does_not_transfer():
    """The bug: one ticker's edge was being claimed on every ticker."""
    trades = [_Trade("ACME", "2026-07-28"), _Trade("ACME", "2026-07-28")]
    result = detect_insider_cluster(
        "OTHER", as_of=date(2026, 7, 30), trade_source=_source(trades)
    )
    assert result.status is EdgeStatus.INACTIVE


def test_single_insider_is_not_a_cluster():
    """The single-buyer control did not clear the hurdle; it is not the edge."""
    trades = [_Trade("ACME", "2026-07-28")]
    result = detect_insider_cluster(
        "ACME", as_of=date(2026, 7, 30), trade_source=_source(trades)
    )
    assert result.status is EdgeStatus.INACTIVE


def test_small_purchases_are_below_the_validated_threshold():
    trades = [_Trade("ACME", "2026-07-28", shares=1.0, price=100.0),
              _Trade("ACME", "2026-07-28", shares=1.0, price=100.0)]
    result = detect_insider_cluster(
        "ACME", as_of=date(2026, 7, 30), trade_source=_source(trades)
    )
    assert result.status is EdgeStatus.INACTIVE


def test_stale_cluster_is_no_longer_the_trade_that_was_measured():
    """The 20-session drift measured from the filing has already happened."""
    trades = [_Trade("ACME", "2026-01-05"), _Trade("ACME", "2026-01-05")]
    result = detect_insider_cluster(
        "ACME", as_of=date(2026, 7, 30), trade_source=_source(trades)
    )
    assert result.status is EdgeStatus.INACTIVE


def test_unavailable_sec_data_is_unknown_not_inactive():
    """"I could not check" must never render as "there is no edge"."""
    from libs.data.sec_insider import SecDataUnavailable

    def broken(year, quarter):
        raise SecDataUnavailable("network down")

    result = detect_insider_cluster("ACME", as_of=date(2026, 7, 30), trade_source=broken)
    assert result.status is EdgeStatus.UNKNOWN


# ------------------------------------------------------------ retail crowding
@dataclass(frozen=True)
class _Point:
    date: str
    long_short_ratio: float
    open_interest: float = 0.0


def test_crowded_long_is_active():
    points = [_Point(f"2026-06-{d:02d}", 1.0) for d in range(1, 31)]
    points.append(_Point("2026-07-01", 5.0))          # a clear extreme
    result = detect_retail_crowding("SOL-USDT", positioning_source=lambda ccy: points)
    assert result.status is EdgeStatus.ACTIVE


def test_ordinary_positioning_is_inactive():
    points = [_Point(f"2026-06-{d:02d}", 1.0 + d * 0.01) for d in range(1, 31)]
    points.append(_Point("2026-07-01", 1.0))          # below the trailing window
    result = detect_retail_crowding("SOL-USDT", positioning_source=lambda ccy: points)
    assert result.status is EdgeStatus.INACTIVE


def test_short_history_is_unknown():
    points = [_Point("2026-06-01", 1.0)]
    result = detect_retail_crowding("SOL-USDT", positioning_source=lambda ccy: points)
    assert result.status is EdgeStatus.UNKNOWN


# ------------------------------------------------------------ billboard listing
@dataclass(frozen=True)
class _Event:
    code: str
    trade_date: str


def test_listed_stock_triggers_the_avoidance_condition():
    events = [_Event("600519", "2026-07-28")]
    result = detect_billboard_listing(
        "600519", as_of=date(2026, 7, 30), event_source=lambda **kw: events
    )
    assert result.status is EdgeStatus.ACTIVE
    assert "龙虎榜" in result.evidence_zh


def test_unlisted_stock_is_checked_and_clear():
    """The old code reported this as clear without ever fetching the list."""
    events = [_Event("000001", "2026-07-28")]
    result = detect_billboard_listing(
        "600519", as_of=date(2026, 7, 30), event_source=lambda **kw: events
    )
    assert result.status is EdgeStatus.INACTIVE


def test_billboard_outage_is_unknown():
    from libs.data.a_share_flow import FlowDataUnavailable

    def broken(**kwargs):
        raise FlowDataUnavailable("provider 503")

    result = detect_billboard_listing(
        "600519", as_of=date(2026, 7, 30), event_source=broken
    )
    assert result.status is EdgeStatus.UNKNOWN


# ------------------------------------------------------------------ dispatcher
def test_an_edge_without_a_detector_cannot_be_claimed():
    """No detector means no way to know — which is not permission."""
    result = detect("some_future_edge", "AAPL")
    assert result.status is EdgeStatus.UNKNOWN
    assert "检测器" in result.evidence_zh


def test_serialisation_round_trip():
    trades = [_Trade("ACME", "2026-07-28"), _Trade("ACME", "2026-07-28")]
    payload = detect_insider_cluster(
        "ACME", as_of=date(2026, 7, 30), trade_source=_source(trades)
    ).to_dict()
    assert payload["status"] == "active"
    assert payload["strategy"] == "us_insider_cluster_buy"
    assert payload["detail"]["filing_date"] == "2026-07-28"


def test_quarterly_bulk_data_cannot_see_recent_filings():
    """A structural limit of the data source, pinned so it is not mistaken for a bug.

    The SEC publishes the Form 345 bulk datasets weeks after a quarter closes,
    so the quarter containing a filing from the last 20 days is normally not out
    yet. The backtest was valid on history; live detection needs EDGAR's daily
    feed, which is not wired up. The detector must say that rather than return a
    bare "unavailable" that reads like a passing network blip — and it must
    never return INACTIVE, which would claim the edge was checked and absent.
    """
    from libs.data.sec_insider import SecDataUnavailable

    def unpublished(year, quarter):
        raise SecDataUnavailable(f"{year}Q{quarter} not published yet")

    result = detect_insider_cluster(
        "AAPL", as_of=date(2026, 8, 1), trade_source=unpublished
    )
    assert result.status is EdgeStatus.UNKNOWN
    assert "EDGAR" in result.evidence_zh
    assert "2026Q3" in result.evidence_zh


# ---------------------------------------------------- live path (EDGAR daily)
def test_live_path_reports_a_cluster_on_this_symbol(monkeypatch):
    """The live feed is what makes this edge actable at all."""
    from libs.data import sec_daily_insider as daily
    from libs.data.sec_daily_insider import ClusterEvent, ClusterScan

    scan = ClusterScan(events=[ClusterEvent("ACME", "2026-07-30", 3, 400_000.0)],
                       days_covered=["2026-07-30"])
    monkeypatch.setattr(daily, "scan_window", lambda *a, **k: scan)

    result = detect_insider_cluster("ACME", as_of=date(2026, 8, 1))
    assert result.status is EdgeStatus.ACTIVE
    assert "EDGAR" in result.evidence_zh
    assert result.detail["insiders"] == 3


def test_live_path_says_inactive_only_with_full_coverage(monkeypatch):
    from libs.data import sec_daily_insider as daily
    from libs.data.sec_daily_insider import ClusterScan

    monkeypatch.setattr(daily, "scan_window",
                        lambda *a, **k: ClusterScan(days_covered=["2026-07-30"]))

    result = detect_insider_cluster("ACME", as_of=date(2026, 8, 1))
    assert result.status is EdgeStatus.INACTIVE


def test_incomplete_coverage_is_unknown_not_inactive(monkeypatch):
    """Nothing found in the days you managed to read is not "nothing happened".

    This is the same silent-pass defect as the A-share trap, one layer down: a
    cold cache would otherwise report every US ticker as cleanly edge-free.
    """
    from libs.data import sec_daily_insider as daily
    from libs.data.sec_daily_insider import ClusterScan

    monkeypatch.setattr(daily, "scan_window", lambda *a, **k: ClusterScan(
        days_covered=["2026-07-30"], days_missing=["2026-07-29", "2026-07-28"]))

    result = detect_insider_cluster("ACME", as_of=date(2026, 8, 1))
    assert result.status is EdgeStatus.UNKNOWN
    assert "warm_insider_cache" in result.evidence_zh


def test_live_path_does_not_fetch_by_default(monkeypatch):
    """A page load must never trigger the thousands of requests a warm costs."""
    from libs.data import sec_daily_insider as daily
    from libs.data.sec_daily_insider import ClusterScan

    seen = {}

    def spy(as_of, window_days, allow_fetch=True, max_fetch_days=None):
        seen["allow_fetch"] = allow_fetch
        return ClusterScan(days_covered=["2026-07-30"])

    monkeypatch.setattr(daily, "scan_window", spy)
    detect_insider_cluster("ACME", as_of=date(2026, 8, 1))
    assert seen["allow_fetch"] is False
