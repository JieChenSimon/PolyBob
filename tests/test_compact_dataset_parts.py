import pyarrow as pa
import pyarrow.parquet as pq

from scripts.compact_dataset_parts import apply_plan, plan


def test_sidecar_compaction_preserves_rows_and_source(tmp_path):
    source_root = tmp_path / "parts"
    partition = source_root / "bars" / "symbol=AAA"
    partition.mkdir(parents=True)
    for index in range(2):
        pq.write_table(
            pa.table({"event_at": [f"2026-01-0{index + 1}"], "close": [100.0 + index]}),
            partition / f"part-{index}.parquet",
        )

    payload = plan("bars", source_root=source_root, destination_root=tmp_path / "compacted")
    result = apply_plan(payload)

    assert result["status"] == "APPLIED"
    assert result["verified"] is True
    assert result["source_preserved"] is True
    assert result["input_files"] == 2
    assert result["input_rows"] == 2
    output = tmp_path / "compacted" / "bars" / "symbol=AAA" / "part-compact-00000.parquet"
    assert output.exists()
    assert pq.ParquetFile(output).metadata.num_rows == 2
    assert len(list(partition.glob("*.parquet"))) == 2
