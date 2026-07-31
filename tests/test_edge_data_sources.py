"""Tests for the edge data sources that produced the three confirmed findings.

These guard the parsing and — more importantly — the *timing discipline* that
makes each result valid. Every edge here is an event study, so the single most
dangerous bug is using a date the market could not have known. Synthetic rows
exercise the code paths only; the results themselves come from real data.
"""

from __future__ import annotations

import pytest

from libs.data.a_share_flow import BillboardEvent, capturable_return
from libs.data.sec_insider import InsiderTrade, _parse_date, cluster_buys
from libs.data.sentiment_indices import (
    SentimentReading,
    _crypto_label,
    _gold_oil_label,
    _vix_label,
)
from libs.data.sentiment_sources import RiskAppetite


def _event(d1=None, d2=None, d5=None, explain="") -> BillboardEvent:
    return BillboardEvent(
        trade_date="2026-07-01", code="600519", name="TEST", change_rate=5.0,
        net_amount=1e6, deal_amount=2e6, turnover_amount=1e7, free_market_cap=1e9,
        explanation="trigger", explain=explain, buy_seats="", sell_seats="",
        d1=d1, d2=d2, d5=d5, d10=None,
    )


# --- A-share dragon-tiger: the timing rule the edge depends on -------------


def test_capturable_return_excludes_the_untradeable_overnight_gap():
    # The list publishes after the event close, so entry is the D1 close.
    # D1=+10%, D5=+21% -> capturable is 1.21/1.10-1 = 10%, NOT 21%.
    event = _event(d1=10.0, d5=21.0)
    assert capturable_return(event, 5) == pytest.approx(0.10, abs=1e-9)


def test_capturable_return_is_none_without_forward_data():
    assert capturable_return(_event(d1=1.0), 5) is None       # no D5 yet
    assert capturable_return(_event(d5=5.0), 5) is None       # no D1 anchor


def test_institutional_buy_parsed_from_exchange_note():
    # Seat fields are numeric codes; the count lives in the EXPLAIN text.
    assert _event(explain="1家机构买入，成功率22.11%").institutional_buy_count == 1
    assert _event(explain="3家机构买入").institutional_buy is True
    assert _event(explain="无机构参与").institutional_buy is False
    assert _event().institutional_buy_count == 0


def test_net_ratio_normalises_by_turnover():
    assert _event().net_ratio == pytest.approx(0.1)


# --- SEC insider: filing date is the only public date ----------------------


def test_sec_date_parsing():
    assert _parse_date("31-MAR-2026") == "2026-03-31"
    assert _parse_date("garbage") == ""


def _trade(code="P", shares=1000.0, price=100.0, date="2026-03-31", symbol="ABC"):
    return InsiderTrade(symbol=symbol, issuer="Test Co", filing_date=date,
                        trans_date="2026-03-20", trans_code=code,
                        shares=shares, price=price)


def test_only_open_market_purchases_count_as_buys():
    assert _trade("P").is_open_market_buy is True
    assert _trade("S").is_open_market_buy is False
    assert _trade("A").is_open_market_buy is False   # award, not a purchase
    assert _trade("M").is_open_market_buy is False   # option exercise
    assert _trade("S").is_open_market_sell is True


def test_cluster_buys_requires_multiple_insiders_and_size():
    trades = [
        _trade(symbol="AAA"), _trade(symbol="AAA"),          # 2 insiders, same day
        _trade(symbol="BBB"),                                 # single insider
        _trade(symbol="CCC", shares=1.0, price=1.0),          # too small
        _trade(symbol="CCC", shares=1.0, price=1.0),
    ]
    clusters = cluster_buys(trades, min_insiders=2, min_value_usd=50_000)
    assert ("AAA", "2026-03-31") in clusters
    assert ("BBB", "2026-03-31") not in clusters
    assert ("CCC", "2026-03-31") not in clusters
    assert clusters[("AAA", "2026-03-31")] == pytest.approx(200_000.0)


def test_cluster_keyed_on_filing_date_not_trade_date():
    # Using trans_date would be look-ahead: it is not public until the filing.
    clusters = cluster_buys([_trade(), _trade()], min_insiders=2)
    assert list(clusters)[0][1] == "2026-03-31"      # filing_date


# --- sentiment gauge labelling --------------------------------------------


@pytest.mark.parametrize("value,label", [
    (10, "extreme_fear"), (29, "fear"), (50, "neutral"), (65, "greed"), (90, "extreme_greed"),
])
def test_crypto_fear_greed_labels(value, label):
    assert _crypto_label(value) == label


@pytest.mark.parametrize("value,label", [
    (12, "complacent"), (18.21, "calm"), (25, "elevated"), (40, "panic"),
])
def test_vix_labels(value, label):
    assert _vix_label(value) == label


def test_gold_oil_labels_flag_stress_when_oil_is_cheap():
    assert _gold_oil_label(48.85) == "stress"
    assert _gold_oil_label(35) == "elevated"
    assert _gold_oil_label(25) == "normal"
    assert _gold_oil_label(15) == "risk_on"


def test_risk_appetite_regimes():
    assert RiskAppetite("2026-07-29", 100).regime == "hot"
    assert RiskAppetite("2026-07-29", 55).regime == "warm"
    assert RiskAppetite("2026-07-29", 10).regime == "cold"


def test_sentiment_reading_serialises():
    reading = SentimentReading("vix", "2026-07-28", 18.21, "calm")
    assert reading.to_dict() == {
        "index": "vix", "date": "2026-07-28", "value": 18.21, "label": "calm",
    }
