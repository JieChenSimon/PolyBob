from __future__ import annotations

from libs.data import real_sources


def test_yahoo_fetcher_normalizes_ohlcv_from_real_adjusted_close(monkeypatch):
    payload = {
        "chart": {"result": [{
            "timestamp": [1_756_000_000, 1_756_086_400],
            "indicators": {
                "quote": [{
                    "open": [10.0, 20.0], "high": [11.0, 22.0],
                    "low": [9.0, 18.0], "close": [10.0, 20.0],
                    "volume": [100.0, 200.0],
                }],
                "adjclose": [{"adjclose": [5.0, 10.0]}],
            },
        }]}
    }
    monkeypatch.setattr(real_sources, "_cached_json", lambda key, loader: payload)
    monkeypatch.setattr(real_sources, "_mirror", lambda bars: bars)

    bars = real_sources.fetch_us_equity_daily("TEST")

    assert bars.price_basis == "yahoo_split_dividend_adjusted_ohlcv"
    assert bars.closes == [5.0, 10.0]
    assert bars.opens == [5.0, 10.0]
    assert bars.highs == [5.5, 11.0]
    assert bars.lows == [4.5, 9.0]
    assert bars.volumes == [200.0, 400.0]
