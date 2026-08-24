from __future__ import annotations

import json

from scripts.deep_drawdown_kernel_replay import _symbols_from_file


def test_symbols_from_file_accepts_discovery_manifest(tmp_path):
    path = tmp_path / "discovery.json"
    path.write_text(json.dumps({
        "candidates": [
            {"symbol": "AAPL", "status": "READY_FOR_RESEARCH"},
            {"symbol": "UNKNOWN", "status": "UNKNOWN"},
        ]
    }), encoding="utf-8")

    assert _symbols_from_file(str(path)) == ["AAPL"]


def test_symbols_from_file_accepts_candidate_symbol_list(tmp_path):
    path = tmp_path / "symbols.json"
    path.write_text(json.dumps({"candidate_symbols": ["BTC-USDT", " AAPL "]}), encoding="utf-8")

    assert _symbols_from_file(str(path)) == ["BTC-USDT", "AAPL"]
