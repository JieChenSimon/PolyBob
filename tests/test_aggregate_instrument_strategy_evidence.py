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
    (data / "crypto_tsmom_walk_forward_replay.json").write_text(json.dumps({"folds": []}))

    report = build_evidence(tmp_path)

    assert report["promotion"] == "BLOCKED"
    assert report["target_status_counts"]["FAIL"] == 1
    assert report["target_status_counts"]["UNKNOWN"] == 1
    assert report["instruments"]["000001"][0]["monthly_target_status"] == "UNKNOWN"


def test_deep_drawdown_cases_are_flattened_without_zero_trade_failures(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    for name in (
        "cross_sectional_standalone_us_oos_candidate_20_30_5.json",
        "cross_sectional_standalone_a_oos_candidate_20_30_5.json",
    ):
        (data / name).write_text(json.dumps({"results": []}))
    (data / "crypto_tsmom_multifold_replay.json").write_text(json.dumps({"folds": []}))
    (data / "crypto_tsmom_walk_forward_replay.json").write_text(json.dumps({"folds": []}))
    (data / "deep_drawdown_kernel_replay.json").write_text(json.dumps({
        "results": [
            {"symbol": "AAA", "domain": "us_equity", "events": [],
             "metrics": {"return_target": {"status": "FAIL"}},
             "event_stats": {"oos": {"n_complete": 0}}, "promotion": "BLOCKED"},
            {"symbol": "BBB", "domain": "us_equity", "events": [{"event_id": "e1"}],
             "metrics": {"return_target": {"status": "FAIL"}},
             "event_stats": {"oos": {"n_complete": 1, "mean_net_return": -0.1}},
             "promotion": "BLOCKED"},
        ]
    }))

    report = build_evidence(tmp_path)

    assert report["instruments"]["AAA"][0]["monthly_target_status"] == "UNKNOWN"
    assert report["instruments"]["BBB"][0]["monthly_target_status"] == "FAIL"


def test_latest_standalone_replays_are_part_of_the_gate_matrix(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    for name in (
        "cross_sectional_standalone_us_oos_candidate_20_30_5.json",
        "cross_sectional_standalone_a_oos_candidate_20_30_5.json",
        "cross_sectional_six_frozen_2022.json",
        "cross_sectional_six_breadth05_2022.json",
        "cross_sectional_six_meanrev20_100_2022.json",
    ):
        (data / name).write_text(json.dumps({"results": []}))
    (data / "crypto_tsmom_multifold_replay.json").write_text(json.dumps({"folds": []}))
    (data / "crypto_tsmom_walk_forward_replay.json").write_text(json.dumps({"folds": []}))
    report = build_evidence(tmp_path)
    assert report["evidence_row_count"] == 0
    assert any("cross_sectional_six_meanrev20_100_2022.json" in source
               for source in report["sources"])
