import json

from scripts.audit_data_layout import audit


def test_layout_audit_classifies_files_and_keeps_duplicate_status_fail_closed(tmp_path):
    store = tmp_path / "store" / "daily_bars" / "symbol=AAA"
    cache = tmp_path / "market_cache"
    parts = tmp_path / "datasets" / "parts" / "bars" / "symbol=AAA"
    raw = tmp_path / "datasets" / "raw" / "provider"
    replay = tmp_path / ".kernel_replay_demo"
    for directory in (store, cache, parts, raw, replay):
        directory.mkdir(parents=True)
    (store / "a.parquet").write_bytes(b"same")
    (store / "a2.parquet").write_bytes(b"same")
    (cache / "b.json").write_bytes(b"same")
    (parts / "c.parquet").write_bytes(b"same")
    (raw / "d.bin").write_bytes(b"raw")
    (replay / "e.sqlite3-wal").write_bytes(b"wal")
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(json.dumps({"path": str(parts / "c.parquet")}) + "\n")

    report = audit(
        (tmp_path / "store", tmp_path / "market_cache", tmp_path / "datasets", replay),
        manifest=manifest,
    )

    assert report["total_files"] == 6
    assert report["by_kind"]["store"]["files"] == 2
    assert report["by_kind"]["cache"]["files"] == 1
    assert report["by_kind"]["normalized"]["files"] == 1
    assert report["by_kind"]["raw_evidence"]["files"] == 1
    assert report["by_kind"]["replay_tmp"]["files"] == 1
    assert report["manifest"]["existing_paths"] == 1
    assert report["duplicate_analysis"]["exact_hash_duplicates_confirmed"] == 0
    assert report["duplicate_analysis"]["metadata_candidate_group_count"] >= 1
