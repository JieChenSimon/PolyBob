import io
import json
import tarfile

import pyarrow.parquet as pq

from scripts import normalize_okx_historical_l2 as normalizer


def _archive(path):
    lines = [
        {"instId": "BTC-USDT", "action": "snapshot", "ts": "1000",
         "asks": [["101", "2", "1"]], "bids": [["99", "3", "1"]]},
        {"instId": "BTC-USDT", "action": "update", "ts": "1010",
         "asks": [["101", "0", "0"], ["102", "4", "1"]], "bids": []},
        {"instId": "BTC-USDT", "action": "update", "ts": "2000",
         "asks": [], "bids": [["99", "0", "0"], ["98", "5", "1"]]},
    ]
    body = b"".join(json.dumps(item).encode() + b"\n" for item in lines)
    with tarfile.open(path, "w:gz") as bundle:
        info = tarfile.TarInfo("BTC.data")
        info.size = len(body)
        bundle.addfile(info, io.BytesIO(body))


def test_normalize_reconstructs_snapshot_updates_and_records_provenance(monkeypatch, tmp_path):
    archive = tmp_path / "source.tar.gz"
    output = tmp_path / "sampled.parquet"
    manifest = tmp_path / "manifest.jsonl"
    _archive(archive)
    monkeypatch.setattr(normalizer, "MANIFEST", manifest)

    result = normalizer.normalize_archive(archive, output, interval_ms=1000)
    table = pq.read_table(output).to_pandas()

    assert result["line_count"] == 3
    assert result["snapshot_count"] == 1
    assert result["update_count"] == 2
    assert result["invalid_count"] == 0
    assert len(table) == 2
    assert table.iloc[0]["best_bid"] == 99.0
    assert table.iloc[0]["best_ask"] == 101.0
    assert table.iloc[-1]["best_bid"] == 98.0
    assert table.iloc[-1]["bid_depth_top20"] == 5.0
    assert table.iloc[-1]["history_scope"] == "historical_orderbook_sampled"
    assert table.iloc[-1]["raw_archive_sha256"] == result["raw_archive_sha256"]
    assert manifest.exists()
