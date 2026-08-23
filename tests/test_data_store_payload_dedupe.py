"""Regression coverage for idempotent provider observations."""

import datetime as dt

from libs.data import store


def test_identical_provider_payload_is_one_observation_and_replays_consistently(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "STORE_ROOT", tmp_path / "data")
    dataset = store.Dataset(
        name="dedupe_probe",
        value_columns=("close",),
        description="test dataset",
    )
    rows = [{"event_date": "2026-08-24", "close": 101.0}]
    stamp = dt.datetime(2026, 8, 24, tzinfo=dt.UTC)
    assert store.write(dataset, "TEST", rows, fetched_at=stamp, deduplicate_payload=True) == 1
    assert store.write(dataset, "TEST", rows, fetched_at=stamp + dt.timedelta(minutes=1), deduplicate_payload=True) == 0
    assert len(list((tmp_path / "data" / "dedupe_probe" / "symbol=TEST").glob("*.parquet"))) == 1
    replay = store.read(dataset, "TEST", as_of=stamp + dt.timedelta(hours=1))
    assert replay.iloc[0]["close"] == 101.0
