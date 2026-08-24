import datetime as dt
import json

from libs.data import data_lake


def test_raw_responses_are_content_addressed_and_deduplicated(tmp_path, monkeypatch):
    monkeypatch.setattr(data_lake, "ROOT", tmp_path / "datasets")
    monkeypatch.setattr(data_lake, "RAW_ROOT", data_lake.ROOT / "raw")
    monkeypatch.setattr(data_lake, "PART_ROOT", data_lake.ROOT / "parts")
    monkeypatch.setattr(data_lake, "MANIFEST", data_lake.ROOT / "manifest.jsonl")
    first = data_lake.record_raw("btc5m", b"payload", source="okx", request="u")
    second = data_lake.record_raw("btc5m", b"payload", source="okx", request="u")
    assert first["sha256"] == second["sha256"]
    assert len(data_lake.read_manifest()) == 1


def test_normalized_records_are_reusable_parquet_parts(tmp_path, monkeypatch):
    monkeypatch.setattr(data_lake, "ROOT", tmp_path / "datasets")
    monkeypatch.setattr(data_lake, "RAW_ROOT", data_lake.ROOT / "raw")
    monkeypatch.setattr(data_lake, "PART_ROOT", data_lake.ROOT / "parts")
    monkeypatch.setattr(data_lake, "MANIFEST", data_lake.ROOT / "manifest.jsonl")
    rows = [{
        "symbol": "BTC-USDT", "event_at": "2026-08-24T00:00:00+00:00",
        "close": 100.0, "source": "okx",
    }]
    result = data_lake.write_records(
        "btc_1m", rows, source="okx", observed_at=dt.datetime.now(dt.UTC)
    )
    assert result["rows"] == 1
    assert result["status"] == "written"
    assert data_lake.inventory()["btc_1m"]["rows"] == 1
    assert json.loads(data_lake.MANIFEST.read_text())["dataset"] == "btc_1m"


def test_normalized_payload_is_idempotent_across_observation_times(tmp_path, monkeypatch):
    monkeypatch.setattr(data_lake, "ROOT", tmp_path / "datasets")
    monkeypatch.setattr(data_lake, "RAW_ROOT", data_lake.ROOT / "raw")
    monkeypatch.setattr(data_lake, "PART_ROOT", data_lake.ROOT / "parts")
    monkeypatch.setattr(data_lake, "MANIFEST", data_lake.ROOT / "manifest.jsonl")
    row = {"symbol": "BTC-USDT", "event_at": "2026-08-24T00:00:00+00:00", "close": 100.0}
    data_lake.write_records("bars", [row], source="okx", observed_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC))
    data_lake.write_records("bars", [row], source="okx", observed_at=dt.datetime(2026, 1, 2, tzinfo=dt.UTC))
    entries = [item for item in data_lake.read_manifest() if item.get("kind") == "normalized"]
    assert len(entries) == 1


def test_normalized_batch_is_partitioned_by_all_symbols(tmp_path, monkeypatch):
    monkeypatch.setattr(data_lake, "ROOT", tmp_path / "datasets")
    monkeypatch.setattr(data_lake, "RAW_ROOT", data_lake.ROOT / "raw")
    monkeypatch.setattr(data_lake, "PART_ROOT", data_lake.ROOT / "parts")
    monkeypatch.setattr(data_lake, "MANIFEST", data_lake.ROOT / "manifest.jsonl")
    rows = [
        {"symbol": "AAPL", "event_at": "2026-08-24T00:00:00+00:00", "close": 1.0},
        {"symbol": "MSFT", "event_at": "2026-08-24T00:00:00+00:00", "close": 2.0},
    ]
    data_lake.write_records("bars", rows, source="test", partition_by=("symbol",))
    assert (data_lake.PART_ROOT / "bars" / "symbol=AAPL").exists()
    assert (data_lake.PART_ROOT / "bars" / "symbol=MSFT").exists()
