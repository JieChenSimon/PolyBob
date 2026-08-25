from datetime import UTC, datetime

import pandas as pd
import pytest

from libs.data import real_sources, store


def _rows():
    return [
        *[
            {
                "timestamp": int(datetime(2024, 1, 1, hour, tzinfo=UTC).timestamp() * 1000),
                "interest_8h": rate,
            }
            for hour, rate in ((0, 0.001), (8, -0.0002), (16, 0.0003))
        ],
        {"timestamp": int(datetime(2024, 1, 2, 0, tzinfo=UTC).timestamp() * 1000), "interest_8h": 0.0003},
    ]


def test_deribit_8h_settlement_daily_sum_and_explicit_store_mirror(monkeypatch):
    monkeypatch.setattr(real_sources, "_cached_json", lambda key, loader: {"rows": _rows()})
    monkeypatch.setattr(real_sources.time, "time", lambda: datetime(2024, 1, 3, tzinfo=UTC).timestamp())
    written = {}

    def write(dataset, symbol, rows):
        written.update(symbol=symbol, rows=rows)

    monkeypatch.setattr(store, "write", write)
    monkeypatch.setattr(store, "read", lambda dataset, symbol: pd.DataFrame(
        columns=["event_date", "rate", "source"]
    ))
    result = real_sources.fetch_deribit_funding_rate_daily("BTC-PERPETUAL", days=3)
    assert result["2024-01-01"] == pytest.approx(0.0011)
    assert written["symbol"] == "BTC-PERPETUAL"
    assert written["rows"][0]["source"] == "deribit_interest_8h_settlement_daily_sum_v2"


def test_deribit_rejects_unsupported_contract():
    with pytest.raises(real_sources.DataUnavailable):
        real_sources.fetch_deribit_funding_rate_daily("SOL-USDT-SWAP")


def test_deribit_bad_payload_is_not_zero_filled(monkeypatch):
    monkeypatch.setattr(real_sources, "_cached_json", lambda key, loader: {"rows": [{"timestamp": "bad"}]})
    with pytest.raises(real_sources.DataUnavailable):
        real_sources.fetch_deribit_funding_rate_daily("ETH-PERPETUAL", days=1)
