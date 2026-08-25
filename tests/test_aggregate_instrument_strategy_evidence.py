import json

from scripts.aggregate_instrument_strategy_evidence import build_evidence


def _standalone(path, symbol, target_status):
    path.write_text(json.dumps({
        "signal_contract": {"strategy_id": "test_strategy"},
        "results": [{
            "symbol": symbol,
            "domain": "us_equity",
            "metrics": {
                "total_return": 0.2,
                "max_drawdown": 0.1,
                "sharpe": 1.0,
                "closed_trade_count": 10,
                "execution_evidence": {"missing_depth_trade_count": 10},
            },
            "return_target": {"status": target_status, "annualized_return": None},
            "stability": {"status": "FAIL_UNSTABLE"},
            "execution_evidence": {"missing_depth_trade_count": 10},
            "promotion": "BLOCKED",
        }],
    }))


def test_aggregator_preserves_unknown_and_never_promotes(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    _standalone(data / "cross_sectional_standalone_us_oos_candidate_20_30_5.json", "AAA", "FAIL")
    _standalone(data / "cross_sectional_standalone_a_oos_candidate_20_30_5.json", "000001", "UNKNOWN")
    (data / "crypto_tsmom_multifold_replay.json").write_text(json.dumps({"folds": []}))

    report = build_evidence(tmp_path)

    assert report["promotion"] == "BLOCKED"
    assert report["target_status_counts"]["FAIL"] == 1
    assert report["target_status_counts"]["UNKNOWN"] == 1
    assert report["instruments"]["000001"][0]["monthly_target_status"] == "UNKNOWN"
