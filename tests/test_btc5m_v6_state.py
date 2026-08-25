import json

import pyarrow as pa
import pyarrow.parquet as pq

from libs.data import data_lake
from scripts import btc5m_mispricing


def _sample():
    return {
        "window_start": 1_000,
        "window_end": 1_300,
        "decision_ts": 1_120,
        "date": "1970-01-01",
        "model_probability": 0.6,
        "market_probability": 0.5,
        "outcome_up": 1,
        "market_token_up": "token",
        "gamma_raw_sha256": "g" * 64,
        "clob_raw_sha256": "c" * 64,
        "okx_raw_sha256": "o" * 64,
    }


def test_v6_snapshot_lineage_requires_one_normalized_row_per_window(tmp_path, monkeypatch):
    sample = _sample()
    checkpoint = tmp_path / "checkpoint.json"
    checkpoint.write_text(json.dumps({"spec": "v6", "samples": [sample]}))
    part = tmp_path / "part.parquet"
    row = btc5m_mispricing._normalized_record(sample)
    row["observed_at"] = "2026-08-25T00:00:00+00:00"
    pq.write_table(pa.Table.from_pylist([row]), part)

    monkeypatch.setattr(btc5m_mispricing, "CHECKPOINT", checkpoint)
    monkeypatch.setattr(btc5m_mispricing, "NORMALIZED_DATASET", "test_v6")
    monkeypatch.setattr(
        btc5m_mispricing,
        "read_manifest",
        lambda: [{"kind": "normalized", "dataset": "test_v6", "path": str(part)}],
    )

    snapshot = btc5m_mispricing._snapshot_lineage([sample])

    assert snapshot["status"] == "consistent"
    assert snapshot["sample_rows"] == 1
    assert snapshot["normalized_rows"] == 1
    assert snapshot["unique_windows"] == 1
    assert len(snapshot["checkpoint_sha256"]) == 64
    assert len(snapshot["raw_sha_set_sha256"]) == 64


def test_v6_snapshot_lineage_blocks_missing_window(tmp_path, monkeypatch):
    sample = _sample()
    checkpoint = tmp_path / "checkpoint.json"
    checkpoint.write_text(json.dumps({"spec": "v6", "samples": [sample]}))
    monkeypatch.setattr(btc5m_mispricing, "CHECKPOINT", checkpoint)
    monkeypatch.setattr(btc5m_mispricing, "NORMALIZED_DATASET", "test_v6")
    monkeypatch.setattr(btc5m_mispricing, "read_manifest", lambda: [])

    snapshot = btc5m_mispricing._snapshot_lineage([sample])

    assert snapshot["status"] == "blocked_inconsistent"
    assert snapshot["normalized_rows"] == 0


def test_live_minute_collection_does_not_recreate_retired_dataset(monkeypatch):
    captured = []
    monkeypatch.setattr(
        btc5m_mispricing,
        "_get_with_digest",
        lambda url: ({"data": [["1000", "1", "0", "0", "2", "0"]]}, "o" * 64),
    )
    monkeypatch.setattr(
        data_lake,
        "write_records",
        lambda dataset, records, **kwargs: captured.append((dataset, list(records), kwargs)),
    )

    rows, _ = btc5m_mispricing._btc_minute_bars_with_provenance(0, 2000)

    assert rows == [(1000, 1.0, 2.0)]
    assert captured[0][0] == "btc_1m_bars_live"
    assert captured[0][0] != "btc_1m_bars"
