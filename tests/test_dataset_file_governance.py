from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from scripts.dataset_file_governance import _file_inventory, compact_dataset


def test_inventory_counts_small_files(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.json").write_text("{}")
    (source / "b.json").write_text("{}")
    report = _file_inventory(source)
    assert report["files"] == 2
    assert report["small_files_lt_64KiB"] == 2
    assert report["by_extension"][".json"]["files"] == 2


def test_compaction_writes_partitioned_copy_and_manifest(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    table = pa.table({"symbol": ["A", "A", "B"], "event_date": ["2024-01-01"] * 3,
                      "close": [1.0, 1.0, 2.0]})
    pq.write_table(table.slice(0, 2), source / "one.parquet")
    pq.write_table(table.slice(2, 1), source / "two.parquet")
    destination = tmp_path / "compact"
    result = compact_dataset(source, destination, partition_by=("symbol",),
                             deduplicate_exact_rows=True)
    assert result["status"] == "written"
    assert result["source_files"] == 2
    assert result["output_files"] == 2
    assert (destination / "compaction_manifest.json").exists()


def test_compaction_can_keep_latest_observation_per_event_key(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    table = pa.table({
        "symbol": ["BTC-USDT", "BTC-USDT"],
        "event_at": ["2026-08-25T00:00:00Z"] * 2,
        "observed_at": ["2026-08-25T01:00:00Z", "2026-08-25T02:00:00Z"],
        "close": [100.0, 101.0],
    })
    pq.write_table(table, source / "parts.parquet")
    destination = tmp_path / "compact"

    result = compact_dataset(
        source,
        destination,
        partition_by=("symbol",),
        deduplicate_keys=("event_at",),
        latest_by="observed_at",
    )

    assert result["status"] == "written"
    assert result["deduplicate_keys"] == ["event_at"]
    output = next(destination.rglob("*.parquet"))
    rows = pq.read_table(output).to_pylist()
    assert rows == [{
        "event_at": "2026-08-25T00:00:00Z",
        "observed_at": "2026-08-25T02:00:00Z",
        "close": 101.0,
    }]
