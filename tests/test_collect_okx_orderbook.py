from datetime import UTC, datetime

import pytest

from scripts.collect_okx_orderbook import normalize_snapshot


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
