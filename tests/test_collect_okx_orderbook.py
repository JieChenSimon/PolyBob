from datetime import UTC, datetime
import json

import pytest

from scripts.collect_okx_orderbook import collect_stream, normalize_snapshot


def test_normalize_orderbook_preserves_depth_and_live_scope():
    snapshot = normalize_snapshot("BTC-USDT", {
        "code": "0",
        "data": [{
            "ts": "1760000000000",
            "seqId": 42,
            "asks": [["101", "3", "0", "4"], ["102", "2", "0", "3"]],
            "bids": [["99", "4", "0", "5"], ["98", "1", "0", "2"]],
        }],
    }, observed_at=datetime(2026, 8, 25, tzinfo=UTC))
    assert snapshot["best_bid"] == 99.0
    assert snapshot["best_ask"] == 101.0
    assert snapshot["bid_depth"] == 5.0
    assert snapshot["ask_depth"] == 5.0
    assert snapshot["quote_quality"] == "full_depth"
    assert snapshot["history_scope"] == "live_observation"


def test_normalize_orderbook_rejects_one_sided_book():
    with pytest.raises(ValueError, match="no two-sided"):
        normalize_snapshot("BTC-USDT", {"code": "0", "data": [{"asks": [], "bids": []}]},
                           observed_at=datetime(2026, 8, 25, tzinfo=UTC))


def test_collect_stream_is_bounded_restartable_and_marks_forward_history(monkeypatch, tmp_path):
    calls = []

    def fake_collect(symbols, *, levels):
        calls.append((symbols, levels))
        return {"observed_at": f"2026-08-25T00:00:0{len(calls)}+00:00", "records": len(symbols)}

    monkeypatch.setattr("scripts.collect_okx_orderbook._collect_once", fake_collect)
    monkeypatch.setattr("scripts.collect_okx_orderbook.time.sleep", lambda _: None)
    checkpoint = tmp_path / "checkpoint.json"

    result = collect_stream(["BTC-USDT"], levels=20, interval_seconds=0.5,
                            polls=2, checkpoint=str(checkpoint))

    assert result["history_scope"] == "forward_real_observation"
    assert result["polls"] == 2
    assert len(result["snapshots"]) == 2
    assert calls == [(["BTC-USDT"], 20), (["BTC-USDT"], 20)]
    assert json.loads(checkpoint.read_text())["status"] == "completed"
