import pyarrow as pa
import pyarrow.parquet as pq
import pytest

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
    assert len(result["groups"][0]["input_sha256"]) == 2
    assert result["outputs"][0]["output_sha256"]
    assert result["outputs"][0]["output_schema_sha256"] == result["groups"][0]["schema_sha256"]
    output = tmp_path / "compacted" / "bars" / "symbol=AAA" / "part-compact-00000.parquet"
    assert output.exists()
    assert pq.ParquetFile(output).metadata.num_rows == 2
    assert len(list(partition.glob("*.parquet"))) == 2


def test_compaction_refuses_source_changed_after_plan(tmp_path):
    source_root = tmp_path / "parts"
    partition = source_root / "bars" / "symbol=AAA"
    partition.mkdir(parents=True)
    source = partition / "part-0.parquet"
    pq.write_table(pa.table({"event_at": ["2026-01-01"], "close": [100.0]}), source)
    payload = plan("bars", source_root=source_root, destination_root=tmp_path / "compacted")
    pq.write_table(pa.table({"event_at": ["2026-01-01"], "close": [101.0]}), source)

    with pytest.raises(RuntimeError, match="source changed after plan"):
        apply_plan(payload)
