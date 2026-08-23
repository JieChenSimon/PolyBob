"""Machine-readable data semantics and idempotent provider mirroring."""

from __future__ import annotations

import datetime as dt

from libs.data import real_sources, store


def _bars(close: float = 101.0) -> real_sources.DailyBars:
    return real_sources.DailyBars(
        symbol="AAPL",
        domain="us_equity",
        dates=["2026-08-11", "2026-08-12"],
        closes=[100.0, close],
        source="test-provider",
        opens=[99.0, 100.0],
        highs=[101.0, max(102.0, close)],
        lows=[98.0, 99.0],
        volumes=[1_000.0, 1_100.0],
        price_basis="provider_quote_adjustment_unknown",
    )


def test_core_dataset_contracts_are_machine_readable():
    contracts = store.dataset_contracts()

    assert set(contracts) == {dataset.name for dataset in store.DATASETS}
    for contract in contracts.values():
        assert contract["instrument"] == "symbol"
        assert contract["effective_at"] == store.EVENT_DATE
        assert contract["observed_at"] == store.FETCHED_AT
        assert contract["pit_level"] == "collected_observation_time"
        assert contract["strict_historical_pit"] is False
        assert contract["price_basis"]

    assert contracts["daily_bars"]["price_basis"] == "row_declared"
    assert "price_basis" in contracts["daily_bars"]["value_columns"]


def test_same_provider_payload_is_mirrored_once(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "STORE_ROOT", tmp_path / "store")
    first = _bars()

    real_sources._mirror(first)
    files_after_first = list(store.DAILY_BARS.path("AAPL").glob("*.parquet"))
    real_sources._mirror(first)
    files_after_second = list(store.DAILY_BARS.path("AAPL").glob("*.parquet"))

    assert len(files_after_first) == 1
    assert files_after_second == files_after_first
    frame = store.read(store.DAILY_BARS, "AAPL")
    assert list(frame["close"]) == [100.0, 101.0]
    assert set(frame["price_basis"]) == {"provider_quote_adjustment_unknown"}


def test_changed_provider_payload_creates_a_new_vintage(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "STORE_ROOT", tmp_path / "store")
    monkeypatch.setattr(
        store,
        "now_utc",
        lambda: dt.datetime(2026, 8, 13, 1, tzinfo=dt.UTC),
    )
    real_sources._mirror(_bars(101.0))
    monkeypatch.setattr(
        store,
        "now_utc",
        lambda: dt.datetime(2026, 8, 13, 2, tzinfo=dt.UTC),
    )
    real_sources._mirror(_bars(103.0))

    assert len(list(store.DAILY_BARS.path("AAPL").glob("*.parquet"))) == 2
    before = store.read(
        store.DAILY_BARS,
        "AAPL",
        as_of=dt.datetime(2026, 8, 13, 1, 30, tzinfo=dt.UTC),
    )
    after = store.read(
        store.DAILY_BARS,
        "AAPL",
        as_of=dt.datetime(2026, 8, 13, 2, 30, tzinfo=dt.UTC),
    )
    assert float(before["close"].iloc[-1]) == 101.0
    assert float(after["close"].iloc[-1]) == 103.0
