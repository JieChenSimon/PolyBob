"""Tests for the EDGAR daily-index insider feed.

This module exists because the validated US edge was structurally unactable: the
quarterly bulk datasets it was measured on are published weeks late, so the
twenty-day window always fell inside an unpublished quarter and the detector
could only ever answer "unknown". These tests pin the parsing and — more
importantly — the coverage semantics, since a feed that quietly reports "no
cluster" for days it never read would reintroduce the exact defect the rest of
this work removed.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from libs.data import sec_daily_insider as daily
from libs.data.sec_daily_insider import (
    ClusterEvent,
    DailyInsiderUnavailable,
    parse_form4,
    scan_window,
)

FORM4 = """
<SEC-DOCUMENT>
<ownershipDocument>
    <issuer><issuerTradingSymbol>ACME</issuerTradingSymbol></issuer>
    <reportingOwner><reportingOwnerId>
        <rptOwnerName>{owner}</rptOwnerName>
    </reportingOwnerId></reportingOwner>
    <nonDerivativeTransaction>
        <transactionCoding><transactionCode>{code}</transactionCode></transactionCoding>
        <transactionAmounts>
            <transactionShares><value>{shares}</value></transactionShares>
            <transactionPricePerShare><value>{price}</value></transactionPricePerShare>
        </transactionAmounts>
    </nonDerivativeTransaction>
</ownershipDocument>
</SEC-DOCUMENT>
"""


def _form4(owner="Jane Doe", code="P", shares=1000, price=100.0):
    return FORM4.format(owner=owner, code=code, shares=shares, price=price)


# ------------------------------------------------------------------ parsing
def test_open_market_purchase_is_parsed():
    purchase = parse_form4(_form4())
    assert purchase is not None
    assert purchase.symbol == "ACME"
    assert purchase.owner == "Jane Doe"
    assert purchase.value_usd == pytest.approx(100_000.0)


def test_award_is_not_a_purchase():
    """Code A is a grant: it says nothing about what the insider thinks it's worth."""
    assert parse_form4(_form4(code="A")) is None


def test_sale_is_not_a_purchase():
    assert parse_form4(_form4(code="S")) is None


def test_multiple_transactions_are_summed():
    doc = _form4()
    extra = """
    <nonDerivativeTransaction>
        <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
        <transactionAmounts>
            <transactionShares><value>500</value></transactionShares>
            <transactionPricePerShare><value>100</value></transactionPricePerShare>
        </transactionAmounts>
    </nonDerivativeTransaction>"""
    doc = doc.replace("</ownershipDocument>", extra + "</ownershipDocument>")
    assert parse_form4(doc).value_usd == pytest.approx(150_000.0)


def test_garbage_is_not_a_filing():
    assert parse_form4("<html>404 not found</html>") is None


def test_missing_ticker_is_skipped():
    doc = _form4().replace("ACME", "NONE")
    assert parse_form4(doc) is None


# --------------------------------------------------------------- day scanning
def _install_day(monkeypatch, filings_by_cik, day):
    """Fake an EDGAR day: {cik: [(path, form4_text), ...]}."""
    rows = [(cik, f"Issuer {cik}", path)
            for cik, filings in filings_by_cik.items() for path, _ in filings]
    texts = {path: text for filings in filings_by_cik.values() for path, text in filings}

    monkeypatch.setattr(daily, "_fetch_index", lambda d: list(rows))
    fetched: list[str] = []

    def fake_get(url, **kwargs):
        path = url.split("/Archives/", 1)[1]
        fetched.append(path)
        return texts[path].encode()

    monkeypatch.setattr(daily, "http_get_bytes", fake_get)
    monkeypatch.setattr(daily.time, "sleep", lambda s: None)
    return fetched


@pytest.fixture()
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(daily, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(daily, "_cache_path", lambda d: tmp_path / f"{d:%Y%m%d}.json")
    return tmp_path


def test_two_insiders_on_one_issuer_is_a_cluster(cache_dir, monkeypatch):
    _install_day(monkeypatch, {
        "111": [("a.txt", _form4(owner="Jane Doe")),
                ("b.txt", _form4(owner="John Roe"))],
    }, date(2026, 7, 30))

    events = daily.scan_day(date(2026, 7, 30))
    assert len(events) == 1
    assert events[0].symbol == "ACME"
    assert events[0].insiders == 2
    assert events[0].value_usd == pytest.approx(200_000.0)


def test_one_filing_issuer_is_never_fetched(cache_dir, monkeypatch):
    """The pre-filter: a single Form 4 cannot be a cluster, so skip the download.

    On a representative day this cut 712 filings to 217 — without it the feed is
    too expensive to run at all.
    """
    fetched = _install_day(monkeypatch, {
        "111": [("a.txt", _form4(owner="Jane Doe")),
                ("b.txt", _form4(owner="John Roe"))],
        "222": [("solo.txt", _form4(owner="Solo Filer"))],
    }, date(2026, 7, 30))

    daily.scan_day(date(2026, 7, 30))
    assert "solo.txt" not in fetched
    assert sorted(fetched) == ["a.txt", "b.txt"]


def test_same_insider_filing_twice_is_not_a_cluster(cache_dir, monkeypatch):
    """Two filings, one person — the mechanism needs independent insiders."""
    _install_day(monkeypatch, {
        "111": [("a.txt", _form4(owner="Jane Doe")),
                ("b.txt", _form4(owner="Jane Doe"))],
    }, date(2026, 7, 30))

    assert daily.scan_day(date(2026, 7, 30)) == []


def test_small_purchases_are_below_the_validated_threshold(cache_dir, monkeypatch):
    _install_day(monkeypatch, {
        "111": [("a.txt", _form4(owner="Jane Doe", shares=1, price=10)),
                ("b.txt", _form4(owner="John Roe", shares=1, price=10))],
    }, date(2026, 7, 30))

    assert daily.scan_day(date(2026, 7, 30)) == []


def test_a_past_day_is_cached_and_not_refetched(cache_dir, monkeypatch):
    fetched = _install_day(monkeypatch, {
        "111": [("a.txt", _form4(owner="Jane Doe")),
                ("b.txt", _form4(owner="John Roe"))],
    }, date(2026, 7, 30))

    daily.scan_day(date(2026, 7, 30))
    count = len(fetched)
    daily.scan_day(date(2026, 7, 30))
    assert len(fetched) == count, "a completed day must be fetched exactly once"


def test_cache_only_mode_never_fetches(cache_dir, monkeypatch):
    """What the API path uses: a page load must not trigger thousands of requests."""
    _install_day(monkeypatch, {"111": [("a.txt", _form4())]}, date(2026, 7, 30))
    with pytest.raises(DailyInsiderUnavailable):
        daily.scan_day(date(2026, 7, 30), allow_fetch=False)


# ------------------------------------------------------------------ coverage
def test_window_reports_days_it_could_not_read(cache_dir, monkeypatch):
    """The point of the whole module: unread days must be visible, not assumed."""
    monkeypatch.setattr(daily, "scan_day",
                        lambda day, allow_fetch=True: (_ for _ in ()).throw(
                            DailyInsiderUnavailable("cold")))

    scan = scan_window(date(2026, 7, 30), window_days=5, allow_fetch=False)
    assert scan.complete is False
    assert scan.days_missing
    assert scan.events == []


def test_window_is_complete_when_every_day_reads(cache_dir, monkeypatch):
    event = ClusterEvent("ACME", "2026-07-29", 2, 200_000.0)
    monkeypatch.setattr(daily, "scan_day",
                        lambda day, allow_fetch=True: [event] if day.day == 29 else [])

    scan = scan_window(date(2026, 7, 30), window_days=5)
    assert scan.complete is True
    assert scan.for_symbol("ACME") == [event]
    assert scan.for_symbol("OTHER") == []


def test_weekends_are_not_counted_as_missing(cache_dir, monkeypatch):
    """EDGAR publishes no weekend index; that is not a gap in coverage."""
    monkeypatch.setattr(daily, "scan_day", lambda day, allow_fetch=True: [])

    scan = scan_window(date(2026, 8, 3), window_days=7)   # a Monday
    assert scan.complete is True
    for day in scan.days_covered:
        assert date.fromisoformat(day).weekday() < 5


def test_max_fetch_days_bounds_the_work(cache_dir, monkeypatch):
    """A cold cache warms over several runs instead of blocking one for minutes."""
    calls: list[date] = []

    def counting(day, allow_fetch=True):
        calls.append(day)
        return []

    monkeypatch.setattr(daily, "scan_day", counting)
    scan = scan_window(date(2026, 7, 30), window_days=20, max_fetch_days=2)

    assert len(calls) == 2
    assert scan.complete is False


def test_events_round_trip_through_the_cache_format():
    event = ClusterEvent("ACME", "2026-07-30", 3, 250_000.0, issuer="Acme Inc")
    assert ClusterEvent.from_dict(json.loads(json.dumps(event.to_dict()))) == event
