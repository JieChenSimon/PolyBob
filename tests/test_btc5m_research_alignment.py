"""Known-answer tests for the causal BTC 5m research price alignment."""

from scripts import btc5m_mispricing


def test_minute_bars_exclude_the_forming_decision_bar(monkeypatch):
    # OKX rows are newest first and use [open time, open, high, low, close, volume].
    rows = [
        [120_000, "101", "102", "100", "102", "9001"],
        [60_000, "100", "101", "99", "101", "8001"],
        [0, "99", "100", "98", "100", "7001"],
    ]
    monkeypatch.setattr(btc5m_mispricing, "_get", lambda _url: {"data": rows})

    bars = btc5m_mispricing.btc_minute_bars(0, 120_000)

    assert bars == [(0, 99.0, 100.0), (60_000, 100.0, 101.0)]
    assert all(timestamp < 120_000 for timestamp, _, _ in bars)


def test_closed_market_resolves_up_token_by_label_not_array_order():
    market = {
        "outcomes": '["DOWN", "UP"]',
        "outcomePrices": '["1", "0"]',
        "clobTokenIds": '["down-token", "up-token"]',
    }

    token, outcome_up = btc5m_mispricing._closed_market_contract(market)

    assert token == "up-token"
    assert outcome_up == 0
